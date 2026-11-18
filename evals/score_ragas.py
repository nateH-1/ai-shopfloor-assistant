"""
Step 3: score saved model answers with Ragas (judge = gpt-4o-mini via the existing tests/ragas_eval.py).
Needs OPENAI_API_KEY (root .env) and `pip install ragas langchain-openai`. Paid: a few cents per model.

    python evals/score_ragas.py                       # score the newest answers file of every model
    python evals/score_ragas.py --retrieval           # also context_precision / context_recall (same chunks for every model: run once)

Only ANSWERABLE questions that reached the model are scored. Faithfulness (is every claim backed by the chunks?) and
answer_relevancy (does it address the question?) are per model. context_* depends only on the chunks, which are
identical across models, so it is only worth running once.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tests"))           # ragas_eval.py currently lives in the root tests/ folder
load_dotenv(ROOT / ".env")

from ragas_eval import score_outputs

RESULTS = HERE / "results"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval", action="store_true")
    ap.add_argument("--models", nargs="+", help="only score these models (default: every model with an answers file)")
    args = ap.parse_args()

    newest = {}
    for p in sorted(RESULTS.glob("answers_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if args.models and d["model"] not in args.models:
            continue
        newest[d["model"]] = (p, d)
    if args.models and (missing := set(args.models) - set(newest)):
        print("no answers file found for:", ", ".join(sorted(missing)))

    out = RESULTS / f"ragas_{time.strftime('%Y%m%d_%H%M%S')}.json"
    summary = {}
    for model, (path, d) in newest.items():
        rows = [{"question": r["question"], "answer": r["answer"], "contexts": r["contexts"],
                 "ground_truth": r["ground_truth"]}
                for r in d["rows"]
                if r["answerable"] and r.get("llm_called") and r["contexts"]
                and not r.get("error") and r["answer"].strip()]
        print(f"\nscoring {model}: {len(rows)} answered questions ...", flush=True)
        try:
            scores = score_outputs(rows, include_retrieval_metrics=args.retrieval)
        except Exception as e:            # one bad model must not lose the others' scores
            print(f"   FAILED, skipping {model}: {type(e).__name__}: {e}"[:300])
            continue
        summary[model] = {"n": len(rows), "source": path.name, **scores}
        print("  ", {k: round(v, 3) for k, v in scores.items()})
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")   # saved after every model

    print("\nsaved", out)


if __name__ == "__main__":
    main()
