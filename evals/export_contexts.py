"""
Step 1 (run on the machine that has the eval index): freeze the retrieved chunks for every question.

The frozen file lets compare_models.py run on ANY machine (e.g. one with a GPU) with only Ollama installed:
no Chroma, no PDFs, no embeddings. It also guarantees every model sees exactly the same evidence.

From backend/ with the venv:
    python ../evals/export_contexts.py --split tune        # writes evals/frozen_contexts_tune.json
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))            # so we can import run_retrieval_eval
sys.path.insert(0, str(HERE.parent / "backend"))

import run_retrieval_eval as E           # reuses open_collection() and relevant()
from rag.keyword import _build_keyword_index
from rag.retrieval import _hybrid_search


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["tune", "heldout", "all"], default="tune")
    args = ap.parse_args()

    questions = json.loads(E.QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if args.split != "all":
        questions = [q for q in questions if q["split"] == args.split]

    collection = E.open_collection()
    index = _build_keyword_index(collection)

    out = []
    for q in questions:
        item = {k: q[k] for k in ("id", "category", "split", "answerable", "question",
                                  "ground_truth", "source_file", "pdf_pages")}
        if q["category"] == "off_topic":      # never reaches retrieval; only the guard sees it
            item.update(enough_evidence=None, chunks=[])
        else:
            chunks, enough = _hybrid_search(collection, q["question"], lambda: index)
            item["enough_evidence"] = enough
            item["chunks"] = [{
                "text": c.page_content,
                "source": Path(c.metadata.get("source", "")).name,
                "page": c.metadata.get("page"),
                "relevant": bool(q["answerable"] and E.relevant(c, q)),
            } for c in chunks]
        out.append(item)

    path = HERE / f"frozen_contexts_{args.split}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path} ({len(out)} questions, {path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
