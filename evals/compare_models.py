"""
Step 2: compare small language models (SLMs) on answer quality, using the frozen contexts.

Runs on any machine with Ollama (e.g. a GPU box). Needs only:  pip install langchain langchain-ollama
and the repo's backend/rag/prompts.py + context.py (no Chroma, no PDFs, no OpenAI key).

For every model it does, with the app's real prompts and settings (temperature 0, num_ctx 16384):
  * GUARD   - the off-topic classifier prompt on every question (model decides; keyword shortcut skipped
              on purpose so the MODEL is what gets tested). Off-topic questions should be YES, all others NO.
  * ANSWER  - QA_PROMPT over the frozen chunks. If retrieval's evidence gate already refused (enough_evidence
              false) the model is not called and the app's NO_INFO_REPLY is recorded (same as the app).
  * CHECKS  - refusal behaviour, SOURCES_USED line validity, whether a cited chunk is a labeled-relevant one, latency.

Usage (from the repo root or anywhere):
    python evals/compare_models.py generate --models qwen2.5:7b gemma3:4b llama3.2:1b
    python evals/compare_models.py generate --models phi4-mini --host http://localhost:11434
    python evals/compare_models.py report                      # table of the newest answers file per model

Answers are saved to evals/results/answers_<model>_<timestamp>.json; score them with score_ragas.py.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

from langchain_ollama import ChatOllama
from rag.context import _build_numbered_context
from rag.prompts import QA_PROMPT, _GUARD_PROMPT

NO_INFO_REPLY = "The uploaded documents do not contain information about this."   # same text as rag.pipeline
NUM_CTX = 16384                                                                   # same as rag.config.OLLAMA_NUM_CTX
RESULTS = HERE / "results"


MAX_ANSWER_TOKENS = 1024   # runaway/looping answers are cut here (real answers are far shorter)
CALL_TIMEOUT_S = 240       # a call slower than this is recorded as an ERROR and the run moves on


def make_llm(model, host, **extra):
    return ChatOllama(model=model, base_url=host, temperature=0, num_ctx=NUM_CTX,
                      client_kwargs={"timeout": CALL_TIMEOUT_S}, **extra)


_REFUSAL_RE = re.compile(
    r"(do(es)? not|don'?t|doesn'?t) (contain|include|provide|specify|mention|state|have)"
    r"|(is|are|was|were) not (explicitly )?(mentioned|stated|specified|provided|covered|found|included)"
    r"|no (specific )?([a-z]+ )?(information|mention|details?)"
    r"|(cannot|can'?t|unable to) (find|answer|determine)"
    r"|not (enough|sufficient) information", re.IGNORECASE)


def is_refusal(text: str) -> bool:
    """Exact app reply, or a model's own wording of 'the context doesn't say' (llama/granite phrase it freely).
    Only the first ~300 chars are checked so a real answer with a late caveat is not flagged."""
    t = text.strip()
    return "do not contain" in t.lower() or bool(_REFUSAL_RE.search(t[:300]))


def parse_sources(raw: str, n_chunks: int):
    """Returns (clean_answer, has_line, cited_indexes_0_based, said_none). Does NOT fall back to all chunks."""
    m = re.search(r"\s*SOURCES_USED:\s*(.+?)\s*$", raw, re.IGNORECASE | re.MULTILINE)
    if not m:
        return raw.strip(), False, [], False
    clean, val = raw[:m.start()].strip(), m.group(1).strip()
    if not val or val.lower() == "none":
        return clean, True, [], True
    idx = []
    for part in val.split(","):
        d = re.search(r"\d+", part)
        if d and 0 <= int(d.group()) - 1 < n_chunks:
            idx.append(int(d.group()) - 1)
    return clean, True, idx, False


def run_model(model, host, items, save):
    """save(rows) is called after every question so an interrupted run keeps its progress."""
    llm, guard = make_llm(model, host, num_predict=MAX_ANSWER_TOKENS), make_llm(model, host, num_predict=3)
    rows = []
    for n, q in enumerate(items, 1):
        row = {"id": q["id"], "category": q["category"], "answerable": q["answerable"], "question": q["question"],
               "ground_truth": q["ground_truth"], "enough_evidence": q["enough_evidence"]}
        t = time.perf_counter()
        try:
            pred = guard.invoke(_GUARD_PROMPT.format(msg=q["question"].replace('"', "'"))).content.strip().upper().startswith("YES")
        except Exception as e:
            print(f"      guard error: {e}")
            pred = False                      # same as the app: fail open
        row.update(guard_said_off_topic=pred, guard_correct=(pred == (q["category"] == "off_topic")),
                   guard_s=round(time.perf_counter() - t, 2))

        if q["category"] != "off_topic":
            chunks = q["chunks"]
            row["contexts"] = [c["text"] for c in chunks]
            if not q["enough_evidence"]:
                row.update(answer=NO_INFO_REPLY, raw=None, llm_called=False, answer_s=0.0)
            else:
                t = time.perf_counter()
                try:
                    raw = llm.invoke(QA_PROMPT.format(context=_build_numbered_context(
                        [type("D", (), {"page_content": c["text"]}) for c in chunks]), question=q["question"])).content
                    answer, has_line, cited, said_none = parse_sources(raw, len(chunks))
                    row.update(answer=answer, raw=raw, llm_called=True, answer_s=round(time.perf_counter() - t, 2),
                               has_sources_line=has_line, cited=[i + 1 for i in cited], said_none=said_none,
                               cited_relevant=any(chunks[i]["relevant"] for i in cited))
                except Exception as e:        # timeout / server error: record a failure and keep going
                    row.update(answer="", raw=None, llm_called=True, answer_s=round(time.perf_counter() - t, 2),
                               error=f"{type(e).__name__}: {e}"[:200], has_sources_line=False, cited=[],
                               said_none=False, cited_relevant=False)
            row["refused"] = is_refusal(row["answer"])
            # an errored/empty answer counts as wrong for both answerable and unanswerable questions
            row["behavior_correct"] = False if row.get("error") else ((not row["refused"]) if q["answerable"] else row["refused"])
        rows.append(row)
        save(rows)
        status = ("ERROR " + row["error"][:40]) if row.get("error") else \
                 "REFUSED" if row.get("refused") else \
                 "answered" if q["category"] != "off_topic" else "guard=" + str(pred)
        print(f"  [{n}/{len(items)}] {q['id']:6} {q['category']:14} {status}  ({row.get('answer_s', 0)}s)", flush=True)
    return rows


def cmd_generate(args):
    items = json.loads(Path(args.input).read_text(encoding="utf-8"))
    RESULTS.mkdir(exist_ok=True)
    for model in args.models:
        print(f"\n=== {model} ===")
        t0 = time.perf_counter()
        out = RESULTS / f"answers_{model.replace(':', '-').replace('/', '_')}_{time.strftime('%Y%m%d_%H%M%S')}.json"

        def save(rows, model=model, out=out, t0=t0):
            out.write_text(json.dumps({"model": model, "host": args.host, "total_s": round(time.perf_counter() - t0),
                                       "complete": len(rows) == len(items), "rows": rows},
                                      indent=1, ensure_ascii=False), encoding="utf-8")
        try:
            run_model(model, args.host, items, save)
        except KeyboardInterrupt:
            print(f"\n  interrupted - partial results kept in {out.name}. Skipping to the next model; press Ctrl+C again to stop.")
            continue
        except Exception as e:     # e.g. model not pulled / server down: report and go on to the next model
            print(f"  FAILED: {e}")
            continue
        print(f"  saved {out}")


def pct(xs):
    return f"{100 * sum(xs) / len(xs):5.1f}%" if xs else "  n/a"


def cmd_report(args):
    newest = {}
    for p in sorted(RESULTS.glob("answers_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        newest[d["model"]] = d
    print(f"\n{'model':16} {'done':>5} {'ans ok':>7} {'refuse ok':>9} {'src line':>8} {'cite rel':>8} {'guard ok':>8} {'avg s':>6} {'errors':>6}")
    for model, d in newest.items():
        r = d["rows"]
        ans = [x for x in r if x["answerable"]]
        un = [x for x in r if not x["answerable"] and x["category"] != "off_topic"]
        called = [x for x in r if x.get("llm_called")]
        errs = sum(1 for x in r if x.get("error"))
        done = f"{len(r)}{'' if d.get('complete', True) else '*'}"
        print(f"{model:16} {done:>5} {pct([x['behavior_correct'] for x in ans]):>7} {pct([x['behavior_correct'] for x in un]):>9} "
              f"{pct([x['has_sources_line'] for x in called]):>8} "
              f"{pct([x['cited_relevant'] for x in called if x['answerable'] and not x['refused']]):>8} "
              f"{pct([x['guard_correct'] for x in r]):>8} {sum(x['answer_s'] for x in called) / max(len(called), 1):6.1f} {errs:6}")
    print("\ndone = questions finished (* = interrupted, partial); errors = timed-out or failed answers (counted as wrong)."
          "\nans ok = answerable questions answered (not refused); refuse ok = unanswerable refused (by gate or model);"
          "\nsrc line = SOURCES_USED line present; cite rel = answered questions citing a labeled-relevant chunk;"
          "\nguard ok = off-topic guard right on every question (off-topic -> YES, others -> NO).")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--models", nargs="+", required=True)
    g.add_argument("--host", default="http://localhost:11434")
    g.add_argument("--input", default=str(HERE / "frozen_contexts_tune.json"))
    g.set_defaults(fn=cmd_generate)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
