# Enterprise Knowledge Intelligence Assistant

HCL Tech AI Engineer hackathon. This is a production-minded RAG assistant that does the following:

- answers questions from approved documents (PDF, DOCX, TXT, MD) and a structured business dataset (SQL tool);
- returns **grounded answers with validated citations**;
- refuses unsupported, conflicting or malicious requests safely;
- logs **every query** to an **observability and evaluation dashboard**.

It is built on the existing [`ai_research_platform`](README.original.md) codebase: FastAPI + Next.js, hybrid dense/sparse retrieval with Reciprocal Rank Fusion, and the Groq generation path. The new code adds a self-contained **local demo mode** that needs no PostgreSQL, MinIO, Redis or Google OAuth.

> All documents, people and figures in `demo/` are **synthetic** (a fictional company, "Orion Synthetic Industries").

---

## Quick start (Windows / macOS / Linux)

Prerequisites: Python 3.11+ and Node.js 20+.

```bash
# 1. Backend
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements-demo.txt     # see note on torch below
cp .env.example .env                     # Windows: copy .env.example .env
#   then set GROQ_API_KEY=... in .env (free key: https://console.groq.com)

python scripts/build_demo.py             # builds demo PDF/DOCX + data/business.db
python scripts/seed_demo.py              # indexes the demo corpus
uvicorn src.main:app --port 8000         # API on http://localhost:8000/docs

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev                              # UI on http://localhost:3000
```

Open **http://localhost:3000**. The UI proxies `/api/v1/*` to the backend on port 8000. To point it elsewhere, set `BACKEND_URL`.

**Embeddings note:** `sentence-transformers` pulls in PyTorch. On a slow network, install the CPU wheel first with `pip install torch --index-url https://download.pytorch.org/whl/cpu`. If the model cannot be loaded or downloaded, the backend falls back automatically to a deterministic **hashing embedder** and a **lexical reranker**. The active choice is shown on the Knowledge Base page and recorded in every query event (`config_label`).

**LLM note:** without `GROQ_API_KEY`, answers use a deterministic **extractive** generator, which still produces citations. Those queries are honestly marked `Partial / LLM_FALLBACK`.

## What is implemented

| Brief requirement | Status | Where |
|---|---|---|
| FR-01 Document intake: type, size, empty or corrupt checks | ✅ | `src/knowledge/parsing.py` |
| FR-02 Text extraction with page, section, category, version and status metadata | ✅ PDF (per page), DOCX (headings and tables), TXT, MD | `parsing.py` |
| Scanned / handwritten documents | ⚠️ Detected and **rejected with an explicit "OCR not enabled" message**. OCR is not implemented. | `parsing.py` |
| FR-03 Configurable chunking, embeddings, repeatable indexing (content-hash dedup) | ✅ | `service.py`, `embeddings.py` |
| FR-04 Hybrid retrieval: vector + BM25, fused with RRF (reuses `src/retrieval/service.py::_reciprocal_rank_fusion`) | ✅ | `retrieval.py` |
| FR-05 Reranking: cross-encoder `ms-marco-MiniLM-L-6-v2`, or a documented lexical scorer | ✅ | `embeddings.py` |
| Metadata filters (category, status) | ✅ (API) | `retrieval.py` |
| FR-06 Multi-turn context: last 3 turns only, follow-up rewrite, selected turns logged | ✅ | `context.py` |
| FR-07 Tool routing: docs / SQL / both | ✅ rule-based and explainable | `router.py` |
| SQL tool: allowlisted parameterised templates, read-only connection | ✅ | `tools.py` |
| FR-08 Grounded generation with `[S1]`/`[T1]` citations | ✅ Groq, plus an extractive fallback | `generation.py` |
| Citation validation and claim-level grounding score | ✅ | `validation.py` |
| FR-09 Conflict handling (two versions of one policy) | ✅ surfaced in the answer and the trace | `validation.py` |
| FR-10 Insufficient-evidence and controlled-error fallbacks | ✅ | `service.py`, `outcome.py` |
| Prompt-injection detection: in the query (blocked) and in documents (stripped, logged) | ✅ | `safety.py` |
| PII redaction on output | ✅ regex-based | `safety.py` |
| FR-11 Helpful / not-helpful feedback with comment | ✅ | `/kis/feedback` |
| FR-12 Dashboard: aggregate KPIs plus per-query drill-down | ✅ | `frontend/src/app/observability` |
| Evaluation set and A/B configuration comparison report | ✅ 16 cases | `demo/eval/eval_set.json`, `reports/evaluation_report.md` |
| Automated tests | ✅ 36 tests, offline | `tests_knowledge/` |
| Container | ⚠️ `docker/Dockerfile.demo` written but **not tested** (no Docker on the dev machine) | `docker/` |

**Simulated or limited, and labelled as such:**
- The `vendor_invoices` SQL template targets a table that does not exist **on purpose**, to demonstrate the tool-failure path. The UI marks it "simulated failure".
- Demo mode has no user accounts. The header shows **"Local demo mode"**. The original OAuth, tenant and PostgreSQL routers are untouched and are used when `DEMO_MODE=false`.
- The cost KPI is an estimate from configured per-1K-token prices.

## Demo script (about 3 minutes)

1. **Knowledge Base**: click **Load demo corpus**. It indexes 6 synthetic docs: a PDF, a DOCX, MD and TXT files, and a superseded policy version. Optionally upload `demo/samples/scanned_receipt_no_text.pdf` or `corrupted_file.pdf` to show validation rejecting them.
2. **Assistant** (config B):
   - *"What is the standard document retention period for business records?"* gives the v2.0 answer (7 years) with a **conflict banner** naming v1.0 (5 years, superseded).
   - *"Who must approve ACR-3310?"* is an exact-ID lookup via BM25. Click the `[S1]` chip to see the source section.
   - *"What is the PDA for international travel?"* matches an acronym and cites the PDF **page 2**.
   - Follow up with *"What is the per diem allowance for domestic travel?"*, then *"And what about international trips?"*. This shows context resolution.
   - *"What is the remaining budget of PRJ-1002 and does a USD 20,000 purchase on it need CFO approval?"* is **combined** SQL `[T1]` + procurement SOP `[S1]`.
   - *"What is the parental leave entitlement?"* falls back honestly to insufficient evidence.
   - *"What are the deployment steps for Project Atlas?"* hits a document with an **embedded injection**. The injection is ignored and logged.
   - *"Show the vendor invoices for PRJ-1001."* is a **tool failure**: controlled error, outcome *Failed*.
   - Give 👍 / 👎 feedback with a comment.
3. **Observability**: show the KPIs, outcome distribution, reason codes and recent-queries table. Click a row for the **full trace**: router decision, retrieval scores (vector, BM25, fused, rerank), citations, grounding, safety, stage latencies, tokens and cost, and feedback.
4. Click **Run evaluation set**. It compares config A (vector only) with B (hybrid + rerank) over the 16 cases and writes `reports/evaluation_report.md`.

## API (`/api/v1/kis`, Swagger at `/docs`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health`, `/health/ready` | Liveness; readiness (store, business DB, models) |
| GET | `/kis/config` | Active embedder, reranker, LLM and configs |
| POST | `/kis/ingest` | Upload and index a document (multipart `file`) |
| POST | `/kis/ingest/demo` | Index `demo/corpus/*` |
| GET / DELETE | `/kis/documents[/{id}]` | List or remove documents |
| POST | `/kis/query` | `{query, session_id?, config_id: "A"\|"B", top_k?, category?, status?}` |
| POST | `/kis/feedback` | `{query_id, helpful, comment?}` |
| GET | `/kis/metrics` | Aggregate KPIs (`config_id`, `outcome`, `since_hours`, `include_eval` filters) |
| GET | `/kis/queries[/{id}]` | Recent query summaries, or the full per-query event |
| POST / GET | `/kis/eval/run`, `/kis/eval/status` | Run the A/B evaluation in the background, then poll |

Every response carries an `X-Request-ID` header, which is stored as the query's correlation ID.

## Tests & quality

```bash
python -m pytest tests_knowledge -q      # 36 tests, offline (hashing embedder, extractive generator)
ruff check src/knowledge tests_knowledge scripts
python scripts/run_eval.py               # A/B report -> reports/evaluation_report.md
cd frontend && npx tsc --noEmit && npm run build
```

`tests/` contains the original Postgres/MinIO integration suite. It needs Docker services and is not part of demo mode.

## Docs

- [docs/architecture.md](docs/architecture.md): architecture diagram and design decisions
- [docs/query_event_schema.md](docs/query_event_schema.md): query event schema and the Success / Partial / Failed rules
- [reports/evaluation_report.md](reports/evaluation_report.md): latest configuration comparison
- [README.original.md](README.original.md): the original platform (production path)

## Environment variables

See [.env.example](.env.example). The key ones:

- `DEMO_MODE` (default `true`)
- `GROQ_API_KEY`, `GROQ_MODEL_NAME`
- `KIS_EMBEDDER`, `KIS_RERANKER`
- `KIS_CHUNK_SIZE`, `KIS_CHUNK_OVERLAP`
- `KIS_MIN_EVIDENCE_SCORE`, `KIS_GROUNDING_THRESHOLD`
- `LLM_PRICE_INPUT_PER_1K`, `LLM_PRICE_OUTPUT_PER_1K`

Frontend:
- `BACKEND_URL` (default `http://127.0.0.1:8000`)
- `NEXT_PUBLIC_DEMO_MODE` (default on; set `false` for the OAuth flow)

## Known limitations

- No OCR: scanned or handwritten PDFs are rejected with a clear message.
- Routing and grounding are rule-based. They are deterministic and explainable, but not semantic.
- The index lives in memory (rebuilt from SQLite at startup), which is fine for demo-scale corpora.
- Conversation memory is per process. Evaluation runs are in-process background tasks.
