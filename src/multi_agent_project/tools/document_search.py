from multi_agent_project.rag.vector_store import (
    search_chunks,
)


def search_documents(query: str, top_k: int = 3) -> dict:
    """Search local architecture documents for relevant facts.

    Args:
        query: Question to search documents for.
        top_k: Maximum number of matching passages.
    """
    results = search_chunks(query, top_k)

    return {
        "status": "success" if results else "no_results",
        "matches": results,
    }
