"""
Document chunking module for RAG system.

This module provides intelligent chunking strategies:
- Business docs: Split by paragraphs, group to ~250-500 tokens, preserve headers
- Posts: No chunking needed (280-500 chars = 1 chunk)
- Replies: No chunking needed (1 reply = 1 chunk)
"""

import re
from typing import Optional

from .notion_client import NotionPage

# Approximate tokens per character (rough estimate for English text)
CHARS_PER_TOKEN = 4
MIN_CHUNK_TOKENS = 250
MAX_CHUNK_TOKENS = 500
MIN_CHUNK_CHARS = MIN_CHUNK_TOKENS * CHARS_PER_TOKEN  # ~1000 chars
MAX_CHUNK_CHARS = MAX_CHUNK_TOKENS * CHARS_PER_TOKEN  # ~2000 chars


def estimate_tokens(text: str) -> int:
    """
    Estimate the number of tokens in a text.

    Uses a simple character-based heuristic (4 chars per token for English).
    """
    return len(text) // CHARS_PER_TOKEN


def split_into_paragraphs(content: str) -> list[str]:
    """
    Split content into paragraphs while preserving meaningful structure.

    Handles:
    - Double newlines as paragraph separators
    - Markdown headers as paragraph boundaries
    - List items grouped with their content
    """
    # Normalize line endings
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # Split on double newlines (paragraph boundaries)
    raw_paragraphs = re.split(r"\n\n+", content)

    paragraphs = []
    for para in raw_paragraphs:
        para = para.strip()
        if para:
            paragraphs.append(para)

    return paragraphs


def extract_headers(content: str) -> dict[str, str]:
    """
    Extract markdown headers from content.

    Returns:
        Dict mapping header level to header text (e.g., {"h1": "Title", "h2": "Section"})
    """
    headers = {}

    # Match h1 headers
    h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if h1_match:
        headers["h1"] = h1_match.group(1).strip()

    # Match h2 headers
    h2_match = re.search(r"^##\s+(.+)$", content, re.MULTILINE)
    if h2_match:
        headers["h2"] = h2_match.group(1).strip()

    return headers


def chunk_business_doc(
    content: str,
    title: str,
    source_id: Optional[str] = None,
    max_tokens: int = MAX_CHUNK_TOKENS,
    min_tokens: int = MIN_CHUNK_TOKENS,
) -> list[dict]:
    """
    Chunk a business document by paragraphs, grouping to reach target token count.

    Strategy:
    1. Split content into paragraphs
    2. Group paragraphs until we reach ~250-500 tokens
    3. Don't split paragraphs (preserve semantic coherence)
    4. Include document title and section headers for context

    Args:
        content: The document content to chunk
        title: Document title (included in each chunk for context)
        source_id: Optional identifier for the source document
        max_tokens: Maximum tokens per chunk (default 500)
        min_tokens: Minimum tokens per chunk (default 250)

    Returns:
        List of chunk dicts with 'content', 'metadata' keys
    """
    max_chars = max_tokens * CHARS_PER_TOKEN
    min_chars = min_tokens * CHARS_PER_TOKEN

    paragraphs = split_into_paragraphs(content)

    if not paragraphs:
        return []

    chunks = []
    current_chunk_parts = []
    current_chunk_chars = 0
    current_section = None

    for para in paragraphs:
        para_chars = len(para)

        # Check if this is a header
        header_match = re.match(r"^(#{1,3})\s+(.+)$", para)
        if header_match:
            current_section = header_match.group(2).strip()

        # If adding this paragraph would exceed max and we have enough content
        if current_chunk_chars + para_chars > max_chars and current_chunk_chars >= min_chars:
            # Save current chunk
            chunk_content = _build_chunk_content(title, current_section, current_chunk_parts)
            chunks.append(
                {
                    "content": chunk_content,
                    "metadata": {
                        "source_id": source_id,
                        "title": title,
                        "section": current_section,
                        "estimated_tokens": estimate_tokens(chunk_content),
                    },
                }
            )
            current_chunk_parts = []
            current_chunk_chars = 0

        # Add paragraph to current chunk
        current_chunk_parts.append(para)
        current_chunk_chars += para_chars

    # Don't forget the last chunk
    if current_chunk_parts:
        chunk_content = _build_chunk_content(title, current_section, current_chunk_parts)
        chunks.append(
            {
                "content": chunk_content,
                "metadata": {
                    "source_id": source_id,
                    "title": title,
                    "section": current_section,
                    "estimated_tokens": estimate_tokens(chunk_content),
                },
            }
        )

    return chunks


def _build_chunk_content(
    title: str, section: Optional[str], paragraphs: list[str]
) -> str:
    """Build the final chunk content with context prefix."""
    parts = []

    # Add title context
    if title:
        parts.append(f"[Document: {title}]")

    # Add section context if available
    if section:
        parts.append(f"[Section: {section}]")

    # Add the actual content
    parts.append("\n\n".join(paragraphs))

    return "\n".join(parts)


def chunk_notion_page(page: NotionPage) -> list[dict]:
    """
    Chunk a Notion page using the business doc strategy.

    Args:
        page: NotionPage object with id, title, content, last_edited_time

    Returns:
        List of chunk dicts ready for embedding
    """
    return chunk_business_doc(
        content=page.content,
        title=page.title,
        source_id=page.id,
    )


def chunk_by_headers(content: str, title: str, source_id: Optional[str] = None) -> list[dict]:
    """
    Alternative chunking strategy: split on ## headers.

    Each chunk includes:
    - The document title for context
    - The section content

    Args:
        content: The document content
        title: Document title
        source_id: Optional source identifier

    Returns:
        List of chunk dicts
    """
    # Split on ## headers
    sections = re.split(r"(?=^##\s+)", content, flags=re.MULTILINE)

    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Extract section title if present
        section_match = re.match(r"^##\s+(.+)$", section, re.MULTILINE)
        section_title = section_match.group(1) if section_match else "Introduction"

        # Build chunk with context
        chunk_content = f"[Document: {title}]\n[Section: {section_title}]\n\n{section}"

        chunks.append(
            {
                "content": chunk_content,
                "metadata": {
                    "source_id": source_id,
                    "title": title,
                    "section": section_title,
                    "estimated_tokens": estimate_tokens(chunk_content),
                },
            }
        )

    # If no sections found, return the whole content as one chunk
    if not chunks:
        chunks.append(
            {
                "content": f"[Document: {title}]\n\n{content}",
                "metadata": {
                    "source_id": source_id,
                    "title": title,
                    "section": None,
                    "estimated_tokens": estimate_tokens(content),
                },
            }
        )

    return chunks


def create_post_chunk(post_content: str, post_id: str, metadata: Optional[dict] = None) -> dict:
    """
    Create a single chunk for a post (no chunking needed).

    Posts are 280-500 characters, which is well within our token limits.

    Args:
        post_content: The post text content
        post_id: Unique identifier for the post
        metadata: Optional additional metadata

    Returns:
        Single chunk dict ready for embedding
    """
    chunk_metadata = {
        "post_id": post_id,
        "estimated_tokens": estimate_tokens(post_content),
    }
    if metadata:
        chunk_metadata.update(metadata)

    return {
        "content": post_content,
        "metadata": chunk_metadata,
    }


def create_reply_chunk(
    reply_content: str,
    reply_id: str,
    original_post_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """
    Create a single chunk for a reply (no chunking needed).

    Args:
        reply_content: The reply text content
        reply_id: Unique identifier for the reply
        original_post_id: ID of the post being replied to
        metadata: Optional additional metadata

    Returns:
        Single chunk dict ready for embedding
    """
    chunk_metadata = {
        "reply_id": reply_id,
        "original_post_id": original_post_id,
        "estimated_tokens": estimate_tokens(reply_content),
    }
    if metadata:
        chunk_metadata.update(metadata)

    return {
        "content": reply_content,
        "metadata": chunk_metadata,
    }
