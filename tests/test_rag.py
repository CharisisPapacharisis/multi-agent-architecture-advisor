from unittest.mock import Mock, patch

import pytest

from multi_agent_project.rag.ingestion import chunk_text, ingest_pdf, normalize_text
from multi_agent_project.rag.vector_store import get_collection, search_chunks
from multi_agent_project.tools.document_search import (
    search_documents,
)


def test_chunking():
    chunks = chunk_text("ABCDEFGHIJ", size=6, overlap=2)

    assert chunks == ["ABCDEF", "EFGHIJ", "IJ"]


def test_invalid_chunking():
    with pytest.raises(ValueError):
        chunk_text("hello", size=5, overlap=5)


def test_empty_query():
    result = search_documents("")

    assert result["status"] == "no_results"
    assert result["matches"] == []


def test_normalize_text() -> None:
    """Collapse PDF line breaks and repeated whitespace into single spaces."""
    assert normalize_text("  Cloud\n\narchitecture\t guide  ") == (
        "Cloud architecture guide"
    )


def test_ingest_pdf_stores_chunks_with_source_and_page_metadata(tmp_path) -> None:
    """Store extracted page text with stable IDs and traceable metadata."""
    pdf_path = tmp_path / "architecture.pdf"
    pdf_path.write_bytes(b"fake PDF content")
    pages = [Mock(), Mock()]
    pages[0].extract_text.return_value = "First\npage"
    pages[1].extract_text.return_value = "Second page"
    collection = Mock()

    with (
        patch("multi_agent_project.rag.ingestion.PdfReader") as reader,
        patch(
            "multi_agent_project.rag.ingestion.get_collection",
            return_value=collection,
        ),
    ):
        reader.return_value.pages = pages
        chunk_count = ingest_pdf(str(pdf_path))

    assert chunk_count == 2
    collection.upsert.assert_called_once()
    stored = collection.upsert.call_args.kwargs
    assert stored["documents"] == ["First page", "Second page"]
    assert stored["metadatas"] == [
        {"source": "architecture.pdf", "page": 1},
        {"source": "architecture.pdf", "page": 2},
    ]
    assert stored["ids"][0].endswith("_p1_c0")
    assert stored["ids"][1].endswith("_p2_c0")


def test_ingest_pdf_skips_pages_without_extractable_text(tmp_path) -> None:
    """Return zero and avoid a database write when a PDF contains no text."""
    pdf_path = tmp_path / "scanned.pdf"
    pdf_path.write_bytes(b"fake scanned PDF")
    pages = [Mock(), Mock()]
    pages[0].extract_text.return_value = None
    pages[1].extract_text.return_value = " \n\t "
    collection = Mock()

    with (
        patch("multi_agent_project.rag.ingestion.PdfReader") as reader,
        patch(
            "multi_agent_project.rag.ingestion.get_collection",
            return_value=collection,
        ) as collection_factory,
    ):
        reader.return_value.pages = pages
        chunk_count = ingest_pdf(str(pdf_path))

    assert chunk_count == 0
    collection_factory.assert_not_called()
    collection.upsert.assert_not_called()


def test_get_collection_reuses_persistent_collection() -> None:
    """Avoid recreating a Chroma client for every retrieval."""
    get_collection.cache_clear()
    with patch(
        "multi_agent_project.rag.vector_store.chromadb.PersistentClient"
    ) as client:
        first = get_collection("test-index")
        second = get_collection("test-index")

    assert first is second
    client.assert_called_once_with(path="test-index")
    get_collection.cache_clear()


def test_search_chunks_shapes_results_and_limits_result_count() -> None:
    """Convert Chroma's nested response and cap results to collection size."""
    collection = Mock()
    collection.count.return_value = 2
    collection.query.return_value = {
        "documents": [["First match", "Second match"]],
        "metadatas": [
            [
                {"source": "guide.pdf", "page": 2},
                {"source": "guide.pdf", "page": 5},
            ]
        ],
        "distances": [[0.1, 0.4]],
    }

    with patch(
        "multi_agent_project.rag.vector_store.get_collection",
        return_value=collection,
    ):
        results = search_chunks("database recommendation", top_k=5)

    collection.query.assert_called_once_with(
        query_texts=["database recommendation"],
        n_results=2,
        include=["documents", "metadatas", "distances"],
    )
    collection.count.assert_called_once_with()
    assert results == [
        {
            "text": "First match",
            "source": "guide.pdf",
            "page": 2,
            "distance": 0.1,
        },
        {
            "text": "Second match",
            "source": "guide.pdf",
            "page": 5,
            "distance": 0.4,
        },
    ]
