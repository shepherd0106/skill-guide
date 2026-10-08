import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(BASE / 'skill-guide/scripts'))
SPEC = importlib.util.spec_from_file_location('skill_index', BASE / 'skill-guide/scripts/skill_index.py')
INDEX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INDEX)


class IndexBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.skills = self.home / 'skills'
        self.skills.mkdir(parents=True)
        self.cache = self.root / 'cache'
        self.args = SimpleNamespace(command='refresh', codex_home=str(self.home),
            cache_dir=str(self.cache), config=str(self.home / 'config.toml'),
            workspace=str(self.root / 'workspace'), root=[], full=False,
            terms='', limit=5, id=[])
        self.roots = INDEX.roots_for
        self.patcher = patch.object(INDEX, 'roots_for', side_effect=lambda args:
            [r for r in self.roots(args) if Path(r['path']).is_relative_to(self.root)])
        self.patcher.start()
        self.add('one', 'alpha', 'Read PDF reports')

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def add(self, folder, name, description, root=None):
        path = (root or self.skills) / folder / 'SKILL.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'---\nname: {name}\ndescription: {description}\n---\nBody\n', encoding='utf-8')
        return path

    def run_index(self, command='refresh', **kwargs):
        self.args.command = command
        for key, value in kwargs.items():
            setattr(self.args, key, value)
        return INDEX.run(self.args)

    def snapshot(self):
        return json.loads((self.cache / 'skills-index.json').read_text(encoding='utf-8'))

    def test_unchanged_and_resource_change_do_not_read_metadata(self):
        self.assertEqual(self.run_index()['stats']['added'], 1)
        resource = self.skills / 'one' / 'large-resource.txt'
        resource.write_text('resource changed', encoding='utf-8')
        result = self.run_index()
        self.assertEqual(result['stats']['metadata_reads'], 0)
        self.assertEqual(result['stats']['reused'], 1)

    def test_add_modify_remove(self):
        self.run_index()
        self.add('two', 'beta', 'Spreadsheet editing')
        self.assertEqual(self.run_index()['stats']['added'], 1)
        self.add('one', 'alpha', 'Convert PDF to images and inspect layout')
        self.assertEqual(self.run_index()['stats']['changed'], 1)
        (self.skills / 'two' / 'SKILL.md').unlink()
        self.assertEqual(self.run_index()['stats']['removed_from_scope'], 1)

    def test_selected_check_catches_same_stat_content_change(self):
        self.run_index()
        entry = self.snapshot()['entries'][0]
        path = Path(entry['path'])
        original = path.stat()
        raw = path.read_bytes().replace(b'Read PDF reports', b'Edit PDF reports')
        path.write_bytes(raw)
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(self.run_index()['stats']['metadata_reads'], 0)
        result = self.run_index('check', id=[entry['id']])['checks'][0]
        self.assertTrue(result['content_changed'])
        self.assertEqual(self.run_index('refresh', full=True)['stats']['changed'], 1)

    def test_disable_excluded_and_check_reads_current_config(self):
        self.run_index()
        entry = self.snapshot()['entries'][0]
        path = Path(entry['path']).as_posix()
        Path(self.args.config).write_text(f'[[skills.config]]\npath = "{path}"\nenabled = false\n', encoding='utf-8')
        checked = self.run_index('check', id=[entry['id']])['checks'][0]
        self.assertEqual(checked['availability'], 'disabled')
        self.assertTrue(checked['enable_state_changed'])
        self.assertEqual(self.run_index('query', terms='pdf')['matching_count'], 0)

    def test_same_name_kept_separate_and_duplicate_root_merged(self):
        self.add('two', 'alpha', 'Read PDF reports')
        self.args.root = [str(self.skills), str(self.skills)]
        result = self.run_index('query', terms='pdf')
        self.assertEqual(result['matching_count'], 2)
        self.assertEqual(len({e['id'] for e in result['candidates']}), 2)
        self.assertEqual(len(self.snapshot()['entries'][0]['contexts']), 1)

    def test_scan_failure_preserves_stale_records(self):
        self.run_index()
        original_scan = INDEX.scan
        with patch.object(INDEX, 'scan', side_effect=lambda r:
            ([], 'error', ['simulated permission failure']) if r['key'] == INDEX.canonical(self.skills)
            else original_scan(r)):
            result = self.run_index('query', terms='pdf')
        self.assertEqual(result['matching_count'], 1)
        self.assertTrue(result['candidates'][0]['stale'])
        self.assertEqual(result['candidates'][0]['availability'], 'unknown')

    def test_busy_lock_keeps_other_writer_lock_and_cache(self):
        self.run_index()
        index_path = self.cache / 'skills-index.json'
        before = index_path.read_bytes()
        lock = self.cache / 'refresh.lock'
        lock.write_text('other writer', encoding='utf-8')
        self.add('two', 'beta', 'Read PDF reports')
        result = self.run_index('query', terms='pdf')
        self.assertFalse(result['cache_persisted'])
        self.assertEqual(result['matching_count'], 2)
        self.assertEqual(index_path.read_bytes(), before)
        self.assertEqual(lock.read_text(), 'other writer')

    def test_unwritable_cache_works_in_memory(self):
        self.cache.write_text('not a directory', encoding='utf-8')
        result = self.run_index('query', terms='pdf')
        self.assertEqual(result['matching_count'], 1)
        self.assertFalse(result['cache_persisted'])

    def test_read_only_path_check_works_without_index(self):
        self.cache.write_text('not a directory', encoding='utf-8')
        candidate = self.run_index('query', terms='pdf')['candidates'][0]
        checked = self.run_index('check', path=[candidate['path']])['checks'][0]
        self.assertIsNone(checked['content_changed'])
        self.assertEqual(checked['content_hashes'], candidate['content_hashes'])
        self.assertTrue(checked['in_current_scope'])

    def test_corrupt_cache_rebuilt(self):
        self.run_index()
        (self.cache / 'skills-index.json').write_text('{broken', encoding='utf-8')
        result = self.run_index()
        self.assertEqual(result['stats']['added'], 1)
        self.assertTrue(result['warnings'])

    def test_switch_scope_hides_but_preserves_previous_entries(self):
        project_a = self.root / 'project-a'
        project_b = self.root / 'project-b'
        self.add('a', 'project-alpha', 'Special project task', project_a / '.agents/skills')
        self.args.workspace = str(project_a)
        self.assertEqual(self.run_index()['stats']['entries'], 2)
        self.args.workspace = str(project_b)
        result = self.run_index('query', terms='special')
        self.assertEqual(result['matching_count'], 0)
        self.assertEqual(result['stats']['inactive_cached'], 1)
        self.assertEqual(len(self.snapshot()['entries']), 2)
        self.args.workspace = str(project_a)
        self.assertEqual(self.run_index('query', terms='special')['matching_count'], 1)

    def test_multiline_description_explicit_policy_and_invalid_metadata(self):
        self.add('two', 'beta', '>\n  Convert PDF reports\n  into images')
        policy = self.skills / 'two/agents/openai.yaml'
        policy.parent.mkdir()
        policy.write_text('policy:\n  allow_implicit_invocation: false\n', encoding='utf-8')
        invalid = self.skills / 'three/SKILL.md'
        invalid.parent.mkdir()
        invalid.write_text('# No frontmatter', encoding='utf-8')
        self.run_index()
        entries = {e['name']: e for e in self.snapshot()['entries']}
        self.assertEqual(entries['beta']['description'], 'Convert PDF reports into images')
        self.assertFalse(entries['beta']['implicit_invocation'])
        self.assertEqual(entries[None]['metadata_status'], 'invalid')

    def test_preferences_preserved_and_aliases_searchable(self):
        self.run_index()
        entry = self.snapshot()['entries'][0]
        preference = self.cache / 'preferences.json'
        preference.write_text(json.dumps({'aliases': {entry['id']: ['报告排版']}}), encoding='utf-8')
        before = preference.read_bytes()
        result = self.run_index('query', terms='报告排版')
        self.assertEqual(result['matching_count'], 1)
        self.assertEqual(preference.read_bytes(), before)

    def test_periodic_hash_refresh_detects_content_without_timestamp_change(self):
        self.run_index()
        data = self.snapshot()
        data['last_full_check'] = 0
        (self.cache / 'skills-index.json').write_text(json.dumps(data), encoding='utf-8')
        result = self.run_index()
        self.assertTrue(result['stats']['full_hash_check'])
        self.assertGreater(result['stats']['metadata_reads'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
