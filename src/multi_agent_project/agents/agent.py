import logging
from collections.abc import AsyncGenerator, Mapping
from typing import override

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from pydantic import ValidationError

from multi_agent_project.agents.analyst_agent import analyst_agent
from multi_agent_project.agents.rag_agent import document_specialist_agent
from multi_agent_project.agents.research_agent import (
    RESEARCH_PLAN_OUTPUT_KEY,
    ResearchPlan,
    research_agent,
    research_planner_agent,
)
from multi_agent_project.agents.routing import (
    ROUTE_OUTPUT_KEY,
    RouteDecision,
    is_internal_document_only_request,
    requests_all_specialists,
    routing_agent,
    selected_specialists,
)
from multi_agent_project.agents.synthesis_agent import synthesis_agent
from multi_agent_project.agents.workflow_stages import (
    DAILY_INGESTION_QUERY,
    SPECIALIST_OUTPUT_KEYS,
    deterministic_analyst_events,
    deterministic_document_events,
    deterministic_research_events,
)

SELECTED_SPECIALISTS_KEY = "temp:selected_specialists"
REQUIRED_STAGE_TOOLS = {
    "document_specialist": {"search_documents"},
    "researcher": {"search_web", "fetch_web_page"},
    "analyst": {"calculate_data_volume"},
}
USABLE_TOOL_STATUSES = {
    "document_specialist": {"success", "no_results"},
    "researcher": {"success"},
    "analyst": {"success"},
}

logger = logging.getLogger("uvicorn.error")


class WorkflowStageError(RuntimeError):
    """Raised when a selected workflow stage produces no usable result."""


def _user_message(ctx: InvocationContext) -> str:
    """Extract text from the user content that started this invocation."""
    if not ctx.user_content or not ctx.user_content.parts:
        return ""
    return " ".join(part.text for part in ctx.user_content.parts if part.text)


def _parse_route(value: object) -> RouteDecision:
    """Validate the structured route stored by the routing agent."""
    if isinstance(value, str):
        return RouteDecision.model_validate_json(value)
    return RouteDecision.model_validate(value)


def _parse_research_plan(value: object) -> ResearchPlan:
    """Validate the structured public research plan."""
    if isinstance(value, str):
        return ResearchPlan.model_validate_json(value)
    return ResearchPlan.model_validate(value)


def _isolated_context(
    ctx: InvocationContext,
    agent_name: str,
) -> InvocationContext:
    """Give one workflow stage a branch isolated from its peer agents."""
    parent_branch = ctx.branch or "architecture_workflow"
    return ctx.model_copy(update={"branch": f"{parent_branch}.{agent_name}"})


def _supplementary_document_queries(selected: list[str]) -> tuple[str, ...]:
    """Request calculation inputs explicitly when the analyst is selected."""
    return (DAILY_INGESTION_QUERY,) if "analyst" in selected else ()


class ArchitectureWorkflow(BaseAgent):
    """Route requests, run selected specialists, and synthesize when needed."""

    @override
    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event]:
        message = _user_message(ctx)

        if requests_all_specialists(message):
            route = RouteDecision(
                needs_documents=True,
                needs_research=True,
                needs_calculation=True,
            )
        elif is_internal_document_only_request(message):
            route = RouteDecision(needs_documents=True)
        else:
            route_value = None
            router = self.find_sub_agent("request_router")
            if router is None:
                raise RuntimeError("Configured routing agent not found")
            router_context = _isolated_context(ctx, router.name)
            async for event in router.run_async(router_context):
                if event.actions and event.actions.state_delta:
                    route_value = event.actions.state_delta.get(ROUTE_OUTPUT_KEY)
                yield event

            if route_value is None:
                route_value = ctx.session.state.get(ROUTE_OUTPUT_KEY)

            try:
                route = _parse_route(route_value)
            except (ValidationError, ValueError, TypeError) as exc:
                raise RuntimeError("Routing agent returned an invalid route") from exc

        selected = selected_specialists(route)
        ctx.session.state[SELECTED_SPECIALISTS_KEY] = selected
        logger.info("Workflow route selected: specialists=%s", selected)

        research_plan = None
        if "researcher" in selected and len(selected) > 1:
            planner = self.find_sub_agent("research_planner")
            if planner is None:
                raise RuntimeError("Configured research planner not found")
            plan_value = None
            planner_context = _isolated_context(ctx, planner.name)
            logger.info("Workflow research planning starting")
            async for event in planner.run_async(planner_context):
                if event.actions and event.actions.state_delta:
                    plan_value = event.actions.state_delta.get(RESEARCH_PLAN_OUTPUT_KEY)
            try:
                research_plan = _parse_research_plan(plan_value)
            except (ValidationError, ValueError, TypeError) as exc:
                raise WorkflowStageError(
                    "The researcher stage could not produce a valid public search plan"
                ) from exc
            logger.info(
                "Workflow research plan ready",
            )

        for agent_name in selected:
            if agent_name == "document_specialist" and len(selected) > 1:
                logger.info("Workflow stage starting: agent=%s", agent_name)
                events, result = await deterministic_document_events(
                    ctx,
                    message,
                    _supplementary_document_queries(selected),
                )
                for event in events:
                    yield event

                status = result.get("status")
                logger.info(
                    "Workflow tool result: agent=%s tool=%s status=%s",
                    agent_name,
                    "search_documents",
                    status,
                )
                if status != "success":
                    raise WorkflowStageError(
                        "The document_specialist stage required tools returned "
                        "no successful result: search_documents"
                    )
                logger.info(
                    "Workflow stage completed: agent=%s tools=%s",
                    agent_name,
                    ["search_documents"],
                )
                continue

            if agent_name == "researcher" and research_plan is not None:
                logger.info("Workflow stage starting: agent=%s", agent_name)
                events, result = await deterministic_research_events(
                    ctx,
                    research_plan,
                )
                for event in events:
                    yield event

                logger.info(
                    "Workflow deterministic research completed: "
                    "agent=%s fetched_pages=%d",
                    agent_name,
                    len(result["fetched_pages"]),
                )
                if result["status"] != "success":
                    raise WorkflowStageError(
                        "The researcher stage could not fetch a relevant public "
                        "documentation page"
                    )
                continue

            if agent_name == "analyst" and len(selected) > 1:
                logger.info("Workflow stage starting: agent=%s", agent_name)
                events, result = await deterministic_analyst_events(ctx, message)
                for event in events:
                    yield event

                logger.info(
                    "Workflow tool result: agent=%s tool=%s status=%s",
                    agent_name,
                    "calculate_data_volume",
                    result.get("status"),
                )
                if result.get("status") == "unavailable":
                    logger.info(
                        "Workflow stage completed with limitation: agent=%s",
                        agent_name,
                    )
                    continue
                if result.get("status") != "success":
                    raise WorkflowStageError(
                        "The analyst stage could not find a daily ingestion "
                        "volume in the retrieved document findings"
                    )
                logger.info(
                    "Workflow stage completed: agent=%s tools=%s",
                    agent_name,
                    ["calculate_data_volume"],
                )
                continue

            agent = self.find_sub_agent(agent_name)
            if agent is None:
                raise RuntimeError(f"Configured specialist not found: {agent_name}")

            output_key = SPECIALIST_OUTPUT_KEYS[agent_name]
            stage_result = None
            called_tools: set[str] = set()
            successful_tools: set[str] = set()
            stage_context = _isolated_context(ctx, agent_name)
            logger.info("Workflow stage starting: agent=%s", agent_name)
            async for event in agent.run_async(stage_context):
                called_tools.update(
                    function_call.name for function_call in event.get_function_calls()
                )
                for function_response in event.get_function_responses():
                    response = function_response.response
                    status = (
                        response.get("status")
                        if isinstance(response, Mapping)
                        else None
                    )
                    logger.info(
                        "Workflow tool result: agent=%s tool=%s status=%s",
                        agent_name,
                        function_response.name,
                        status,
                    )
                    if (
                        isinstance(response, Mapping)
                        and status in USABLE_TOOL_STATUSES[agent_name]
                    ):
                        successful_tools.add(function_response.name)
                if event.actions and event.actions.state_delta:
                    value = event.actions.state_delta.get(output_key)
                    if value:
                        stage_result = value
                yield event

            if stage_result is None:
                raise WorkflowStageError(
                    f"The {agent_name} stage completed without a result"
                )

            missing_tools = REQUIRED_STAGE_TOOLS[agent_name] - successful_tools
            if missing_tools:
                uncalled_tools = missing_tools - called_tools
                if uncalled_tools:
                    reason = "did not call required tools: " + ", ".join(
                        sorted(uncalled_tools)
                    )
                else:
                    reason = (
                        "required tools returned no successful result: "
                        + ", ".join(sorted(missing_tools))
                    )
                logger.error(
                    "Workflow stage failed tool requirement: agent=%s "
                    "called=%s successful=%s",
                    agent_name,
                    sorted(called_tools),
                    sorted(successful_tools),
                )
                raise WorkflowStageError(f"The {agent_name} stage {reason}")

            logger.info(
                "Workflow stage completed: agent=%s tools=%s",
                agent_name,
                sorted(successful_tools),
            )

        # A single specialist can answer directly. Multiple findings require
        # the coordinator; no specialist means a direct coordinator response.
        if len(selected) != 1:
            coordinator = self.find_sub_agent("architecture_coordinator")
            if coordinator is None:
                raise RuntimeError("Configured synthesis agent not found")
            logger.info("Workflow synthesis starting: specialists=%s", selected)
            coordinator_context = _isolated_context(ctx, coordinator.name)
            async for event in coordinator.run_async(coordinator_context):
                yield event
            logger.info("Workflow synthesis completed")


root_agent = ArchitectureWorkflow(
    name="architecture_workflow",
    description=(
        "Routes architecture questions through the required specialists and "
        "returns multi-specialist work to the architecture coordinator."
    ),
    sub_agents=[
        routing_agent,
        research_planner_agent,
        document_specialist_agent,
        research_agent,
        analyst_agent,
        synthesis_agent,
    ],
)
