# Enterprise Knowledge Intelligence Assistant

HCL Tech AI Engineer hackathon. A production-minded RAG assistant that:

- answers questions from approved documents (PDF, DOCX, TXT, MD, scanned pages and photos of handwriting) and a structured business dataset (SQL tool);
- returns **grounded answers with validated citations**, safe arithmetic over tables, and charts drawn only from cited values;
- separates **users** (a full-window assistant) from **administrators** (knowledge base, observability, users, evaluation), enforced by the API;
- masks personal data and salaries for users, while admins see raw data;
- declines unsupported, conflicting or malicious requests safely;
- logs **every query** to an **observability and evaluation dashboard**, with per-user activity and unusual-activity rules.

It is built on the existing [`ai_research_platform`](README.original.md) codebase: FastAPI + Next.js, hybrid dense/sparse retrieval with Reciprocal Rank Fusion, and Groq for generation and vision. The **local demo mode** needs no PostgreSQL, MinIO, Redis or Google OAuth.

> All documents, people and figures in `demo/` are **synthetic** (a fictional company, "Orion Synthetic Industries").

---

## Quick start (Windows / macOS / Linux)

Prerequisites: Python 3.11+ and Node.js 20.9+.

```bash
# 1. Backend
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements-demo.txt     # see note on torch below
cp .env.example .env                     # Windows: copy .env.example .env
#   set GROQ_API_KEY=... (free key: https://console.groq.com)
#   set JWT_SECRET_KEY to a long random value:
#     python -c "import secrets; print(secrets.token_hex(32))"

python scripts/build_demo.py             # demo PDFs/DOCX/images + data/business.db
python scripts/seed_demo.py              # demo accounts + indexes the corpus
uvicorn src.main:app --port 8000         # API on http://localhost:8000/docs

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev                              # UI on http://localhost:3000
```

Open **http://localhost:3000** and sign in:

| Account | Password | Role | Sees |
|---|---|---|---|
| `admin` | `admin123` | admin | Assistant, Knowledge Base, Observability, Users, Evaluation |
| `alice`, `bob` | `user123` | user | A full-window assistant and *My history* only |

There is one sign-in form; the account decides the role. Admins can create more users on the **Users** page. The UI hides admin pages from users, but the security boundary is the API: every admin endpoint returns **403** to a user token (and the attempt is logged).

The UI proxies `/api/v1/*` to the backend on port 8000 (set `BACKEND_URL` to change it).

**Without a Groq key** the app still works: answers come from a deterministic **extractive** generator (marked `Partial / LLM_FALLBACK`), and scanned pages, photos and chart images are skipped with a clear message because they need the vision model.

**Embeddings note:** `sentence-transformers` pulls in PyTorch. On a slow network, install the CPU wheel first (`pip install torch --index-url https://download.pytorch.org/whl/cpu`). If the model cannot load, the backend falls back to a deterministic **hashing embedder** and **lexical reranker**; the active choice is shown on the Knowledge Base page and recorded in every query event.

## What is implemented

| Requirement | Status | Where |
|---|---|---|
| FR-01 Intake: type, 20 MB size, empty/corrupt, magic bytes, renamed executables, metadata form fields | ✅ | `src/knowledge/parsing.py` |
| FR-02 Extraction with page, section, category, version, status; tables kept in reading order | ✅ PDF (PyMuPDF), DOCX (body order), TXT, MD | `parsing.py` |
| Scanned PDFs and handwritten/photographed notes | ✅ with `GROQ_API_KEY` (Groq vision OCR; page image kept as an asset). ⚠️ Without a key they are skipped with a message | `vision.py`, `parsing.py` |
| Charts inside PDFs | ✅ with a key: chart → text summary + data table chunk, original image returned when cited | `parsing.py`, `visuals.py` |
| FR-03 Configurable chunking; a table is one chunk (split by rows with the header repeated) | ✅ | `service.py` |
| FR-04 Hybrid retrieval: vector + BM25 + RRF; `doc_id`/`version`/`category`/`status` filters | ✅ | `retrieval.py` |
| FR-05 Reranking: cross-encoder `ms-marco-MiniLM-L-6-v2` (or lexical fallback) | ✅ | `embeddings.py` |
| FR-06 Multi-turn: last 3 turns, strict follow-up detection, LLM rewrite when a key is set | ✅ (context-leak bug from the audit fixed and tested) | `context.py` |
| FR-07 Tool routing: docs / SQL / both, rule-based; allowlisted, parameterised, read-only SQL | ✅ (project **IDs** only, see limitations) | `router.py`, `tools.py` |
| FR-08 Grounded generation with `[S#]`/`[T#]`/`[U1]` citations; safe `{{calc: …}}` arithmetic | ✅ | `generation.py`, `calc.py`, `validation.py` |
| FR-09 Conflicts between versions (incl. a draft v3.0) | ✅ | `validation.py` |
| FR-10 Insufficient-evidence and controlled-error fallbacks | ✅ | `service.py`, `outcome.py` |
| FR-11 Feedback (helpful / not helpful + comment), only on your own answers | ✅ | `/kis/feedback` |
| FR-12 Dashboard: KPIs, charts, anomalies, per-user filter, per-query drill-down with the prompt sent | ✅ | `frontend/src/app/observability` |
| Login with admin/user roles (JWT, bcrypt), sessions owned by one user | ✅ | `auth.py`, `routes.py` |
| Masking of personal data and salaries for users (admins see raw) | ✅ | `masking.py` |
| Per-user history, sessions, tokens; unusual-activity rules | ✅ | `anomaly.py`, `/kis/admin/*`, `/kis/my/*` |
| Token budgets (input/output limits, per-stage accounting, truncation flags) | ✅ | `generation.py`, `service.py` |
| Image as query input | ✅ with a key | `/kis/query/multimodal` |
| Prompt-injection: question blocked; instructions in documents/images stripped and logged | ✅ | `safety.py` |
| Evaluation: 40 cases, configs A/B/C, hit@1, MRR@5, optional LLM judge | ✅ | `evaluation.py`, `demo/eval/eval_set.json` |
| Automated tests | ✅ 162 tests, offline | `tests_knowledge/` |
| Containers | ⚠️ `docker-compose.demo.yml` written but **not built** (no Docker on the dev machine) | `docker/` |

## Demo script (about 5 minutes)

1. **Sign in as `admin`.** On **Knowledge Base**, click **Load demo corpus** (19 synthetic documents). Upload `demo/samples/corrupted_file.pdf` (rejected with a reason) and, with a Groq key, `demo/samples/handwritten_ops_note.jpg` (accepted, read by OCR).
2. **Assistant** — use **Try a scenario**:
   - *Conflict*: retention period → v2.0 (7 years) with a banner naming the other versions of HR-POL-007.
   - *Exact ID*: "Who must approve ACR-3310?" → CISO; click `[S1]` to see the highlighted sentence.
   - *SQL + policy*: PRJ-1002 remaining budget plus CFO approval → `[T1]` table + `[S1]`.
   - *Table maths* (needs a key): total profit of the last 5 months → `228,000 (= 37,000+…)`.
   - *Chart*: "Plot the monthly profit…" → a line chart built only from the cited table.
   - *Injection*, *No evidence*, *Tool failure*: safe behaviour, each explained in one status line.
3. **Sign in as `alice`** in another window: the full-window assistant only. Ask *Personal data* ("annual salary and email of Tom Becker") → `[SALARY]`, `[EMAIL]`. Ask the same as admin → raw values. Try opening `/observability` as alice → redirected; the API returns 403.
4. **Observability** (admin): KPIs, latency and A/B charts, unusual activity (alice's 403s appear as `FORBIDDEN_ACCESS`), filter by user, open a trace: outcome summary, stage timeline, scores per chunk, citations, grounding, masking, the prompt sent.
5. **Users**: per-user tokens and sessions → open a transcript. **Evaluation**: run A/B/C and read the per-case table.

## API (`/api/v1/kis`, Swagger at `/docs`)

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/auth/login` | public | Username + password → JWT |
| GET | `/auth/me` | any | Current user (never a password field) |
| GET | `/config` | any | Active embedder, reranker, LLM, vision, limits |
| POST | `/query` | any | `{query, session_id?, config_id A\|B\|C, top_k?, category?, status?, doc_id?, version?, max_input_tokens?, max_output_tokens?}` |
| POST | `/query/multimodal` | any | Multipart: `image` (png/jpg/webp ≤ 10 MB) + optional `query` |
| POST | `/feedback` | any | `{query_id, helpful, comment?}` (own answers only) |
| GET | `/assets/{id}` | any | Original chart / page / photo image for a citation |
| GET | `/my/sessions`, `/my/history` | any | Own conversations (masked for users) and token use |
| POST | `/ingest`, `/ingest/demo` | admin | Upload (multipart `file` + optional `category`, `version`, `status`, `effective_date`) / index the demo corpus |
| GET / DELETE | `/documents[/{id}]`, `/documents/{id}/chunks` | admin | List, remove, view chunks |
| GET | `/metrics`, `/queries[/{id}]` | admin | KPIs and events (filters incl. `user_id`) |
| GET / POST | `/admin/users`, `/admin/users/summary`, `/admin/users/{id}/sessions`, `/admin/sessions/{id}`, `/admin/anomalies` | admin | Users, activity, transcripts, unusual activity |
| POST / GET | `/eval/run`, `/eval/status` | admin | Run the A/B/C evaluation; latest result survives restarts |

Every response carries an `X-Request-ID` header, stored as the query's correlation ID.

## Tests & quality

```bash
python -m pytest tests_knowledge -q      # 162 tests, offline (fake vision, stubbed LLM where needed)
ruff check src/knowledge tests_knowledge scripts
python scripts/run_eval.py               # A/B/C report -> reports/evaluation_report.md
cd frontend && npx tsc --noEmit && npm run build
```

`tests/` contains the original Postgres/MinIO integration suite. It needs Docker services and is not part of demo mode.

## Docs

- [docs/HLD.md](docs/HLD.md): high-level design
- [docs/architecture.md](docs/architecture.md): architecture diagram and design decisions
- [docs/authentication.md](docs/authentication.md): how sign-in, tokens and roles work in the backend
- [docs/query_event_schema.md](docs/query_event_schema.md): query event schema and the Success / Partial / Failed rules
- [reports/evaluation_report.md](reports/evaluation_report.md): latest configuration comparison
- [README.original.md](README.original.md): the original platform (production path, `DEMO_MODE=false`)

## Environment variables

All are listed with comments in [.env.example](.env.example). The main ones:

- `DEMO_MODE` (default `true`), `JWT_SECRET_KEY` (set it; otherwise a random per-process secret is used and logins end on restart), `KIS_TOKEN_EXPIRE_MINUTES`
- `GROQ_API_KEY`, `GROQ_MODEL_NAME` (default `llama-3.3-70b-versatile`), `GROQ_VISION_MODEL` (default `meta-llama/llama-4-scout-17b-16e-instruct`)
- `KIS_EMBEDDER`, `KIS_RERANKER`, `KIS_CHUNK_SIZE`, `KIS_CHUNK_OVERLAP`, `KIS_TABLE_CHUNK_MAX_CHARS`
- `KIS_MAX_UPLOAD_MB` (20), `KIS_VISION_ENABLED`, `KIS_VISION_MAX_PAGES`, `KIS_QUERY_IMAGE_MAX_MB`, `KIS_STORE_QUERY_IMAGES`
- `KIS_MIN_EVIDENCE_SCORE`, `KIS_GROUNDING_THRESHOLD`, `KIS_MAX_INPUT_TOKENS_CAP`, `KIS_MAX_OUTPUT_TOKENS_CAP`
- `KIS_ANOMALY_*`, `KIS_USER_DAILY_TOKEN_CAP`, `KIS_OFF_HOURS_START/END`
- `LLM_PRICE_INPUT_PER_1K`, `LLM_PRICE_OUTPUT_PER_1K`

Frontend: `BACKEND_URL` (default `http://127.0.0.1:8000`, read at build time), `NEXT_PUBLIC_DEMO_MODE` (default on).

## Docker (untested)

```bash
JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") \
GROQ_API_KEY=... docker compose -f docker-compose.demo.yml up --build
```

Backend and frontend run as two services; data lives in the `kis-data` volume and is seeded on start-up. **This has not been built**: Docker was not available on the development machine.

## Known limitations

- **The Groq paths were not run against the live API on the dev machine** (no key there): LLM generation, `{{calc}}`, model charts, follow-up rewrites, vision OCR, chart reading and image questions are covered by tests with a stubbed LLM and a fake vision client. Run the demo questions with a key before presenting, and check that `GROQ_MODEL_NAME` / `GROQ_VISION_MODEL` are still served by Groq.
- **SQL tool resolves project IDs only.** "How much has been spent on Project Atlas?" does not reach SQL (a team decision kept the tool unchanged; it is an eval case that fails on purpose).
- Routing and grounding are rule-based: explainable, but not semantic. Two paraphrase eval cases fall below the evidence threshold even with the semantic embedder.
- Person names are not masked (that would need NER); masking is pattern-based.
- The JWT is kept in `localStorage` (as the existing client did); an httpOnly cookie would be safer against XSS.
- The index lives in memory (rebuilt from SQLite at start-up). Conversation memory is per process, so a restart drops follow-up context.
- Without a key, the cost KPI is zero; with a key it is an estimate from configured prices.




Project Assumptions

Purpose: The project is an internal knowledge assistant for finding and understanding organizational information. It is not intended to be a general-purpose chatbot.

Target users: Employees use the assistant to ask questions and review their own query history. Administrators manage documents, users, evaluation runs, and observability.

Primary use cases: Users need to look up policies, procedures, technical guidance, and selected business facts; compare document versions; and combine document evidence with structured business data when supported.

Trusted sources: Answers should be based on organization-approved documents and the configured business dataset. The assistant should cite its sources and decline when evidence is missing or conflicting.

Data scope: The demo uses synthetic company data. A real deployment would require an organization to supply and govern its own approved documents and structured data; confidential or regulated data is outside the demo’s intended scope.

Supported workflows: The initial scope covers document questions, allowlisted business lookups, and questions that combine those sources. It does not include arbitrary database queries or unrestricted access to enterprise systems.

User access: The project assumes two main roles: employee and administrator. Employees see only their own history and permitted answers; administrators have broader management and diagnostic access.

Interaction model: The primary experience is a browser-based assistant. Document and image ingestion are administrative workflows; image understanding depends on the configured vision service.

AI behavior: External language and vision models may be unavailable. The project therefore assumes transparent fallbacks are acceptable, even when they provide less capable answers than the hosted models.

Deployment and scale: The current implementation is a hackathon/demo MVP intended for low-volume evaluation, not a production service with defined availability, throughput, or support guarantees.

Success criteria: Trustworthiness, traceable answers, safe handling of insufficient evidence, and useful administration are more important than answering every question.

Limitations

LLM and vision behavior isn’t live-verified. Groq generation, OCR, chart reading, and image questions were tested with stubs, not against the live API. Without a Groq key, the app uses extractive answers and skips vision features.
SQL coverage is narrow. Queries resolve project IDs, not project names; for example, “Project Atlas” won’t resolve to its SQL record.
Routing and grounding use rules. Some paraphrased questions fall below the evidence threshold even with semantic embeddings.
PII masking is pattern-based. It masks configured identifiers and salary patterns, but not people’s names; data is unmasked at ingestion, and admins see raw values.
The demo is single-process. The retrieval index is rebuilt in memory from SQLite at startup, and conversation context is process-local, so restarts drop follow-up context.
Local authentication needs configuration for persistence. In this run, JWT_SECRET_KEY was unset, so the app generated a per-process secret; restarting the backend invalidates existing tokens. The frontend stores JWTs in localStorage.
Cost reporting is approximate. It reports zero without an LLM key and estimates cost from configured prices when a key is used.
The production path wasn’t validated here. PostgreSQL, MinIO, multi-tenant RLS, and deployment behavior are separate from the local demo path.
Current test caveat: the run had 161 passing tests and one failure: test_off_hours puts the event just before the configured window. The frontend install also reported 6 dependency advisories: 5 high and 1 critical


Example:
“What is the remaining budget of PRJ-1002 and does a USD 20,000 purchase need CFO approval?”
