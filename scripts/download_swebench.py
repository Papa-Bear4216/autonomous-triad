import urllib.request
import json
from pathlib import Path

url = "https://datasets-server.huggingface.co/rows?dataset=princeton-nlp%2FSWE-bench_Verified&config=default&split=test&offset=0&limit=30"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode("utf-8"))

rows = data.get("rows", [])[:30]
print(f"Total rows fetched: {len(rows)}")

def parse_list_or_str(val):
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return val

extracted = []
for item in rows:
    row = item.get("row", {})
    inst = {
        "instance_id": row.get("instance_id"),
        "repo": row.get("repo"),
        "base_commit": row.get("base_commit"),
        "problem_statement": row.get("problem_statement"),
        "test_patch": row.get("test_patch"),
        "patch": row.get("patch"),
        "FAIL_TO_PASS": parse_list_or_str(row.get("FAIL_TO_PASS")),
        "PASS_TO_PASS": parse_list_or_str(row.get("PASS_TO_PASS")),
        "version": row.get("version"),
        "difficulty": row.get("difficulty"),
    }
    extracted.append(inst)

out_file = Path("triad/bench/swebench_instances.json")
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(extracted, f, indent=2, ensure_ascii=False)

print(f"Successfully saved {len(extracted)} instances to {out_file.resolve()}")
if extracted:
    sample = extracted[0]
    print(f"Sample instance ID: {sample['instance_id']}")
    print(f"Repo: {sample['repo']}")
    print(f"Base commit: {sample['base_commit']}")
    print(f"FAIL_TO_PASS type: {type(sample['FAIL_TO_PASS'])}, value: {sample['FAIL_TO_PASS']}")
    print(f"PASS_TO_PASS type: {type(sample['PASS_TO_PASS'])}, count: {len(sample['PASS_TO_PASS']) if isinstance(sample['PASS_TO_PASS'], list) else len(str(sample['PASS_TO_PASS']))}")
    print(f"Problem statement length: {len(sample['problem_statement'] or '')}")
    print(f"Patch length: {len(sample['patch'] or '')}")
    print(f"Test patch length: {len(sample['test_patch'] or '')}")
