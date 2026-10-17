import logging

from ddgs import DDGS

logger = logging.getLogger(__name__)


def search_web(query: str, max_results: int = 5) -> dict:
    """Search the public web for technical information.

    Args:
        query: Search query.
        max_results: Requested result count, clamped to between 1 and 10.

    Returns:
        Success status and title, URL, and snippet records, or an error status
        with an empty result list and an error description.
    """
    if not query.strip():
        return {"status": "error", "results": [], "error": "Empty query"}

    try:
        results = DDGS().text(
            query,
            max_results=min(max(max_results, 1), 10),
        )

        return {
            "status": "success",
            "results": [
                {
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "snippet": item.get("body", ""),
                }
                for item in results
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Web search failed: %s", exc)

        return {
            "status": "error",
            "results": [],
            "error": type(exc).__name__,
        }
