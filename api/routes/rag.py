"""
RAG (Retrieval-Augmented Generation) API routes.

Provides endpoints for:
- Embedding documents from Notion
- Searching the vector database
- Getting RAG statistics
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/rag", tags=["rag"])


class RAGStatsResponse(BaseModel):
    """Response model for RAG statistics."""

    total_embeddings: int = Field(..., description="Total number of embeddings")
    by_type: dict[str, int] = Field(..., description="Counts by source type")


class EmbedDocsResponse(BaseModel):
    """Response model for embedding documents."""

    status: str
    pages_processed: int = Field(..., description="Number of pages processed")
    chunks_created: int = Field(..., description="Number of chunks created")
    previous_chunks_deleted: int = Field(
        0, description="Number of previous chunks deleted"
    )
    errors: list[str] = Field(default_factory=list, description="Any errors encountered")


class SearchResult(BaseModel):
    """A single search result."""

    id: int
    content: str
    source_type: str
    source_id: str | None
    final_score: float
    bm25_score: float
    semantic_score: float
    metadata: dict


class SearchResponse(BaseModel):
    """Response model for search queries."""

    query: str
    results: list[SearchResult]
    total_results: int


@router.get("/stats", response_model=RAGStatsResponse)
async def get_rag_stats():
    """
    Get statistics about the RAG vector database.

    Returns counts of embeddings by source type (business_doc, post, reply).
    """
    try:
        from workshop1.rag import get_rag_stats

        stats = get_rag_stats()
        return RAGStatsResponse(
            total_embeddings=stats["total"],
            by_type=stats["by_type"],
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error getting RAG stats: {str(e)}"
        )


@router.post("/embed-docs", response_model=EmbedDocsResponse)
async def embed_notion_docs():
    """
    Trigger re-embedding of all Notion documents.

    This will:
    1. Delete existing business_doc embeddings
    2. Fetch all Notion pages (parent and children)
    3. Chunk and embed each document

    Use this to refresh the RAG knowledge base after manual Notion updates.
    """
    try:
        from workshop1.rag import embed_notion_docs

        stats = embed_notion_docs()
        return EmbedDocsResponse(
            status="success",
            pages_processed=stats.get("pages_processed", 0),
            chunks_created=stats.get("chunks_created", 0),
            previous_chunks_deleted=stats.get("previous_chunks_deleted", 0),
            errors=stats.get("errors", []),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error embedding documents: {str(e)}"
        )


@router.get("/search", response_model=SearchResponse)
async def search_rag(
    query: str = Query(..., description="Search query"),
    top_k: int = Query(10, ge=1, le=50, description="Number of results to return"),
    source_types: str | None = Query(
        None,
        description="Comma-separated source types to filter (business_doc,post,reply)",
    ),
):
    """
    Search the RAG vector database using hybrid search.

    Combines BM25 keyword search with semantic vector search.

    Args:
        query: The search query text
        top_k: Number of results to return (1-50)
        source_types: Optional filter for source types

    Returns:
        Search results with relevance scores
    """
    try:
        from workshop1.rag import retrieve_context
        from workshop1.vector_db import generate_embedding, hybrid_search, init_vector_db

        # Parse source types if provided
        types_list = None
        if source_types:
            types_list = [t.strip() for t in source_types.split(",") if t.strip()]

        # Get results
        _, results = retrieve_context(
            query=query,
            source_types=types_list,
            top_k=top_k,
        )

        return SearchResponse(
            query=query,
            results=[SearchResult(**r) for r in results],
            total_results=len(results),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error searching RAG: {str(e)}"
        )


@router.delete("/embeddings/{source_type}")
async def delete_embeddings_by_type(
    source_type: str,
    source_id: str | None = Query(None, description="Optional specific source ID"),
):
    """
    Delete embeddings by source type.

    Args:
        source_type: Type of embeddings to delete (business_doc, post, reply)
        source_id: Optional specific source ID to delete

    Returns:
        Number of embeddings deleted
    """
    valid_types = ["business_doc", "post", "reply"]
    if source_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source_type. Must be one of: {valid_types}",
        )

    try:
        from workshop1.vector_db import delete_embeddings_by_source, init_vector_db

        conn = init_vector_db()
        try:
            deleted = delete_embeddings_by_source(conn, source_type, source_id)
            return {
                "status": "success",
                "deleted_count": deleted,
                "source_type": source_type,
                "source_id": source_id,
            }
        finally:
            conn.close()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error deleting embeddings: {str(e)}"
        )
