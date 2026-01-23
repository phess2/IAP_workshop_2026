"""
Mastodon listener module for auto-replying to mentions and comments.

This module monitors Mastodon for mentions/replies and automatically:
1. Retrieves RAG context based on the mention content
2. Generates contextually relevant replies
3. Posts replies (with optional approval workflow)
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from .config import settings
from .llm import generate_reply_with_rag
from .mastodon_client import MastodonPost, reply_to_status
from .rag import embed_reply, retrieve_all_context
from .telegram_client import request_approval

# State file for tracking last processed notification
STATE_FILE = Path(settings.database_dir) / ".mastodon_listener_state.json"


def load_listener_state() -> dict:
    """Load the listener state from file."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_notification_id": None, "processed_notifications": []}


def save_listener_state(state: dict) -> None:
    """Save the listener state to file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def _get_headers() -> dict:
    """Get authorization headers for Mastodon API."""
    return {"Authorization": f"Bearer {settings.mastodon_access_token}"}


def _strip_html(html: str) -> str:
    """Strip HTML tags from content."""
    import re

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_notifications(
    since_id: Optional[str] = None,
    notification_types: Optional[list[str]] = None,
    limit: int = 20,
) -> list[dict]:
    """
    Fetch notifications from Mastodon API.

    Args:
        since_id: Only fetch notifications newer than this ID
        notification_types: Filter by types (mention, reblog, favourite, follow, etc.)
        limit: Maximum notifications to fetch

    Returns:
        List of notification dicts
    """
    base_url = settings.mastodon_base_url.rstrip("/")
    headers = _get_headers()

    params = {"limit": limit}
    if since_id:
        params["since_id"] = since_id
    if notification_types:
        params["types[]"] = notification_types

    response = httpx.get(
        f"{base_url}/api/v1/notifications",
        headers=headers,
        params=params,
        timeout=30.0,
    )
    response.raise_for_status()

    return response.json()


def fetch_status_context(status_id: str) -> dict:
    """
    Fetch the context (ancestors and descendants) of a status.

    Useful for understanding the conversation thread.

    Args:
        status_id: The Mastodon status ID

    Returns:
        Dict with 'ancestors' and 'descendants' lists
    """
    base_url = settings.mastodon_base_url.rstrip("/")
    headers = _get_headers()

    response = httpx.get(
        f"{base_url}/api/v1/statuses/{status_id}/context",
        headers=headers,
        timeout=30.0,
    )
    response.raise_for_status()

    return response.json()


def parse_notification(notification: dict) -> Optional[dict]:
    """
    Parse a notification into a structured format for processing.

    Args:
        notification: Raw notification dict from Mastodon API

    Returns:
        Parsed notification dict or None if not processable
    """
    notification_type = notification.get("type")
    status = notification.get("status")
    account = notification.get("account", {})

    if notification_type != "mention" or not status:
        return None

    return {
        "id": notification.get("id"),
        "type": notification_type,
        "created_at": notification.get("created_at"),
        "status_id": status.get("id"),
        "status_content": _strip_html(status.get("content", "")),
        "status_url": status.get("url"),
        "author_id": account.get("id"),
        "author_handle": f"@{account.get('acct', 'unknown')}",
        "author_display_name": account.get("display_name", "Unknown"),
        "in_reply_to_id": status.get("in_reply_to_id"),
    }


async def process_mention(
    notification: dict,
    auto_reply: bool = False,
    min_relevance: float = 0.3,
) -> Optional[dict]:
    """
    Process a mention notification: retrieve context and generate reply.

    Args:
        notification: Parsed notification dict
        auto_reply: If True, reply without approval
        min_relevance: Minimum relevance score to reply (0.0-1.0)

    Returns:
        Dict with reply details if successful, None otherwise
    """
    print(f"Processing mention from {notification['author_handle']}")
    print(f"  Content: {notification['status_content'][:100]}...")

    # Step 1: Retrieve RAG context based on the mention content
    try:
        query = notification["status_content"]
        rag_context, search_results = retrieve_all_context(query, top_k=5)

        # Calculate average relevance from search results
        if search_results:
            avg_relevance = sum(r["final_score"] for r in search_results) / len(
                search_results
            )
        else:
            avg_relevance = 0.0

        print(f"  RAG relevance: {avg_relevance:.2f}")

        # Skip if not relevant enough
        if avg_relevance < min_relevance and not auto_reply:
            print(f"  Skipping: relevance ({avg_relevance:.2f}) below threshold ({min_relevance})")
            return None

    except Exception as e:
        print(f"  Error retrieving RAG context: {e}")
        rag_context = "No additional context available."

    # Step 2: Generate reply content
    try:
        reply_content = generate_reply_with_rag(
            rag_context=rag_context,
            post_content=notification["status_content"],
            post_author=notification["author_display_name"],
        )
        print(f"  Generated reply ({len(reply_content)} chars)")
    except Exception as e:
        print(f"  Error generating reply: {e}")
        return None

    # Step 3: Request approval or auto-reply
    if not auto_reply:
        try:
            approval_result = await request_approval(
                content_type="reply",
                content=reply_content,
                source_title=f"Reply to {notification['author_handle']}",
                original_content=notification["status_content"],
            )

            if approval_result["action"] == "reject":
                print(f"  Reply rejected: {approval_result.get('feedback', 'No feedback')}")
                return None
            elif approval_result["action"] == "edit":
                reply_content = approval_result["edited_content"]
                print(f"  Reply edited, new length: {len(reply_content)} chars")
        except Exception as e:
            print(f"  Error requesting approval: {e}")
            return None

    # Step 4: Post reply to Mastodon
    try:
        posted = reply_to_status(
            status_id=notification["status_id"],
            content=reply_content,
        )
        print(f"  Posted reply: {posted.url}")

        return {
            "notification_id": notification["id"],
            "original_status_id": notification["status_id"],
            "original_content": notification["status_content"],
            "author_handle": notification["author_handle"],
            "reply_content": reply_content,
            "mastodon_url": posted.url,
            "mastodon_id": posted.id,
        }
    except Exception as e:
        print(f"  Error posting reply: {e}")
        return None


async def run_mastodon_listener(
    interval_seconds: Optional[int] = None,
    auto_reply: bool = False,
    min_relevance: float = 0.3,
    max_iterations: Optional[int] = None,
) -> None:
    """
    Run the Mastodon listener in a polling loop.

    Args:
        interval_seconds: Seconds between checks (defaults to settings.mastodon_poll_interval)
        auto_reply: If True, reply without approval
        min_relevance: Minimum relevance score to reply
        max_iterations: If set, stop after this many iterations (useful for testing)
    """
    if interval_seconds is None:
        interval_seconds = settings.mastodon_poll_interval

    print(f"Starting Mastodon listener (interval: {interval_seconds}s, auto_reply: {auto_reply})")

    state = load_listener_state()
    last_notification_id = state.get("last_notification_id")

    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        iteration += 1
        print(f"\n[{datetime.now().isoformat()}] Checking for Mastodon notifications...")

        try:
            # Fetch new notifications
            notifications = fetch_notifications(
                since_id=last_notification_id,
                notification_types=["mention"],
            )

            if notifications:
                print(f"Found {len(notifications)} new notification(s)")

                # Process from oldest to newest
                for notif in reversed(notifications):
                    parsed = parse_notification(notif)
                    if not parsed:
                        continue

                    result = await process_mention(
                        notification=parsed,
                        auto_reply=auto_reply,
                        min_relevance=min_relevance,
                    )

                    if result:
                        # Store the reply in vector DB for future retrieval
                        try:
                            embed_reply(
                                reply_content=result["reply_content"],
                                reply_id=result["mastodon_id"],
                                original_post_id=result["original_status_id"],
                                metadata={
                                    "mastodon_url": result["mastodon_url"],
                                    "author_handle": result["author_handle"],
                                },
                            )
                            print(f"  Stored reply in vector DB")
                        except Exception as e:
                            print(f"  Error storing reply in vector DB: {e}")

                    # Update last processed ID
                    last_notification_id = notif["id"]
                    state["last_notification_id"] = last_notification_id
                    save_listener_state(state)
            else:
                print("No new notifications")

        except Exception as e:
            print(f"Error in listener iteration: {e}")

        if max_iterations is None or iteration < max_iterations:
            print(f"Sleeping for {interval_seconds} seconds...")
            await asyncio.sleep(interval_seconds)

    print("Mastodon listener stopped")


def run_mastodon_listener_sync(
    interval_seconds: Optional[int] = None,
    auto_reply: bool = False,
    min_relevance: float = 0.3,
    max_iterations: Optional[int] = None,
) -> None:
    """
    Synchronous wrapper for run_mastodon_listener.

    Use this when you need to run the listener from a non-async context.
    """
    asyncio.run(
        run_mastodon_listener(
            interval_seconds=interval_seconds,
            auto_reply=auto_reply,
            min_relevance=min_relevance,
            max_iterations=max_iterations,
        )
    )


async def process_recent_mentions(
    limit: int = 10,
    auto_reply: bool = False,
    min_relevance: float = 0.3,
) -> list[dict]:
    """
    Process recent mentions (useful for manual trigger or catch-up).

    Args:
        limit: Maximum mentions to process
        auto_reply: If True, reply without approval
        min_relevance: Minimum relevance score to reply

    Returns:
        List of reply result dicts
    """
    results = []

    try:
        notifications = fetch_notifications(
            notification_types=["mention"],
            limit=limit,
        )
    except Exception as e:
        print(f"Error fetching notifications: {e}")
        return results

    print(f"Processing {len(notifications)} recent mention(s)...")

    for notif in reversed(notifications):  # Process oldest first
        parsed = parse_notification(notif)
        if not parsed:
            continue

        result = await process_mention(
            notification=parsed,
            auto_reply=auto_reply,
            min_relevance=min_relevance,
        )

        if result:
            results.append(result)

            # Store in vector DB
            try:
                embed_reply(
                    reply_content=result["reply_content"],
                    reply_id=result["mastodon_id"],
                    original_post_id=result["original_status_id"],
                    metadata={
                        "mastodon_url": result["mastodon_url"],
                        "author_handle": result["author_handle"],
                    },
                )
            except Exception as e:
                print(f"Error storing reply in vector DB: {e}")

    return results


def get_account_mentions_count() -> int:
    """
    Get the count of unread mentions.

    Returns:
        Number of unread mentions
    """
    state = load_listener_state()
    last_id = state.get("last_notification_id")

    try:
        notifications = fetch_notifications(
            since_id=last_id,
            notification_types=["mention"],
            limit=100,
        )
        return len(notifications)
    except Exception:
        return 0
