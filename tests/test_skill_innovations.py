import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skill-guide/scripts'
sys.path.insert(0, str(SCRIPTS))
import skill_plan as C
import skill_workflows as W


def stage(key, kind='skill', inputs=None, fmt='json', fields=None):
    return {'id': key, 'kind': kind, 'name': key, 'inputs': inputs or [],
            'output': {'format': fmt, 'fields': fields or ['source', 'claim']}}


def requirement(key, providers, status='documented'):
    return {'id': key, 'critical': True, 'providers': [
        {'stage': name, 'evidence': 'SKILL.md reading section', 'status': status} for name in providers]}


class CompositionTests(unittest.TestCase):
    def test_redundant_candidates_not_marked_necessary(self):
        plan = {'stages': [stage('a'), stage('b'), stage('format', 'prompt')], 'requirements': [
            requirement('read', ['a', 'b']), requirement('format', ['format'])]}
        result = C.review(plan)
        self.assertEqual([r['status'] for r in result['removals']], ['removal_candidate'] * 2)
        # Removing one requires recomputing; do not remove both at once.
        plan['stages'].pop(1)
        plan['requirements'][0]['providers'].pop(1)
        self.assertEqual(C.review(plan)['removals'][0]['status'], 'necessary_in_matrix')

    def test_dependency_cascade_preserves_needed_upstream_stage(self):
        handoff = {'from': 'a', 'contract': {'format': 'json', 'fields': ['source']}, 'adapter': None}
        result = C.review({'stages': [stage('a'), stage('b', inputs=[handoff])],
                           'requirements': [requirement('final', ['b'])]})
        self.assertEqual(result['removals'][0]['critical_requirements_lost'], ['final'])
        self.assertEqual(result['removals'][0]['dependent_stages'], ['b'])
        self.assertEqual(result['handoffs'][0]['status'], 'direct')
        self.assertFalse(result['handoffs'][0]['verified'])

    def test_handoff_missing_fields_adapter_and_unknown(self):
        inp = {'from': 'a', 'contract': {'format': 'csv', 'fields': ['evidence']}, 'adapter': None}
        plan = {'stages': [stage('a'), stage('b', inputs=[inp])], 'requirements': []}
        self.assertEqual(C.review(plan)['handoffs'][0]['status'], 'incompatible')
        inp['adapter'] = 'bounded conversion, pending source verification'
        self.assertEqual(C.review(plan)['handoffs'][0]['status'], 'adapter_required')
        plan['stages'][0]['output']['format'] = 'unknown'
        self.assertEqual(C.review(plan)['handoffs'][0]['status'], 'unknown')

    def test_cycles_duplicate_ids_and_unbound_providers_rejected(self):
        for plan in [
            {'stages': [stage('a'), stage('a')], 'requirements': []},
            {'stages': [stage('a', inputs=[{'from': 'a', 'contract': {'format': 'json', 'fields': []}, 'adapter': None}])], 'requirements': []},
            {'stages': [], 'requirements': [requirement('read', ['missing'])]}]:
            with self.assertRaises(ValueError):
                C.review(plan)

    def test_pending_and_preexisting_gaps_not_certified(self):
        result = C.review({'stages': [stage('a')], 'requirements': [
            requirement('maybe', ['a'], 'pending'), requirement('gap', [])]})
        self.assertEqual(result['pending'], ['maybe'])
        self.assertEqual(result['uncovered'], ['gap'])
        self.assertEqual(result['removals'][0]['critical_requirements_lost'], ['maybe'])
        self.assertEqual(result['removals'][0]['status'], 'needs_review')

    def test_json_csv_missing_invalid_and_size_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'result'
            expected = {'format': 'json', 'fields': ['source']}
            self.assertEqual(C.artifact_check(path, expected)['status'], 'missing_file')
            path.write_text('{"source":"paper", "claim":"x"}', encoding='utf-8')
            original = path.read_bytes()
            self.assertTrue(C.artifact_check(path, expected)['ok'])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(C.artifact_check(path, expected, 3)['status'], 'size_limit')
            expected['fields'] = ['missing']
            self.assertEqual(C.artifact_check(path, expected)['status'], 'missing_fields')
            path.write_text('[]', encoding='utf-8')
            self.assertEqual(C.artifact_check(path, expected)['status'], 'invalid_content')
            path.write_text('\ufeffsource,claim\npaper,x\n', encoding='utf-8')
            self.assertTrue(C.artifact_check(path, {'format': 'csv', 'fields': ['source']})['ok'])
            with self.assertRaises(ValueError):
                C.artifact_check(path, {'format': 'file', 'fields': ['source']})


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = self.root / 'data/workflows.json'
        self.skill = self.root / 'skills/read/SKILL.md'
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text('---\nname: reader\ndescription: Read papers\n---\nReading process\n', encoding='utf-8')
        self.resource = self.skill.parent / 'reading.md'
        self.resource.write_text('Preserve sources', encoding='utf-8')
        self.target = W.bind(self.skill, ['reading.md'])
        self.spec = {'id': 'paper-comparison', 'name': 'Paper comparison', 'scope': {'kind': 'personal'},
            'task_tags': ['paper'], 'input_type': 'pdf', 'output_type': 'markdown',
            'constraints': {'citation': 'required'}, 'environment': {'pdf_tool': 'available'},
            'stages': [{'kind': 'skill', 'role': 'read and compare sources', 'input_type': 'pdf',
                        'output_type': 'markdown', 'target': self.target}],
            'evidence': {'status': 'used', 'checked': 'Source citations were checked',
                         'limits': 'Content quality must be checked for each task'}}

    def tearDown(self):
        self.temp.cleanup()

    def apply(self):
        return W.mutate(self.store, 'apply', True, self.spec)

    def query(self, **changes):
        args = {'workspace': str(self.root), 'task_tags': ['paper'], 'input_type': 'pdf',
            'output_type': 'markdown', 'constraints': {'citation': 'required'},
            'environment': {'pdf_tool': 'available'}, 'active_skill_ids': [self.target['id']]}
        args.update(changes)
        return W.candidates(W.load(self.store), **args)

    def test_read_only_missing_store_and_no_authorization(self):
        self.assertEqual(W.load(self.store)['recipes'], [])
        self.assertFalse(self.store.parent.exists())
        with self.assertRaises(ValueError):
            W.mutate(self.store, 'apply', spec=self.spec)
        self.assertFalse(self.store.parent.exists())

    def test_saved_recipe_matches_but_still_requires_user_review(self):
        self.apply()
        original = self.store.read_bytes()
        result = self.query()[0]
        self.assertEqual(result['status'], 'eligible_for_review')
        self.assertFalse(result['semantic_validation'])
        self.assertEqual(self.store.read_bytes(), original)
        self.assertEqual(self.query(input_type='image'), [])
        self.assertEqual(self.query(task_tags=['code']), [])

    def test_unknown_conditions_and_host_not_assumed_ready(self):
        self.apply()
        result = self.query(environment={}, active_skill_ids=None)[0]
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(len(result['unknown_conditions']), 2)
        self.assertEqual(self.query(active_skill_ids=[])[0]['status'], 'blocked')
        self.assertEqual(self.query(constraints={'citation': 'optional'})[0]['status'], 'blocked')

    def test_query_caps_bindings_and_gives_project_priority(self):
        self.apply()
        for number in range(6):
            self.spec['id'] = 'project-' + str(number)
            self.spec['scope'] = {'kind': 'project', 'path': str(self.root)}
            self.apply()
        with patch.object(W, 'binding_status', wraps=W.binding_status) as check:
            found = self.query()
            self.assertEqual(len(found), 5)
            self.assertEqual(check.call_count, 5)
        self.assertTrue(all(item['recipe']['scope']['kind'] == 'project' for item in found))

    def test_project_scope_is_path_containment_not_prefix(self):
        project = self.root / 'project'
        self.spec['scope'] = {'kind': 'project', 'path': str(project)}
        self.apply()
        self.assertEqual(len(self.query(workspace=str(project / 'sub'))), 1)
        self.assertEqual(self.query(workspace=str(self.root / 'project-other')), [])

    def test_skill_resource_and_config_drift_require_review(self):
        self.apply()
        self.resource.write_text('Changed reading process', encoding='utf-8')
        self.assertEqual(self.query()[0]['bindings'][0]['status'], 'changed')
        self.resource.write_text('Preserve sources', encoding='utf-8')
        config = self.skill.parent / 'agents/openai.yaml'
        config.parent.mkdir()
        config.write_text('policy:\n  allow_implicit_invocation: false\n', encoding='utf-8')
        self.assertEqual(self.query()[0]['status'], 'needs_review')
        config.unlink()
        self.skill.write_text(self.skill.read_text(encoding='utf-8') + 'New rule', encoding='utf-8')
        self.assertEqual(self.query()[0]['bindings'][0]['status'], 'changed')

    def test_same_named_skill_does_not_rebind_missing_target(self):
        self.apply()
        other = self.root / 'other/SKILL.md'
        other.parent.mkdir()
        other.write_bytes(self.skill.read_bytes())
        self.skill.unlink()
        result = self.query(active_skill_ids=[W.P.identity(other)])[0]
        self.assertEqual(result['status'], 'blocked')
        self.assertNotEqual(result['bindings'][0]['id'], W.P.identity(other))

    def test_unconfirmed_stale_and_extra_material_fields_rejected(self):
        for change in ('unconfirmed', 'material', 'stale'):
            spec = copy.deepcopy(self.spec)
            if change == 'unconfirmed':
                spec['evidence']['status'] = 'proposed'
            elif change == 'material':
                spec['task_material'] = 'should not persist'
            else:
                self.resource.write_text('Changed', encoding='utf-8')
            with self.assertRaises(ValueError):
                W.mutate(self.store, 'apply', True, spec)
            self.assertFalse(self.store.exists())

    def test_resource_escape_rejected(self):
        with self.assertRaises(ValueError):
            W.bind(self.skill, ['../../outside.md'])

    def test_disable_enable_remove_and_unknown_id(self):
        self.apply()
        created = W.load(self.store)['recipes'][0]['created_at']
        W.mutate(self.store, 'disable', True, recipe_id=self.spec['id'])
        self.assertEqual(self.query(), [])
        W.mutate(self.store, 'enable', True, recipe_id=self.spec['id'])
        self.apply()
        self.assertEqual(W.load(self.store)['recipes'][0]['created_at'], created)
        before = self.store.read_bytes()
        with self.assertRaises(ValueError):
            W.mutate(self.store, 'remove', True, recipe_id='unknown')
        self.assertEqual(self.store.read_bytes(), before)
        W.mutate(self.store, 'remove', True, recipe_id=self.spec['id'])
        self.assertEqual(W.load(self.store)['recipes'], [])

    def test_corrupt_future_schema_lock_and_failed_replace_preserve_original(self):
        self.store.parent.mkdir()
        for raw in ('broken', '{"schema_version":2,"recipes":[]}'):
            self.store.write_text(raw, encoding='utf-8')
            with self.assertRaises(ValueError):
                self.apply()
            self.assertEqual(self.store.read_text(encoding='utf-8'), raw)
        self.store.unlink()
        self.apply()
        original = self.store.read_bytes()
        lock = self.store.with_name('workflows.json.lock')
        lock.write_text('busy', encoding='utf-8')
        with self.assertRaises(W.P.PreferenceError):
            self.apply()
        self.assertEqual(self.store.read_bytes(), original)
        lock.unlink()
        with patch.object(W.os, 'replace', side_effect=PermissionError('read-only')):
            with self.assertRaises(PermissionError):
                self.apply()
        self.assertEqual(self.store.read_bytes(), original)
        self.assertEqual(list(self.store.parent.glob('.workflows-*')), [])

    def test_cli_bind_and_list_never_write_workflow_data(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / 'skill_workflows.py'), 'bind',
            '--path', str(self.skill), '--file', str(self.store)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['target']['id'], self.target['id'])
        self.assertFalse(self.store.parent.exists())


if __name__ == '__main__':
    unittest.main()
