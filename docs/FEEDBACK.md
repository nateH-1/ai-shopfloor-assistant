# Local answer feedback

The manufacturing chatbot now supports Helpful / Not helpful votes, optional
reasons and comments, changing a vote, and withdrawing feedback. No user login,
Supabase account, additional database service, or additional dependency is needed.

## Using it

Start the backend and frontend as described in the main README. Ask a new
question. Use the feedback buttons below a completed answer. A Not helpful vote
is saved immediately; selecting a reason or writing a comment is optional.
Click Save details to save those details. Remove feedback withdraws the vote
and erases its reason/comment.

Existing answers from before this feature have no server answer ID and cannot
be rated. New conversations survive refresh in the same tab using sessionStorage.
Closing the tab clears that browser history; submitted feedback remains on disk
for 7 days.
Clearing cookies creates a new anonymous browser identity, so old feedback will
no longer be editable from that browser.

## Storage and integrity

- Collection: answer_feedback_v1 in the existing local chroma_db directory.
  With the documented manual startup from backend/, this is backend/chroma_db.
- The documents collection and its document embeddings are untouched.
- Each eligible answer gets a server-generated UUID, but it is not written to
  Chroma unless the user submits feedback.
- Saved feedback includes the original question, answer, source citations, model
  name, session ID, UTC creation time, and a hash of the anonymous browser
  credential.
- Each answer has one rating. PUT updates rating fields in that existing record;
  repeated clicks and retries cannot insert duplicate votes.
- Chroma stores metadata and JSON with an explicit constant vector and no
  embedding function. Feedback is never embedded or sent to OpenAI.
- Feedback text is limited to 2,000 characters and reasons/votes use allowlists.
  Votes cannot replace the stored answer, sources, or ownership.
- No feedback data is added to retrieval, prompts, or model training.
- DELETE removes the saved feedback record.
- Saved feedback is automatically deleted after 7 days.

The feedback HTTP endpoints accept only answer IDs, not arbitrary collection
names. The Next.js proxy derives ownership from a random HttpOnly, SameSite=Strict
cookie, checks Origin on browser requests, and sends a fixed ownership header to
Flask. Feedback is scoped to that browser; it is not proof of a person's identity.
This is intended for the existing trusted local deployment, not an authenticated
multi-user public service. Keep Flask private; do not expose it directly to
untrusted networks. Authentication was explicitly excluded from this feature.

## API

Frontend proxy: /api/feedback/{message_id}
Backend: same path. Internal header: X-Feedback-Owner (UUID browser credential).

- GET: returns {feedback: null} or the current vote, reason, comment, updated_at.
- PUT: JSON {vote: "helpful" | "not_helpful", reason?: string, comment?: string}.
- DELETE: returns {feedback: null} after withdrawing the rating.
- 400 invalid input, 401 missing browser identity, 404 absent or other-browser
  answer, 413 oversized body, 503 local database failure (502 for proxy failures).

Chat responses receive message_id for eligible answers. Unrated answers stay in
backend memory briefly so the matching answer can be saved if the user rates it;
they are not persisted to Chroma.

## Inspecting results locally

Use Chroma's Python API rather than editing chroma.sqlite3 or binary index files.
From the project root, activate backend/venv and run Python:

```python
import chromadb
client = chromadb.PersistentClient(path="backend/chroma_db")
feedback = client.get_collection("answer_feedback_v1", embedding_function=None)
rows = feedback.get(where={"vote": {"$ne": "unrated"}},
                    include=["documents", "metadatas"], limit=100)
print(rows)
```

The example prints answer/comment content: run it only on a trusted local
terminal. For larger exports, paginate using limit and offset.

For reports, count helpful and not_helpful rows.
Helpful rate = helpful / (helpful + not_helpful). Return no score when no votes
exist. These measure perceived helpfulness, not factual accuracy. RAGAS
evaluations remain separate.

## Validation

Run these as separate commands: the existing backend conftest mocks Chroma, while
the new integration tests deliberately use real temporary Chroma databases.

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest -v
cd ..
.\backend\venv\Scripts\python.exe -m pytest tests/test_feedback_integration.py -q -p no:langsmith
cd frontend
.\node_modules\.bin\tsc.cmd --noEmit --incremental false
```

Integration tests cover persistence, answer integrity, changes, repeat/concurrent
votes, ownership isolation, validation, withdrawal, and database failure handling.
The store's lock covers one Flask process; this deployment is single-process.
Before scaling to multiple workers or hosts, revisit concurrency and use a local
Chroma server or another supported production deployment.

References:
- https://docs.trychroma.com/reference/python/client
- https://docs.trychroma.com/docs/collections/update-data
