# RAG Evaluation — Kuldeep Chatbot

Two files in the `tests/` folder implement automated quality evaluation for the chatbot's RAG pipeline:

| File | Purpose |
|---|---|
| `ragas_eval.py` | Core evaluation library — wraps Ragas, exposes simple functions |
| `regression_test.py` | Full regression pipeline — queries the live chatbot and scores it |

---

## How it works

The system uses [Ragas](https://docs.ragas.io/) to score chatbot outputs across four metrics. Ragas uses an LLM (gpt-4o-mini) to judge each response — it does **not** just compare strings.

### The four metrics

| Metric | What it measures | Needs ground truth? |
|---|---|---|
| **faithfulness** | Are all claims in the answer actually supported by the retrieved context? Catches hallucination. | No |
| **answer_relevancy** | Does the answer actually address the question asked? Catches off-topic responses. | No |
| **context_precision** | Are the retrieved chunks relevant and useful for the question? Measures retriever quality. | Yes |
| **context_recall** | Does the retrieved context cover the key facts in the reference answer? | Yes |

All scores are in the range **0.0 – 1.0**. Higher is better.

### How each metric is computed

**Faithfulness:**
1. Ragas breaks the chatbot's answer into individual atomic statements ("G41 is a CNC code", "hot food must be held at 135°F", etc.)
2. Each statement is checked against the retrieved context chunks
3. `faithfulness = supported statements / total statements`

**Answer relevancy:**
1. Ragas generates several possible questions that the answer could be responding to
2. Those generated questions are embedded and compared to the original question using cosine similarity
3. High similarity → the answer is on-topic

**Context precision:**
1. Each retrieved chunk is ranked by how useful it actually was for answering the question
2. Relevant chunks ranked higher = better precision

**Context recall:**
1. The ground truth answer is broken into statements
2. Each statement is checked against the context to see if it was retrievable
3. `context_recall = statements found in context / total statements`

---

## Requirements

```
OPENAI_API_KEY=<your key>   # in .env at the project root
```

```bash
pip install ragas langchain-openai
```

The Flask backend must be running on `http://localhost:5000` for the regression pipeline.

---

## Running the regression test

1) Start the backend server.

2) Add a testing account to the application.
    start the frontend and backend, create a new Admin account.

4) Upload the documents for the tests in settings.

5) add environment variables to terminal to run tests.
    ```bash
    $env:REGRESSION_USERNAME = "your test username"
    $env:REGRESSION_PASSWORD = "your test password"
    ```

3) From the project root, run:

```bash
# Report scores — does NOT fail on threshold violations
python tests/regression_test.py --no-fail

# Full CI mode — exits with code 1 if any metric is below its threshold
python tests/regression_test.py

# Override specific thresholds
python tests/regression_test.py --faithfulness 0.80 --answer-relevancy 0.75
```

Results are saved to `tests/regression_results_<timestamp>.json` after every run.

### Default thresholds

| Metric | Threshold |
|---|---|
| faithfulness | 0.70 |
| answer_relevancy | 0.70 |
| context_precision | 0.60 |
| context_recall | 0.60 |

### Score history

#### Run 1 — 2026-04-30 | chatbot: gpt-4o-mini | Ragas judge: gpt-4o-mini (max_tokens=8192) — **Baseline**

| Metric | Score | Notes |
|---|---|---|
| faithfulness | 0.8775 | Stable |
| answer_relevancy | 0.9279 | Includes REG-05 and REG-20 which require whole-word guard matching (`\bsing\b`) to score correctly |
| context_precision | 0.9318 | Large improvement — ground truths rewritten from actual document text |
| context_recall | 0.7565 | **Passing** — ground truths written from actual document text |

**Notes:**
- Ground truths for all 24 RAG tests written verbatim from source documents
- Guard fast-check uses whole-word regex matching (`\bsing\b`) instead of substring to avoid false positives
- Guard prompt covers 3 categories only (personal, small talk, entertainment) — general knowledge excluded to prevent false positives on technical questions
- Guard runs on every message including those with history
- 4 behavioral tests included (BEH-01 to BEH-04): off-topic guard, broad path, clarification path, pass path
- Result file: `tests/regression_results_20260430_122026.json`

---

## Using `ragas_eval.py` directly

You can call the evaluation library on any arbitrary rows without the full regression pipeline:

```python
import sys
sys.path.insert(0, 'tests')
from ragas_eval import score_outputs, score_single, print_score_table

# Score a list of rows
rows = [
    {
        "question":     "What is the safe hot-holding temperature?",
        "answer":       "135°F (57°C) per the FDA Food Code.",
        "contexts":     ["TIME/TEMPERATURE CONTROL FOR SAFETY food shall be maintained at 57°C (135°F) or above."],
        "ground_truth": "The FDA Food Code requires food to be held at 135°F (57°C) or above.",
    }
]

scores = score_outputs(rows, include_retrieval_metrics=True)
print_score_table(scores)

# Or score a single response directly
scores = score_single(
    question="Who manages calibration?",
    answer="The lab quality manager.",
    contexts=["The lab/ITU quality manager reviews calibrations nearing expiration."],
)
print(scores)
```

### Row format

| Key | Type | Required | Notes |
|---|---|---|---|
| `question` | str | Always | The question sent to the chatbot |
| `answer` | str | Always | The chatbot's response |
| `contexts` | list[str] | Always | The retrieved text chunks |
| `ground_truth` | str | For retrieval metrics | A short reference answer (1–3 sentences of plain prose) |

---

## Adding or editing test cases

Edit the `REGRESSION_TESTS` list in `regression_test.py`. Each entry:

```python
{
    "id": "REG-15",
    "category": "food-safety",
    "question": "At what temperature must cold food be held?",
    "ground_truth": (
        "The FDA Food Code requires cold food to be held at 41°F (5°C) or below "
        "to prevent bacterial growth."
    ),
},
```

**Ground truth writing tips:**
- Write in plain prose, not bullet points
- Include the specific fact(s) the context must contain — be precise, not general
- Keep it short (1–3 sentences)
- Base it on what the actual document says, not general domain knowledge — wrong ground truths corrupt `context_recall` scores

---

## Implementation notes

- **LLM used for evaluation:** `gpt-4o-mini` (chosen for its 4096-token output limit, which prevents truncation errors when scoring verbose answers)
- **Embeddings:** `text-embedding-ada-002` via `LangchainEmbeddingsWrapper` (required by `AnswerRelevancy`)
- **Ragas version:** 0.4.x — import from `ragas.metrics` directly, **not** `ragas.metrics.collections` (different class hierarchy, not accepted by `evaluate()`)
- **Context truncation:** Each retrieved chunk is capped at 800 characters before being passed to Ragas, preventing token limit issues on very long chunks
- **REG-14 (hallucination guard):** Has no `ground_truth` — only faithfulness and answer_relevancy are scored. Tests that the system doesn't fabricate an answer for a topic not in any document.
