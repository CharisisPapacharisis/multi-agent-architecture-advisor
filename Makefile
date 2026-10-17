
.PHONY: help install test lint fix format check agent api ui

help:
	@echo "Available commands:"
	@echo "  make install  - Install dependencies"
	@echo "  make test     - Run pytest"
	@echo "  make lint     - Check code quality"
	@echo "  make fix      - Auto-fix lint issues"
	@echo "  make format   - Format Python files"
	@echo "  make check    - Run all quality checks"
	@echo "  make agent    - Start ADK web interface"
	@echo "  make api      - Start FastAPI"
	@echo "  make ui       - Start Streamlit"

install:
	uv sync

test:
	uv run pytest -q

lint:
	uv run ruff check .

fix:
	uv run ruff check . --fix

format:
	uv run ruff format .

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pytest -q

agent:
	uv run adk web src/multi_agent_project

api:
	uv run uvicorn multi_agent_project.api.main:app --reload --host 127.0.0.1 --port 8001

ui:
	uv run streamlit run src/multi_agent_project/frontend/streamlit_app.py --server.address 127.0.0.1
