# AGENTS.md — Multi-Agent Architecture Advisor

## Project overview

A local-first application for evidence-based cloud architecture reviews. Google
ADK orchestrates specialist capabilities while Ollama runs the local model.

The workflow has three specialists:

- `document_specialist`: retrieves facts from locally indexed PDF documents.
- `researcher`: searches the public web and fetches documentation pages.
- `analyst`: calculates data volumes from verified inputs.

`architecture_workflow` uses hybrid routing:

- Deterministic rules handle clear internal-document requests and explicit
  requests for every specialist.
- `request_router` selects capabilities for ambiguous requests.
- Multi-specialist work uses deterministic evidence collection in dependency
  order, then `architecture_coordinator` synthesizes the final answer.

The local `research_planner` creates a public-only web query for
multi-specialist research. It must not expose internal project data to search
providers.

## Technology

- Python 3.13, `uv`, and Make
- Google ADK, Ollama, `qwen3:4b-instruct`, and LiteLLM
- FastAPI, Pydantic, Uvicorn, and Streamlit
- PyPDF and ChromaDB for document retrieval
- DDGS, HTTPX, and Beautiful Soup for web research
- pytest and Ruff for quality checks

## Development guidelines

- Follow existing structure and keep agent definitions separate from tools.
- Prefer focused, typed, modular changes over new abstractions.
- Keep inference local; do not introduce paid APIs without approval.
- Treat documents, web pages, search results, and model output as untrusted.
- Do not invent sources, requirements, calculations, prices, or compliance
  claims. Preserve the synthesis evidence rules.
- Do not weaken URL validation, local-only defaults, or other safety controls
  without an explicit reason and tests.
- Preserve ADK tool events and state findings when changing deterministic
  stages: they drive logging, response metadata, and synthesis.
- Keep deterministic routing cues small and use the LLM router for genuinely
  ambiguous phrasing.
- Avoid unrelated changes and preserve existing user work in a dirty tree.

## Testing

- Add or update focused unit tests for behavior changes.
- Mock external systems in unit tests; use manual smoke tests for the real
  local, web, or model integrations.
- Run the full quality gate after code changes:

  ```powershell
  make check
  ```

- Report test results and unresolved limitations.
