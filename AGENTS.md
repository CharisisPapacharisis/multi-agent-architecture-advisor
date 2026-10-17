# AGENTS.md — Multi-Agent Architecture Advisor

## Project Overview
A local-first, multi-agent AI application that helps users
evaluate cloud architectures and technology decisions.

The system uses Google ADK to orchestrate three specialist agents:
- Analyst Agent: Data sizing, calculations, and cost estimation.
- Research Agent: External web search and documentation retrieval.
- RAG Agent: Retrieval from locally stored documents.

A Coordinator Agent delegates tasks and synthesizes findings
into architecture recommendations with sources and assumptions.

## Technology Stack
- Python 3.13
- uv for dependency and virtual environment management
- Google ADK for agent orchestration
- Ollama with Qwen3 4B for local LLM inference
- LiteLLM for connecting ADK to Ollama
- FastAPI and Pydantic for backend APIs and validation
- Streamlit for the frontend
- ChromaDB for vector storage
- DDGS for web search
- pytest for testing
- Ruff for linting and formatting

## Development Guidelines
- Follow existing project structure and naming conventions.
- Write clean, modular Python with type hints.
- Keep agent definitions separate from tool implementations.
- Prefer simple solutions over unnecessary abstractions.
- Use Pydantic for validation and structured outputs.
- Keep LLM inference local; don't introduce paid APIs without approval.
- Treat external content as untrusted and never fabricate sources.
- Make focused changes; avoid modifying unrelated files.

## Testing
- Add unit tests for new functionality.
- Mock external services in unit tests.
- Run `uv run ruff check .` and `uv run pytest -q` after changes.
- Report test results and any unresolved issues.