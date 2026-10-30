"""Measure the triage classifier against a hand-labeled golden set before it goes live.

Usage:
    python eval/evaluate.py           # real run with Claude, needs ANTHROPIC_API_KEY (24 calls)
    python eval/evaluate.py --mock    # offline: copies the expected labels, to check the pipeline

Uses the exact prompt and schema from workflow/classifier.json that n8n sends,
and the exact priority rules from workflow/policy.js (run through Node).
"""

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER = json.loads((ROOT / "workflow" / "classifier.json").read_text())
FIELDS = ["category", "impact", "urgency"]


def load_tickets():
    return [json.loads(line) for line in (ROOT / "samples" / "tickets.jsonl").read_text().splitlines() if line.strip()]


def classify_with_claude(client, ticket: dict) -> dict:
    content = f"{CLASSIFIER['instructions']}\n\n<reporter>{ticket['reporter']}</reporter>\n<issue>\n{ticket['text']}\n</issue>"
    message = client.beta.messages.create(
        model=CLASSIFIER["model"],
        max_tokens=2000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"format": {"type": "json_schema", "schema": CLASSIFIER["schema"]}},
        messages=[{"role": "user", "content": content}],
    )
    if message.stop_reason == "refusal":
        return {"category": "other", "impact": "medium", "urgency": "medium", "confidence": 0.0, "summary": "", "reasoning": "refused"}
    return json.loads(next(b.text for b in message.content if b.type == "text"))


def priorities(pairs: list[tuple[str, str]]) -> list[str]:
    """Apply policy.js's priority matrix via Node, so Python never re-implements the rules."""
    script = f"const p=require({json.dumps(str(ROOT / 'workflow' / 'policy.js'))});" \
             f"console.log(JSON.stringify({json.dumps(pairs)}.map(([i,u])=>p.priorityFor(i,u))))"
    return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)


def evaluate(mock: bool = False) -> dict:
    tickets = load_tickets()
    if mock:
        predictions = [{**t["expected"], "confidence": 0.9, "summary": t["text"][:60], "reasoning": "mock"} for t in tickets]
    else:
        import anthropic

        client = anthropic.Anthropic()
        predictions = []
        for t in tickets:
            predictions.append(classify_with_claude(client, t))
            print(f"{t['id']}: {predictions[-1]['category']} / {predictions[-1]['impact']} / {predictions[-1]['urgency']}")

    expected_p = priorities([(t["expected"]["impact"], t["expected"]["urgency"]) for t in tickets])
    predicted_p = priorities([(p["impact"], p["urgency"]) for p in predictions])
    rows = []
    for t, p, ep, pp in zip(tickets, predictions, expected_p, predicted_p):
        rows.append({"id": t["id"], "text": t["text"], **{f"expected_{f}": t["expected"][f] for f in FIELDS},
                     **{f"predicted_{f}": p[f] for f in FIELDS}, "expected_priority": ep, "predicted_priority": pp,
                     "confidence": p["confidence"], "reasoning": p.get("reasoning", "")})

    rank = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
    accuracy = {f: sum(r[f"expected_{f}"] == r[f"predicted_{f}"] for r in rows) / len(rows) for f in FIELDS + ["priority"]}
    under = [r["id"] for r in rows if rank[r["predicted_priority"]] > rank[r["expected_priority"]]]
    missed_p1 = [r["id"] for r in rows if r["expected_priority"] == "P1" and r["predicted_priority"] != "P1"]
    result = {
        "mode": "mock" if mock else CLASSIFIER["model"],
        "tickets": len(rows),
        "accuracy": accuracy,
        "under_prioritized": under,
        "missed_p1": missed_p1,
        "category_confusion": Counter(f"{r['expected_category']} -> {r['predicted_category']}" for r in rows
                                      if r["expected_category"] != r["predicted_category"]),
        "rows": rows,
    }
    out = ROOT / "eval" / f"results_{'mock' if mock else 'claude'}.json"
    out.write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true")
    r = evaluate(mock=parser.parse_args().mock)
    print(f"\n[{r['mode']}] {r['tickets']} tickets")
    for field, acc in r["accuracy"].items():
        print(f"  {field:<9} {acc:.0%}")
    print(f"  under-prioritized: {r['under_prioritized'] or 'none'} · missed P1: {r['missed_p1'] or 'none'}")
