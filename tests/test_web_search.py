from unittest.mock import patch

from multi_agent_project.tools.web_search import search_web


def test_search_returns_structured_results() -> None:
    """Normalize mocked search provider results into source records."""
    fake_results = [
        {
            "title": "BigQuery documentation",
            "href": "https://cloud.google.com/bigquery/docs",
            "body": "Official documentation",
        }
    ]

    with patch("multi_agent_project.tools.web_search.DDGS") as mock_ddgs:
        mock_ddgs.return_value.text.return_value = fake_results

        result = search_web("BigQuery documentation", 3)

    assert result["status"] == "success"
    assert len(result["results"]) == 1
    assert result["results"][0]["url"] == ("https://cloud.google.com/bigquery/docs")


def test_empty_query() -> None:
    """Return a structured error for an empty search query."""
    result = search_web("")

    assert result["status"] == "error"
    assert result["results"] == []


def test_search_provider_failure() -> None:
    """Return a structured error when the search provider fails."""
    with patch("multi_agent_project.tools.web_search.DDGS") as mock_ddgs:
        mock_ddgs.return_value.text.side_effect = RuntimeError("Unavailable")

        result = search_web("BigQuery")

    assert result["status"] == "error"
    assert result["error"] == "RuntimeError"
