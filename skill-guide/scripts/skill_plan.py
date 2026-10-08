#!/usr/bin/env python3
"""Read-only checks of a small, agent-authored plan. Python 3.11+, stdlib only."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def contract(value):
    require(isinstance(value, dict) and set(value) == {'format', 'fields'}, 'Invalid contract')
    require(isinstance(value['format'], str) and bool(value['format'].strip()), 'Format required')
    require(isinstance(value['fields'], list) and all(isinstance(x, str) and x.strip()
            for x in value['fields']), 'fields must contain nonempty names')
    return value


def review(plan):
    """Removal results concern this supplied matrix, not actual semantic coverage."""
    require(isinstance(plan, dict) and set(plan) == {'stages', 'requirements'}, 'Invalid plan fields')
    stages = plan['stages']
    require(isinstance(stages, list) and len(stages) <= 12, 'Use at most 12 stages')
    by_id = {}
    handoffs = []
    for stage in stages:
        require(isinstance(stage, dict) and set(stage) == {'id', 'kind', 'name', 'inputs', 'output'},
                'Invalid stage fields')
        key = stage['id']
        require(isinstance(key, str) and key.strip() and key not in by_id, 'Unique stage ID required')
        require(stage['kind'] in {'skill', 'prompt', 'tool'}, 'Invalid stage kind')
        require(isinstance(stage['name'], str) and stage['name'].strip(), 'Stage name required')
        contract(stage['output'])
        require(isinstance(stage['inputs'], list), 'inputs must be a list')
        for item in stage['inputs']:
            require(isinstance(item, dict) and set(item) == {'from', 'contract', 'adapter'}, 'Invalid input')
            expected = contract(item['contract'])
            source = item['from']
            require(isinstance(source, str) and (source == '$material' or source in by_id),
                    'Inputs must reference material or an earlier stage; cycles are not allowed')
            adapter = item['adapter']
            require(adapter is None or isinstance(adapter, str) and adapter.strip(), 'Invalid adapter')
            offered = by_id[source]['output'] if source != '$material' else None
            unknown = offered is None or 'unknown' in {offered['format'], expected['format']}
            missing = sorted(set(expected['fields']) - set(offered['fields'])) if offered else []
            compatible = offered is not None and offered['format'] == expected['format'] and not missing
            status = 'unknown' if unknown else ('direct' if compatible else
                     ('adapter_required' if adapter else 'incompatible'))
            handoffs.append({'from': source, 'to': key, 'status': status, 'missing_fields': missing,
                             'adapter': adapter, 'verified': False})
        by_id[key] = stage
    requirements = plan['requirements']
    require(isinstance(requirements, list), 'requirements must be a list')
    seen = set()
    for req in requirements:
        require(isinstance(req, dict) and set(req) == {'id', 'critical', 'providers'}, 'Invalid requirement')
        require(isinstance(req['id'], str) and req['id'].strip() and req['id'] not in seen,
                'Unique requirement ID required')
        seen.add(req['id'])
        require(type(req['critical']) is bool and isinstance(req['providers'], list), 'Invalid requirement types')
        for provider in req['providers']:
            require(isinstance(provider, dict) and set(provider) == {'stage', 'evidence', 'status'}, 'Invalid provider')
            require(provider['stage'] in by_id, 'Unknown provider stage')
            require(isinstance(provider['evidence'], str) and provider['evidence'].strip(), 'Evidence reference required')
            require(provider['status'] in {'documented', 'verified', 'pending'}, 'Invalid evidence status')

    def lost_after(removal):
        removed = set(removal)
        for stage in stages:
            if any(item['from'] in removed for item in stage['inputs']):
                removed.add(stage['id'])
        lost, uncertain = [], []
        for req in requirements:
            if not req['critical']:
                continue
            remaining = [p for p in req['providers'] if p['stage'] not in removed]
            if not remaining:
                lost.append(req['id'])
            elif all(p['status'] == 'pending' for p in remaining):
                uncertain.append(req['id'])
        return removed, lost, uncertain

    _, uncovered, pending = lost_after([])
    removals = []
    for stage in stages:
        if stage['kind'] != 'skill':
            continue
        removed, lost, uncertain = lost_after([stage['id']])
        marginal = sorted(set(lost) - set(uncovered))
        extra_pending = sorted(set(uncertain) - set(pending))
        removals.append({'stage': stage['id'], 'dependent_stages': sorted(removed - {stage['id']}),
                         'critical_requirements_lost': marginal, 'new_pending_requirements': extra_pending,
                         'status': 'necessary_in_matrix' if marginal and not set(marginal) & set(pending) else
                         ('needs_review' if marginal else
                         ('needs_review' if extra_pending else 'removal_candidate'))})
    return {'ok': True, 'uncovered': uncovered, 'pending': pending, 'removals': removals,
            'handoffs': handoffs, 'semantic_validation': False,
            'note': 'Coverage, evidence and contracts were supplied by the caller; inspect actual skills and artifacts.'}


def artifact_check(path, expected, max_bytes=2_000_000):
    """Check a regular local file only. JSON fields are top-level; CSV fields are headers."""
    expected = contract(expected)
    path = Path(path)
    require(expected['format'] in {'file', 'json', 'csv'}, 'Supported checks: file, json, csv')
    require(expected['format'] != 'file' or not expected['fields'], 'file checks cannot validate fields')
    if not path.is_file():
        return {'ok': False, 'status': 'missing_file', 'path': str(path)}
    if path.stat().st_size > max_bytes:
        return {'ok': False, 'status': 'size_limit', 'path': str(path)}
    try:
        with path.open('rb') as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            return {'ok': False, 'status': 'size_limit', 'path': str(path)}
        fields = set()
        if expected['format'] == 'json':
            value = json.loads(raw.decode('utf-8-sig'))
            require(isinstance(value, dict), 'JSON must be an object')
            fields = set(value)
        elif expected['format'] == 'csv':
            import io
            fields = set(next(csv.reader(io.StringIO(raw.decode('utf-8-sig'))), []))
        missing = sorted(set(expected['fields']) - fields)
        return {'ok': not missing, 'status': 'missing_fields' if missing else 'passed',
                'path': str(path), 'missing_fields': missing, 'semantic_validation': False}
    except (ValueError, UnicodeError, csv.Error) as exc:
        return {'ok': False, 'status': 'invalid_content', 'path': str(path), 'error': str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('review').add_argument('--plan', required=True)
    check = sub.add_parser('check')
    check.add_argument('--path', required=True)
    check.add_argument('--format', required=True, choices=('file', 'json', 'csv'))
    check.add_argument('--field', action='append', default=[])
    args = parser.parse_args()
    try:
        result = review(json.loads(Path(args.plan).read_text(encoding='utf-8-sig'))) if args.command == 'review' else artifact_check(
            args.path, {'format': args.format, 'fields': args.field})
    except (ValueError, TypeError, KeyError, OSError) as exc:
        result = {'ok': False, 'error': str(exc)}
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
