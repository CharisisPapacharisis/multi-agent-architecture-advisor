# Architecture Evolution Notes

This note records why the application moved from a simple coordinator with
three transferable subagents to the current hybrid workflow. It is a concise
reference for future changes, not a replacement for the [development
guide](DEVELOPMENT.md).

## Starting point

The first design used a coordinator agent that decided, through normal LLM
tool calling, whether to transfer a request to the document specialist,
researcher, or analyst. Each specialist could then respond or transfer again.

That is a useful learning design, but a small local model made the execution
path unreliable for tasks that needed several sources of evidence. A model
could describe its intent to transfer instead of calling the transfer tool,
skip a required tool, stop after one specialist, or lose useful findings when
the active agent changed.

## Evolution of the workflow

### 1. Flexible transfers established the roles

The original coordinator chose a specialist and transferred control to it. It
was a useful way to establish the roles and independently validate document
search, web research, and calculation tools. It also showed that a coordinator
needs a way to combine findings rather than simply pass the conversation on.

### 2. Synthesis was separated from specialist work

For questions needing more than one evidence source, returning to a dedicated
coordinator for synthesis made the result much more coherent. Specialists
collect or calculate; the coordinator compares their findings and writes the
answer. This also avoids making one specialist responsible for another
specialist's domain.

### 3. Routing became hybrid

Some requests have intent that is obvious from their wording: a clear
internal-document question needs the document specialist, and an explicit
request to consult all specialists needs all of them. Asking a local LLM to
decide those cases added latency and another chance to route incorrectly.

Those cases now use deterministic rules. Less obvious or mixed requests still
go to `request_router`, which returns a structured specialist selection. This
keeps natural-language flexibility without growing an unmaintainable list of
exact keyword rules.

### 4. Multi-source evidence collection became controlled

Free-form handoffs could skip a required tool, stop after one specialist, or
lose the path back to synthesis. `ArchitectureWorkflow` now runs selected
stages in dependency-safe order and always synthesizes a multi-specialist
answer.

For multi-specialist research, `research_planner` first creates a public-only
search query. The workflow then searches and fetches up to two
documentation-like pages deterministically. This avoids internal project terms
polluting web searches and avoids relying on a small local model to remember
to fetch pages after a search.

The same principle applies to a requested data-volume calculation: when a
multi-specialist workflow has retrieved a daily ingestion figure, the workflow
calls the calculation tool directly instead of relying on the analyst model to
choose that mandatory tool call.

The workflow also performs a focused local retrieval for the daily-ingestion
requirement. If that fact is genuinely unavailable, it records the calculation
as a limitation for synthesis instead of failing the entire request.

### 5. Completion means evidence, not just model text

An agent can generate a convincing response without having used its tool. The
workflow therefore records ADK events and rejects a selected stage when its
required tool has no successful result. FastAPI returns the resulting
`agents_used` and `tools_called` metadata, making an answer easier to inspect.

### 6. Final-answer safeguards were tightened

The synthesis instructions now treat retrieved project requirements as
authoritative. A budget conclusion needs a cost calculation; compliance and
residency statements remain conditional; technical claims need fetched-page
evidence; and citations must be URLs from those fetched pages. This reduces
the risk that a model fills gaps with general knowledge.

### 7. Model selection and response hygiene improved local reliability

The local model was moved to the instruction-tuned `qwen3:4b-instruct` variant
and extended thinking was disabled through the LiteLLM/Ollama configuration.
That improves response speed and reduces leaked reasoning, while retaining a
defensive response cleanup boundary. It removes thinking tags, rejects
token-limited outputs as incomplete, and safely repairs common text-encoding
artifacts.

### 8. Service, UI, and security boundaries were made explicit

FastAPI now validates non-empty messages, creates UUID session identifiers,
returns the agents and tools used, logs request duration and workflow events,
and maps expected failures to safe HTTP responses. Streamlit calls that API
rather than running ADK separately; its ten-minute timeout distinguishes a
slow local workflow from an unreachable service.

The web-page tool was also simplified to standard `httpx` and constrained to
public HTTP(S) destinations on ports 80 and 443. It rejects localhost,
private, reserved, and unresolved addresses, does not follow redirects, and
uses a short request timeout. This reduces SSRF risk before any future
deployment beyond the local machine.

### 9. Development feedback became faster and more repeatable

The project added focused unit tests around tools, routing, API behavior, UI
requests, and deterministic workflow stages. External systems are mocked in
those tests; `make check` runs Ruff and the full suite. ADK Web, FastAPI logs,
and response metadata provide progressively deeper observability when a manual
end-to-end test is needed.

## Current request paths

```text
Request
  |
  +-- obvious internal-only request ------> document specialist
  |
  +-- explicit all-specialist request ----> document -> researcher -> analyst
  |
  +-- other request ----------------------> LLM request router -> selected stages
                                                        |
                                                        +-- one stage: return its answer
                                                        +-- multiple stages: coordinator synthesis
```

For the all-specialist path, the document specialist retrieves local facts,
the researcher gathers public evidence, and the analyst calculates from the
available inputs. The coordinator receives the collected findings and creates
the final response; it does not replace evidence collection.

## Practical lessons

- Use LLM judgment where natural-language flexibility matters; use code where
  workflow guarantees matter.
- A completed model response is not proof that a task was completed. Record
  and inspect the specialist and tool events.
- Keep tools deterministic and independently testable. Agents should decide
  how to use evidence, not reimplement retrieval or calculations.
- Treat external pages, PDFs, and model output as untrusted. Preserve source
  boundaries and state uncertainty when evidence is incomplete.
- Local inference makes the system private and inexpensive, but complex,
  sequential workflows can take minutes. Design the API and UI timeouts around
  that constraint.

## Where to inspect behavior

- FastAPI logs show route selection, stage starts and completions, tool calls,
  synthesis, and total request duration.
- `POST /chat` returns `agents_used` and `tools_called` for each completed
  request.
- ADK Web provides Events and Traces while developing agent behavior.
- `tests/test_routing.py` covers the hybrid-routing and deterministic-workflow
  rules without requiring a running local model.
