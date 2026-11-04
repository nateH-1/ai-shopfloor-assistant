# Retrieval baseline results

Log of retrieval evaluation runs. Newest at the bottom. Add a new section for every run so changes can be compared.

## How to reproduce
From `backend/` with the venv active:

    python ../evals/run_retrieval_eval.py --ingest        # once; builds evals/chroma_db (5,680 chunks, ~$0.12 OpenAI embeddings)
    python ../evals/run_retrieval_eval.py --split tune    # or --split heldout, or no flag for all

Raw per-question output is saved to `evals/results/retrieval_<timestamp>.json` (gitignored, local only).

## What is measured
Retrieval only (no Ollama): the app's `_hybrid_search` across all 15 PDFs in `testing-documentation/`, no scope detection.
A chunk counts as relevant if its file is in the question's `source_file` and page+1 is in `pdf_pages` (page-level labels, coarser than exact passages).
`off_topic` questions are skipped (the guard needs Ollama).

---

## Run 1: 2026-11-04, tune split, baseline
Code: `main` at 92895fb (hybrid search, KEYWORD_FALLBACK_DISTANCE 0.20, evidence gate). Embeddings: ada-002. Questions: `questions_draft.json` (42 draft questions, labels checked by the user).
Raw file: `evals/results/retrieval_20261104_003500.json`

| Group | Answerable | Hit@5 | Hit@12 | Recall@5 | False rejection | Unanswerable | Correct rejection |
|---|---|---|---|---|---|---|---|
| ALL (tune) | 25 | 88.0% | 96.0% | 88.0% | 0.0% | 2 | **0.0%** |
| exact_figure | 8 | 87.5% | 87.5% | 87.5% | 0.0% | | |
| plain | 7 | 85.7% | 100% | 85.7% | 0.0% | | |
| paraphrase | 3 | 100% | 100% | 100% | 0.0% | | |
| exact_code | 4 | 75.0% | 100% | 75.0% | 0.0% | | |
| multi_document | 2 | 100% | 100% | 100% | 0.0% | | |
| multi_passage | 1 | 100% | 100% | 100% | 0.0% | | |
| unanswerable | | | | | | 2 | 0.0% |

Average retrieval time about 334 ms per question.

Targets (provisional): Hit@5 >= 95%, Recall@5 >= 90%, correct rejection >= 95%. Hit@5, Recall@5 and correct rejection are below target.

### Findings
- **Evidence gate fails on the larger corpus.** Both unanswerable questions were answered instead of refused: EV-11 (lathe chuck bolt torque) and EV-41 (SolarEdge inverter cost).
  Their words ("torque", "SolarEdge") appear somewhere in the 15 PDFs, so the "important word appears in no chunk" rule rarely fires. The gate was tuned on 2 PDFs.
- **Misses:** EV-24 (exact_figure) not in the top 12; EV-15 (exact_code) first relevant at rank 6; EV-27 (plain) at rank 8.
- Not yet checked whether these misses are true retrieval failures or page-label issues.

### Caveats
- Only 2 unanswerable questions in the tune set. Too few to judge; add more.
- 25 answerable questions: one miss moves a percentage by 4 points.
- Heldout split (14 questions) not run yet; keep it untouched until final measurement.

### Next
1. Inspect EV-24, EV-15, EV-27 (top-12 contents vs labeled pages).
2. Add more unanswerable and off-topic questions; add follow-ups and more multi-passage/multi-document questions.
3. Only then consider changing the evidence gate; tune on `tune`, confirm on `heldout`.
4. Build the answer-level eval (Ollama): refusals, citation validity, key facts.

---

## Run 2: 2026-11-04, tune split, after label fix and 10 new unanswerable questions
Same code and index as Run 1. Changes to the question set only: EV-24 label corrected to pages [14, 41] (the "39 percent" figure is on both); added EV-43..EV-55 (10 unanswerable, 3 off-topic).
Set is now 55 questions: 35 tune / 20 heldout; 13 unanswerable (7 tune / 6 heldout), 5 off-topic.
Raw file: `evals/results/retrieval_20261104_005720.json`

| Group | Answerable | Hit@5 | Hit@12 | Recall@5 | False rejection | Unanswerable | Correct rejection |
|---|---|---|---|---|---|---|---|
| ALL (tune) | 25 | 92.0% | 100% | 90.0% | 0.0% | 7 | **28.6% (2 of 7)** |

Hit@12 rose from 96% to 100% and Hit@5 from 88% to 92% only because EV-24 was relabeled, not because retrieval changed.

### Findings
- **Review of the Run 1 misses** (top 12 inspected):
  - EV-24: label issue, fixed (answer is on pages 14 and 41; page 41 ranked 5th).
  - EV-15 ("error 3xA"): real ranking weakness. The right chunk (page 5) ranked 6th behind unrelated error-code tables that share "inverter" and "error".
  - EV-27 ("kinds of waste"): real competition. The short lean_manufacturing slide ranked 8th behind long Boeing text about waste.
- **Evidence gate:** only 2 of 7 unanswerable questions refused (EV-43 crane payload, EV-51 capital of France).
  Wrongly answered: EV-11, EV-41, EV-45 (inverter firmware), EV-47 (inverter operating temperature), EV-49 (vise torque).
  Pattern: the gate fails when the question's words each exist in the corpus, even if the answer is not there. This is the main thing to fix.
- Questions screened out as answerable while drafting: Boeing Auburn headcount (about 700), CS late-work policy (seminar syllabus).

### Caveats
- Only the tune split has been run, so the gate can be adjusted without touching heldout.
- New questions are checked against the PDF text but not yet verified by a human.
- 7 unanswerable questions is still a small sample.

---

## Status update, 2026-11-04
- **Questions EV-43 to EV-55 verified by the user** (checked as unanswerable / off-topic). Together with the earlier check of the first 42, all 55 questions are now human-checked.
- **Deadline decision:** the evidence-gate redesign is parked. Priority now is comparing more small language models (SLMs) on answer quality with Ragas.

## Parked: better evidence-gate design (not built)
Problem: the gate refuses only when the best vector distance is >= 0.20 AND a query word is missing from every chunk. With 15 PDFs almost every word exists somewhere, so unanswerable questions that use real corpus words (inverter firmware, vise torque, shelf life of cutting fluid) get answered. Run 2: 2 of 7 correctly refused.

Ideas, roughly cheapest first. Tune on the `tune` split, confirm once on `heldout`:
1. **Check words against the retrieved chunks, not the whole corpus.** Require important query terms (e.g. "firmware", "torque", "shelf life") to appear in the top-k chunks, not merely anywhere in the index.
2. **Co-occurrence check.** Require key terms together in one chunk or one page (e.g. "cutting fluid" and "shelf life" never appear together).
3. **Retune the distance cut-off** on the larger set; the 0.20 value came from 18 questions on 2 PDFs. Plot best distance for answerable vs unanswerable first.
4. **LLM relevance check** on the top 3 chunks ("does this text answer the question? yes/no") using the local model. Most accurate, adds one model call per question.
5. Score unanswerable and answerable questions separately so the gate cannot look good by refusing everything (keep false rejection at 0%).

---

## SLM comparison with Ragas (set up 2026-11-04; results below once run)

Goal: compare small models on answer quality. Generation runs on a GPU machine (this PC is CPU-only: a 1B model takes ~45 s per answer, a 7B ~2.5 min).
All models get identical evidence (frozen chunks from the retrieval step), so differences come from the model, not retrieval.

Files (all in `evals/`):
- `export_contexts.py` - freezes retrieved chunks to `frozen_contexts_tune.json` (35 tune questions; 2 refused by the evidence gate, 3 off-topic, 30 reach the model). Already generated, 358 KB.
- `compare_models.py` - `generate` (guard + answer + automatic checks per model) and `report` (table).
- `score_ragas.py` - Ragas faithfulness + answer_relevancy per model (judge gpt-4o-mini, OpenAI key needed, a few cents per model); `--retrieval` adds context precision/recall once.

### On the GPU machine
1. Get the repo on branch `eval-baseline` (the three scripts, `frozen_contexts_tune.json` and `backend/rag/` are needed; no PDFs or Chroma needed). Commit the frozen file so it travels with the branch.
2. `pip install langchain langchain-ollama` (generation); `pip install ragas langchain-openai python-dotenv` too if scoring there.
3. `ollama pull` each model, then:
       python evals/compare_models.py generate --models qwen2.5:7b gemma3:4b llama3.2:1b <others>
       python evals/compare_models.py report
4. Scoring (anywhere with OPENAI_API_KEY in the root .env): `python evals/score_ragas.py`
5. Copy `evals/results/*.json` back and paste the two tables here.

### What the automatic checks mean
- ans ok: answerable questions answered, not refused. refuse ok: unanswerable questions refused (by the gate or by the model).
- src line / cite rel: the SOURCES_USED line is present / cites a chunk on a labeled-relevant page.
- guard ok: the off-topic classifier (model-decided, keyword shortcut skipped) is right: off-topic -> YES, everything else -> NO.
- Caveats: only the tune split (heldout reserved for the final pick); Ragas faithfulness/relevancy are judged by gpt-4o-mini and score "answer vs chunks", not "answer vs truth" (compare answers to `ground_truth` by hand for the top 1-2 models).
