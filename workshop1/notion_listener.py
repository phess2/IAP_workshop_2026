"""
Notion listener module for auto-posting on document changes.

This module monitors Notion for document updates and automatically:
1. Re-embeds changed documents in the vector database
2. Retrieves RAG context for post generation
3. Generates and posts content (with optional approval workflow)
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import settings
from .llm import generate_image_prompt, generate_post_with_rag
from .mastodon_client import post_status, upload_media
from .notion_client import NotionPage, fetch_child_pages, fetch_parent_page
from .rag import embed_single_notion_page, retrieve_business_context
from .replicate_client import generate_image
from .telegram_client import request_approval

# State file for tracking last sync times
STATE_FILE = Path(settings.database_dir) / ".notion_listener_state.json"


def load_listener_state() -> dict:
    """Load the listener state from file."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_sync": None, "page_timestamps": {}}


def save_listener_state(state: dict) -> None:
    """Save the listener state to file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def check_notion_updates() -> list[NotionPage]:
    """
    Check for Notion pages that have been updated since last sync.

    Returns:
        List of NotionPage objects that have been updated
    """
    state = load_listener_state()
    page_timestamps = state.get("page_timestamps", {})

    updated_pages = []

    # Check parent page
    try:
        parent_page = fetch_parent_page()
        last_known = page_timestamps.get(parent_page.id)
        if last_known is None or parent_page.last_edited_time.isoformat() > last_known:
            updated_pages.append(parent_page)
    except Exception as e:
        print(f"Error fetching parent page: {e}")

    # Check child pages
    try:
        child_pages = fetch_child_pages()
        for page in child_pages:
            last_known = page_timestamps.get(page.id)
            if last_known is None or page.last_edited_time.isoformat() > last_known:
                updated_pages.append(page)
    except Exception as e:
        print(f"Error fetching child pages: {e}")

    return updated_pages


def update_page_timestamp(page_id: str, timestamp: datetime) -> None:
    """Update the stored timestamp for a page."""
    state = load_listener_state()
    if "page_timestamps" not in state:
        state["page_timestamps"] = {}
    state["page_timestamps"][page_id] = timestamp.isoformat()
    state["last_sync"] = datetime.now().isoformat()
    save_listener_state(state)


async def process_doc_update(
    page: NotionPage,
    auto_post: bool = False,
    generate_images: bool = True,
) -> Optional[dict]:
    """
    Process a document update: re-embed and optionally generate a post.

    Args:
        page: The updated NotionPage
        auto_post: If True, post without approval. If False, request approval via Telegram.
        generate_images: If True, generate images for posts

    Returns:
        Dict with post details if successful, None otherwise
    """
    print(f"Processing update for page: {page.title}")

    # Step 1: Re-embed the document
    try:
        chunks_created = embed_single_notion_page(page)
        print(f"  Re-embedded {chunks_created} chunks")
    except Exception as e:
        print(f"  Error embedding page: {e}")
        return None

    # Step 2: Retrieve RAG context
    try:
        # Use the page title and a snippet of content as the query
        query = f"{page.title} {page.content[:200]}"
        rag_context, _ = retrieve_business_context(query, top_k=5)
    except Exception as e:
        print(f"  Error retrieving RAG context: {e}")
        rag_context = "No additional context available."

    # Step 3: Generate post content
    try:
        post_content = generate_post_with_rag(
            rag_context=rag_context,
            page_content=page.content,
            page_title=page.title,
        )
        print(f"  Generated post ({len(post_content)} chars)")
    except Exception as e:
        print(f"  Error generating post: {e}")
        return None

    # Step 4: Request approval or auto-post
    if not auto_post:
        try:
            approval_result = await request_approval(
                content_type="post",
                content=post_content,
                source_title=page.title,
            )

            if approval_result["action"] == "reject":
                print(f"  Post rejected: {approval_result.get('feedback', 'No feedback')}")
                update_page_timestamp(page.id, page.last_edited_time)
                return None
            elif approval_result["action"] == "edit":
                post_content = approval_result["edited_content"]
                print(f"  Post edited, new length: {len(post_content)} chars")
        except Exception as e:
            print(f"  Error requesting approval: {e}")
            return None

    # Step 5: Generate image (optional)
    media_id = None
    if generate_images:
        try:
            image_prompt = generate_image_prompt(post_content)
            image_url = generate_image(image_prompt)
            if image_url:
                media_id = upload_media(image_url, description=f"AI-generated image for: {page.title}")
                print(f"  Generated and uploaded image")
        except Exception as e:
            print(f"  Image generation failed (continuing without image): {e}")

    # Step 6: Post to Mastodon
    try:
        media_ids = [media_id] if media_id else None
        posted = post_status(post_content, media_ids=media_ids)
        print(f"  Posted to Mastodon: {posted.url}")

        # Update timestamp after successful post
        update_page_timestamp(page.id, page.last_edited_time)

        return {
            "page_id": page.id,
            "page_title": page.title,
            "post_content": post_content,
            "mastodon_url": posted.url,
            "mastodon_id": posted.id,
            "has_image": media_id is not None,
        }
    except Exception as e:
        print(f"  Error posting to Mastodon: {e}")
        return None


async def run_notion_listener(
    interval_seconds: Optional[int] = None,
    auto_post: bool = False,
    generate_images: bool = True,
    max_iterations: Optional[int] = None,
) -> None:
    """
    Run the Notion listener in a polling loop.

    Args:
        interval_seconds: Seconds between checks (defaults to settings.notion_poll_interval)
        auto_post: If True, post without approval
        generate_images: If True, generate images for posts
        max_iterations: If set, stop after this many iterations (useful for testing)
    """
    if interval_seconds is None:
        interval_seconds = settings.notion_poll_interval

    print(f"Starting Notion listener (interval: {interval_seconds}s, auto_post: {auto_post})")

    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        iteration += 1
        print(f"\n[{datetime.now().isoformat()}] Checking for Notion updates...")

        try:
            updated_pages = check_notion_updates()

            if updated_pages:
                print(f"Found {len(updated_pages)} updated page(s)")
                for page in updated_pages:
                    result = await process_doc_update(
                        page=page,
                        auto_post=auto_post,
                        generate_images=generate_images,
                    )
                    if result:
                        # Import here to avoid circular imports
                        from .rag import embed_post

                        # Store the post in vector DB for future retrieval
                        try:
                            embed_post(
                                post_content=result["post_content"],
                                post_id=result["mastodon_id"],
                                metadata={
                                    "mastodon_url": result["mastodon_url"],
                                    "page_title": result["page_title"],
                                },
                            )
                            print(f"  Stored post in vector DB")
                        except Exception as e:
                            print(f"  Error storing post in vector DB: {e}")
            else:
                print("No updates found")

        except Exception as e:
            print(f"Error in listener iteration: {e}")

        if max_iterations is None or iteration < max_iterations:
            print(f"Sleeping for {interval_seconds} seconds...")
            await asyncio.sleep(interval_seconds)

    print("Notion listener stopped")


def run_notion_listener_sync(
    interval_seconds: Optional[int] = None,
    auto_post: bool = False,
    generate_images: bool = True,
    max_iterations: Optional[int] = None,
) -> None:
    """
    Synchronous wrapper for run_notion_listener.

    Use this when you need to run the listener from a non-async context.
    """
    asyncio.run(
        run_notion_listener(
            interval_seconds=interval_seconds,
            auto_post=auto_post,
            generate_images=generate_images,
            max_iterations=max_iterations,
        )
    )


async def process_all_pages_once(
    auto_post: bool = False,
    generate_images: bool = True,
) -> list[dict]:
    """
    Process all Notion pages once (useful for initial setup or manual trigger).

    This will embed all pages and optionally generate posts for any that
    haven't been posted yet.

    Args:
        auto_post: If True, post without approval
        generate_images: If True, generate images for posts

    Returns:
        List of post result dicts
    """
    results = []

    # Get all pages
    try:
        parent_page = fetch_parent_page()
        pages = [parent_page] + fetch_child_pages()
    except Exception as e:
        print(f"Error fetching pages: {e}")
        return results

    print(f"Processing {len(pages)} page(s)...")

    for page in pages:
        result = await process_doc_update(
            page=page,
            auto_post=auto_post,
            generate_images=generate_images,
        )
        if result:
            results.append(result)

            # Store in vector DB
            from .rag import embed_post

            try:
                embed_post(
                    post_content=result["post_content"],
                    post_id=result["mastodon_id"],
                    metadata={
                        "mastodon_url": result["mastodon_url"],
                        "page_title": result["page_title"],
                    },
                )
            except Exception as e:
                print(f"Error storing post in vector DB: {e}")

    return results
