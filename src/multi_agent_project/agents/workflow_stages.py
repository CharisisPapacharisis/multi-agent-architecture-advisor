"""Deterministic evidence-collection stages for the architecture workflow."""

import asyncio
import json
import re

from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from multi_agent_project.agents.research_agent import ResearchPlan
from multi_agent_project.tools.calculations import calculate_data_volume
from multi_agent_project.tools.document_search import search_documents
from multi_agent_project.tools.web_fetch import fetch_web_page
from multi_agent_project.tools.web_search import search_web

SPECIALIST_OUTPUT_KEYS = {
    "document_specialist": "document_findings",
    "researcher": "research_findings",
    "analyst": "analysis_findings",
}
DAILY_INGESTION_QUERY = "daily data ingestion requirement"

_SEARCH_RESULT_LIMIT = 5
_FETCHED_PAGE_LIMIT = 2
_FETCH_ATTEMPT_LIMIT = 3

_DAILY_INGESTION_PATTERNS = (
    re.compile(
        r"(?P<daily_gb>\d+(?:\.\d+)?)\s*gb\s*(?:/|per\s+)(?:day|daily)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:daily\s+(?:data\s+)?ingestion|daily\s+ingestion)"
        r"[^\d]{0,40}(?P<daily_gb>\d+(?:\.\d+)?)\s*gb",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<daily_gb>\d+(?:\.\d+)?)\s*gb\s+(?:daily|each\s+day)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:data\s+)?ingestion[^\d]{0,40}(?P<daily_gb>\d+(?:\.\d+)?)"
        r"\s*gb[^\n]{0,80}\bdaily\b",
        re.IGNORECASE,
    ),
)
_DAYS_PATTERN = re.compile(
    r"(?:assuming|over|for)\s+(?P<days>\d+)\s+days?",
    re.IGNORECASE,
)


def _stage_branch(ctx: InvocationContext, agent_name: str) -> str:
    """Return an isolated branch name for a deterministic stage."""
    parent_branch = ctx.branch or "architecture_workflow"
    return f"{parent_branch}.{agent_name}"


def _tool_events(
    ctx: InvocationContext,
    agent_name: str,
    tool_name: str,
    arguments: dict,
    result: dict,
) -> list[Event]:
    """Represent one deterministic tool execution as ADK call/response events."""
    branch = _stage_branch(ctx, agent_name)
    return [
        Event(
            invocation_id=ctx.invocation_id,
            author=agent_name,
            branch=branch,
            content=types.Content(
                role="model",
                parts=[types.Part.from_function_call(name=tool_name, args=arguments)],
            ),
        ),
        Event(
            invocation_id=ctx.invocation_id,
            author=agent_name,
            branch=branch,
            content=types.Content(
                role="user",
                parts=[
                    types.Part.from_function_response(
                        name=tool_name,
                        response=result,
                    )
                ],
            ),
        ),
    ]


def _store_stage_findings(events: list[Event], agent_name: str, result: dict) -> None:
    """Attach one deterministic stage result to the final ADK event."""
    events[-1].actions = EventActions(
        state_delta={
            SPECIALIST_OUTPUT_KEYS[agent_name]: json.dumps(
                result,
                ensure_ascii=False,
            )
        }
    )


def _is_documentation_result(result: dict) -> bool:
    """Prefer search results that look like provider documentation."""
    title_and_snippet = f"{result.get('title', '')} {result.get('snippet', '')}"
    url = str(result.get("url", "")).lower()
    return (
        "documentation" in title_and_snippet.lower() or "/docs" in url or "docs." in url
    )


async def deterministic_document_events(
    ctx: InvocationContext,
    query: str,
    supplementary_queries: tuple[str, ...] = (),
) -> tuple[list[Event], dict]:
    """Run mandatory local retrieval and represent it as standard ADK events."""
    events: list[Event] = []
    matches = []
    seen_matches: set[str] = set()
    statuses = []
    for search_query in (query, *supplementary_queries):
        search_result = await asyncio.to_thread(search_documents, search_query)
        statuses.append(search_result.get("status"))
        for match in search_result.get("matches", []):
            fingerprint = json.dumps(match, sort_keys=True, ensure_ascii=False)
            if fingerprint not in seen_matches:
                seen_matches.add(fingerprint)
                matches.append(match)
        events.extend(
            _tool_events(
                ctx,
                "document_specialist",
                "search_documents",
                {"query": search_query},
                search_result,
            )
        )

    result = {
        "status": "success" if "success" in statuses else "no_results",
        "matches": matches,
    }
    _store_stage_findings(events, "document_specialist", result)
    return events, result


async def deterministic_research_events(
    ctx: InvocationContext,
    plan: ResearchPlan,
) -> tuple[list[Event], dict]:
    """Execute a model-produced public research plan deterministically."""
    events: list[Event] = []
    search_result = await asyncio.to_thread(
        search_web,
        plan.query,
        _SEARCH_RESULT_LIMIT,
    )
    events.extend(
        _tool_events(
            ctx,
            "researcher",
            "search_web",
            {"query": plan.query, "max_results": _SEARCH_RESULT_LIMIT},
            search_result,
        )
    )

    fetched_pages = []
    attempted_urls = []
    ranked_results = sorted(
        search_result.get("results", []),
        key=lambda item: 0 if _is_documentation_result(item) else 1,
    )
    for item in ranked_results:
        url = item.get("url", "")
        if not url:
            continue
        attempted_urls.append(url)
        fetch_result = await asyncio.to_thread(fetch_web_page, url)
        events.extend(
            _tool_events(
                ctx,
                "researcher",
                "fetch_web_page",
                {"url": url},
                fetch_result,
            )
        )
        if fetch_result.get("status") == "success":
            fetched_pages.append(
                {
                    "url": url,
                    "content": fetch_result.get("content", "")[:6000],
                }
            )
        if (
            len(fetched_pages) == _FETCHED_PAGE_LIMIT
            or len(attempted_urls) == _FETCH_ATTEMPT_LIMIT
        ):
            break

    result = {
        "status": (
            "success"
            if search_result.get("status") == "success" and fetched_pages
            else "error"
        ),
        "query": plan.query,
        "search_results": search_result.get("results", []),
        "fetched_pages": fetched_pages,
        "attempted_urls": attempted_urls,
    }
    _store_stage_findings(events, "researcher", result)
    return events, result


def _volume_inputs(message: str, document_findings: str) -> tuple[float, int] | None:
    """Extract a daily ingestion figure and requested period for a volume tool."""
    for pattern in _DAILY_INGESTION_PATTERNS:
        match = pattern.search(document_findings)
        if match:
            daily_gb = float(match.group("daily_gb"))
            break
    else:
        return None

    days_match = _DAYS_PATTERN.search(message)
    days = int(days_match.group("days")) if days_match else 30
    return daily_gb, days


def _unavailable_analyst_event(ctx: InvocationContext, result: dict) -> Event:
    """Store a calculation limitation without falsely recording a tool call."""
    return Event(
        invocation_id=ctx.invocation_id,
        author="analyst",
        branch=_stage_branch(ctx, "analyst"),
        content=types.Content(
            role="model",
            parts=[types.Part(text=result["limitation"])],
        ),
        actions=EventActions(
            state_delta={
                SPECIALIST_OUTPUT_KEYS["analyst"]: json.dumps(
                    result,
                    ensure_ascii=False,
                )
            }
        ),
    )


async def deterministic_analyst_events(
    ctx: InvocationContext,
    message: str,
) -> tuple[list[Event], dict]:
    """Run the mandatory data-volume calculation for multi-stage requests."""
    document_findings = str(
        ctx.session.state.get(SPECIALIST_OUTPUT_KEYS["document_specialist"], "")
    )
    inputs = _volume_inputs(message, document_findings)
    if inputs is None:
        result = {
            "status": "unavailable",
            "limitation": (
                "Monthly ingestion could not be calculated because no daily "
                "ingestion volume was found in the retrieved documents."
            ),
        }
        return [_unavailable_analyst_event(ctx, result)], result

    daily_gb, days = inputs
    result = await asyncio.to_thread(calculate_data_volume, daily_gb, days)
    result["daily_gb"] = daily_gb
    result["input_source"] = "document_findings"
    events = _tool_events(
        ctx,
        "analyst",
        "calculate_data_volume",
        {"daily_gb": daily_gb, "days": days},
        result,
    )
    _store_stage_findings(events, "analyst", result)
    return events, result
