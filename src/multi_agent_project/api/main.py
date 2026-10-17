import logging
from dataclasses import dataclass, field
from math import ceil
from time import perf_counter
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from multi_agent_project.models.llm import (
    IncompleteModelOutputError,
    clean_model_text,
)
from multi_agent_project.models.schemas import (
    ChatRequest,
    ChatResponse,
)

load_dotenv()

from multi_agent_project.agents.agent import WorkflowStageError, root_agent

app = FastAPI(title="Multi-Agent Architecture Advisor")

logger = logging.getLogger("uvicorn.error")

APP_NAME = "architecture_advisor"

session_service = InMemorySessionService()

runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)


@dataclass
class AgentRunResult:
    """User-facing result and execution metadata from the run."""

    answer: str
    agents_used: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)


class EmptyAgentResponseError(RuntimeError):
    """Raised when an ADK run finishes without a user-facing answer."""


def clean_model_answer(answer: str) -> str:
    """Remove reasoning tags that a local model may leak into final text."""
    return clean_model_text(answer)


async def ask_agent(message: str, session_id: str) -> AgentRunResult:
    """Run the ADK coordinator and return its final answer."""
    user_id = session_id

    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )

    if session is None:
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )

    content = types.Content(
        role="user",
        parts=[types.Part(text=message)],
    )

    answer = ""
    agents_used: list[str] = []
    seen_agents: set[str] = set()
    tools_called: list[str] = []
    seen_tools: set[str] = set()

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        if event.author and event.author not in seen_agents:
            seen_agents.add(event.author)
            agents_used.append(event.author)
            logger.info("ADK agent event: agent=%s", event.author)

        for function_call in event.get_function_calls():
            qualified_tool = f"{event.author}.{function_call.name}"
            if qualified_tool not in seen_tools:
                seen_tools.add(qualified_tool)
                tools_called.append(qualified_tool)
            logger.info(
                "ADK tool call: agent=%s tool=%s",
                event.author,
                function_call.name,
            )

        for function_response in event.get_function_responses():
            logger.info(
                "ADK tool response: agent=%s tool=%s",
                event.author,
                function_response.name,
            )

        if event.is_final_response() and event.content:
            answer = clean_model_answer(
                " ".join(
                    part.text
                    for part in (event.content.parts or [])
                    if part.text and not getattr(part, "thought", False)
                )
            )

    if not answer:
        raise EmptyAgentResponseError(
            "Agent run completed without a final text response"
        )

    return AgentRunResult(
        answer=answer,
        agents_used=agents_used,
        tools_called=tools_called,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id or str(uuid4())
    started_at = perf_counter()

    try:
        result = await ask_agent(
            message=request.message,
            session_id=session_id,
        )
    except WorkflowStageError as exc:
        logger.exception("Agent workflow stage failed")
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except (EmptyAgentResponseError, IncompleteModelOutputError):
        logger.exception("Agent invocation returned no final answer")
        raise HTTPException(
            status_code=502,
            detail="The agent completed without producing an answer.",
        ) from None
    except Exception:
        logger.exception("Agent invocation failed")
        raise HTTPException(
            status_code=503,
            detail="The agent service is temporarily unavailable.",
        ) from None
    finally:
        logger.info(
            "Chat request completed: session_id=%s duration_seconds=%d",
            session_id,
            ceil(perf_counter() - started_at),
        )

    return ChatResponse(
        answer=result.answer,
        session_id=session_id,
        agents_used=result.agents_used,
        tools_called=result.tools_called,
    )
