# Google ADK Concepts Demonstrated by This Project

This project uses Google Agent Development Kit (ADK) as an **agent
orchestration framework**. ADK connects models, tools, state, agents, and
execution events. The rest of the application supplies the domain logic:
document retrieval, web access, calculations, safety checks, and the UI.

The important lesson is not the number of agents. It is how probabilistic
model behavior is combined with deterministic application code to create a
workflow that is observable and easier to trust.

An agent framework becomes useful when an application needs more than a single
prompt and response. A real request may require the model to choose a
capability, call external code, carry verified results into a later step, and
leave enough execution history to explain what happened. ADK supplies a shared
set of abstractions for those concerns. It does not remove the need for normal
software design; it gives agent-oriented code a consistent runtime model.

## The architecture in one view

```text
User request
    |
    v
ADK Runner and Session
    |
    v
Custom ADK workflow
    |
    +-- route the request
    +-- collect evidence with selected specialists and tools
    +-- pass findings through workflow state
    +-- synthesize a final answer when several capabilities were used
    |
    v
Stream of ADK Events -> API response and execution metadata
```

During one request, the runner creates an invocation context and asks the root
workflow to run. The workflow may invoke child agents or deterministic stages.
Each stage emits events, and some events update shared session state. A later
stage reads the approved findings from that state. Finally, the API consumes
the same event stream to find the final response and report which capabilities
were actually used.

This gives three related but distinct channels:

- **Context** describes the current invocation and gives code access to the
  user message, session, state, and branch.
- **State** carries data that later stages need.
- **Events** record what occurred during execution and deliver outputs to the
  runner and host application.

The implementation begins with `root_agent` in
[`agents/agent.py`](../src/multi_agent_project/agents/agent.py). The runtime that
executes it is configured in
[`api/main.py`](../src/multi_agent_project/api/main.py).

## 1. Agents are configured capabilities

An ADK `Agent` combines a model with a role, instructions, and optionally tools
and structured output. In this project, agents represent capabilities rather
than independent personalities:

- The router classifies which capabilities are needed.
- The document specialist retrieves internal evidence.
- The researcher retrieves public evidence.
- The analyst performs a verified calculation.
- The coordinator turns several findings into one answer.

A simplified agent definition looks like this:

```python
from google.adk.agents import Agent

analyst = Agent(
    name="analyst",
    model=get_local_model(),
    instruction="Use the calculation tool for ingestion calculations.",
    tools=[calculate_data_volume],
    output_key="analysis_findings",
)
```

The main concept is **capability packaging**: the model decides how to perform
a bounded role, while its tools and instructions limit what that role can do.
See [`analyst_agent.py`](../src/multi_agent_project/agents/analyst_agent.py).

Splitting work into agents is useful when capabilities need meaningfully
different tools, instructions, evidence rules, or output contracts. It is not
automatically useful for every logical function. A regular Python function is
usually the better choice when no model judgment is required. In this project,
calculating a volume is a function; deciding that a calculation is needed is
an agent/workflow concern.

The agent's instruction is also more than a persona prompt. It defines the
operating contract for that capability: its scope, mandatory tools, acceptable
evidence, and behavior when evidence is missing. Deterministic checks in the
workflow then enforce the most important parts of that contract.

## 2. Tools connect model decisions to normal Python

ADK tools are the boundary between model reasoning and application behavior.
The project passes typed Python functions directly to an agent. ADK uses their
signatures and docstrings to expose them to the model.

For example, the analyst can call `calculate_data_volume`, but the arithmetic
remains deterministic Python. The same pattern exposes local document search
and public web operations.

```python
def calculate_data_volume(daily_gb: float, days: int = 30) -> dict:
    return {
        "total_gb": round(daily_gb * days, 2),
        "days": days,
        "status": "success",
    }
```

This separation is central to agent applications:

- Use the model for interpretation, selection, and language generation.
- Use tools for retrieval, network access, calculations, and other operations
  whose results should be inspectable and testable.

The functions under [`tools/`](../src/multi_agent_project/tools/) are ordinary
application code. ADK lets agents call them and records the calls as events.

Conceptually, a model-driven tool call has four steps:

1. ADK tells the model which tools exist and what arguments they accept.
2. The model emits a structured function call rather than pretending to have
   performed the operation.
3. The application executes the Python function and returns its structured
   result.
4. ADK gives that result back to the agent so it can continue or answer.

This distinction is particularly important for retrieval. The model does not
directly “know” the local PDF contents or the current web page. It asks a tool
to retrieve data and can ground its response in the returned evidence.

Tool availability is not the same as tool enforcement. A model can sometimes
skip an instructed tool or call it poorly. This project therefore inspects the
event stream and checks required tool names and result statuses. Instructions
guide behavior; application code enforces critical requirements.

## 3. Custom workflows combine agents with deterministic control flow

The project goes beyond a single LLM agent. `ArchitectureWorkflow` subclasses
ADK's `BaseAgent` and defines the order in which work happens.

```python
class ArchitectureWorkflow(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext):
        child = self.find_sub_agent("request_router")
        async for event in child.run_async(ctx):
            yield event
```

The real workflow uses normal Python conditions and loops to:

1. Select the required capabilities.
2. Run them in dependency order.
3. Verify that required tools actually succeeded.
4. Run synthesis only when needed.

This is a **hybrid workflow**. Clear cases use deterministic routing rules;
ambiguous cases use an LLM router. Multi-stage evidence collection is
deterministic, while an LLM produces the final explanation.

This matters when comparing ADK with frameworks centered on autonomous agent
conversations. ADK supports model-directed agents, but it also lets this
application keep orchestration under explicit program control. The specialists
cannot freely transfer control to one another; the root workflow owns every
handoff.

The execution order is also a data dependency, not just an organizational
preference. Document retrieval must happen before the analyst can calculate
from a documented ingestion value. All selected evidence must exist before the
coordinator can synthesize it. Encoding this order in Python makes the
dependency explicit and testable.

For a simpler application, ADK's prebuilt workflow patterns or a single agent
may be sufficient. A custom `BaseAgent` is appropriate here because routing,
failure policy, mandatory tool use, and conditional synthesis are application
rules. The trade-off is additional orchestration code that the project must
test and maintain.

See [`agents/agent.py`](../src/multi_agent_project/agents/agent.py) for the
orchestrator and
[`workflow_stages.py`](../src/multi_agent_project/agents/workflow_stages.py) for
the deterministic stages.

## 4. Structured output makes model decisions usable by code

Some model responses are intermediate decisions rather than user-facing text.
ADK's `output_schema` lets the project require a Pydantic structure:

```python
class RouteDecision(BaseModel):
    needs_documents: bool = False
    needs_research: bool = False
    needs_calculation: bool = False
```

The router returns this shape instead of prose. The workflow validates it and
uses the booleans in ordinary Python control flow.

The research planner uses the same idea to create a constrained public search
query before deterministic code performs the search:

```text
Model produces a typed plan -> application validates it -> code executes it
```

This is more reliable than parsing a conversational response. See
[`routing.py`](../src/multi_agent_project/agents/routing.py) and
[`research_agent.py`](../src/multi_agent_project/agents/research_agent.py).

Structured output does not make the model deterministic. It constrains the
shape of its answer so that invalid output can be detected and valid output can
be handled safely. The semantic decision may still be wrong, which is why the
project keeps small deterministic rules for routes that are unambiguous and
uses the model for genuinely ambiguous wording.

## 5. State connects stages without merging their conversations

ADK session state acts as the workflow's data bus. A stage can store findings
under an `output_key`, and a later stage can read them from its context.

```text
document specialist -> document_findings -> analyst/coordinator
researcher          -> research_findings -> coordinator
analyst             -> analysis_findings -> coordinator
```

Dynamic instructions receive a `ReadonlyContext`, allowing the analyst or
coordinator to build its prompt from only the relevant state. The coordinator,
for example, reads selected specialist findings rather than relying on one
large shared conversation.

The project also assigns separate ADK branches to peer agents. Branches isolate
their histories while they remain part of the same invocation. Together,
**state passes approved data** and **branches isolate conversational context**.

See [`synthesis_agent.py`](../src/multi_agent_project/agents/synthesis_agent.py)
for dynamic instructions and selective state use.

It helps to distinguish **session state** from model context. Session state is
application-managed data associated with a conversation. Model context is the
content actually supplied to one model call. Dynamic instructions bridge the
two by deliberately selecting which state should enter a particular prompt.
This is safer and more predictable than automatically exposing every prior
finding to every agent.

The project uses temporary keys for invocation-specific decisions and named
keys for specialist findings. The coordinator also consults the current list
of selected specialists, reducing the risk that an old finding from an earlier
turn is treated as evidence for the current request.

## 6. Events make execution observable

An ADK run produces a stream of `Event` objects rather than only returning a
final string. Events can contain model content, tool calls, tool responses,
state changes, and the final response.

The API consumes this stream to determine which agents and tools were actually
used:

```python
async for event in runner.run_async(...):
    calls = event.get_function_calls()
    responses = event.get_function_responses()
    if event.is_final_response():
        ...
```

The deterministic workflow stages also emit ADK-compatible call and response
events and attach findings through `EventActions.state_delta`. Manually
controlled work therefore remains visible in ADK traces and API metadata.

This illustrates one of ADK's most useful architectural ideas: **events are the
execution protocol** shared by agents, tools, state updates, and the host
application.

Events are different from ordinary logs. Logs are diagnostic messages chosen
by application code. ADK events are structured runtime records that participate
in execution: they can contain content, function interactions, and state
changes. The project can derive `agents_used` and `tools_called` from events
instead of trusting a model-generated account of its own work. Logs can still
be produced from those events for operators.

Manually emitting tool events in the deterministic stages preserves this
common protocol. Without them, the tools would still run, but ADK tracing and
the API would see an incomplete picture of the workflow.

## 7. Runner and sessions provide the runtime boundary

The `Runner` executes the root agent. A session service supplies conversation
state across requests.

```python
session_service = InMemorySessionService()

runner = Runner(
    agent=root_agent,
    app_name="architecture_advisor",
    session_service=session_service,
)
```

FastAPI creates an ADK user message, starts `runner.run_async(...)`, and
consumes the events. This is the boundary between the web application and the
agent runtime.

This project uses `InMemorySessionService`, which is convenient locally but is
not persistent or shared between server processes. That is an infrastructure
choice, not a limitation of the agent design.

The runner is therefore more than a function that calls the model. It connects
the root agent to session storage, creates the runtime environment for an
invocation, and streams the resulting events. The FastAPI layer should not
reimplement those responsibilities; it translates between HTTP requests and
the ADK runtime.

A production deployment would normally replace in-memory session storage with
a durable implementation and define clearer user/session identity rules. The
agents and workflow could remain largely unchanged because they depend on the
session abstraction rather than a particular storage engine.

## 8. Models and callbacks are replaceable runtime components

ADK coordinates agents; it does not host the model. This project uses ADK's
`LiteLlm` adapter to connect to a local Ollama model:

```python
LiteLlm(model="ollama_chat/qwen3:4b-instruct", think=False)
```

This keeps inference local while the workflow continues to use ADK
abstractions.

An `after_model_callback` removes leaked reasoning tags, handles encoding
problems, and rejects token-truncated output before that output is stored or
passed to another stage. Callbacks are ADK extension points for behavior that
should apply consistently around model execution.

Both pieces are in [`models/llm.py`](../src/multi_agent_project/models/llm.py).

Model portability has limits: different models vary in instruction following,
structured-output reliability, and tool selection. An adapter makes the API
consistent, but it cannot make all model behavior identical. The workflow's
validation and deterministic stages reduce the impact of those differences.

## What ADK provides—and what it does not

This separation is the clearest way to compare the project with other agent
frameworks.

| Concern | In this project |
| --- | --- |
| Agent definitions and hierarchy | ADK `Agent`, `BaseAgent`, and `sub_agents` |
| Agent execution | ADK `Runner` |
| Conversation state | ADK session service and state |
| Tool-call protocol | ADK tool integration and events |
| Execution observability | ADK event stream and traces |
| Model connection | ADK `LiteLlm` adapter, backed by Ollama/LiteLLM |
| Workflow policy | Project-specific Python in `ArchitectureWorkflow` |
| Document retrieval | PyPDF and ChromaDB, exposed as an ADK tool |
| Web research | DDGS, HTTPX, and Beautiful Soup, exposed as ADK tools |
| Input/output validation | Pydantic |
| HTTP and UI layers | FastAPI and Streamlit |

ADK does not perform RAG, web scraping, domain calculations, or UI rendering
for this application. It provides the common runtime through which those
capabilities are selected, executed, connected, and observed.

This is also why ADK can coexist with many other libraries. ChromaDB can be
replaced without redesigning the agent runtime as long as the document tool
keeps a suitable contract. FastAPI can be replaced by another delivery layer
that still invokes the runner. The model backend can change behind its adapter.
ADK sits between those components and coordinates their use during an agent
invocation.

## The main design lesson

The project combines four layers:

1. **Probabilistic decisions** — routing ambiguous requests, planning a safe
   query, and synthesizing language.
2. **Deterministic capabilities** — retrieval, fetching, calculation, result
   validation, and workflow ordering.
3. **ADK coordination** — agents, tools, context, state, events, sessions, and
   the runner.
4. **Application delivery** — FastAPI, Streamlit, logs, and tests.

ADK is the coordination layer, not the entire application. To evaluate another
framework, compare how it models agents, tools, workflows, state, events, and
runtime execution. Then separately consider which retrieval, model, storage,
and delivery components you would need to bring yourself.

Useful comparison questions include:

- Does the framework favor autonomous handoffs, explicit workflows, or both?
- Are tool calls and state changes first-class, inspectable runtime objects?
- Can model output be constrained to typed structures?
- How is context isolated or shared between agents?
- Can deterministic code participate without becoming invisible to tracing?
- Are model providers and session stores replaceable?
- How much framework-specific code is required to express failure and retry
  policy?

This project chooses explicit orchestration and evidence validation over high
agent autonomy. That is not universally the correct choice, but it fits an
architecture-review application where sources, calculations, and limitations
need to remain visible.

For a practical walkthrough of running and testing the application, see
[`DEVELOPMENT.md`](DEVELOPMENT.md). For the reasons behind the hybrid workflow,
see [`ARCHITECTURE_EVOLUTION.md`](ARCHITECTURE_EVOLUTION.md).
