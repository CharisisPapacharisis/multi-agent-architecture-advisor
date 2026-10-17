import asyncio
import logging
from types import SimpleNamespace

from fastapi.testclient import TestClient

from multi_agent_project.api import main

client = TestClient(main.app)


class FakeEvent:
    def __init__(
        self,
        author: str,
        text: str | None = None,
        tool: str | None = None,
    ) -> None:
        self.author = author
        self.tool = tool
        self.content = (
            SimpleNamespace(parts=[SimpleNamespace(text=text)]) if text else None
        )

    def get_function_calls(self) -> list:
        return [SimpleNamespace(name=self.tool)] if self.tool else []

    def get_function_responses(self) -> list:
        return []

    def is_final_response(self) -> bool:
        return self.content is not None


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat(monkeypatch):
    async def fake_ask_agent(message, session_id):
        return main.AgentRunResult(
            answer=f"Received: {message}",
            agents_used=["architecture_coordinator", "researcher"],
            tools_called=["researcher.search_web"],
        )

    monkeypatch.setattr(main, "ask_agent", fake_ask_agent)

    response = client.post(
        "/chat",
        json={"message": "What is BigQuery?"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == ("Received: What is BigQuery?")
    assert response.json()["session_id"]
    assert response.json()["agents_used"] == [
        "architecture_coordinator",
        "researcher",
    ]
    assert response.json()["tools_called"] == ["researcher.search_web"]


def test_chat_logs_total_duration(monkeypatch, caplog):
    async def fake_ask_agent(message, session_id):
        return main.AgentRunResult(answer="Done")

    elapsed_values = iter([100.0, 102.3456])
    monkeypatch.setattr(main, "ask_agent", fake_ask_agent)
    monkeypatch.setattr(main, "perf_counter", lambda: next(elapsed_values))

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        response = client.post(
            "/chat",
            json={"message": "Hello", "session_id": "session-1"},
        )

    assert response.status_code == 200
    assert (
        "Chat request completed: session_id=session-1 duration_seconds=3" in caplog.text
    )


def test_empty_message():
    response = client.post(
        "/chat",
        json={"message": ""},
    )

    assert response.status_code == 422


def test_whitespace_message():
    response = client.post(
        "/chat",
        json={"message": "   \n\t  "},
    )

    assert response.status_code == 422


def test_chat_returns_bad_gateway_for_empty_agent_answer(monkeypatch):
    async def fake_ask_agent(message, session_id):
        raise main.EmptyAgentResponseError

    monkeypatch.setattr(main, "ask_agent", fake_ask_agent)

    response = client.post(
        "/chat",
        json={"message": "What is BigQuery?"},
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "The agent completed without producing an answer."
    }


def test_chat_returns_bad_gateway_for_missing_workflow_stage(monkeypatch):
    async def fake_ask_agent(message, session_id):
        raise main.WorkflowStageError("researcher produced no result")

    monkeypatch.setattr(main, "ask_agent", fake_ask_agent)

    response = client.post(
        "/chat",
        json={"message": "Compare internal and external requirements."},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "researcher produced no result"}


def test_chat_returns_service_unavailable_for_agent_failure(monkeypatch):
    async def fake_ask_agent(message, session_id):
        raise RuntimeError("Ollama unavailable")

    monkeypatch.setattr(main, "ask_agent", fake_ask_agent)

    response = client.post(
        "/chat",
        json={"message": "What is BigQuery?"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "The agent service is temporarily unavailable."
    }


def test_clean_model_answer_removes_thinking_trace():
    answer = (
        "Private reasoning that should not be returned.\n"
        "</think>\n\n"
        "The maximum acceptable delay is 15 minutes."
    )

    assert main.clean_model_answer(answer) == (
        "The maximum acceptable delay is 15 minutes."
    )


def test_ask_agent_collects_unique_event_authors_in_order(monkeypatch):
    class FakeSessionService:
        get_session_kwargs = None

        async def get_session(self, **kwargs):
            self.get_session_kwargs = kwargs
            return object()

    class FakeRunner:
        run_kwargs = None

        async def run_async(self, **kwargs):
            self.run_kwargs = kwargs
            yield FakeEvent("architecture_coordinator")
            yield FakeEvent("document_specialist", tool="search_documents")
            yield FakeEvent("document_specialist", tool="search_documents")
            yield FakeEvent("document_specialist", "The answer is 15 minutes.")

    session_service = FakeSessionService()
    runner = FakeRunner()
    monkeypatch.setattr(main, "session_service", session_service)
    monkeypatch.setattr(main, "runner", runner)

    result = asyncio.run(main.ask_agent("What is the requirement?", "session-1"))

    assert result.answer == "The answer is 15 minutes."
    assert result.agents_used == [
        "architecture_coordinator",
        "document_specialist",
    ]
    assert result.tools_called == ["document_specialist.search_documents"]
    assert session_service.get_session_kwargs["user_id"] == "session-1"
    assert runner.run_kwargs["user_id"] == "session-1"
