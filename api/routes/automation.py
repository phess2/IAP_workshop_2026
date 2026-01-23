import asyncio
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from ..schemas import AutomationResponse
from workshop1 import makePosts, replyPosts

router = APIRouter(prefix="/automation", tags=["automation"])

# Global state for tracking running listeners
_listener_tasks: dict[str, asyncio.Task] = {}


class ListenerStatus(BaseModel):
    """Status of a listener."""

    running: bool
    listener_type: str
    message: str


class ListenerConfig(BaseModel):
    """Configuration for starting a listener."""

    auto_approve: bool = Field(False, description="Auto-approve without Telegram")
    generate_images: bool = Field(True, description="Generate images for posts (Notion listener only)")
    min_relevance: float = Field(0.3, ge=0.0, le=1.0, description="Minimum relevance for replies (Mastodon listener only)")


@router.post("/make-posts", response_model=AutomationResponse)
async def trigger_make_posts(
    use_rag: bool = Query(True, description="Use RAG-enhanced post generation"),
):
    """
    Trigger the makePosts automation script.

    This will:
    - Load Notion pages
    - Embed documents for RAG (if enabled)
    - Generate posts for updated pages using RAG context
    - Request approval via Telegram
    - Post to Mastodon after approval
    - Store posts in vector database

    Args:
        use_rag: If True, use RAG-enhanced post generation

    Returns immediately after completion (may take time if waiting for Telegram approval).
    """
    try:
        posts_made = await makePosts.async_main(use_rag=use_rag)

        return AutomationResponse(
            status="success",
            message=f"Automation completed successfully. Made {posts_made} post(s).",
            posts_made=posts_made,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error running makePosts automation: {str(e)}"
        )


@router.post("/reply-posts", response_model=AutomationResponse)
async def trigger_reply_posts(
    keywords: str = Query(
        ...,
        description="Comma-separated keywords to search for (e.g., 'AI,startup,tech')",
    ),
    use_rag: bool = Query(True, description="Use RAG-enhanced reply generation"),
):
    """
    Trigger the replyPosts automation script.

    This will:
    - Search Mastodon for posts matching keywords
    - Generate replies using RAG context (if enabled)
    - Request approval via Telegram
    - Post replies to Mastodon after approval
    - Store replies in vector database

    Args:
        keywords: Comma-separated keywords to search for
        use_rag: If True, use RAG-enhanced reply generation

    Returns immediately after completion (may take time if waiting for Telegram approval).
    """
    try:
        # Parse keywords
        keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

        if not keyword_list:
            raise HTTPException(
                status_code=400, detail="At least one keyword must be provided"
            )

        replies_made = await replyPosts.async_main_with_keywords(keyword_list, use_rag=use_rag)

        return AutomationResponse(
            status="success",
            message=f"Automation completed successfully. Made {replies_made} reply(ies).",
            replies_made=replies_made,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error running replyPosts automation: {str(e)}"
        )


@router.post("/notion-listener/start", response_model=ListenerStatus)
async def start_notion_listener(
    background_tasks: BackgroundTasks,
    config: Optional[ListenerConfig] = None,
):
    """
    Start the Notion listener in the background.

    The listener polls Notion for document updates and automatically:
    - Re-embeds changed documents
    - Generates posts using RAG context
    - Posts to Mastodon (with or without approval)

    Args:
        config: Optional configuration for the listener
    """
    if "notion" in _listener_tasks and not _listener_tasks["notion"].done():
        return ListenerStatus(
            running=True,
            listener_type="notion",
            message="Notion listener is already running",
        )

    config = config or ListenerConfig()

    async def run_listener():
        from workshop1.notion_listener import run_notion_listener

        await run_notion_listener(
            auto_post=config.auto_approve,
            generate_images=config.generate_images,
        )

    task = asyncio.create_task(run_listener())
    _listener_tasks["notion"] = task

    return ListenerStatus(
        running=True,
        listener_type="notion",
        message="Notion listener started in background",
    )


@router.post("/notion-listener/stop", response_model=ListenerStatus)
async def stop_notion_listener():
    """Stop the Notion listener if running."""
    if "notion" not in _listener_tasks or _listener_tasks["notion"].done():
        return ListenerStatus(
            running=False,
            listener_type="notion",
            message="Notion listener is not running",
        )

    _listener_tasks["notion"].cancel()
    try:
        await _listener_tasks["notion"]
    except asyncio.CancelledError:
        pass

    return ListenerStatus(
        running=False,
        listener_type="notion",
        message="Notion listener stopped",
    )


@router.get("/notion-listener/status", response_model=ListenerStatus)
async def get_notion_listener_status():
    """Get the status of the Notion listener."""
    running = "notion" in _listener_tasks and not _listener_tasks["notion"].done()
    return ListenerStatus(
        running=running,
        listener_type="notion",
        message="Notion listener is running" if running else "Notion listener is not running",
    )


@router.post("/mastodon-listener/start", response_model=ListenerStatus)
async def start_mastodon_listener(
    background_tasks: BackgroundTasks,
    config: Optional[ListenerConfig] = None,
):
    """
    Start the Mastodon listener in the background.

    The listener polls Mastodon for mentions and automatically:
    - Retrieves RAG context based on mention content
    - Generates contextually relevant replies
    - Posts replies (with or without approval)

    Args:
        config: Optional configuration for the listener
    """
    if "mastodon" in _listener_tasks and not _listener_tasks["mastodon"].done():
        return ListenerStatus(
            running=True,
            listener_type="mastodon",
            message="Mastodon listener is already running",
        )

    config = config or ListenerConfig()

    async def run_listener():
        from workshop1.mastodon_listener import run_mastodon_listener

        await run_mastodon_listener(
            auto_reply=config.auto_approve,
            min_relevance=config.min_relevance,
        )

    task = asyncio.create_task(run_listener())
    _listener_tasks["mastodon"] = task

    return ListenerStatus(
        running=True,
        listener_type="mastodon",
        message="Mastodon listener started in background",
    )


@router.post("/mastodon-listener/stop", response_model=ListenerStatus)
async def stop_mastodon_listener():
    """Stop the Mastodon listener if running."""
    if "mastodon" not in _listener_tasks or _listener_tasks["mastodon"].done():
        return ListenerStatus(
            running=False,
            listener_type="mastodon",
            message="Mastodon listener is not running",
        )

    _listener_tasks["mastodon"].cancel()
    try:
        await _listener_tasks["mastodon"]
    except asyncio.CancelledError:
        pass

    return ListenerStatus(
        running=False,
        listener_type="mastodon",
        message="Mastodon listener stopped",
    )


@router.get("/mastodon-listener/status", response_model=ListenerStatus)
async def get_mastodon_listener_status():
    """Get the status of the Mastodon listener."""
    running = "mastodon" in _listener_tasks and not _listener_tasks["mastodon"].done()
    return ListenerStatus(
        running=running,
        listener_type="mastodon",
        message="Mastodon listener is running" if running else "Mastodon listener is not running",
    )
