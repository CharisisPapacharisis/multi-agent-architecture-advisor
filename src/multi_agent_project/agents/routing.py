from google.adk.agents import Agent
from pydantic import BaseModel

from multi_agent_project.models.llm import get_local_model, sanitize_model_response

ROUTE_OUTPUT_KEY = "route_decision"


class RouteDecision(BaseModel):
    """Specialist capabilities required to answer one user request."""

    needs_documents: bool = False
    needs_research: bool = False
    needs_calculation: bool = False


def requests_all_specialists(message: str) -> bool:
    """Recognize explicit requests that must invoke every specialist."""
    normalized = " ".join(message.lower().split())
    phrases = (
        "all three specialist",
        "all 3 specialist",
        "all specialist agents",
        "every specialist",
        "each specialist",
    )
    return any(phrase in normalized for phrase in phrases)


def is_internal_document_only_request(message: str) -> bool:
    """Identify an unambiguous local-document request without other work."""
    normalized = " ".join(message.lower().split())
    internal_cues = (
        "internal",
        "project atlas",
        "atlas project",
        "local document",
    )
    external_cues = (
        "bigquery",
        "current capabilities",
        "official documentation",
        "research",
        "search the web",
    )
    calculation_cues = (
        "calculate",
        "total monthly",
        "assuming 30 days",
        "cost estimate",
    )
    return (
        any(cue in normalized for cue in internal_cues)
        and not any(cue in normalized for cue in external_cues)
        and not any(cue in normalized for cue in calculation_cues)
    )


def selected_specialists(route: RouteDecision) -> list[str]:
    """Return selected specialists in dependency-safe execution order."""
    selected = []
    if route.needs_documents:
        selected.append("document_specialist")
    if route.needs_research:
        selected.append("researcher")
    if route.needs_calculation:
        selected.append("analyst")
    return selected


routing_agent = Agent(
    name="request_router",
    model=get_local_model(),
    description="Selects the capabilities required for a user request.",
    instruction="""
    Classify the user's request by selecting only the capabilities it requires.

    - needs_documents: internal or local project documents and requirements
    - needs_research: current external information or public documentation
    - needs_calculation: arithmetic, sizing, volume, or cost calculations

    Select multiple capabilities for requests that combine them. Select none
    for greetings or general architecture guidance that needs no specialist.
    Do not answer the request; return only the routing decision.
    """,
    output_schema=RouteDecision,
    output_key=ROUTE_OUTPUT_KEY,
    after_model_callback=sanitize_model_response,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
