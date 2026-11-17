"""
Before/after keyword search: same questions, same eval index, two retrieval modes.

  BEFORE = vector search only (top 12 by embedding distance, no keyword fallback, no evidence gate).
           This is how the app retrieved before PRs A/B/C. Without a gate it never refuses.
  AFTER  = rag.retrieval._hybrid_search (vector + BM25 fallback + evidence gate), the current app.

Retrieval only (no Ollama). Uses the separate index at evals/chroma_db (build it with run_retrieval_eval.py --ingest).

Run from backend/ with the venv:
    python ../evals/compare_keyword.py --split tune
    python ../evals/compare_keyword.py --split heldout     # only for the final measurement

Writes evals/results/keyword_compare_<timestamp>.json (gitignored) with per-question rows and the summary,
which evals/make_keyword_slide.py reads.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_retrieval_eval import QUESTIONS, RESULTS_DIR, open_collection, relevant  # noqa: E402
from rag.keyword import _build_keyword_index  # noqa: E402
from rag.retrieval import _hybrid_search, _similarity_search  # noqa: E402

K_LIST = (5, 12)


def run_mode(mode, collection, get_index, questions):
    rows = []
    for q in questions:
        if q["category"] == "off_topic":
            continue
        t = time.perf_counter()
        if mode == "before":
            chunks, enough = _similarity_search(collection, q["question"], k=12), True
        else:
            chunks, enough = _hybrid_search(collection, q["question"], get_index)
        ms = (time.perf_counter() - t) * 1000
        row = {"id": q["id"], "category": q["category"], "answerable": q["answerable"],
               "enough_evidence": enough, "ms": round(ms)}
        if q["answerable"]:
            for k in K_LIST:
                pages = {c.metadata["page"] + 1 for c in chunks[:k] if relevant(c, q)}
                row[f"hit@{k}"] = bool(pages)
                row[f"recall@{k}"] = len(pages) / len(q["pdf_pages"])
            rank = next((i + 1 for i, c in enumerate(chunks) if relevant(c, q)), None)
            row["first_rank"] = rank
            row["rr"] = 1 / rank if rank else 0.0  # reciprocal rank, for MRR
        rows.append(row)
    return rows


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def summarize(rows):
    ans = [r for r in rows if r["answerable"]]
    un = [r for r in rows if not r["answerable"]]
    return {
        "n_answerable": len(ans), "n_unanswerable": len(un),
        "hit@5": mean([r["hit@5"] for r in ans]), "hit@12": mean([r["hit@12"] for r in ans]),
        "recall@5": mean([r["recall@5"] for r in ans]), "recall@12": mean([r["recall@12"] for r in ans]),
        "mrr": mean([r["rr"] for r in ans]),
        "false_rejection": mean([not r["enough_evidence"] for r in ans]),
        "correct_rejection": mean([not r["enough_evidence"] for r in un]),
        "avg_ms": mean([r["ms"] for r in rows]),
    }


def fmt(v, kind="pct"):
    if v is None:
        return "n/a"
    return f"{v:.3f}" if kind == "num" else f"{100 * v:.1f}%" if kind == "pct" else f"{v:.0f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["tune", "heldout"])
    args = ap.parse_args()

    collection = open_collection()
    if collection.count() == 0:
        sys.exit("Eval index is empty. Run run_retrieval_eval.py --ingest first.")
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if args.split:
        questions = [q for q in questions if q["split"] == args.split]

    idx = _build_keyword_index(collection)
    before = run_mode("before", collection, lambda: idx, questions)
    after = run_mode("after", collection, lambda: idx, questions)
    sb, sa = summarize(before), summarize(after)

    metrics = [("Hit@5", "hit@5", "pct"), ("Hit@12", "hit@12", "pct"), ("Recall@5", "recall@5", "pct"),
               ("Recall@12", "recall@12", "pct"), ("MRR", "mrr", "num"),
               ("False rejection (lower=better)", "false_rejection", "pct"),
               ("Correct rejection", "correct_rejection", "pct"), ("Avg latency ms", "avg_ms", "ms")]
    print(f"\nsplit={args.split or 'all'}  answerable={sb['n_answerable']}  unanswerable={sb['n_unanswerable']}")
    print(f"{'metric':32} {'before':>9} {'after':>9} {'change':>9}")
    for label, key, kind in metrics:
        b, a = sb[key], sa[key]
        d = "" if b is None or a is None else (f"{a - b:+.3f}" if kind == "num" else f"{a - b:+.0f}ms" if kind == "ms" else f"{100 * (a - b):+.1f}pt")
        print(f"{label:32} {fmt(b, kind):>9} {fmt(a, kind):>9} {d:>9}")

    # Per-category Hit@5 / Recall@5
    cats = sorted({r["category"] for r in before if r["answerable"]})
    by_cat = {}
    print(f"\n{'category':16} {'n':>3} {'hit@5 before':>13} {'hit@5 after':>12} {'rec@5 before':>13} {'rec@5 after':>12}")
    for c in cats:
        b = [r for r in before if r["answerable"] and r["category"] == c]
        a = [r for r in after if r["answerable"] and r["category"] == c]
        by_cat[c] = {"n": len(b), "hit@5": [mean([r["hit@5"] for r in b]), mean([r["hit@5"] for r in a])],
                     "recall@5": [mean([r["recall@5"] for r in b]), mean([r["recall@5"] for r in a])]}
        print(f"{c:16} {len(b):3} {fmt(by_cat[c]['hit@5'][0]):>13} {fmt(by_cat[c]['hit@5'][1]):>12} "
              f"{fmt(by_cat[c]['recall@5'][0]):>13} {fmt(by_cat[c]['recall@5'][1]):>12}")

    # Which questions changed
    bm = {r["id"]: r for r in before}
    flips = {"fixed@5": [], "broken@5": [], "rank_changed": [], "now_refused_correctly": [], "now_refused_wrongly": []}
    for r in after:
        b = bm[r["id"]]
        if r["answerable"]:
            if r["hit@5"] and not b["hit@5"]:
                flips["fixed@5"].append(r["id"])
            if b["hit@5"] and not r["hit@5"]:
                flips["broken@5"].append(r["id"])
            if r["first_rank"] != b["first_rank"]:
                flips["rank_changed"].append(f"{r['id']}: {b['first_rank']} -> {r['first_rank']}")
            if not r["enough_evidence"]:
                flips["now_refused_wrongly"].append(r["id"])
        elif not r["enough_evidence"]:
            flips["now_refused_correctly"].append(r["id"])
    print("\nQuestion-level changes:")
    for k, v in flips.items():
        print(f"  {k:24} {len(v):2}  {', '.join(v)}")

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"keyword_compare_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps({"split": args.split or "all", "before": sb, "after": sa, "by_category": by_cat,
                               "flips": flips, "rows_before": before, "rows_after": after}, indent=2), encoding="utf-8")
    print("\nsaved", out)


if __name__ == "__main__":
    main()
