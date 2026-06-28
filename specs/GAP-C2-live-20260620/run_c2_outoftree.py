"""Variant harness using an OUT-OF-TREE scratch dir to avoid the project's
pyproject.toml `addopts = ['-v']` leaking into the subprocess (which forces
pytest into tree-style output the validator's regex can't parse).

This mirrors the production code path, where `scratch_dir=None` defaults
to `tempfile.TemporaryDirectory(prefix='devloop_testexec_')` under %TEMP%.
"""
import json
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, r'C:\Users\v-liyuanjun\source\repos\devloop')

from devloop.spec_phase.schemas import Spec
from devloop.spec_phase.validators.test_executability import (
    extract_test_references,
    verify_spec_test_executability,
)

ws = pathlib.Path(r'C:\Users\v-liyuanjun\source\repos\devloop\specs\GAP-C2-live-20260620')
spec = Spec.model_validate(json.loads((ws / 'spec.json').read_text(encoding='utf-8')))

refs = extract_test_references(spec)
print(f'EXTRACTED: {refs}')

# Use a temp dir OUTSIDE the project to avoid pytest discovering the project's
# pyproject.toml when walking up from rootdir.
with tempfile.TemporaryDirectory(prefix='devloop_c2_live_') as tmp:
    scratch = pathlib.Path(tmp)
    tests_dir = scratch / 'tests'
    tests_dir.mkdir(parents=True)
    (tests_dir / '__init__.py').write_text('', encoding='utf-8')
    (tests_dir / 'test_gap_c2_ok.py').write_text(
        'def test_baseline():\n    pass\n', encoding='utf-8'
    )
    (tests_dir / 'test_gap_c2_brokenimport.py').write_text(
        'from nonexistent_module import nope\n\ndef test_x():\n    pass\n',
        encoding='utf-8',
    )
    (tests_dir / 'test_gap_c2_nofunc.py').write_text(
        'def test_present():\n    pass\n', encoding='utf-8'
    )

    problems = verify_spec_test_executability(
        spec, target_repo=scratch, scratch_dir=scratch
    )
    print(f'PROBLEMS: {len(problems)}')
    for p in problems:
        print(f'  - {p.test_path}::{p.test_name}  kind={p.problem}')
        print(f'    detail: {p.detail[:240]}')

    # Copy the stub tree into the workspace for the writeup record.
    out = ws / 'scratch_outoftree_snapshot'
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(scratch, out)
