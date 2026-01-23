from fastapi import APIRouter, HTTPException, Query

from ..schemas import AutomationResponse
from workshop1 import makePosts, replyPosts

router = APIRouter(prefix="/automation", tags=["automation"])


@router.post("/make-posts", response_model=AutomationResponse)
async def trigger_make_posts():
    """
    Trigger the makePosts automation script.

    This will:
    - Load Notion pages
    - Generate posts for updated pages
    - Request approval via Telegram
    - Post to Mastodon after approval

    Returns immediately after completion (may take time if waiting for Telegram approval).
    """
    try:
        posts_made = await makePosts.async_main()

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
):
    """
    Trigger the replyPosts automation script.

    This will:
    - Search Mastodon for posts matching keywords
    - Generate replies for found posts
    - Request approval via Telegram
    - Post replies to Mastodon after approval

    Args:
        keywords: Comma-separated keywords to search for

    Returns immediately after completion (may take time if waiting for Telegram approval).
    """
    try:
        # Parse keywords
        keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

        if not keyword_list:
            raise HTTPException(
                status_code=400, detail="At least one keyword must be provided"
            )

        replies_made = await replyPosts.async_main_with_keywords(keyword_list)

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
