"""Quick dump of the v1 spec for review use."""
import json
from pathlib import Path

WORKSPACE = Path(r"C:\Users\v-liyuanjun\source\repos\devloop\specs\case6-live-new-20260620")

data = json.loads((WORKSPACE / "spec.json").read_text(encoding="utf-8"))

print("=== SUMMARY ===")
print(data["summary"])
print()
print("=== USER STORIES ===")
for us in data["user_stories"]:
    print(f"  {us['id']} ({us['priority']}): {us['title']}")
print()
print("=== FRs ===")
for fr in data["functional_requirements"]:
    txt = fr["text"][:240]
    print(f"  {fr['id']}: {txt}")
print()
print("=== SCs ===")
for sc in data["success_criteria"]:
    print(f"  {sc['id']}: {sc['text'][:160]}")
print()
print("=== EDGE CASES ===")
for ec in data["edge_cases"]:
    print(f"  - {ec['description']}")
    h = ec.get("handling", "")[:240]
    print(f"    handling: {h}")
print()
print("=== ASSUMPTIONS ===")
for a in data.get("assumptions", []):
    print(f"  - {a}")
print()
print("=== OUT_OF_SCOPE ===")
for o in data.get("out_of_scope", []):
    print(f"  - {o}")
print()
print("=== KEY ENTITIES ===")
for e in data.get("key_entities", []):
    print(f"  - {e['name']}: {e.get('description','')[:140]}")
print()
print("=== NEEDS_CLARIFICATION ===")
for nc in data["needs_clarification"]:
    print(f"  {nc['id']}: {nc['title']}")
    print(f"    conflict: {nc['conflict'][:200]}")
    print(f"    default:  {nc['recommended_default'][:200]}")
print()
print("=== SELF-CONCERNS ===")
for c in data.get("self_concerns", []):
    print(f"  loc={c['location']}: {c['concern'][:200]}")
