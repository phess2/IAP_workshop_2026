"""
Vector database module using SQLite with sqlite-vec for vector storage and FTS5 for keyword search.

This module provides:
- Local embeddings using MiniLM-L6-v2 (384 dimensions) via fastembed
- Vector storage and similarity search via sqlite-vec
- BM25 keyword search via FTS5
- Hybrid search combining both approaches
"""

import json
import os
import sqlite3
import struct
from datetime import datetime
from pathlib import Path
from typing import Optional

import sqlite_vec
from fastembed import TextEmbedding

from .config import settings

# Suppress Hugging Face token warning
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"

# Embedding model dimensions
EMBEDDING_DIM = 384

# Global embedding model (lazy loaded)
_embedding_model: Optional[TextEmbedding] = None


def _get_embedding_model() -> TextEmbedding:
    """Get or initialize the embedding model (singleton pattern)."""
    global _embedding_model
    if _embedding_model is None:
        print("Loading MiniLM-L6-v2 embedding model (ONNX)...")
        _embedding_model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
        print("Model loaded successfully!")
    return _embedding_model


def init_vector_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Initialize the vector database with embeddings table, FTS5 for BM25, and vec0 for vectors.

    Args:
        db_path: Path to the database file. If None, uses settings.vector_db_path

    Returns:
        SQLite connection with sqlite-vec extension loaded
    """
    if db_path is None:
        db_path = Path(settings.vector_db_path)

    # Ensure directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Load sqlite-vec extension
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    cursor = conn.cursor()

    # Metadata table (stores content and metadata, linked to vectors by rowid)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS embeddings_meta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id TEXT,
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Vector table using sqlite-vec (384 dimensions for MiniLM-L6-v2)
    cursor.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_embeddings USING vec0(
            embedding float[{EMBEDDING_DIM}] distance_metric=cosine
        )
    """)

    # FTS5 virtual table for BM25 keyword search
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS embeddings_fts USING fts5(
            content,
            source_type,
            source_id,
            content='embeddings_meta',
            content_rowid='id'
        )
    """)

    # Triggers to keep FTS5 in sync with embeddings_meta table
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS embeddings_ai AFTER INSERT ON embeddings_meta BEGIN
            INSERT INTO embeddings_fts(rowid, content, source_type, source_id)
            VALUES (new.id, new.content, new.source_type, new.source_id);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS embeddings_ad AFTER DELETE ON embeddings_meta BEGIN
            INSERT INTO embeddings_fts(embeddings_fts, rowid, content, source_type, source_id)
            VALUES ('delete', old.id, old.content, old.source_type, old.source_id);
        END
    """)

    # Index for faster lookups by source_type and source_id
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_embeddings_source
        ON embeddings_meta(source_type, source_id)
    """)

    conn.commit()
    return conn


def generate_embedding(text: str) -> list[float]:
    """
    Generate a 384-dimensional embedding for the given text.

    Args:
        text: The text to embed

    Returns:
        List of 384 float values representing the embedding
    """
    model = _get_embedding_model()
    embeddings = list(model.embed([text]))
    return embeddings[0].tolist()


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for multiple texts in a batch (more efficient).

    Args:
        texts: List of texts to embed

    Returns:
        List of embeddings, one per input text
    """
    if not texts:
        return []
    model = _get_embedding_model()
    embeddings = list(model.embed(texts))
    return [emb.tolist() for emb in embeddings]


def serialize_embedding(embedding: list[float]) -> bytes:
    """Serialize embedding to binary format for sqlite-vec."""
    return struct.pack(f'{len(embedding)}f', *embedding)


def save_embedding(
    conn: sqlite3.Connection,
    source_type: str,
    content: str,
    embedding: list[float],
    source_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> int:
    """
    Save an embedding to the database.

    Inserts into:
    1. embeddings_meta - content and metadata (FTS5 updated via trigger)
    2. vec_embeddings - vector for similarity search (matched by rowid)

    Args:
        conn: Database connection
        source_type: Type of source (business_doc, post, reply)
        content: The text content that was embedded
        embedding: The embedding vector
        source_id: Optional identifier for the source (e.g., page_id, post_id)
        metadata: Optional additional metadata as dict

    Returns:
        The rowid of the inserted embedding
    """
    cursor = conn.cursor()

    # Insert metadata (FTS5 index updated automatically via trigger)
    cursor.execute(
        """
        INSERT INTO embeddings_meta (source_type, source_id, content, metadata, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            source_type,
            source_id,
            content,
            json.dumps(metadata) if metadata else None,
            datetime.now().isoformat(),
        ),
    )
    rowid = cursor.lastrowid

    # Insert vector with matching rowid
    cursor.execute(
        """
        INSERT INTO vec_embeddings (rowid, embedding)
        VALUES (?, ?)
        """,
        (rowid, serialize_embedding(embedding)),
    )

    conn.commit()
    return rowid


def delete_embeddings_by_source(
    conn: sqlite3.Connection,
    source_type: str,
    source_id: Optional[str] = None,
) -> int:
    """
    Delete embeddings by source type and optionally source ID.

    Args:
        conn: Database connection
        source_type: Type of source to delete
        source_id: Optional specific source ID to delete

    Returns:
        Number of embeddings deleted
    """
    cursor = conn.cursor()

    # Get IDs to delete
    if source_id:
        cursor.execute(
            "SELECT id FROM embeddings_meta WHERE source_type = ? AND source_id = ?",
            (source_type, source_id),
        )
    else:
        cursor.execute(
            "SELECT id FROM embeddings_meta WHERE source_type = ?",
            (source_type,),
        )

    ids = [row[0] for row in cursor.fetchall()]

    if not ids:
        return 0

    # Delete from vec_embeddings first (no trigger, manual delete)
    placeholders = ",".join("?" * len(ids))
    cursor.execute(f"DELETE FROM vec_embeddings WHERE rowid IN ({placeholders})", ids)

    # Delete from embeddings_meta (trigger will update FTS5)
    cursor.execute(f"DELETE FROM embeddings_meta WHERE id IN ({placeholders})", ids)

    conn.commit()
    return len(ids)


def bm25_search(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 100,
    source_types: Optional[list[str]] = None,
) -> dict[int, float]:
    """
    Search using BM25 ranking via FTS5.

    Note: FTS5 BM25 scores are NEGATIVE (more negative = better match).

    Args:
        conn: Database connection
        query: Search query text
        limit: Maximum results to return
        source_types: Optional list of source types to filter by

    Returns:
        Dict mapping embedding_id to raw BM25 score
    """
    cursor = conn.cursor()

    # Escape special FTS5 characters
    safe_query = query.replace('"', '""')

    try:
        if source_types:
            # Filter by source type using subquery
            type_filter = " OR ".join(f'source_type:"{t}"' for t in source_types)
            full_query = f"({safe_query}) AND ({type_filter})"
            cursor.execute(
                """
                SELECT rowid, bm25(embeddings_fts) as score
                FROM embeddings_fts
                WHERE embeddings_fts MATCH ?
                LIMIT ?
                """,
                (full_query, limit),
            )
        else:
            cursor.execute(
                """
                SELECT rowid, bm25(embeddings_fts) as score
                FROM embeddings_fts
                WHERE embeddings_fts MATCH ?
                LIMIT ?
                """,
                (safe_query, limit),
            )

        return {row[0]: row[1] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        # No matches or invalid query
        return {}


def semantic_search(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    limit: int = 100,
    source_types: Optional[list[str]] = None,
) -> dict[int, float]:
    """
    Search using sqlite-vec's native cosine distance.

    Note: cosine distance is in [0, 2] where 0 = identical, 2 = opposite.

    Args:
        conn: Database connection
        query_embedding: Pre-computed embedding of the query
        limit: Maximum results to return
        source_types: Optional list of source types to filter by

    Returns:
        Dict mapping rowid to cosine distance
    """
    cursor = conn.cursor()

    if source_types:
        # Get all vector results first, then filter
        cursor.execute(
            """
            SELECT v.rowid, v.distance
            FROM vec_embeddings v
            JOIN embeddings_meta m ON v.rowid = m.id
            WHERE v.embedding MATCH ?
              AND v.k = ?
              AND m.source_type IN ({})
            ORDER BY v.distance
            """.format(",".join("?" * len(source_types))),
            (serialize_embedding(query_embedding), limit * 2, *source_types),
        )
    else:
        cursor.execute(
            """
            SELECT rowid, distance
            FROM vec_embeddings
            WHERE embedding MATCH ?
              AND k = ?
            ORDER BY distance
            """,
            (serialize_embedding(query_embedding), limit),
        )

    results = {row[0]: row[1] for row in cursor.fetchall()}

    # Return only up to limit results
    return dict(list(results.items())[:limit])


def normalize_bm25_scores(bm25_scores: dict[int, float]) -> dict[int, float]:
    """
    Normalize BM25 scores to [0, 1] range.

    FTS5 BM25 scores are negative (more negative = better).
    We invert so that best match gets 1.0, worst gets 0.0.
    """
    if not bm25_scores:
        return {}

    scores = list(bm25_scores.values())
    min_score = min(scores)  # Most negative = best
    max_score = max(scores)  # Least negative = worst

    if min_score == max_score:
        return {id: 1.0 for id in bm25_scores}

    score_range = max_score - min_score
    return {id: (max_score - score) / score_range for id, score in bm25_scores.items()}


def normalize_distances(distances: dict[int, float]) -> dict[int, float]:
    """
    Normalize cosine distances to similarity scores in [0, 1].

    Cosine distance is in [0, 2] where 0 = identical.
    We convert to similarity: 1 - (distance / 2)
    Then normalize so best match gets 1.0.
    """
    if not distances:
        return {}

    # Convert distances to similarities
    similarities = {id: 1 - (dist / 2) for id, dist in distances.items()}

    # Normalize to [0, 1] range
    min_sim = min(similarities.values())
    max_sim = max(similarities.values())

    if min_sim == max_sim:
        return {id: 1.0 for id in similarities}

    sim_range = max_sim - min_sim
    return {id: (sim - min_sim) / sim_range for id, sim in similarities.items()}


def get_metadata_by_ids(conn: sqlite3.Connection, ids: list[int]) -> dict[int, dict]:
    """Retrieve metadata for given IDs from embeddings_meta table."""
    if not ids:
        return {}

    cursor = conn.cursor()
    placeholders = ",".join("?" * len(ids))
    cursor.execute(
        f"""
        SELECT id, source_type, source_id, content, metadata
        FROM embeddings_meta
        WHERE id IN ({placeholders})
        """,
        ids,
    )

    results = {}
    for row in cursor.fetchall():
        results[row[0]] = {
            "source_type": row[1],
            "source_id": row[2],
            "content": row[3],
            "metadata": json.loads(row[4]) if row[4] else {},
        }
    return results


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    query_embedding: list[float],
    keyword_weight: Optional[float] = None,
    semantic_weight: Optional[float] = None,
    top_k: int = 10,
    source_types: Optional[list[str]] = None,
) -> list[dict]:
    """
    Perform hybrid search combining BM25 and sqlite-vec cosine similarity.

    Formula: final_score = keyword_weight * bm25 + semantic_weight * cosine_sim

    Args:
        conn: Database connection
        query: Search query text
        query_embedding: Pre-computed embedding of the query
        keyword_weight: Weight for BM25 (0-1), defaults to settings.rag_keyword_weight
        semantic_weight: Weight for cosine similarity (0-1), defaults to settings.rag_semantic_weight
        top_k: Number of results to return
        source_types: Optional list of source types to filter by

    Returns:
        List of results sorted by combined score (highest first)
    """
    # Use settings defaults if not provided
    if keyword_weight is None:
        keyword_weight = settings.rag_keyword_weight
    if semantic_weight is None:
        semantic_weight = settings.rag_semantic_weight

    # Step 1: Get BM25 scores from FTS5
    bm25_raw = bm25_search(conn, query, source_types=source_types)
    bm25_normalized = normalize_bm25_scores(bm25_raw)

    # Step 2: Get semantic distances from sqlite-vec
    semantic_raw = semantic_search(conn, query_embedding, limit=100, source_types=source_types)
    semantic_normalized = normalize_distances(semantic_raw)

    # Step 3: Get all unique IDs from both searches
    all_ids = set(bm25_normalized.keys()) | set(semantic_normalized.keys())

    if not all_ids:
        return []

    # Step 4: Get metadata for all candidates
    metadata = get_metadata_by_ids(conn, list(all_ids))

    # Step 5: Compute combined scores
    scored_results = []

    for id in all_ids:
        # BM25 score (0 if no keyword match)
        bm25_score = bm25_normalized.get(id, 0.0)

        # Semantic score (0 if not in top semantic results)
        semantic_score = semantic_normalized.get(id, 0.0)

        # Combined score
        final_score = (keyword_weight * bm25_score) + (semantic_weight * semantic_score)

        meta = metadata.get(id, {})
        scored_results.append(
            {
                "id": id,
                "content": meta.get("content", ""),
                "source_type": meta.get("source_type", ""),
                "source_id": meta.get("source_id", ""),
                "metadata": meta.get("metadata", {}),
                "bm25_score": bm25_score,
                "semantic_score": semantic_score,
                "final_score": final_score,
            }
        )

    # Sort by final score (descending)
    scored_results.sort(key=lambda x: x["final_score"], reverse=True)

    return scored_results[:top_k]


def get_embedding_stats(conn: sqlite3.Connection) -> dict:
    """
    Get statistics about embeddings in the database.

    Returns:
        Dict with counts by source_type and total count
    """
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT source_type, COUNT(*) as count
        FROM embeddings_meta
        GROUP BY source_type
        """
    )

    stats = {"by_type": {}, "total": 0}
    for row in cursor.fetchall():
        stats["by_type"][row[0]] = row[1]
        stats["total"] += row[1]

    return stats
