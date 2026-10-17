import hashlib
import re
from pathlib import Path

from pypdf import PdfReader

from multi_agent_project.rag.vector_store import (
    get_collection,
)


def chunk_text(
    text: str,
    size: int = 800,
    overlap: int = 100,
) -> list[str]:
    """Split text into overlapping character chunks."""
    if not 0 <= overlap < size:
        raise ValueError("Require 0 <= overlap < size")

    step = size - overlap
    return [
        text[i : i + size].strip()
        for i in range(0, len(text), step)
        if text[i : i + size].strip()
    ]


def ingest_pdf(path: str) -> int:
    """Extract and index text from a PDF."""
    pdf_path = Path(path)

    ids = []
    documents = []
    metadatas = []

    # Hash content to distinguish documents with the same name.
    doc_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]

    reader = PdfReader(pdf_path)

    for page_num, page in enumerate(reader.pages, start=1):
        text = normalize_text(page.extract_text() or "")

        for index, chunk in enumerate(chunk_text(text)):
            ids.append(f"{doc_hash}_p{page_num}_c{index}")
            documents.append(chunk)
            metadatas.append(
                {
                    "source": pdf_path.name,
                    "page": page_num,
                }
            )

    if not documents:
        return 0

    collection = get_collection()
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
    )

    return len(documents)


def normalize_text(text: str) -> str:
    """Remove excessive whitespace from extracted PDF text."""
    return re.sub(r"\s+", " ", text).strip()
