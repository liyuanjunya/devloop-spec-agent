import json
import pathlib
import sys

sys.path.insert(0, r'C:\Users\v-liyuanjun\source\repos\devloop')

from devloop.spec_phase.schemas import ConsolidatedExploration
from devloop.spec_phase.validators.coverage_gap_detector import detect_coverage_gaps

p = pathlib.Path(
    r'C:\Users\v-liyuanjun\source\repos\devloop\specs\GAP-B2-live-20260620\synthetic_exploration.json'
)
data = json.loads(p.read_text(encoding='utf-8'))
exp = ConsolidatedExploration.model_validate(data)
gaps = detect_coverage_gaps(exp)
print(f'GAPS DETECTED: {len(gaps)}')
for g in gaps:
    print(f'  - kind={g.kind}  detail={g.detail[:120]}')
    print(f'    question={g.suggested_re_explore_question[:200]}')
    print(f'    primary_perspective={g.primary_perspective}')
