"""
Retrieval baseline: measures whether the right PDF page shows up in the retrieved chunks.

It does NOT call Ollama. It uses the app's own retrieval code (rag.retrieval._hybrid_search),
searching ALL documents (no scope detection), against a SEPARATE index at evals/chroma_db
so the real chroma_db is never touched. Embeddings use OpenAI (needs OPENAI_API_KEY, tiny cost).

Run from the backend folder with the venv:
    python ../evals/run_retrieval_eval.py --ingest      # build the eval index (once; skips files already indexed)
    python ../evals/run_retrieval_eval.py               # run all questions
    python ../evals/run_retrieval_eval.py --split tune  # only tune (or heldout) questions

Matching rule (page level): a chunk is relevant if its file is in the question's source_file
and its page (PyPDFLoader pages start at 0) + 1 is in pdf_pages. This is coarser than labeling
exact passages, so treat numbers as a baseline, not final accuracy.
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "backend"))

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from dotenv import load_dotenv

from rag.ingestion import _ingest_file
from rag.keyword import _build_keyword_index
from rag.retrieval import _hybrid_search

load_dotenv(ROOT / ".env")

QUESTIONS = HERE / "questions_draft.json"
DOCS_DIR = ROOT / "testing-documentation"
EVAL_DB = str(HERE / "chroma_db")
RESULTS_DIR = HERE / "results"


def open_collection():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY is not set (checked the environment and the root .env).")
    ef = OpenAIEmbeddingFunction(api_key=key, model_name="text-embedding-ada-002")
    client = chromadb.PersistentClient(path=EVAL_DB)
    return client.get_or_create_collection(name="documents", embedding_function=ef)


def ingest(collection):
    done = {m["source"] for m in collection.get(include=["metadatas"])["metadatas"]}
    for pdf in sorted(DOCS_DIR.glob("*.pdf")):
        if str(pdf) in done:
            print(f"skip   {pdf.name} (already indexed)")
            continue
        ok, msg, n = _ingest_file(pdf, collection)
        print(f"{'ok  ' if ok else 'FAIL'}   {pdf.name}: {msg}")
    print("chunks in eval index:", collection.count())


def relevant(chunk, q) -> bool:
    files = {f.strip() for f in (q["source_file"] or "").split(";")}
    page = chunk.metadata.get("page")
    return (Path(chunk.metadata.get("source", "")).name in files
            and page is not None and (page + 1) in q["pdf_pages"])


def evaluate(collection, questions):
    index_holder = {"idx": _build_keyword_index(collection)}
    get_index = lambda: index_holder["idx"]
    rows = []
    for q in questions:
        if q["category"] == "off_topic":
            continue  # handled by the off-topic guard (needs Ollama), not retrieval
        t = time.perf_counter()
        chunks, enough = _hybrid_search(collection, q["question"], get_index)
        ms = (time.perf_counter() - t) * 1000
        row = {"id": q["id"], "category": q["category"], "split": q["split"],
               "answerable": q["answerable"], "enough_evidence": enough, "ms": round(ms)}
        if q["answerable"]:
            for k in (5, 12):
                top = chunks[:k]
                hit_pages = {c.metadata.get("page") + 1 for c in top if relevant(c, q)}
                row[f"hit@{k}"] = bool(hit_pages)
                row[f"recall@{k}"] = len(hit_pages) / len(q["pdf_pages"])
            # rank of the first relevant chunk (None if absent)
            row["first_rank"] = next((i + 1 for i, c in enumerate(chunks) if relevant(c, q)), None)
        rows.append(row)
    return rows


def pct(xs):
    return f"{100 * sum(xs) / len(xs):5.1f}%" if xs else "   n/a"


def report(rows):
    groups = {"ALL": rows}
    for key in ("category", "split"):
        for r in rows:
            groups.setdefault(f"{key}={r[key]}", []).append(r)
    print(f"\n{'group':26} {'n_ans':>5} {'hit@5':>7} {'hit@12':>7} {'rec@5':>7} {'falseRej':>8} | {'n_un':>4} {'correctRej':>10} | avg ms")
    for name, rs in groups.items():
        ans = [r for r in rs if r["answerable"]]
        un = [r for r in rs if not r["answerable"]]
        print(f"{name:26} {len(ans):5} {pct([r['hit@5'] for r in ans]):>7} {pct([r['hit@12'] for r in ans]):>7} "
              f"{pct([r['recall@5'] for r in ans]):>7} {pct([not r['enough_evidence'] for r in ans]):>8} | "
              f"{len(un):4} {pct([not r['enough_evidence'] for r in un]):>10} | {sum(r['ms'] for r in rs) // max(len(rs), 1)}")
    print("\nMisses (answerable, not in top 12) and wrongly refused / accepted:")
    for r in rows:
        if r["answerable"] and not r["hit@12"]:
            print(f"  MISS@12  {r['id']} ({r['category']}) refused={not r['enough_evidence']}")
        elif r["answerable"] and not r["hit@5"]:
            print(f"  miss@5   {r['id']} ({r['category']}) first_rank={r['first_rank']}")
        elif not r["answerable"] and r["enough_evidence"]:
            print(f"  ACCEPTED unanswerable {r['id']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest", action="store_true", help="build the eval index from testing-documentation/ and exit")
    ap.add_argument("--split", choices=["tune", "heldout"])
    args = ap.parse_args()

    collection = open_collection()
    if args.ingest:
        ingest(collection)
        return
    if collection.count() == 0:
        sys.exit("Eval index is empty. Run with --ingest first.")

    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if args.split:
        questions = [q for q in questions if q["split"] == args.split]
    rows = evaluate(collection, questions)
    report(rows)

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"retrieval_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("\nsaved", out)


if __name__ == "__main__":
    main()
