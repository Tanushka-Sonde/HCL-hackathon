# AI Research Platform

## The Problem We Are Solving

Modern AI research platforms often suffer from premature architectural complexity. When building multi-tenant Retrieval-Augmented Generation (RAG) applications, teams frequently adopt disjointed tech stacks: ChromaDB or Qdrant for vector search, Elasticsearch for full-text search, Celery/Redis for job queuing, and PostgreSQL for relational metadata. This introduces distributed data consistency problems, complex operational overhead, and makes tenant isolation difficult.

This project solves these challenges by adopting a **Postgres-Maximalist** philosophy. We are building a scalable, multi-tenant AI research platform with hybrid retrieval (dense + sparse + Reciprocal Rank Fusion) using a single, unified data store. We leverage PostgreSQL's native capabilities to handle relational data, vector search (via `pgvector`), full-text search (via `tsvector`), and job queuing (via `SKIP LOCKED`), ensuring ACID compliance and strong tenant isolation via Row-Level Security (RLS) across the entire platform.

## Architecture

**Core Principle:** PostgreSQL handles relational data, vector search, full-text search, and job queuing. Additional infrastructure enters only when PostgreSQL provably cannot serve the requirement.

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Frontend | Next.js (React) | Multi-tenant SaaS UI with role-based access control |
| API | FastAPI | Async HTTP API with JWT auth |
| Authentication | Google OAuth 2.0 | Secure, passwordless authentication |
| Database | PostgreSQL 16 + pgvector | Relational data, vectors, full-text, job queue, RLS |
| Tenancy | PostgreSQL RLS + organizations | Tenant isolation and RBAC |
| Object Storage | MinIO (S3-compatible) | Document file storage |
| Embedding | sentence-transformers (all-MiniLM-L6-v2) | Local embedding model |
| RAG Synthesis & CRAG | Groq (Llama 3) | Fast AI generation and relevance evaluation |
| Web Fallback | Tavily | Live web search when internal chunks are irrelevant |
| Rate Limiting | aiolimiter (v2.0) / Redis (v3.0) | Token bucket rate limiting |
| Logging | structlog | Structured JSON logging |
| Migrations | Alembic | Database schema versioning |

## Implementation

The platform is designed around several key technical implementations:

- **Multi-Tenant Architecture**: Robust data isolation using PostgreSQL Row-Level Security (RLS) patterns and tenant-aware routing.
- **PostgreSQL-Powered**: Uses PostgreSQL for strict state management, tenant isolation, pgvector for dense embeddings, full-text search for sparse keyword matching, and SKIP LOCKED for scalable background job queues.
- **Passwordless Authentication**: Enforces Google OAuth 2.0 globally across the platform, eliminating stored password hashes and simplifying user onboarding.
- **Fail-Open Rate Limiting**: Redis-backed distributed rate limiting via atomic Lua scripts to prevent API abuse, prioritizing availability if the cache goes down.
- **Hybrid Retrieval**: Asynchronous concurrent database queries combining Dense (semantic) + Sparse (keyword) search using Reciprocal Rank Fusion (RRF).
- **Corrective RAG (CRAG) & Web Fallback**: Evaluates internal search results using a fast Groq LLM. If the internal chunks are deemed useless, it automatically triggers a fallback to Tavily's live web search engine.
- **Asynchronous Ingestion**: Fault-tolerant background workers to process, chunk, and embed documents in isolation.
- **Deep Observability**: Out-of-the-box Prometheus instrumentation tracking API latency, database connection pools, LLM usage, and circuit-breaker state metrics.

### Project Structure
```
ai-research-platform/
├── alembic/                  # Database migrations
├── src/
│   ├── core/                 # Config, database, security, logging, exceptions
│   ├── auth/                 # Google OAuth and JWT generation
│   ├── documents/            # Document upload and management
│   ├── ingestion/            # Chunking, embedding, worker daemon
│   ├── retrieval/            # Hybrid search, CRAG eval, Tavily fallback, Groq synthesis
│   ├── evaluation/           # LLM gateway
│   ├── tenants/              # Multi-tenancy, RBAC (v3.0)
│   ├── observability/        # Prometheus metrics, health checks (v3.0)
│   └── main.py               # FastAPI application factory
├── mcp_server/               # MCP stdio interface
├── frontend/                 # Next.js React frontend
│   ├── src/app/              # App router pages (dashboard, search, etc.)
│   ├── src/components/       # Reusable React components (TenantProvider, Header)
│   └── src/lib/              # Frontend API client and permissions logic
├── tests/
│   ├── unit/                 # Pure logic tests
│   ├── integration/          # Tests requiring running services
│   ├── concurrency/          # Race condition and locking tests
│   └── load/                 # Locust load test scripts
├── docker/
│   ├── Dockerfile
│   ├── docker-compose.yml    # Dev: PG + MinIO
│   └── docker-compose.prod.yml  # Prod: + Nginx + Redis + Prometheus
├── requirements.in           # Human-maintained dependency constraints
├── pyproject.toml            # Tool configuration (ruff, mypy, pytest)
└── .env.example              # Environment variable template
```

## How to Clone and Run

### Prerequisites

- Python 3.11+
- Git
- Make sure you have Docker and Docker Compose installed.

### Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/Dhruv-Sharma01/ai_research_platform.git
   cd ai_research_platform
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv .venv
   
   # Windows:
   .venv\Scripts\activate
   
   # Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install backend dependencies**
   ```bash
   pip install -r requirements.in
   ```

4. **Install frontend dependencies**
   ```bash
   cd frontend
   npm install
   cd ..
   ```

5. **Configure environment variables**
   ```bash
   # Windows:
   copy .env.example .env
   
   # Linux/macOS:
   cp .env.example .env
   ```
   
   **Required Configuration in `.env`:**
   Open the `.env` file and set the required API keys for authentication and RAG:
   ```env
   GOOGLE_CLIENT_ID="your-google-oauth-client-id"
   GROQ_API_KEY="gsk_your_groq_api_key"
   GROQ_MODEL_NAME="llama3-8b-8192"  # or llama-3.3-70b-versatile
   TAVILY_API_KEY="tvly-your_tavily_key"
   ```

6. **Start Infrastructure Services**

### Production Environment

To run the full production-ready stack (2x API instances, 2x Workers, PostgreSQL, Redis, MinIO, Nginx, Prometheus, Grafana):

```bash
docker-compose -f docker-compose.prod.yml up -d
```

### Local Development

To run the infrastructure backing the app:

```bash
docker-compose up -d
```

7. **Run database migrations**
   ```bash
   alembic upgrade head
   ```

8. **Start the applications**
   You will need multiple terminal windows (with the virtual environment activated in each) to run the services.

   **Terminal 1 (API Server):**
   ```bash
   uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
   ```
   
   **Terminal 2 (Ingestion Worker):**
   ```bash
   python -m src.ingestion.worker
   ```

   **Terminal 3 (Frontend):**
   ```bash
   cd frontend
   npm run dev
   ```
   
   **Terminal 4 (Optional: MCP Server):**
   ```bash
   python -m mcp_server
   ```

### Accessing the Application
Once the servers are running, visit:
- **Frontend App:** http://localhost:3000
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **Health Check:** http://localhost:8000/health

## License

MIT
