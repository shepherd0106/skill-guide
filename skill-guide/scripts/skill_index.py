#!/usr/bin/env python3
"""Local, incremental Skill metadata index. Python 3.11+, standard library only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import tomllib
from pathlib import Path

import skill_preferences as preference_store

SCHEMA = 1
FULL_INTERVAL = 7 * 86400


def canonical(path):
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(path):
    return digest(canonical(path).encode())[:20]


def stamp(path):
    try:
        s = Path(path).stat()
        return {"mtime_ns": s.st_mtime_ns, "size": s.st_size}
    except FileNotFoundError:
        return None


def scalar(value):
    """Deliberately limited YAML string reader; unsupported syntax is not guessed."""
    value = value.strip()
    if value.startswith('"'):
        try:
            end = json.JSONDecoder().raw_decode(value)
            if isinstance(end[0], str) and (not value[end[1]:].strip() or
                                          value[end[1]:].lstrip().startswith('#')):
                return end[0]
        except ValueError:
            pass
        return None
    if value.startswith("'"):
        match = re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", value)
        return match[1].replace("''", "'") if match else None
    if not value or value[0] in "&*!{[>|" or value in {"true", "false", "null", "~"}:
        return None
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def metadata(data):
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return {"name": None, "description": "", "metadata_status": "invalid"}
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
    if end is None:
        return {"name": None, "description": "", "metadata_status": "invalid"}
    fields = {}
    for i in range(1, end):
        match = re.match(r"^(name|description):\s*(.*)$", lines[i])
        if not match:
            continue
        key, value = match.groups()
        following = []
        for line in lines[i + 1:end]:
            if line and not line[0].isspace():
                break
            if line.strip() and not line.lstrip().startswith('#'):
                following.append(line.strip())
        if re.fullmatch(r"[>|][+-]?\s*(?:#.*)?", value):
            fields[key] = ('\n' if value.startswith('|') else ' ').join(following)
        else:
            fields[key] = scalar(value)
            if following and fields[key] is not None and not value.startswith(('"', "'")):
                fields[key] += ' ' + ' '.join(following)
    valid = bool(fields.get('name') and fields.get('description'))
    return {"name": fields.get('name'), "description": fields.get('description') or "",
            "metadata_status": "parsed" if valid else "needs_review"}


def invocation_policy(data):
    if data is None:
        return True
    text = data.decode('utf-8-sig')
    match = re.search(r"(?m)^policy:\s*(?:#.*)?$", text)
    if not match:
        # Inline policy forms need a real YAML reader / manual verification.
        return None if re.search(r"(?m)^policy:", text) else True
    block = text[match.end():]
    block = re.split(r"\n(?=\S)", block, maxsplit=1)[0]
    setting = re.search(r"(?m)^\s+allow_implicit_invocation:\s*(.*?)\s*$", block)
    if not setting:
        return True
    value = re.split(r"\s+#", setting[1], maxsplit=1)[0].strip().lower()
    return {'true': True, 'false': False}.get(value)


def read_json(path, warnings, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        warnings.append(f"Cannot read {path}: {type(exc).__name__}; rebuilding or using defaults")
        return default


def load_index(cache, warnings):
    data = read_json(cache / 'skills-index.json', warnings, {})
    if (not isinstance(data, dict) or data.get('schema_version') != SCHEMA or
            not isinstance(data.get('entries'), list) or
            any(not isinstance(e, dict) or not all(k in e for k in
                ('id', 'path', 'contexts', 'files', 'name', 'description', 'configured_enabled'))
                or not isinstance(e.get('files'), dict)
                or not all(isinstance(e['files'].get(k), dict) for k in ('stamps', 'hashes'))
                or not isinstance(e.get('contexts'), list)
                or any(not isinstance(c, dict) or 'key' not in c for c in e.get('contexts', []))
                for e in data.get('entries', []))):
        if data:
            warnings.append('Invalid index schema; rebuilding')
        return {}
    return data


def roots_for(args):
    home = Path(args.codex_home).expanduser().resolve()
    roots = [(home / 'skills', 'user'), (home / 'skills' / '.system', 'system'),
             (Path.home() / '.agents' / 'skills', 'user')]
    workspace = Path(args.workspace).expanduser().resolve()
    chain = [workspace, *workspace.parents]
    stop = next((i for i, p in enumerate(chain) if (p / '.git').exists()), 0)
    for directory in chain[:stop + 1]:
        roots.extend((directory / kind / 'skills', 'project') for kind in ('.agents', '.codex'))
    roots.extend((Path(p).expanduser().resolve(), 'explicit') for p in args.root)
    merged = {}
    for path, scope in roots:
        key = canonical(path)
        merged.setdefault(key, {'path': str(path), 'key': key, 'scopes': []})
        if scope not in merged[key]['scopes']:
            merged[key]['scopes'].append(scope)
    return list(merged.values())


def scan(root):
    path = Path(root['path'])
    try:
        if stamp(path / 'SKILL.md') is not None:
            return [path / 'SKILL.md'], 'ok', []
        entries, errors = [], []
        with os.scandir(path) as children:
            for child in children:
                if child.name == '.system':
                    continue
                try:
                    if child.is_dir() and stamp(Path(child.path) / 'SKILL.md') is not None:
                        entries.append(Path(child.path) / 'SKILL.md')
                except OSError as exc:
                    errors.append(f"{child.path}: {type(exc).__name__}")
        return entries, 'partial' if errors else 'ok', errors
    except FileNotFoundError:
        return [], 'missing', []
    except OSError as exc:
        return [], 'error', [f"{path}: {type(exc).__name__}"]


def enable_config(config_path, warnings):
    try:
        data = tomllib.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        settings = data.get('skills', {}).get('config', [])
        if not isinstance(settings, list):
            raise ValueError('skills.config must be a list')
        values = {}
        for item in settings:
            if isinstance(item, dict) and isinstance(item.get('path'), str):
                path = Path(item['path']).expanduser()
                if not path.is_absolute():
                    warnings.append('Relative skill configuration path: enable state unknown')
                    return {}, 'unknown'
                enabled = item.get('enabled', True)
                if not isinstance(enabled, bool):
                    raise ValueError('enabled must be boolean')
                values[canonical(path)] = enabled
        return values, 'read'
    except FileNotFoundError:
        return {}, 'absent'
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        warnings.append(f"Skill enable configuration unknown: {type(exc).__name__}")
        return {}, 'unknown'


def enrich(entry, settings, evidence):
    key = canonical(entry['path'])
    entry['configured_enabled'] = settings.get(key) if evidence != 'unknown' else None
    entry['enable_evidence'] = evidence
    # No config entry is not proof that the host loaded a skill.
    entry['availability'] = ('disabled' if settings.get(key) is False else
                             'unknown' if entry.get('stale') or evidence == 'unknown' or
                             entry.get('metadata_status') != 'parsed' else 'discovered')
    return entry


def refresh(args, old, warnings):
    now = time.time()
    full = args.full or not old or now - old.get('last_full_check', 0) >= FULL_INTERVAL
    before = {e['id']: e for e in old.get('entries', [])}
    found, scanned = {}, []
    roots = roots_for(args)
    active_roots = {root['key'] for root in roots}
    for root in roots:
        files, status, errors = scan(root)
        scanned.append({**root, 'status': status})
        warnings.extend(errors)
        context = {**root, 'status': status}
        for path in files:
            item = found.setdefault(identity(path), {'path': canonical(path), 'contexts': []})
            item['contexts'].append(context)
        if status != 'ok':
            retained = 0
            for entry in before.values():
                if any(c['key'] == root['key'] for c in entry['contexts']):
                    item = found.setdefault(entry['id'], {'path': entry['path'], 'contexts': []})
                    if not any(c['key'] == root['key'] for c in item['contexts']):
                        item['contexts'].append(context)
                    retained += 1
            if retained:
                warnings.append(f"Root {root['path']} is {status}; preserved {retained} entries as stale")
    settings, evidence = enable_config(args.config, warnings)
    inactive = [dict(e, active_scope=False) for e in before.values()
                if not any(c['key'] in active_roots for c in e['contexts'])]
    counts = {'entries': 0, 'inactive_cached': len(inactive), 'metadata_reads': 0,
              'reused': 0, 'added': 0, 'changed': 0,
              'removed_from_scope': len(set(before) - set(found)) - len(inactive),
              'full_hash_check': full}
    result = []
    for key, item in sorted(found.items()):
        previous = before.get(key)
        path = Path(item['path'])
        try:
            stamps = {'skill': stamp(path), 'ui': stamp(path.parent / 'agents' / 'openai.yaml')}
            if stamps['skill'] is None:
                raise FileNotFoundError(str(path))
            if previous and not full and previous['files']['stamps'] == stamps:
                entry = {**previous}
                counts['reused'] += 1
            else:
                raw = path.read_bytes()
                ui = ((path.parent / 'agents' / 'openai.yaml').read_bytes()
                      if stamps['ui'] else None)
                counts['metadata_reads'] += 1 + (ui is not None)
                hashes = {'skill': digest(raw), 'ui': digest(ui) if ui is not None else None}
                entry = {'id': key, 'path': str(path), **metadata(raw),
                         'implicit_invocation': invocation_policy(ui),
                         'files': {'stamps': stamps, 'hashes': hashes}, 'checked_at': now}
                if not previous:
                    counts['added'] += 1
                elif previous['files']['hashes'] != hashes:
                    counts['changed'] += 1
            entry['active_scope'] = True
            entry['contexts'] = item['contexts'] + ([c for c in previous['contexts']
                if c['key'] not in active_roots] if previous else [])
            entry['stale'] = all(c['status'] != 'ok' for c in item['contexts'])
            result.append(enrich(entry, settings, evidence))
        except (OSError, UnicodeError, ValueError, KeyError) as exc:
            warnings.append(f"Cannot inspect {path}: {type(exc).__name__}")
            entry = ({**previous} if previous else
                     {'id': key, 'path': str(path), 'name': None, 'description': '',
                      'metadata_status': 'needs_review', 'files': {'stamps': {}, 'hashes': {}},
                      'implicit_invocation': None})
            entry.update(contexts=item['contexts'], stale=True, active_scope=True)
            result.append(enrich(entry, settings, evidence))
    counts['entries'] = len(result)
    return {'schema_version': SCHEMA, 'updated_at': now,
            'last_full_check': now if full else old.get('last_full_check', 0),
            'roots': scanned, 'entries': result + inactive}, counts


def atomic_write(path, value):
    fd, temp = tempfile.mkstemp(prefix='.index-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def query(index, terms, limit, preferences, warnings, preference_context=None):
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_-]*|[\u3400-\u9fff]+", terms.lower()))
    aliases = preferences.get('aliases', {}) if isinstance(preferences, dict) else {}
    if not isinstance(aliases, dict):
        warnings.append('Invalid aliases; ignored')
        aliases = {}
    candidates = []
    decisions = (preference_context or {}).get('decisions', {})
    explicit = set((preference_context or {}).get('explicit_choices', []))
    conflicts = {c['target_id'] for c in (preference_context or {}).get('conflicts', [])}
    for entry in index.get('entries', []):
        if (entry.get('active_scope') is False or entry['availability'] == 'disabled' or
                entry['name'] == 'skill-guide'):
            continue
        extra = aliases.get(entry['id'], [])
        extra = extra if isinstance(extra, list) and all(isinstance(x, str) for x in extra) else []
        text = ' '.join([entry['name'] or Path(entry['path']).parent.name,
                         entry['description'], *extra]).lower()
        matches = sorted(t for t in tokens if t in text)
        decision = decisions.get(entry['id'], {})
        if decision.get('kind') == 'exclude':
            continue
        if tokens and not matches and decision.get('kind') != 'prefer' and entry['id'] not in explicit:
            continue
        candidates.append({k: entry.get(k) for k in
            ('id', 'name', 'path', 'description', 'availability', 'metadata_status',
             'stale', 'implicit_invocation', 'configured_enabled')} |
            {'matched_terms': matches, 'content_hashes': entry['files']['hashes'],
             'preference': decision or None, 'preference_conflict': entry['id'] in conflicts,
             'explicit_selection': entry['id'] in explicit,
             'retrieval_reason': 'explicit_selection' if entry['id'] in explicit else
                 'keyword' if matches else 'preference' if decision else 'overview'})
    # Preferences nominate candidates, never establish task coverage or readiness.
    candidates.sort(key=lambda e: (
        not e['explicit_selection'],
        (e['preference'] or {}).get('kind') == 'avoid',
        (e['preference'] or {}).get('kind') != 'prefer',
        -len(e['matched_terms']), bool(e['stale']), e['name'] or e['path']))
    return candidates[:limit], len(candidates)


def check(args, index, warnings):
    entries = {e['id']: e for e in index.get('entries', [])}
    settings, evidence = enable_config(args.config, warnings)
    active = {r['key'] for r in roots_for(args)}
    results = []
    targets = [(key, entries.get(key), None) for key in args.id]
    targets.extend((identity(path), entries.get(identity(path)), Path(path).expanduser().resolve())
                   for path in getattr(args, 'path', []))
    for key, entry, explicit_path in targets:
        if not entry and explicit_path is None:
            results.append({'id': key, 'status': 'not_indexed', 'hint': 'Use check --path with the known candidate path'})
            continue
        path = explicit_path or Path(entry['path'])
        try:
            raw = path.read_bytes()
            ui_path = path.parent / 'agents' / 'openai.yaml'
            ui = ui_path.read_bytes() if stamp(ui_path) is not None else None
            hashes = {'skill': digest(raw), 'ui': digest(ui) if ui is not None else None}
            current = enrich({'path': str(path), 'stale': False, **metadata(raw)}, settings, evidence)
            results.append({'id': key, 'path': str(path), 'status': 'checked',
                'content_changed': hashes != entry['files']['hashes'] if entry else None,
                'content_hashes': hashes,
                'in_current_scope': (canonical(path.parent) in active or
                                     canonical(path.parent.parent) in active),
                'name': current['name'], 'description': current['description'],
                'metadata_status': current['metadata_status'], 'availability': current['availability'],
                'configured_enabled': current['configured_enabled'],
                'implicit_invocation': invocation_policy(ui),
                'enable_state_changed': (current['configured_enabled'] != entry['configured_enabled']
                                         if entry else None)})
        except (OSError, UnicodeError, ValueError) as exc:
            results.append({'id': key, 'path': str(path), 'status': 'unreadable',
                            'error': type(exc).__name__})
    return results


def run(args):
    started = time.perf_counter()
    cache = Path(args.cache_dir).expanduser().resolve()
    warnings = []
    if args.command == 'check':
        old = load_index(cache, warnings)
        return {'checks': check(args, old, warnings), 'warnings': warnings,
                'elapsed_ms': round((time.perf_counter() - started) * 1000, 2)}
    lock = cache / 'refresh.lock'
    locked = False
    try:
        try:
            cache.mkdir(parents=True, exist_ok=True)
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            locked = True
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump({'pid': os.getpid(), 'created_at': time.time()}, stream)
        except OSError as exc:
            warnings.append(f"Cache lock/write unavailable ({type(exc).__name__}); read-only memory refresh")
        # Reload inside the lock to avoid overwriting another writer's newer index.
        old = load_index(cache, warnings)
        index, counts = refresh(args, old, warnings)
        persisted = False
        if locked:
            try:
                atomic_write(cache / 'skills-index.json', index)
                persisted = True
            except OSError as exc:
                warnings.append(f"Cache write failed ({type(exc).__name__}); using memory result")
        result = {'stats': counts, 'cache_persisted': persisted, 'warnings': warnings}
        if args.command in {'query', 'list'}:
            preference_path = Path(getattr(args, 'preferences_file', None) or cache / 'preferences.json')
            preferences = preference_store.load_for_query(preference_path, warnings)
            preference_context = preference_store.context(
                preferences, index.get('entries', []), args.workspace,
                getattr(args, 'tag', []), getattr(args, 'override_skill', []))
            candidates, total = query(index, args.terms if args.command == 'query' else '',
                                      args.limit, preferences, warnings,
                                      preference_context if args.command == 'query' else None)
            if args.command == 'list':
                for entry in candidates:
                    entry['description'] = entry['description'][:160]
            result.update(candidates=candidates, matching_count=total,
                          preferences={**preference_context, 'path': str(preference_path)})
        result['elapsed_ms'] = round((time.perf_counter() - started) * 1000, 2)
        return result
    finally:
        if locked:
            try:
                lock.unlink()
            except OSError as exc:
                warnings.append(f"Cannot remove own cache lock: {type(exc).__name__}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('refresh', 'query', 'list', 'check'))
    parser.add_argument('--codex-home', default=os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    parser.add_argument('--cache-dir')
    parser.add_argument('--preferences-file', help='Authoritative preferences file, independent of cache fallback')
    parser.add_argument('--tag', action='append', default=[], help='Explicit task classification for scoped preferences')
    parser.add_argument('--override-skill', action='append', default=[], help='Verified skill ID explicitly chosen for this task; overrides historical skill rules')
    parser.add_argument('--config')
    parser.add_argument('--workspace', default=str(Path.cwd()))
    parser.add_argument('--root', action='append', default=[])
    parser.add_argument('--terms', default='')
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--id', action='append', default=[])
    parser.add_argument('--path', action='append', default=[], help='Known SKILL.md path for read-only checks without a persisted index')
    parser.add_argument('--full', action='store_true')
    args = parser.parse_args()
    args.cache_dir = args.cache_dir or str(Path(args.codex_home) / 'skills' / '.skill-guide-data')
    args.preferences_file = args.preferences_file or str(Path(args.codex_home) / 'skills/.skill-guide-data/preferences.json')
    args.config = args.config or str(Path(args.codex_home) / 'config.toml')
    if args.limit < 1:
        parser.error('--limit must be positive')
    if args.command == 'check' and not (args.id or args.path):
        parser.error('check requires at least one --id or --path')
    if args.command == 'query' and not args.terms.strip():
        parser.error('query requires --terms; use list for an unfiltered overview')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
