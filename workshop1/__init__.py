"""
Workshop 1: Social Media Automation with RAG

This package provides:
- Notion integration for content management
- Mastodon integration for social media posting
- RAG (Retrieval-Augmented Generation) for context-aware content
- Automated listeners for document updates and mentions
"""

__all__ = [
    # Core modules
    "config",
    "llm",
    "notion_client",
    "mastodon_client",
    "replicate_client",
    "telegram_client",
    # RAG modules
    "vector_db",
    "chunker",
    "rag",
    # Workflow modules
    "makePosts",
    "replyPosts",
    # Listener modules
    "notion_listener",
    "mastodon_listener",
]
