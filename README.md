# Multi-Agent Architecture Advisor

A local-first application for evidence-based cloud architecture reviews. Google
ADK coordinates specialist agents, while Ollama runs `qwen3:4b-instruct`
locally through LiteLLM.

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

Deterministic rules handle intent that must be predictable, such as clear
internal-document questions or an explicit request for every specialist. Other
requests go to the LLM router, which can interpret varied wording and select
document retrieval, web research, and/or calculation.

For multi-specialist assessments, a local structured planner creates a
public-only query, then the workflow collects document, web, and calculation
evidence in dependency-safe order. This avoids relying on a small local model
to remember mandatory tool calls while keeping focused research-only questions
flexible.

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

The normal application flow is:

```text
User
  -> Streamlit UI
  -> FastAPI POST /chat
  -> ADK Runner
  -> architecture_workflow
       -> request_router (when classification is needed)
       -> research_planner (public query, when needed)
       -> document_specialist -> search_documents -> ChromaDB
       -> researcher ---------> search_web, fetch_web_page
       -> analyst ------------> calculate_data_volume
       -> architecture_coordinator (multi-specialist synthesis)
  -> FastAPI response
  -> Streamlit UI
  -> User
```

Two development and testing entry points use the same underlying components:

- **Swagger UI** (`/docs`) sends requests to FastAPI, so it follows the same
  API-to-ADK path as Streamlit.
- **ADK Web** invokes the ADK application directly and provides Events and
  Traces for agent development; it is not part of the Streamlit request path.

### Code mental model

```text
routing.py
-> decides which capabilities are needed

workflow_stages.py
-> guarantees evidence collection for complex multi-stage work

agent.py
-> controls execution order, validation, and synthesis

specialist agent files
-> define each role, tools, and prompt

synthesis_agent.py
-> turns collected findings into the final user-facing answer
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

The generated ChromaDB index is stored under `data/chroma/` and is excluded
from version control.

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
docs/          development guide and architecture notes
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
