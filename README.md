# Multi-Agent Architecture Advisor

A local-first application for evaluating cloud architectures and technology
decisions. Google ADK coordinates specialist agents, while Ollama runs the
Qwen3 4B model locally through LiteLLM.

## What it does

The workflow identifies the capabilities required for each request and runs the
selected specialists in a controlled order:

- `analyst`: validates inputs and calculates data volumes.
- `researcher`: searches the public web, fetches relevant pages, and cites
  sources.
- `document_specialist`: retrieves facts from locally indexed PDF documents.

Most requests use the model-based `request_router`. Clear internal-document
questions and explicit requests for all specialists use deterministic routing
to avoid unnecessary model decisions. Single-specialist results are returned
directly; multi-specialist results are passed to `architecture_coordinator` for
final synthesis.

### Why hybrid routing?

Deterministic rules handle requests whose intent must be predictable, such as
clear internal-document questions or an explicit instruction to consult every
specialist. Other requests go to the LLM router, which can recognize equivalent
intent across varied natural-language wording and select any combination of
document retrieval, web research, and calculation.

This balance avoids asking a small local model to classify obvious requests,
while avoiding a large and fragile keyword list for every possible phrasing. It
also reduces latency and failure opportunities by running only the specialists
a request needs. Selected stages execute in dependency-safe order, and explicit
all-specialist requests remain guaranteed rather than model-dependent.

For multi-specialist assessments, a local structured planner creates a
public-only query. The workflow then executes document retrieval, web search,
and page fetching deterministically, prioritizing documentation-like search
results. This prevents the small local model from skipping mandatory evidence
collection without tying the workflow to one provider or product.
Focused research-only questions still use the researcher agent's tool selection.

The current application includes:

- Multi-agent orchestration and tool calling with Google ADK.
- Local inference with `ollama_chat/qwen3:4b-instruct`; extended thinking is
  disabled, with response sanitization as a fallback.
- PDF ingestion, overlapping text chunks, and persistent ChromaDB retrieval.
- Web search with DDGS and page extraction with HTTPX and Beautiful Soup.
- A FastAPI interface with conversation sessions, response validation,
  participating-agent metadata, and safe error responses.
- A Streamlit chat interface that uses FastAPI as its backend.
- Unit tests with external services mocked.

## Technology stack

- **Language and environment:** Python 3.13, `uv`, and Make convenience
  commands.
- **Agent runtime:** Google ADK orchestrates the workflow; Ollama runs the
  local `qwen3:4b-instruct` model; LiteLLM connects ADK to Ollama.
- **Backend:** FastAPI, Pydantic, and Uvicorn provide the validated HTTP API
  and in-memory conversation sessions.
- **Frontend:** Streamlit provides the local chat interface.
- **Document retrieval:** PyPDF extracts PDF text; ChromaDB stores embeddings
  and retrieves relevant chunks.
- **Web research:** DDGS searches the web; HTTPX and Beautiful Soup fetch and
  extract public documentation pages.
- **Quality:** pytest covers behavior with mocked external services; Ruff
  handles linting and formatting.

## Architecture

There is a detailed architecture graph under docs.

The same flow in compact text form:

```text
Client
  |
  +-- ADK Web (development and agent tracing)
  |
  +-- FastAPI POST /chat
          |
          v
  architecture_workflow
          |
          +-- request_router (when classification is needed)
          +-- research_planner (public query)
          +-- document_specialist -> search_documents -> ChromaDB
          +-- researcher ---------> search_web, fetch_web_page
          +-- analyst ------------> calculate_data_volume
          +-- architecture_coordinator (multi-specialist synthesis)
```

Web content and retrieved documents are treated as untrusted data. The agents
must distinguish sourced facts from assumptions and must not invent citations
or prices.

## Requirements and installation

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com/)
- Make, if you want to use the convenience commands

From the project root:

```powershell
uv sync
ollama pull qwen3:4b-instruct
```

Ensure Ollama is running. If it is not already running as a service:

```powershell
ollama serve
```

## Quick start

### Inspect agents in ADK Web

```powershell
make agent
```

Equivalent command without Make:

```powershell
uv run adk web src/multi_agent_project
```

Open <http://127.0.0.1:8000>, select the application, and use **Events** or
**Traces** to inspect transfers and tool calls.

### Use the FastAPI interface

On the first run, index the included sample document:

```powershell
uv run python -c "from multi_agent_project.rag.ingestion import ingest_pdf; print(ingest_pdf('data/sample_documents/Internal_atlas_project.pdf'))"
```

Then start the API:

```powershell
make api
```

Open <http://127.0.0.1:8001/docs> and execute `POST /chat`:

```json
{
  "message": "What is the internal Project Atlas reporting latency requirement?"
}
```

The response contains an answer, a generated session ID, and execution metadata
showing which agents and tools participated:

```json
{
  "answer": "The maximum acceptable delay is 15 minutes.",
  "session_id": "generated-uuid",
  "agents_used": [
    "document_specialist"
  ],
  "tools_called": [
    "document_specialist.search_documents"
  ]
}
```

Pass the returned `session_id` in a later request to continue the same
conversation. Sessions are currently held in memory and are lost when the API
restarts.

Available endpoints:

- `GET /health`: process liveness check.
- `POST /chat`: invoke the multi-agent workflow.
- `GET /docs`: interactive Swagger documentation.

`GET /` is not defined, so opening the server root returns `404 Not Found`.

### Use the Streamlit interface

Keep FastAPI running, then start Streamlit in another terminal:

```powershell
make ui
```

Streamlit sends chat requests to `http://127.0.0.1:8001` by default. Override
the backend when needed by setting the `API_BASE_URL` environment variable.

## Local document retrieval

Index the included sample PDF before asking document-specific questions:

```powershell
uv run python -c "from multi_agent_project.rag.ingestion import ingest_pdf; print(ingest_pdf('data/sample_documents/Internal_atlas_project.pdf'))"
```

The ChromaDB index is stored under `data/chroma/` and is intentionally excluded
from version control.

## Project layout

```text
src/multi_agent_project/
  agents/      ADK coordinator and specialist definitions
  api/         FastAPI application
  frontend/    Streamlit chat interface
  models/      shared LLM configuration and Pydantic schemas
  rag/         PDF ingestion and ChromaDB access
  tools/       deterministic agent tools
tests/         unit and API tests
data/          sample documents and generated local vector data
docs/          detailed development guide
```

## Development

For the complete staged workflow, exact test commands, agent test prompts,
FastAPI and Streamlit checks, observability, and
troubleshooting, see [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

For the design decisions behind the current hybrid workflow, see
[docs/ARCHITECTURE_EVOLUTION.md](docs/ARCHITECTURE_EVOLUTION.md).

A full local quality check is:

```powershell
make check
```

## Example end-to-end prompt

```text
Using the internal Project Atlas requirements document, evaluate whether Google
BigQuery is a suitable analytics platform. First retrieve the project's
ingestion, latency, budget, and data residency requirements. Then research
BigQuery's current capabilities using official Google Cloud documentation.
Calculate the monthly data ingestion volume assuming 30 days. Combine the
findings into an architecture recommendation with trade-offs, cost assumptions,
and source references.
```

This prompt should exercise all three specialists. Web research requires an
internet connection; model inference and document retrieval remain local.
The same request body is available in [`example_prompt_api.json`](example_prompt_api.json).

## Security

This project is intended for local development, not production deployment.
FastAPI and Streamlit bind to `127.0.0.1`, and web fetching blocks common SSRF
targets such as local, private, and reserved addresses. Retrieved webpages and
documents must still be treated as untrusted input.

Before exposing the application to other users or networks, add authentication,
TLS, persistent sessions, request limits, network controls, secure secret
storage, dependency scanning, and a dedicated security review.
