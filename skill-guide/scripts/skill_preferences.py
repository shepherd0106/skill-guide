#!/usr/bin/env python3
"""Scoped local preferences. Python 3.11+, standard library only."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

SCHEMA = 1
KINDS = {'prefer', 'avoid', 'exclude', 'prompt'}


class PreferenceError(ValueError):
    pass


def canonical(path):
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def identity(path):
    return hashlib.sha256(canonical(path).encode()).hexdigest()[:20]


def text(value, field, maximum=2048):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PreferenceError(f'{field} must be a nonempty string of at most {maximum} characters')
    return value.strip()


def tags(values):
    if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
        raise PreferenceError('task_tags must be a list of nonempty strings')
    return sorted({v.strip().casefold() for v in values})


def validate_rule(rule):
    if not isinstance(rule, dict) or set(rule) - {
            'id', 'kind', 'scope', 'task_tags', 'target', 'instruction', 'reason',
            'enabled', 'created_at', 'updated_at'}:
        raise PreferenceError('Invalid rule fields')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', rule.get('id', '')):
        raise PreferenceError('Invalid rule ID')
    if rule.get('kind') not in KINDS or type(rule.get('enabled')) is not bool:
        raise PreferenceError('Invalid rule kind or enabled state')
    text(rule.get('instruction'), 'instruction')
    if not isinstance(rule.get('reason'), str) or len(rule['reason']) > 512:
        raise PreferenceError('reason must be a string of at most 512 characters')
    tags(rule.get('task_tags'))
    scope = rule.get('scope')
    if not isinstance(scope, dict) or scope.get('kind') not in {'personal', 'project'}:
        raise PreferenceError('Invalid scope')
    expected = {'kind'} if scope['kind'] == 'personal' else {'kind', 'path'}
    if set(scope) != expected:
        raise PreferenceError('Invalid scope fields')
    if scope['kind'] == 'project':
        text(scope['path'], 'scope.path')
        if not Path(scope['path']).is_absolute():
            raise PreferenceError('Project path must be absolute')
    for field in ('created_at', 'updated_at'):
        value = text(rule.get(field), field, 64)
        try:
            if datetime.fromisoformat(value).tzinfo is None:
                raise ValueError('timezone required')
        except ValueError as exc:
            raise PreferenceError(f'Invalid {field}') from exc
    target = rule.get('target')
    if rule['kind'] == 'prompt':
        if target is not None:
            raise PreferenceError('Prompt rules cannot bind a skill')
    else:
        if not isinstance(target, dict) or set(target) != {'id', 'path', 'name', 'skill_hash'}:
            raise PreferenceError('Invalid skill target')
        text(target['name'], 'target.name', 128)
        text(target['path'], 'target.path')
        if (not Path(target['path']).is_absolute() or os.path.normcase(Path(target['path']).name) != os.path.normcase('SKILL.md')
                or target['id'] != identity(target['path'])):
            raise PreferenceError('Target must bind the exact absolute SKILL.md path and ID')
        if not re.fullmatch(r'[0-9a-f]{64}', target['skill_hash']):
            raise PreferenceError('Invalid target content hash')


def validate(data):
    if not isinstance(data, dict) or set(data) - {'schema_version', 'aliases', 'rules'}:
        raise PreferenceError('Invalid preference document')
    if type(data.get('schema_version', SCHEMA)) is not int or data.get('schema_version', SCHEMA) != SCHEMA:
        raise PreferenceError('Unsupported preference schema; do not overwrite')
    aliases = data.get('aliases', {})
    if (not isinstance(aliases, dict) or not all(isinstance(k, str) and isinstance(v, list)
            and all(isinstance(alias, str) for alias in v) for k, v in aliases.items())):
        raise PreferenceError('Invalid aliases')
    rules = data.get('rules', [])
    if not isinstance(rules, list):
        raise PreferenceError('rules must be a list')
    seen = set()
    for rule in rules:
        validate_rule(rule)
        if rule['id'] in seen:
            raise PreferenceError('Duplicate rule ID')
        seen.add(rule['id'])
    return {'schema_version': SCHEMA, 'aliases': aliases, 'rules': rules}


def load(path):
    try:
        return validate(json.loads(Path(path).read_text(encoding='utf-8-sig')))
    except FileNotFoundError:
        return validate({})
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise PreferenceError(f'Cannot read preferences ({type(exc).__name__}): {exc}') from exc


def load_for_query(path, warnings):
    try:
        return load(path)
    except PreferenceError as exc:
        warnings.append(str(exc) + '; stored file preserved, preferences not applied')
        return validate({})


def applicable(data, workspace, task_tags):
    workspace_path = Path(canonical(workspace))
    current_tags = set(tags(task_tags)) if task_tags is not None else None
    result = []
    for rule in data['rules']:
        if not rule['enabled'] or (current_tags is not None and not set(tags(rule['task_tags'])).issubset(current_tags)):
            continue
        project = rule['scope']['kind'] == 'project'
        if project and not workspace_path.is_relative_to(Path(canonical(rule['scope']['path']))):
            continue
        result.append({**rule, 'priority': 2 if project else 1})
    return sorted(result, key=lambda r: (-r['priority'], r['id']))


def context(data, entries, workspace, task_tags, overrides=()):
    """Return evidence, scoped decisions and unresolved conflicts, not capability judgments."""
    by_id = {e['id']: e for e in entries}
    rules = applicable(data, workspace, task_tags)
    groups = {}
    for rule in rules:
        target = rule['target']
        if target is None:
            rule['binding_status'] = 'not_applicable'
            continue
        entry = by_id.get(target['id'])
        if entry is None or canonical(entry['path']) != canonical(target['path']):
            status = 'missing'
        elif entry.get('active_scope') is False:
            status = 'out_of_scope'
        elif entry.get('availability') == 'disabled':
            status = 'disabled'
        elif entry.get('stale'):
            status = 'needs_review'
        elif (entry.get('name') != target['name'] or
              entry.get('files', {}).get('hashes', {}).get('skill') != target['skill_hash']):
            status = 'changed'
        else:
            status = 'current'
        rule['binding_status'] = status
        if status in {'current', 'changed', 'needs_review'}:
            groups.setdefault(target['id'], []).append(rule)
    decisions, conflicts = {}, []
    for key, group in groups.items():
        level = max(r['priority'] for r in group)
        strongest = [r for r in group if r['priority'] == level]
        kinds = {r['kind'] for r in strongest}
        # avoid + exclude agree on direction; prefer vs either needs user resolution.
        if 'prefer' in kinds and kinds & {'avoid', 'exclude'}:
            conflicts.append({'target_id': key, 'rule_ids': [r['id'] for r in strongest]})
            continue
        kind = 'exclude' if 'exclude' in kinds else ('avoid' if 'avoid' in kinds else 'prefer')
        decisions[key] = {'kind': kind, 'rule_ids': [r['id'] for r in strongest]}
    overridden = []
    for key in set(overrides):
        if key in decisions:
            overridden.append({'target_id': key, **decisions.pop(key)})
        conflicts = [c for c in conflicts if c['target_id'] != key]
    explicit_choices = [key for key in sorted(set(overrides)) if key in by_id
                        and by_id[key].get('active_scope') is not False]
    available_tags = sorted({tag for rule in applicable(data, workspace, None)
                             for tag in tags(rule['task_tags'])})
    return {'rules': rules, 'decisions': decisions, 'conflicts': conflicts,
            'explicit_choices': explicit_choices,
            'available_task_tags': available_tags,
            'overridden': overridden, 'requires_review': bool(conflicts)}


@contextmanager
def write_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + '.lock')
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PreferenceError('Preference lock busy; no write performed') from exc
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'pid': os.getpid()}, stream)
        yield
    finally:
        lock.unlink()


def save(path, data):
    data = validate(data)
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.preferences-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def make_rule(spec, previous=None):
    if not isinstance(spec, dict) or set(spec) - {
            'id', 'kind', 'scope', 'task_tags', 'target', 'instruction', 'reason'}:
        raise PreferenceError('Invalid rule specification')
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    scope = spec.get('scope', {})
    if isinstance(scope, dict) and scope.get('kind') == 'project' and isinstance(scope.get('path'), str):
        scope = {**scope, 'path': canonical(scope['path'])}
    target = None
    if spec.get('kind') != 'prompt':
        supplied = spec.get('target')
        if not isinstance(supplied, dict) or set(supplied) != {'path', 'name'}:
            raise PreferenceError('Supply a verified target path and actual skill name')
        path = Path(supplied['path']).expanduser().resolve()
        if os.path.normcase(path.name) != os.path.normcase('SKILL.md'):
            raise PreferenceError('Target must be SKILL.md')
        raw = path.read_bytes()
        from skill_index import metadata
        actual = metadata(raw)
        if actual['metadata_status'] != 'parsed' or actual['name'] != supplied['name']:
            raise PreferenceError('Target name must match the actual verified SKILL.md entry')
        # Pin identity and bytes; suitability still requires reading the full instructions.
        target = {'id': identity(path), 'path': str(path), 'name': supplied['name'],
                  'skill_hash': hashlib.sha256(raw).hexdigest()}
    elif spec.get('target') is not None:
        raise PreferenceError('Prompt rule must not specify a target')
    rule = {'id': spec.get('id') or uuid.uuid4().hex[:16], 'kind': spec.get('kind'),
            'scope': scope, 'task_tags': tags(spec.get('task_tags', [])), 'target': target,
            'instruction': text(spec.get('instruction'), 'instruction'),
            'reason': spec.get('reason', ''), 'enabled': previous['enabled'] if previous else True,
            'created_at': previous['created_at'] if previous else now, 'updated_at': now}
    validate_rule(rule)
    return rule


def mutate(path, command, authorized=False, spec=None, rule_id=None):
    if not authorized:
        raise PreferenceError('Explicit user authorization is required for preference changes')
    if command == 'apply' and not isinstance(spec, dict):
        raise PreferenceError('Rule specification must be an object')
    with write_lock(path):
        data = load(path)  # Never rebuild or overwrite malformed personal data.
        existing = next((r for r in data['rules'] if r['id'] == (rule_id or (spec or {}).get('id'))), None)
        if command == 'apply':
            rule = make_rule(spec, existing)
            data['rules'] = [r for r in data['rules'] if r['id'] != rule['id']] + [rule]
        else:
            if existing is None:
                raise PreferenceError('Unknown rule ID; no write performed')
            rule = existing
            if command == 'remove':
                data['rules'] = [r for r in data['rules'] if r['id'] != rule_id]
            elif command in {'disable', 'enable'}:
                existing['enabled'] = command == 'enable'
                existing['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            else:
                raise PreferenceError('Unknown mutation')
        save(path, data)
    return {'ok': True, 'persisted': True, 'command': command, 'rule': rule, 'path': str(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('list', 'apply', 'remove', 'disable', 'enable'))
    parser.add_argument('--file', help='Authoritative preferences.json path; independent of index cache')
    parser.add_argument('--codex-home', default=os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    parser.add_argument('--rule-file', help='UTF-8 JSON specification for apply')
    parser.add_argument('--id')
    parser.add_argument('--workspace', default=str(Path.cwd()))
    parser.add_argument('--tag', action='append', default=[])
    parser.add_argument('--applicable', action='store_true', help='List only rules matching workspace and tags')
    parser.add_argument('--authorized', action='store_true', help='Caller has explicit user authorization; not a permission bypass')
    args = parser.parse_args()
    path = Path(args.file or str(Path(args.codex_home) / 'skills/.skill-guide-data/preferences.json')).expanduser().resolve()
    try:
        if args.command == 'list':
            data = load(path)
            rules = applicable(data, args.workspace, args.tag) if args.applicable else data['rules']
            result = {'ok': True, 'path': str(path), 'exists': path.exists(),
                      'aliases': data['aliases'], 'rules': rules}
        else:
            if args.command == 'apply' and not args.rule_file:
                raise PreferenceError('apply requires --rule-file')
            if args.command != 'apply' and not args.id:
                raise PreferenceError('This command requires --id')
            spec = json.loads(Path(args.rule_file).read_text(encoding='utf-8-sig')) if args.rule_file else None
            result = mutate(path, args.command, args.authorized, spec, args.id)
    except (PreferenceError, OSError, UnicodeError, ValueError, TypeError) as exc:
        result = {'ok': False, 'persisted': False, 'error': str(exc), 'path': str(path)}
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
