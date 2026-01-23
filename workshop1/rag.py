"""
RAG (Retrieval-Augmented Generation) module.

This module provides high-level functions for:
- Retrieving relevant context using hybrid search
- Embedding documents from Notion
- Embedding posts and replies for future retrieval
- Formatting context for LLM prompts
"""

import sqlite3
from pathlib import Path
from typing import Optional

from .chunker import chunk_notion_page, create_post_chunk, create_reply_chunk
from .config import settings
from .notion_client import NotionPage, fetch_child_pages, fetch_parent_page
from .vector_db import (
    delete_embeddings_by_source,
    generate_embedding,
    generate_embeddings_batch,
    get_embedding_stats,
    hybrid_search,
    init_vector_db,
    save_embedding,
)

# Source type constants
SOURCE_BUSINESS_DOC = "business_doc"
SOURCE_POST = "post"
SOURCE_REPLY = "reply"


def get_vector_db_connection() -> sqlite3.Connection:
    """Get a connection to the vector database, initializing if needed."""
    db_path = Path(settings.vector_db_path)
    return init_vector_db(db_path)


def retrieve_context(
    query: str,
    source_types: Optional[list[str]] = None,
    top_k: int = 10,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[str, list[dict]]:
    """
    High-level function to retrieve and format context for RAG.

    Args:
        query: The search query (e.g., topic for post generation)
        source_types: List of source types to search (business_doc, post, reply)
                     If None, searches all types
        top_k: Number of results to return
        conn: Optional existing database connection

    Returns:
        Tuple of (formatted_context_string, raw_results_list)
    """
    should_close = conn is None
    if conn is None:
        conn = get_vector_db_connection()

    try:
        # Generate embedding for the query
        query_embedding = generate_embedding(query)

        # Perform hybrid search
        results = hybrid_search(
            conn=conn,
            query=query,
            query_embedding=query_embedding,
            top_k=top_k,
            source_types=source_types,
        )

        # Format results for LLM prompt
        formatted = format_context_for_prompt(results)

        return formatted, results
    finally:
        if should_close:
            conn.close()


def format_context_for_prompt(results: list[dict], max_chars: int = 4000) -> str:
    """
    Format search results into context for the LLM prompt.

    Args:
        results: List of search results from hybrid_search
        max_chars: Maximum characters to include in context

    Returns:
        Formatted string suitable for inclusion in LLM prompt
    """
    if not results:
        return "No relevant context found."

    context_parts = []
    chars_used = 0

    for i, result in enumerate(results, 1):
        source_label = _get_source_label(result["source_type"])
        header = f"[{i}. {source_label}] (relevance: {result['final_score']:.2f})"
        content = result["content"]

        available = max_chars - chars_used - len(header) - 10
        if available <= 100:
            break

        if len(content) > available:
            content = content[: available - 3] + "..."

        entry = f"{header}\n{content}\n"
        context_parts.append(entry)
        chars_used += len(entry)

    return "\n".join(context_parts)


def _get_source_label(source_type: str) -> str:
    """Get a human-readable label for a source type."""
    labels = {
        SOURCE_BUSINESS_DOC: "Business Documentation",
        SOURCE_POST: "Previous Post",
        SOURCE_REPLY: "Previous Reply",
    }
    return labels.get(source_type, source_type)


def embed_notion_docs(conn: Optional[sqlite3.Connection] = None) -> dict:
    """
    Fetch and embed all Notion documents (parent and child pages).

    This will:
    1. Delete existing business_doc embeddings
    2. Fetch parent page (business description)
    3. Fetch all child pages
    4. Chunk and embed all documents

    Args:
        conn: Optional existing database connection

    Returns:
        Dict with statistics about embedded documents
    """
    should_close = conn is None
    if conn is None:
        conn = get_vector_db_connection()

    try:
        stats = {"pages_processed": 0, "chunks_created": 0, "errors": []}

        # Delete existing business doc embeddings
        deleted = delete_embeddings_by_source(conn, SOURCE_BUSINESS_DOC)
        stats["previous_chunks_deleted"] = deleted

        # Fetch parent page (business description)
        try:
            parent_page = fetch_parent_page()
            _embed_notion_page(conn, parent_page, stats)
        except Exception as e:
            stats["errors"].append(f"Failed to fetch parent page: {e}")

        # Fetch child pages
        try:
            child_pages = fetch_child_pages()
            for page in child_pages:
                _embed_notion_page(conn, page, stats)
        except Exception as e:
            stats["errors"].append(f"Failed to fetch child pages: {e}")

        return stats
    finally:
        if should_close:
            conn.close()


def _embed_notion_page(
    conn: sqlite3.Connection, page: NotionPage, stats: dict
) -> None:
    """Helper to chunk and embed a single Notion page."""
    try:
        chunks = chunk_notion_page(page)

        # Batch generate embeddings
        texts = [c["content"] for c in chunks]
        embeddings = generate_embeddings_batch(texts)

        # Save each chunk
        for chunk, embedding in zip(chunks, embeddings):
            save_embedding(
                conn=conn,
                source_type=SOURCE_BUSINESS_DOC,
                content=chunk["content"],
                embedding=embedding,
                source_id=page.id,
                metadata=chunk["metadata"],
            )

        stats["pages_processed"] += 1
        stats["chunks_created"] += len(chunks)
    except Exception as e:
        stats["errors"].append(f"Failed to embed page {page.title}: {e}")


def embed_single_notion_page(
    page: NotionPage, conn: Optional[sqlite3.Connection] = None
) -> int:
    """
    Embed a single Notion page, replacing any existing embeddings for it.

    Args:
        page: The NotionPage to embed
        conn: Optional existing database connection

    Returns:
        Number of chunks created
    """
    should_close = conn is None
    if conn is None:
        conn = get_vector_db_connection()

    try:
        # Delete existing embeddings for this page
        delete_embeddings_by_source(conn, SOURCE_BUSINESS_DOC, page.id)

        # Chunk the page
        chunks = chunk_notion_page(page)

        # Batch generate embeddings
        texts = [c["content"] for c in chunks]
        embeddings = generate_embeddings_batch(texts)

        # Save each chunk
        for chunk, embedding in zip(chunks, embeddings):
            save_embedding(
                conn=conn,
                source_type=SOURCE_BUSINESS_DOC,
                content=chunk["content"],
                embedding=embedding,
                source_id=page.id,
                metadata=chunk["metadata"],
            )

        return len(chunks)
    finally:
        if should_close:
            conn.close()


def embed_post(
    post_content: str,
    post_id: str,
    metadata: Optional[dict] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Embed a posted Mastodon post for future retrieval.

    Args:
        post_content: The text content of the post
        post_id: Unique identifier for the post (Mastodon post ID)
        metadata: Optional additional metadata (e.g., mastodon_url, posted_at)
        conn: Optional existing database connection

    Returns:
        The rowid of the saved embedding
    """
    should_close = conn is None
    if conn is None:
        conn = get_vector_db_connection()

    try:
        # Create chunk (no actual chunking, posts are small enough)
        chunk = create_post_chunk(post_content, post_id, metadata)

        # Generate embedding
        embedding = generate_embedding(chunk["content"])

        # Save to database
        rowid = save_embedding(
            conn=conn,
            source_type=SOURCE_POST,
            content=chunk["content"],
            embedding=embedding,
            source_id=post_id,
            metadata=chunk["metadata"],
        )

        return rowid
    finally:
        if should_close:
            conn.close()


def embed_reply(
    reply_content: str,
    reply_id: str,
    original_post_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """
    Embed a posted Mastodon reply for future retrieval.

    Args:
        reply_content: The text content of the reply
        reply_id: Unique identifier for the reply (Mastodon status ID)
        original_post_id: ID of the post being replied to
        metadata: Optional additional metadata
        conn: Optional existing database connection

    Returns:
        The rowid of the saved embedding
    """
    should_close = conn is None
    if conn is None:
        conn = get_vector_db_connection()

    try:
        # Create chunk
        chunk = create_reply_chunk(reply_content, reply_id, original_post_id, metadata)

        # Generate embedding
        embedding = generate_embedding(chunk["content"])

        # Save to database
        rowid = save_embedding(
            conn=conn,
            source_type=SOURCE_REPLY,
            content=chunk["content"],
            embedding=embedding,
            source_id=reply_id,
            metadata=chunk["metadata"],
        )

        return rowid
    finally:
        if should_close:
            conn.close()


def get_rag_stats(conn: Optional[sqlite3.Connection] = None) -> dict:
    """
    Get statistics about the RAG vector database.

    Returns:
        Dict with embedding counts by type and total
    """
    should_close = conn is None
    if conn is None:
        conn = get_vector_db_connection()

    try:
        return get_embedding_stats(conn)
    finally:
        if should_close:
            conn.close()


def retrieve_business_context(
    query: str, top_k: int = 5, conn: Optional[sqlite3.Connection] = None
) -> tuple[str, list[dict]]:
    """
    Retrieve context from business documentation only.

    Useful for generating posts that should be grounded in business docs.

    Args:
        query: The search query
        top_k: Number of results to return
        conn: Optional existing database connection

    Returns:
        Tuple of (formatted_context, raw_results)
    """
    return retrieve_context(
        query=query,
        source_types=[SOURCE_BUSINESS_DOC],
        top_k=top_k,
        conn=conn,
    )


def retrieve_post_history(
    query: str, top_k: int = 5, conn: Optional[sqlite3.Connection] = None
) -> tuple[str, list[dict]]:
    """
    Retrieve context from previous posts only.

    Useful for maintaining consistency with past posts.

    Args:
        query: The search query
        top_k: Number of results to return
        conn: Optional existing database connection

    Returns:
        Tuple of (formatted_context, raw_results)
    """
    return retrieve_context(
        query=query,
        source_types=[SOURCE_POST],
        top_k=top_k,
        conn=conn,
    )


def retrieve_all_context(
    query: str, top_k: int = 10, conn: Optional[sqlite3.Connection] = None
) -> tuple[str, list[dict]]:
    """
    Retrieve context from all sources (business docs, posts, replies).

    Args:
        query: The search query
        top_k: Number of results to return
        conn: Optional existing database connection

    Returns:
        Tuple of (formatted_context, raw_results)
    """
    return retrieve_context(
        query=query,
        source_types=None,  # All types
        top_k=top_k,
        conn=conn,
    )
