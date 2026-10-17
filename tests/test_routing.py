import asyncio

import pytest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from multi_agent_project.agents import workflow_stages as stages_module
from multi_agent_project.agents.analyst_agent import analyst_instruction
from multi_agent_project.agents.research_agent import ResearchPlan
from multi_agent_project.agents.routing import (
    RouteDecision,
    is_internal_document_only_request,
    requests_all_specialists,
    selected_specialists,
)
from multi_agent_project.agents.synthesis_agent import synthesis_instruction
from multi_agent_project.models.llm import (
    IncompleteModelOutputError,
    clean_model_text,
    sanitize_model_response,
)


@pytest.mark.parametrize(
    "message",
    [
        "Consult all three specialist agents.",
        "Use every specialist for this assessment.",
        "Please ask all specialist agents before answering.",
    ],
)
def test_explicit_all_specialists_request_is_detected(message: str) -> None:
    assert requests_all_specialists(message)


def test_selected_specialists_use_dependency_safe_order() -> None:
    route = RouteDecision(
        needs_documents=True,
        needs_research=True,
        needs_calculation=True,
    )

    assert selected_specialists(route) == [
        "document_specialist",
        "researcher",
        "analyst",
    ]


def test_internal_document_only_request_bypasses_model_routing() -> None:
    assert is_internal_document_only_request(
        "What is the internal Project Atlas reporting latency requirement?"
    )
    assert not is_internal_document_only_request(
        "Compare Project Atlas with BigQuery official documentation."
    )


def test_atlas_project_word_order_still_routes_to_internal_documents() -> None:
    assert is_internal_document_only_request("Who is the CEO of Atlas Project?")


def test_deterministic_document_stage_emits_tool_events(monkeypatch) -> None:
    result = {"status": "success", "matches": [{"text": "350 GB daily"}]}
    monkeypatch.setattr(stages_module, "search_documents", lambda query: result)

    class FakeContext:
        invocation_id = "invocation-1"
        branch = "architecture_workflow"

        def model_copy(self, update):
            return type("BranchContext", (), update)()

    events, actual_result = asyncio.run(
        stages_module.deterministic_document_events(
            FakeContext(),
            "Project Atlas requirements",
        )
    )

    assert actual_result == result
    assert events[0].get_function_calls()[0].name == "search_documents"
    assert events[1].get_function_responses()[0].response == result
    assert "350 GB daily" in events[1].actions.state_delta["document_findings"]


def test_document_stage_merges_supplementary_retrieval(monkeypatch) -> None:
    def document_results(query):
        return {
            "status": "success",
            "matches": [{"text": query}],
        }

    monkeypatch.setattr(stages_module, "search_documents", document_results)

    class FakeContext:
        invocation_id = "invocation-1"
        branch = "architecture_workflow"

    events, result = asyncio.run(
        stages_module.deterministic_document_events(
            FakeContext(),
            "general requirements",
            ("daily data ingestion requirement",),
        )
    )

    assert len(events) == 4
    assert [match["text"] for match in result["matches"]] == [
        "general requirements",
        "daily data ingestion requirement",
    ]


def test_deterministic_research_stage_fetches_official_page(monkeypatch) -> None:
    search_result = {
        "status": "success",
        "results": [
            {"url": "https://example.com/opinion"},
            {"url": "https://docs.aws.amazon.com/redshift/latest/dg/welcome.html"},
        ],
    }
    fetch_result = {
        "status": "success",
        "url": "https://docs.aws.amazon.com/redshift/latest/dg/welcome.html",
        "content": "Official Amazon Redshift documentation",
    }
    monkeypatch.setattr(
        stages_module, "search_web", lambda *args, **kwargs: search_result
    )
    monkeypatch.setattr(stages_module, "fetch_web_page", lambda url: fetch_result)

    class FakeContext:
        invocation_id = "invocation-1"
        branch = "architecture_workflow"

        def model_copy(self, update):
            return type("BranchContext", (), update)()

    events, result = asyncio.run(
        stages_module.deterministic_research_events(
            FakeContext(),
            ResearchPlan(
                query="Amazon Redshift official documentation capabilities",
            ),
        )
    )

    calls = [call.name for event in events for call in event.get_function_calls()]
    assert calls == ["search_web", "fetch_web_page", "fetch_web_page"]
    assert result["status"] == "success"
    assert result["fetched_pages"][0]["content"] == (
        "Official Amazon Redshift documentation"
    )
    assert len(result["fetched_pages"]) == 2
    assert "research_findings" in events[-1].actions.state_delta


def test_deterministic_analyst_stage_calculates_document_volume() -> None:
    class FakeContext:
        invocation_id = "invocation-1"
        branch = "architecture_workflow"
        session = type(
            "Session",
            (),
            {"state": {"document_findings": "Daily data ingestion: 350 GB."}},
        )()

        def model_copy(self, update):
            return type("BranchContext", (), update)()

    events, result = asyncio.run(
        stages_module.deterministic_analyst_events(
            FakeContext(),
            "Calculate the monthly data ingestion assuming 30 days.",
        )
    )

    assert result["status"] == "success"
    assert result["total_gb"] == 10_500
    assert result["input_source"] == "document_findings"
    assert events[0].get_function_calls()[0].name == "calculate_data_volume"
    assert events[1].actions.state_delta["analysis_findings"]


def test_analyst_stage_reports_missing_volume_for_synthesis() -> None:
    class FakeContext:
        invocation_id = "invocation-1"
        branch = "architecture_workflow"
        session = type("Session", (), {"state": {"document_findings": ""}})()

    events, result = asyncio.run(
        stages_module.deterministic_analyst_events(
            FakeContext(),
            "Calculate the monthly data ingestion assuming 30 days.",
        )
    )

    assert result["status"] == "unavailable"
    assert not events[0].get_function_calls()
    assert (
        "could not be calculated" in events[0].actions.state_delta["analysis_findings"]
    )


def test_analyst_instruction_receives_document_findings() -> None:
    context = type(
        "Context",
        (),
        {"state": {"document_findings": "Daily ingestion is 350 GB."}},
    )()

    instruction = analyst_instruction(context)

    assert "Daily ingestion is 350 GB." in instruction


def test_synthesis_uses_only_current_selected_findings() -> None:
    context = type(
        "Context",
        (),
        {
            "state": {
                "temp:selected_specialists": ["document_specialist", "analyst"],
                "document_findings": "Current document result",
                "analysis_findings": "Current calculation",
                "research_findings": "Stale result from a previous request",
            }
        },
    )()

    instruction = synthesis_instruction(context)

    assert "Current document result" in instruction
    assert "Current calculation" in instruction
    assert "Stale result from a previous request" not in instruction
    assert "Repeat their values exactly" in instruction
    assert "Cite only fetched-page URLs" in instruction


def test_clean_model_text_repairs_common_mojibake() -> None:
    assert clean_model_text("350 GB/day Ã— 30 days â‰¤ 15 minutes") == (
        "350 GB/day × 30 days ≤ 15 minutes"
    )


def test_model_response_sanitizer_removes_thinking() -> None:
    response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(text="Private reasoning</think>Final answer")],
        )
    )

    sanitized = sanitize_model_response(None, response)

    assert sanitized is not None
    assert sanitized.content.parts[0].text == "Final answer"


def test_model_response_sanitizer_rejects_token_limit() -> None:
    response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(text="Unfinished reasoning")],
        ),
        finish_reason=types.FinishReason.MAX_TOKENS,
    )

    with pytest.raises(IncompleteModelOutputError):
        sanitize_model_response(None, response)
