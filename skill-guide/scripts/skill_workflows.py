#!/usr/bin/env python3
"""Authorized, minimal workflow recipes; no automatic learning or execution."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

import skill_preferences as P
from skill_index import metadata


def need(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def config_hash(path):
    config = Path(path).parent / 'agents/openai.yaml'
    return digest(config) if config.exists() else None


def bind(path, resources=()):
    """Snapshot selected files before approval/use; this is not suitability validation."""
    path = Path(path).expanduser().resolve()
    need(path.name.casefold() == 'skill.md', 'Bind SKILL.md only')
    actual = metadata(path.read_bytes())
    need(actual['metadata_status'] == 'parsed', 'Read and review unresolved skill metadata first')
    hashes = {}
    for relative in resources:
        resource = (path.parent / relative).resolve()
        need(not Path(relative).is_absolute() and resource.is_relative_to(path.parent),
             'Resource must stay within skill directory')
        hashes[relative] = digest(resource)
    return {'id': P.identity(path), 'path': str(path), 'name': actual['name'],
            'skill_hash': digest(path), 'config_hash': config_hash(path), 'resources': hashes}


def strings(value, label):
    need(isinstance(value, dict) and all(isinstance(k, str) and k.strip() and
         isinstance(v, str) and v.strip() and len(v) <= 256 for k, v in value.items()),
         label + ' must map condition names to short, nonempty strings')
    return value


def validate_recipe(recipe):
    need(isinstance(recipe, dict) and set(recipe) == {'id', 'name', 'scope', 'task_tags',
         'input_type', 'output_type', 'constraints', 'environment', 'stages', 'evidence',
         'enabled', 'created_at', 'updated_at'}, 'Invalid recipe fields')
    need(isinstance(recipe['id'], str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', recipe['id']), 'Invalid ID')
    for field in ('name', 'input_type', 'output_type'):
        P.text(recipe[field], field, 128)
    P.tags(recipe['task_tags'])
    need(bool(recipe['task_tags']), 'At least one task tag required')
    scope = recipe['scope']
    need(isinstance(scope, dict) and (scope == {'kind': 'personal'} or
         set(scope) == {'kind', 'path'} and scope['kind'] == 'project' and
         isinstance(scope['path'], str) and Path(scope['path']).is_absolute()), 'Invalid scope')
    strings(recipe['constraints'], 'constraints')
    strings(recipe['environment'], 'environment')
    evidence = recipe['evidence']
    need(isinstance(evidence, dict) and set(evidence) == {'status', 'checked', 'limits'} and
         evidence['status'] in {'confirmed', 'used'}, 'Only user-confirmed or used workflows can be saved')
    P.text(evidence['checked'], 'evidence.checked', 512)
    P.text(evidence['limits'], 'evidence.limits', 512)
    need(type(recipe['enabled']) is bool, 'enabled must be boolean')
    for field in ('created_at', 'updated_at'):
        need(datetime.fromisoformat(recipe[field]).tzinfo is not None, 'Timestamp needs timezone')
    stages = recipe['stages']
    need(isinstance(stages, list) and 1 <= len(stages) <= 12, 'Use 1–12 stages')
    for stage in stages:
        need(isinstance(stage, dict) and set(stage) == {'kind', 'role', 'input_type', 'output_type', 'target'},
             'Invalid stage fields')
        need(stage['kind'] in {'skill', 'prompt', 'tool'}, 'Invalid stage kind')
        for field in ('role', 'input_type', 'output_type'):
            P.text(stage[field], field, 256)
        target = stage['target']
        if stage['kind'] != 'skill':
            need(target is None, 'Only skill stages bind a skill')
            continue
        need(isinstance(target, dict) and set(target) == {'id', 'path', 'name', 'skill_hash',
             'config_hash', 'resources'}, 'Invalid target fields')
        P.text(target['name'], 'target.name', 128)
        need(isinstance(target['path'], str) and Path(target['path']).is_absolute() and
             Path(target['path']).name.casefold() == 'skill.md' and target['id'] == P.identity(target['path']),
             'Bind an exact absolute SKILL.md identity')
        for value in (target['skill_hash'], target['config_hash']):
            need(value is None or isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value), 'Invalid hash')
        need(target['skill_hash'] is not None, 'Skill hash required')
        need(isinstance(target['resources'], dict), 'resources must be a hash map')
        base = Path(target['path']).parent.resolve()
        for relative, value in target['resources'].items():
            need(isinstance(relative, str) and not Path(relative).is_absolute() and
                 (base / relative).resolve().is_relative_to(base), 'Resource must stay within skill directory')
            need(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value), 'Invalid resource hash')
    return recipe


def load(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return {'schema_version': 1, 'recipes': []}
    need(isinstance(data, dict) and set(data) == {'schema_version', 'recipes'} and
         type(data['schema_version']) is int and data['schema_version'] == 1,
         'Unsupported or invalid workflow document; preserve original')
    need(isinstance(data['recipes'], list), 'recipes must be a list')
    ids = set()
    for recipe in data['recipes']:
        validate_recipe(recipe)
        need(recipe['id'] not in ids, 'Duplicate workflow ID')
        ids.add(recipe['id'])
    return data


def binding_status(target):
    path = Path(target['path'])
    try:
        if not path.is_file():
            return 'missing'
        actual = metadata(path.read_bytes())
        if actual['metadata_status'] != 'parsed':
            return 'needs_review'
        if (actual['name'] != target['name'] or digest(path) != target['skill_hash'] or
                config_hash(path) != target['config_hash']):
            return 'changed'
        for relative, value in target['resources'].items():
            resource = path.parent / relative
            if not resource.is_file() or digest(resource) != value:
                return 'changed'
        return 'current'
    except (OSError, ValueError, UnicodeError):
        return 'needs_review'


def query_recipes(data, workspace, task_tags, input_type, output_type, constraints, environment,
                  active_skill_ids=None, limit=5, offset=0):
    """Filter cheap conditions before bounded file checks; expose unexamined candidates."""
    current_tags = set(P.tags(task_tags))
    strings(constraints, 'constraints')
    strings(environment, 'environment')
    need(type(limit) is int and 1 <= limit <= 20, 'Query limit must be 1–20')
    need(type(offset) is int and offset >= 0, 'Query offset must be a nonnegative integer')
    pool, rejected = [], []
    task_matches = 0
    for recipe in sorted(data['recipes'], key=lambda r: (r['scope']['kind'] != 'project', r['id'])):
        if not recipe['enabled'] or not set(P.tags(recipe['task_tags'])).issubset(current_tags):
            continue
        scope = recipe['scope']
        if scope['kind'] == 'project' and not Path(P.canonical(workspace)).is_relative_to(Path(P.canonical(scope['path']))):
            continue
        if recipe['input_type'] != input_type or recipe['output_type'] != output_type:
            continue
        task_matches += 1
        mismatches, unknown = [], []
        for category, actual in (('constraints', constraints), ('environment', environment)):
            for key, expected in recipe[category].items():
                if key not in actual:
                    unknown.append(category + '.' + key)
                elif actual[key] != expected:
                    mismatches.append(category + '.' + key)
        if mismatches:
            rejected.append({'id': recipe['id'], 'mismatches': mismatches})
            continue
        pool.append((recipe, unknown))
    result, binding_cache = [], {}
    for recipe, unknown in pool[offset:offset + limit]:
        bindings = []
        for index, stage in enumerate(recipe['stages']):
            target = stage['target']
            if target is None:
                continue
            if active_skill_ids is not None and target['id'] not in active_skill_ids:
                state = 'out_of_scope_or_disabled'
            else:
                cache_key = json.dumps(target, sort_keys=True)
                if cache_key not in binding_cache:
                    binding_cache[cache_key] = binding_status(target)
                state = binding_cache[cache_key]
                if active_skill_ids is None:
                    unknown.append('host_availability.stage_' + str(index + 1))
            bindings.append({'stage': index + 1, 'id': target['id'], 'status': state})
        blocked = any(b['status'] in {'missing', 'out_of_scope_or_disabled'} for b in bindings)
        review = unknown or any(b['status'] != 'current' for b in bindings)
        result.append({'recipe': recipe, 'status': 'blocked' if blocked else
                       ('needs_review' if review else 'eligible_for_review'),
                       'mismatches': [], 'unknown_conditions': unknown, 'bindings': bindings,
                       'semantic_validation': False})
    end = min(offset + limit, len(pool))
    has_more = end < len(pool)
    return {'candidates': result, 'query': {'task_matches': task_matches,
            'filtered_conditions': len(rejected), 'condition_candidates': len(pool),
            'checked_recipes': len(result), 'distinct_binding_checks': len(binding_cache),
            'offset': offset, 'has_more': has_more, 'next_offset': end if has_more else None},
            'rejected_conditions': rejected[:limit]}


def candidates(data, workspace, task_tags, input_type, output_type, constraints, environment,
               active_skill_ids=None, limit=5, offset=0):
    """Compatibility API for callers needing only the current candidate batch."""
    return query_recipes(data, workspace, task_tags, input_type, output_type, constraints,
                         environment, active_skill_ids, limit, offset)['candidates']


def mutate(path, command, authorized=False, spec=None, recipe_id=None):
    need(authorized, 'Explicit user authorization required for workflow changes')
    need(command in {'apply', 'disable', 'enable', 'remove'}, 'Unknown mutation')
    if command == 'apply':
        need(isinstance(spec, dict), 'Recipe specification required')
    with P.write_lock(path):
        data = load(path)
        key = recipe_id if command != 'apply' else spec.get('id')
        previous = next((r for r in data['recipes'] if r['id'] == key), None)
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        if command == 'apply':
            need(not (set(spec) & {'enabled', 'created_at', 'updated_at'}), 'Do not supply managed fields')
            recipe = {**spec, 'id': key or uuid.uuid4().hex[:16], 'enabled': previous['enabled'] if previous else True,
                      'created_at': previous['created_at'] if previous else now, 'updated_at': now}
            recipe['task_tags'] = P.tags(recipe.get('task_tags'))
            if isinstance(recipe.get('scope'), dict) and recipe['scope'].get('kind') == 'project':
                recipe['scope'] = {**recipe['scope'], 'path': P.canonical(recipe['scope']['path'])}
            validate_recipe(recipe)
            for stage in recipe['stages']:
                if stage['target'] is not None:
                    need(binding_status(stage['target']) == 'current',
                         'Skill or tracked resource changed since confirmation; review before saving')
            data['recipes'] = [r for r in data['recipes'] if r['id'] != recipe['id']] + [recipe]
        else:
            need(previous is not None, 'Unknown workflow ID; no write performed')
            recipe = previous
            if command == 'remove':
                data['recipes'] = [r for r in data['recipes'] if r['id'] != key]
            else:
                recipe['enabled'] = command == 'enable'
                recipe['updated_at'] = now
        path = Path(path)
        fd, temporary = tempfile.mkstemp(prefix='.workflows-', suffix='.tmp', dir=path.parent)
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
    return {'ok': True, 'persisted': True, 'recipe': recipe, 'path': str(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('list', 'query', 'bind', 'apply', 'disable', 'enable', 'remove'))
    parser.add_argument('--file')
    parser.add_argument('--codex-home', default=os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    parser.add_argument('--recipe-file')
    parser.add_argument('--context-file', help='Query context JSON; see references/workflows.md')
    parser.add_argument('--id')
    parser.add_argument('--limit', type=int, default=5, help='Maximum matching workflows checked (1–20)')
    parser.add_argument('--offset', type=int, default=0, help='Continue from query.next_offset using the same context')
    parser.add_argument('--path', help='Selected SKILL.md for a read-only bind snapshot')
    parser.add_argument('--resource', action='append', default=[], help='Relevant resource path relative to skill directory')
    parser.add_argument('--authorized', action='store_true', help='Caller has user authorization; not a permission bypass')
    args = parser.parse_args()
    path = Path(args.file or str(Path(args.codex_home) / 'skills/.skill-guide-data/workflows.json')).expanduser().resolve()
    try:
        if args.command == 'bind':
            need(args.path is not None, 'bind requires --path')
            result = {'ok': True, 'target': bind(args.path, args.resource), 'semantic_validation': False}
        elif args.command == 'list':
            result = {'ok': True, 'exists': path.exists(), 'path': str(path), **load(path)}
        elif args.command == 'query':
            need(args.context_file is not None, 'query requires --context-file')
            context = json.loads(Path(args.context_file).read_text(encoding='utf-8-sig'))
            need(isinstance(context, dict) and set(context) == {'workspace', 'task_tags', 'input_type',
                 'output_type', 'constraints', 'environment', 'active_skill_ids'}, 'Invalid query context')
            active = context['active_skill_ids']
            need(active is None or isinstance(active, list) and all(isinstance(x, str) for x in active),
                 'active_skill_ids must be a list or null')
            result = {'ok': True, 'path': str(path),
                      **query_recipes(load(path), **context, limit=args.limit, offset=args.offset)}
        else:
            need(args.command == 'apply' or args.id is not None, 'Workflow ID required')
            need(args.command != 'apply' or args.recipe_file is not None, 'apply requires --recipe-file')
            spec = json.loads(Path(args.recipe_file).read_text(encoding='utf-8-sig')) if args.recipe_file else None
            result = mutate(path, args.command, args.authorized, spec, args.id)
    except (P.PreferenceError, OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        result = {'ok': False, 'persisted': False, 'error': str(exc), 'path': str(path)}
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
