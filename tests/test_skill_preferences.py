import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
SCRIPTS = BASE / 'skill-guide/scripts'
sys.dont_write_bytecode = True
sys.path.insert(0, str(SCRIPTS))
import skill_preferences as P
import skill_index as I


class PreferenceBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = self.root / 'data/preferences.json'
        self.project = self.root / 'project'
        self.project.mkdir()
        self.a = self.skill('a', 'same-name', 'Read PDF reports')
        self.b = self.skill('b', 'same-name', 'Read PDF reports')

    def tearDown(self):
        self.temp.cleanup()

    def skill(self, folder, name, description):
        path = self.root / 'skills' / folder / 'SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text(f'---\nname: {name}\ndescription: {description}\n---\nRead sources.\n', encoding='utf-8')
        return path

    def spec(self, kind='prefer', path=None, scope=None, rule_id=None, task_tags=None):
        result = {'kind': kind, 'scope': scope or {'kind': 'personal'},
                  'task_tags': task_tags if task_tags is not None else ['paper'],
                  'instruction': '用户已明确指定的规则', 'reason': 'explicit user preference'}
        if kind != 'prompt':
            result['target'] = {'path': str(path or self.a), 'name': 'same-name'}
        if rule_id:
            result['id'] = rule_id
        return result

    def add(self, **kwargs):
        return P.mutate(self.store, 'apply', authorized=True, spec=self.spec(**kwargs))['rule']

    def entries(self):
        return [{'id': I.identity(path), 'path': str(path), 'name': 'same-name',
                 'description': 'Read PDF reports', 'availability': 'unknown',
                 'stale': False, 'active_scope': True, 'metadata_status': 'parsed',
                 'files': {'hashes': {'skill': hashlib.sha256(path.read_bytes()).hexdigest()}}}
                for path in (self.a, self.b)]

    def ctx(self, workspace=None, tags=None, overrides=(), entries=None):
        return P.context(P.load(self.store), entries if entries is not None else self.entries(),
                         str(workspace or self.project), tags if tags is not None else ['paper'], overrides)

    def candidates(self, ctx, terms='pdf', limit=5):
        return I.query({'entries': self.entries()}, terms, limit, P.load(self.store), [], ctx)[0]

    def test_explicit_authorization_required_and_no_file_created(self):
        with self.assertRaises(P.PreferenceError):
            P.mutate(self.store, 'apply', spec=self.spec())
        self.assertFalse(self.store.exists())
        self.assertFalse(self.store.parent.exists())

    def test_legacy_aliases_read_only_and_preserved_on_authorized_upgrade(self):
        self.store.parent.mkdir()
        old = {'aliases': {I.identity(self.a): ['论文精读']}}
        self.store.write_text(json.dumps(old), encoding='utf-8')
        before = self.store.read_bytes()
        self.assertEqual(P.load(self.store)['rules'], [])
        self.assertEqual(self.store.read_bytes(), before)
        self.add()
        self.assertEqual(P.load(self.store)['aliases'], old['aliases'])
        self.assertEqual(P.load(self.store)['schema_version'], 1)

    def test_create_update_disable_enable_remove_exact_rule(self):
        first = self.add()
        second = self.add(kind='prompt')
        self.add(kind='avoid', rule_id=first['id'])
        data = P.load(self.store)
        updated = next(r for r in data['rules'] if r['id'] == first['id'])
        self.assertEqual(updated['kind'], 'avoid')
        self.assertEqual(updated['created_at'], first['created_at'])
        P.mutate(self.store, 'disable', True, rule_id=first['id'])
        self.assertNotIn(first['id'], [r['id'] for r in self.ctx()['rules']])
        P.mutate(self.store, 'enable', True, rule_id=first['id'])
        self.assertIn(first['id'], [r['id'] for r in self.ctx()['rules']])
        P.mutate(self.store, 'remove', True, rule_id=first['id'])
        self.assertEqual([r['id'] for r in P.load(self.store)['rules']], [second['id']])
        self.assertTrue(self.a.exists())

    def test_project_scope_includes_child_but_not_prefix_or_other_project(self):
        self.add(scope={'kind': 'project', 'path': str(self.project)})
        self.assertEqual(len(self.ctx(workspace=self.project / 'child')['rules']), 1)
        self.assertEqual(self.ctx(workspace=self.root / 'project-other')['rules'], [])
        self.assertEqual(self.ctx(workspace=self.root / 'another')['rules'], [])

    def test_all_tags_required_and_matching_is_case_insensitive(self):
        self.add(task_tags=['Paper', 'close-reading'])
        self.assertEqual(self.ctx(tags=['paper'])['rules'], [])
        self.assertEqual(len(self.ctx(tags=['PAPER', 'close-reading', 'pdf'])['rules']), 1)

    def test_tag_catalog_enables_rematching_without_leaking_other_project_scope(self):
        self.add(task_tags=['论文', '精读'])
        self.add(kind='prompt', task_tags=['other-project-only'],
                 scope={'kind': 'project', 'path': str(self.root / 'other')})
        ctx = self.ctx(tags=['paper'])
        self.assertEqual(ctx['rules'], [])
        self.assertEqual(ctx['available_task_tags'], ['精读', '论文'])
        self.assertEqual(len(self.ctx(tags=['论文', '精读'])['rules']), 1)

    def test_same_name_other_path_is_not_bound(self):
        self.add(kind='exclude')
        candidates = self.candidates(self.ctx())
        self.assertEqual([c['id'] for c in candidates], [I.identity(self.b)])

    def test_personal_exclusion_overridden_by_project_preference(self):
        self.add(kind='exclude')
        project_rule = self.add(scope={'kind': 'project', 'path': str(self.project)})
        ctx = self.ctx()
        self.assertEqual(ctx['decisions'][I.identity(self.a)]['kind'], 'prefer')
        self.assertEqual(ctx['decisions'][I.identity(self.a)]['rule_ids'], [project_rule['id']])

    def test_current_explicit_choice_overrides_exclusion_without_rewriting(self):
        self.add(kind='exclude')
        before = self.store.read_bytes()
        ctx = self.ctx(overrides=[I.identity(self.a)])
        self.assertFalse(ctx['decisions'])
        self.assertEqual(len(ctx['overridden']), 1)
        self.assertEqual(len(self.candidates(ctx)), 2)
        self.assertEqual([c['id'] for c in self.candidates(ctx, terms='unmatched')], [I.identity(self.a)])
        self.assertEqual(self.store.read_bytes(), before)

    def test_same_priority_conflict_is_reported_and_not_silently_resolved(self):
        self.add()
        self.add(kind='avoid')
        ctx = self.ctx()
        self.assertTrue(ctx['requires_review'])
        self.assertNotIn(I.identity(self.a), ctx['decisions'])
        candidate = next(c for c in self.candidates(ctx) if c['id'] == I.identity(self.a))
        self.assertTrue(candidate['preference_conflict'])

    def test_avoid_and_exclude_agree_on_direction(self):
        self.add(kind='avoid')
        self.add(kind='exclude')
        ctx = self.ctx()
        self.assertFalse(ctx['requires_review'])
        self.assertEqual(ctx['decisions'][I.identity(self.a)]['kind'], 'exclude')

    def test_preferred_candidate_can_be_retrieved_without_keyword_match(self):
        self.add()
        result = self.candidates(self.ctx(), terms='unmatched')
        self.assertEqual([c['id'] for c in result], [I.identity(self.a)])
        self.assertEqual(result[0]['retrieval_reason'], 'preference')
        self.assertEqual(result[0]['matched_terms'], [])

    def test_avoid_is_soft_and_kept_when_no_alternative(self):
        self.add(kind='avoid')
        result = self.candidates(self.ctx())
        self.assertEqual(result[0]['id'], I.identity(self.b))
        self.assertIn(I.identity(self.a), [c['id'] for c in result])

    def test_content_changes_need_review_but_keep_exact_identity_exclusion(self):
        self.add(kind='exclude')
        self.a.write_text(self.a.read_text(encoding='utf-8') + 'Changed capability', encoding='utf-8')
        ctx = self.ctx()
        self.assertEqual(ctx['rules'][0]['binding_status'], 'changed')
        self.assertNotIn(I.identity(self.a), [c['id'] for c in self.candidates(ctx)])

    def test_missing_target_preserved_without_rebinding_same_name(self):
        self.add()
        before = self.store.read_bytes()
        ctx = self.ctx(entries=[self.entries()[1]])
        self.assertEqual(ctx['rules'][0]['binding_status'], 'missing')
        self.assertFalse(ctx['decisions'])
        self.assertEqual(self.store.read_bytes(), before)

    def test_disabled_out_of_scope_and_stale_statuses(self):
        self.add()
        for field, value, status in [('availability', 'disabled', 'disabled'),
                                     ('active_scope', False, 'out_of_scope'),
                                     ('stale', True, 'needs_review')]:
            entries = self.entries()
            entries[0][field] = value
            self.assertEqual(self.ctx(entries=entries)['rules'][0]['binding_status'], status)

    def test_prompt_rules_have_no_target_and_keep_scope_priority(self):
        self.add(kind='prompt')
        self.add(kind='prompt', scope={'kind': 'project', 'path': str(self.project)})
        ctx = self.ctx()
        self.assertEqual([r['priority'] for r in ctx['rules']], [2, 1])
        self.assertTrue(all(r['target'] is None for r in ctx['rules']))
        self.assertFalse(ctx['decisions'])

    def test_corruption_and_future_schema_preserved_on_query_and_write(self):
        self.store.parent.mkdir()
        for contents in ('{broken', '{"schema_version":2,"rules":[]}'):
            self.store.write_text(contents, encoding='utf-8')
            before = self.store.read_bytes()
            warnings = []
            self.assertEqual(P.load_for_query(self.store, warnings)['rules'], [])
            self.assertTrue(warnings)
            with self.assertRaises(P.PreferenceError):
                self.add()
            self.assertEqual(self.store.read_bytes(), before)

    def test_busy_lock_does_not_overwrite_or_remove_other_lock(self):
        self.add()
        before = self.store.read_bytes()
        lock = self.store.with_name('preferences.json.lock')
        lock.write_text('another writer', encoding='utf-8')
        with self.assertRaises(P.PreferenceError):
            self.add(kind='avoid')
        self.assertEqual(self.store.read_bytes(), before)
        self.assertEqual(lock.read_text(), 'another writer')

    def test_atomic_replace_failure_preserves_old_file_and_cleans_own_lock(self):
        self.add()
        before = self.store.read_bytes()
        with patch.object(P.os, 'replace', side_effect=PermissionError('simulated')):
            with self.assertRaises(PermissionError):
                self.add(kind='avoid')
        self.assertEqual(self.store.read_bytes(), before)
        self.assertFalse(self.store.with_name('preferences.json.lock').exists())
        self.assertFalse(list(self.store.parent.glob('.preferences-*.tmp')))

    def test_unknown_rule_and_invalid_spec_do_not_mutate_store(self):
        self.add()
        before = self.store.read_bytes()
        with self.assertRaises(P.PreferenceError):
            P.mutate(self.store, 'remove', True, rule_id='nonexistent')
        invalid = self.spec()
        invalid['chat_log'] = 'must not store chat logs'
        with self.assertRaises(P.PreferenceError):
            P.mutate(self.store, 'apply', True, spec=invalid)
        self.assertEqual(self.store.read_bytes(), before)

    def test_wrong_skill_name_and_invalid_rule_document_are_rejected(self):
        self.add()
        before = self.store.read_bytes()
        spec = self.spec()
        spec['target']['name'] = 'invented-name'
        with self.assertRaises(P.PreferenceError):
            P.mutate(self.store, 'apply', True, spec=spec)
        with self.assertRaises(P.PreferenceError):
            P.mutate(self.store, 'apply', True, spec=['invalid'])
        self.assertEqual(self.store.read_bytes(), before)

    def cli(self, script, *args):
        run = subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                             text=True, encoding='utf-8', capture_output=True)
        return run, json.loads(run.stdout)

    def test_cli_write_query_and_authoritative_preferences_survive_cache_fallback(self):
        rule_file = self.root / 'rule.json'
        rule_file.write_text(json.dumps(self.spec()), encoding='utf-8')
        run, result = self.cli('skill_preferences.py', 'apply', '--file', str(self.store),
                              '--rule-file', str(rule_file))
        self.assertEqual(run.returncode, 2)
        self.assertFalse(result['persisted'])
        run, result = self.cli('skill_preferences.py', 'apply', '--file', str(self.store),
                              '--rule-file', str(rule_file), '--authorized')
        self.assertEqual(run.returncode, 0)
        self.assertTrue(result['persisted'])
        before = self.store.read_bytes()
        unwritable_cache = self.root / 'not-a-directory'
        unwritable_cache.write_text('occupied', encoding='utf-8')
        run, result = self.cli('skill_index.py', 'query', '--codex-home', str(self.root / 'empty-home'),
                              '--root', str(self.root / 'skills'), '--workspace', str(self.project),
                              '--cache-dir', str(unwritable_cache), '--preferences-file', str(self.store),
                              '--terms', 'unmatched-term', '--tag', 'paper')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertFalse(result['cache_persisted'])
        self.assertEqual([c['id'] for c in result['candidates']], [I.identity(self.a)])
        self.assertEqual(self.store.read_bytes(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
