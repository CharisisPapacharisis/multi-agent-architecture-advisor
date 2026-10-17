from functools import lru_cache
from pathlib import Path

import chromadb

DB_PATH = Path("data/chroma")
COLLECTION_NAME = "architecture_documents"


@lru_cache(maxsize=4)
def get_collection(db_path: str | Path = DB_PATH):
    """Return the persistent local document collection."""
    client = chromadb.PersistentClient(path=str(db_path))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
    )


def search_chunks(
    query: str,
    top_k: int = 3,
    db_path: str | Path = DB_PATH,
) -> list[dict]:
    """Find document chunks similar to the question."""
    if not query.strip():
        return []

    collection = get_collection(db_path)
    collection_size = collection.count()
    if collection_size == 0:
        return []

    result = collection.query(
        query_texts=[query],
        n_results=max(1, min(top_k, collection_size)),
        include=["documents", "metadatas", "distances"],
    )

    return [
        {
            "text": text,
            "source": metadata["source"],
            "page": metadata["page"],
            "distance": distance,
        }
        for text, metadata, distance in zip(
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        )
    ]
