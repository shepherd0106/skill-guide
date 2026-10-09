"""Validate source and build a skill-only ZIP; no personal data is bundled."""
import ast
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import zipfile

BASE = Path(__file__).resolve().parents[1]
PACKAGE = BASE / 'skill-guide'
sys.path.insert(0, str(PACKAGE / 'scripts'))
import skill_index as I


def official_validation(package, validator):
    """Attempt the installed checker; missing optional dependencies are explicit."""
    if not validator.is_file():
        return {'status': 'unavailable', 'attempted': False, 'reason': 'Validator file not found'}
    try:
        run = subprocess.run([sys.executable, str(validator), str(package)],
                             capture_output=True, text=True, encoding='utf-8',
                             timeout=30, env={**os.environ, 'PYTHONUTF8': '1'})
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'status': 'unavailable', 'attempted': True, 'reason': str(error)}
    diagnostics = (run.stdout + run.stderr).strip()
    if run.returncode == 0:
        status = 'passed'
    elif "ModuleNotFoundError: No module named 'yaml'" in diagnostics:
        status = 'unavailable'
    else:
        status = 'failed'
    return {'status': status, 'attempted': True, 'returncode': run.returncode,
            'diagnostics': diagnostics[-4000:]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validator', type=Path, default=Path(os.environ.get(
        'CODEX_HOME', str(Path.home() / '.codex'))) / 'skills/.system/skill-creator/scripts/quick_validate.py')
    args = parser.parse_args()
    files = sorted(p for p in PACKAGE.rglob('*') if p.is_file())
    required = {'SKILL.md', 'agents/openai.yaml', 'scripts/skill_index.py',
                'scripts/skill_preferences.py', 'scripts/skill_plan.py', 'scripts/skill_workflows.py'}
    assert required <= {p.relative_to(PACKAGE).as_posix() for p in files}, 'Missing required package files'
    allowed = {'agents': '.yaml', 'scripts': '.py', 'references': '.md'}
    for path in files:
        relative = path.relative_to(PACKAGE)
        assert relative.as_posix() == 'SKILL.md' or (len(relative.parts) == 2 and
            relative.parts[0] in allowed and path.suffix == allowed[relative.parts[0]]), ('Unexpected package file', relative)
    assert not any(p.suffix in {'.pyc', '.json', '.zip'} or '__pycache__' in p.parts for p in files)
    for path in files:
        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    raw = (PACKAGE / 'SKILL.md').read_bytes()
    meta = I.metadata(raw)
    assert meta['metadata_status'] == 'parsed' and meta['name'] == 'skill-guide'
    front = raw.decode('utf-8').split('---', 2)[1]
    assert set(re.findall(r'^([a-z_]+):', front, re.M)) == {'name', 'description'}
    assert len(meta['description']) <= 1024
    ui = (PACKAGE / 'agents/openai.yaml').read_text(encoding='utf-8')
    strings = {key: json.loads(value) for key, value in re.findall(r'^  (\w+): (".*")$', ui, re.M)}
    assert 25 <= len(strings['short_description']) <= 64
    assert '$skill-guide' in strings['default_prompt']
    assert 'policy:' not in ui, 'Preserve existing default invocation policy'
    for path in files + [BASE / 'README.md', BASE / 'README.en.md']:
        if path.suffix != '.md':
            continue
        content = path.read_text(encoding='utf-8')
        for target in re.findall(r'\]\(([^)]+)\)', content):
            if '://' not in target and not target.startswith('#'):
                assert (path.parent / target.split('#')[0]).is_file(), (path, target)
    for name in ('composition.md', 'workflows.md'):
        for example in re.findall(r'```json\n(.*?)\n```', (PACKAGE / 'references' / name).read_text(encoding='utf-8'), re.S):
            json.loads(example)
    official = official_validation(PACKAGE, args.validator)
    assert official['status'] != 'failed', ('Official validation failed', official)
    output = BASE / 'outputs'
    output.mkdir(exist_ok=True)
    bundle = output / 'skill-guide.zip'
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, 'skill-guide/' + path.relative_to(PACKAGE).as_posix())
    with zipfile.ZipFile(bundle) as archive:
        assert len(archive.namelist()) == len(files)
        for path in files:
            assert archive.read('skill-guide/' + path.relative_to(PACKAGE).as_posix()) == path.read_bytes()
    result = {'package_files': len(files), 'script_syntax': 'passed', 'entry_metadata': 'passed',
              'ui_metadata': 'passed', 'relative_links': 'passed', 'json_examples': 'passed',
              'archive_bytes': 'passed', 'official_validator': official,
              'semantic_validation': 'Requires actual task acceptance checks',
              'manifest': {p.relative_to(PACKAGE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (output / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'manifest'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
