# Development Guide

This is the practical playbook for changing, testing, and debugging the
project. The README explains the product and provides the quick start; this
document focuses on how to develop each layer safely and how to verify the
boundaries between layers.

Run all commands from the repository root unless stated otherwise.

## 1. Restore the development environment

When returning to the project after a long break, start here.

```powershell
uv sync
ollama pull qwen3:4b-instruct
ollama list
make check
```

If Ollama is not installed as a background service, start it in a separate
terminal and leave that terminal open:

```powershell
ollama serve
```

Useful command overview:

```powershell
make help
```

Make targets and direct equivalents:

| Goal | Make | Direct command |
|---|---|---|
| Install dependencies | `make install` | `uv sync` |
| Run unit tests | `make test` | `uv run pytest -q` |
| Lint | `make lint` | `uv run ruff check .` |
| Apply safe lint fixes | `make fix` | `uv run ruff check . --fix` |
| Format | `make format` | `uv run ruff format .` |
| Run all checks | `make check` | See quality gate below |
| Start ADK Web | `make agent` | `uv run adk web src/multi_agent_project` |
| Start FastAPI | `make api` | `uv run uvicorn multi_agent_project.api.main:app --reload --host 127.0.0.1 --port 8001` |
| Start Streamlit | `make ui` | `uv run streamlit run src/multi_agent_project/frontend/streamlit_app.py --server.address 127.0.0.1` |

## 2. The development sequence

Build outward one boundary at a time:

```text
tool function
    -> specialist agent
    -> coordinator delegation
    -> FastAPI
    -> Streamlit
    -> end-to-end workflow
```

At each stage, keep the lower-level tests passing. A good final answer from an
LLM is not enough evidence by itself: inspect whether the expected agent and
tool were actually used.

## 3. Stage 1: develop a tool independently

Tools live under `src/multi_agent_project/tools/`. Keep them separate from
agent definitions so they can be validated without Ollama or ADK.

For every tool change:

1. Define typed inputs and a predictable return shape.
2. Validate invalid and boundary inputs.
3. Handle expected external failures explicitly.
4. Add unit tests with network, filesystem, PDF, or database dependencies
   mocked where appropriate.
5. Run a real smoke test only after the unit tests pass.

Run tests for one tool area:

```powershell
uv run pytest tests/test_calculations.py -v
uv run pytest tests/test_web_search.py -v
uv run pytest tests/test_web_fetch.py -v
uv run pytest tests/test_rag.py -v
```

Direct smoke tests:

```powershell
uv run python -c "from multi_agent_project.tools.calculations import calculate_data_volume; print(calculate_data_volume(350, 30))"
```

```powershell
uv run python -c "from multi_agent_project.tools.web_search import search_web; print(search_web('Google BigQuery official documentation', 3))"
```

```powershell
uv run python -c "from multi_agent_project.tools.web_fetch import fetch_web_page; print(fetch_web_page('https://cloud.google.com/bigquery/docs'))"
```

Unit tests must not require Ollama or live internet access. Smoke tests may fail
when a real service, DNS, or the internet is unavailable.

## 4. Stage 2: develop and verify RAG

RAG has three distinct steps. Test them separately:

1. `ingestion.py` extracts, normalizes, and chunks PDF text.
2. `vector_store.py` persists chunks and runs similarity queries.
3. `document_search.py` exposes retrieval as an agent-friendly tool.

Run the unit tests:

```powershell
uv run pytest tests/test_rag.py -v
```

Index the sample document:

```powershell
uv run python -c "from multi_agent_project.rag.ingestion import ingest_pdf; print(ingest_pdf('data/sample_documents/Internal_atlas_project.pdf'))"
```

Query the indexed document without invoking an agent:

```powershell
uv run python -c "from multi_agent_project.tools.document_search import search_documents; print(search_documents('What is the Project Atlas reporting latency requirement?'))"
```

Confirm that the result includes:

- `status: success`
- the relevant passage
- `Internal_atlas_project.pdf`
- page `1`

The persistent index lives in `data/chroma/`. Re-ingesting the same PDF uses
stable chunk IDs and upserts records rather than creating a new ID for every
run.

## 5. Stage 3: test one specialist agent

A specialist-agent test answers a different question from a tool test:

- Tool test: does the Python function work?
- Agent test: does the model choose the tool, provide suitable arguments, and
  use the result correctly?

The most convenient visual test is ADK Web, but the normal root there is the
coordinator. To isolate a specialist, run it directly with an in-memory runner.

Example for the document specialist:

```powershell
@'
import asyncio

from google.adk.runners import InMemoryRunner
from multi_agent_project.agents.rag_agent import document_specialist_agent


async def main() -> None:
    runner = InMemoryRunner(agent=document_specialist_agent)
    await runner.run_debug(
        "What is the Project Atlas reporting latency requirement?",
        verbose=True,
    )


asyncio.run(main())
'@ | uv run python -
```

For another specialist, replace the import and agent passed to
`InMemoryRunner`:

- `analyst_agent`: ask, "Calculate monthly ingestion for 350 GB per day over
  30 days."
- `research_agent`: ask for current BigQuery capabilities and require official
  sources.
- `document_specialist_agent`: ask a fact that exists in the indexed Project
  Atlas document.

Verify:

- The correct tool is called.
- Arguments are valid and relevant.
- Tool errors are represented honestly.
- The final answer uses the tool result.
- Sources are included where required.
- The model does not invent missing facts.

The shared model factory requests non-thinking output. Because Qwen may still
emit reasoning through the Ollama/LiteLLM path, every agent also sanitizes
complete `<think>` output before it enters workflow state. Token-truncated
responses are rejected instead of being exposed as final answers.

## 6. Stage 4: combine agents under the coordinator

Start ADK Web:

```powershell
make agent
```

Open <http://127.0.0.1:8000>. If that port is occupied:

```powershell
uv run adk web --port 8002 src/multi_agent_project
```

Use targeted prompts before testing a multi-specialist prompt:

```text
Calculate monthly ingestion for 350 GB per day over 30 days.
```

Expected route: `request_router -> analyst`.

```text
What is the internal Project Atlas reporting latency requirement?
```

Expected route: `document_specialist`. Clear internal-only questions bypass the
model router and use deterministic routing.

```text
Using official documentation, explain whether BigQuery supports data residency in the EU.
```

Expected route: `request_router -> researcher`.

Then use the end-to-end prompt from the README to exercise all specialists.

In **Events** or **Traces**, verify:

- The router selected the required capabilities.
- Only the selected specialists ran for a targeted request.
- Each specialist called the intended tool.
- Function responses precede claims based on them.
- Multi-specialist work finishes with `architecture_coordinator` synthesis.

An explicit request for all specialists skips model classification and runs
`document_specialist`, `researcher`, and `analyst` in that order before final
synthesis. For this multi-specialist path, local document retrieval is executed
deterministically so a small model cannot skip the required search. For web
research, a local structured planner creates a public-only query for the
technology in the request. The workflow then executes search and page fetching
deterministically, prioritizing documentation-like results, regardless of
whether the subject is a cloud provider, an open-source product, or an
on-premises technology. The blocking retrieval functions run in worker threads.
The other specialists cannot transfer control themselves. Each stage runs on
an isolated ADK branch so peer responses do not replace the original request.
Dependencies and synthesis use validated workflow state; a selected stage that
produces no result fails instead of allowing invented findings.

ADK Web only displays runs initiated through its own server. It does not
automatically display requests sent through the separate FastAPI runner.

## 7. Stage 5: put FastAPI in front of the agents

First run the mocked API tests; they do not invoke Ollama:

```powershell
uv run pytest tests/test_api.py -v
```

These tests should cover request validation, response structure, agent-author
metadata, reasoning-trace cleanup, empty agent responses, and controlled agent
failures.

Start the API:

```powershell
make api
```

Open <http://127.0.0.1:8001/docs>, expand `POST /chat`, select **Try it out**,
and submit:

```json
{
  "message": "What is the internal Project Atlas reporting latency requirement?"
}
```

For the first message, omit `session_id` or set it to `null`. Copy the returned
ID into a follow-up request:

```json
{
  "message": "What other requirements are in the same document?",
  "session_id": "paste-the-returned-session-id"
}
```

Verify all API layers:

- HTTP status is `200` for a successful run.
- `answer` contains no `<think>` reasoning trace.
- `session_id` is returned and can continue the conversation.
- `agents_used` reflects the ADK event authors in first-seen order.
- `tools_called` reflects unique `agent.tool` calls in first-seen order.
- Uvicorn logs the selected route, each specialist handoff, successful tools,
  and the start and completion of synthesis.
- Uvicorn logs the rounded total `/chat` execution time as `duration_seconds`,
  including requests that end with a workflow or model error.
- A selected specialist that skips a required tool or receives an unsuccessful
  tool response fails the request with `502` instead of synthesizing a refusal.
- Whitespace-only input returns `422`.
- Missing final model output returns `502`.
- Agent/model failure returns a sanitized `503` while details remain in server
  logs.

The API uses `InMemorySessionService`. Restarting it—including an automatic
reload after saving a Python file—erases sessions and may interrupt an active
request. Avoid editing watched files during a long smoke test.

Opening <http://127.0.0.1:8001/> returns `404` because no root route exists.
Use `/docs` or `/health` instead. A browser request for `/favicon.ico` may also
return `404`; that is harmless.

## 8. Stage 6: test Streamlit

Streamlit should call FastAPI rather than construct its own ADK runner. Start
the services in separate terminals:

```powershell
make api
```

```powershell
make ui
```

Verify that:

- A new chat receives a session ID and follow-up messages reuse it.
- Answers, participating agents, and sources render correctly.
- Starting a new chat clears the intended session state.
- API, connection, and timeout errors are shown without crashing the UI. The
  local UI allows a request up to 10 minutes because multi-specialist local
  model workflows can take several minutes.

Keep UI tests independent of Ollama by mocking calls to FastAPI. Use a manual
smoke test for the real UI-to-API-to-agent path.

## 9. Stage 7: end-to-end regression

Before completing a feature:

```powershell
make check
uv run python -c "from multi_agent_project.rag.ingestion import ingest_pdf; print(ingest_pdf('data/sample_documents/Internal_atlas_project.pdf'))"
```

Start FastAPI and Streamlit, then test:

| Case | Expected behavior |
|---|---|
| 350 GB/day for 30 days | Analyst uses the calculation tool |
| Atlas reporting latency | Document specialist cites the PDF and page |
| Current BigQuery capability | Researcher cites public URLs |
| README end-to-end prompt | All specialists run, then the coordinator synthesizes |
| Missing evidence | Agent clearly says it was not found |

Use ADK Web separately when you need to inspect routing, agent events, and tool
calls.

## 10. Command reference

```powershell
uv run pytest -q                              # All tests
uv run pytest -v                              # Verbose output
uv run pytest tests/test_api.py -v            # One file
uv run pytest tests/test_api.py::test_chat -v # One test
uv run pytest -k "search"                     # Match test names
uv run pytest -x                              # Stop on first failure

uv run ruff check .                           # Lint
uv run ruff check . --fix                     # Apply safe fixes
uv run ruff format .                          # Format
uv run ruff format --check .                  # Check formatting
make check                                    # Lint, format check, and tests
```

## 11. Troubleshooting

- **A request appears stuck:** watch FastAPI logs for agent and tool events;
  confirm the model with `ollama list` and `ollama show qwen3:4b-instruct`.
- **Document search returns nothing:** run the direct retrieval command from
  Stage 2 and ingest the PDF if necessary.
- **ADK warns about `context_cache_config`:** this is a performance warning,
  not a failed workflow step.
- **FastAPI returns 404:** use `/docs`, `/health`, or `POST /chat`; `/` is not
  defined.
- **A session loses history:** API sessions are in memory and disappear after a
  reload or restart.
- **HTTP exception tests fail:** production and test code must both use HTTPX;
  patch `multi_agent_project.tools.web_fetch.httpx.Client`.

## 12. Definition of done

- [ ] Relevant unit tests and edge cases pass.
- [ ] External dependencies are mocked in automated tests.
- [ ] The affected tool, specialist, and integration boundary are verified.
- [ ] Sources and assumptions are represented correctly.
- [ ] A real smoke test passes where appropriate.
- [ ] `make check` passes.
- [ ] Documentation is updated when behavior or commands change.
