import asyncio
import json
from datetime import datetime
from pathlib import Path

from .notion_client import fetch_parent_page, fetch_child_pages, NotionPage
from .mastodon_client import post_status, upload_media
from .llm import generate_post, generate_image_prompt
from .replicate_client import generate_image
from .telegram_client import request_approval, store_rejection, Decision

STATE_FILE = Path(".workshop1_state.json")


def load_state() -> dict:
    """Load the state file tracking posted pages."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"pages": {}}


def save_state(state: dict) -> None:
    """Save the state file."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def is_page_updated(page: NotionPage, state: dict) -> bool:
    """Check if a page has been updated since last post."""
    page_state = state["pages"].get(page.id)

    if page_state is None:
        # New page, never posted
        return True

    last_edited = page.last_edited_time.isoformat()
    stored_edited = page_state.get("last_edited_time", "")

    return last_edited > stored_edited


def print_preview(post_content: str, page: NotionPage) -> None:
    """Print a formatted preview of the post."""
    print("\n" + "=" * 60)
    print(f"📄 Source: {page.title}")
    print("=" * 60)
    print("\n📝 Generated Post:\n")
    print("-" * 40)
    print(post_content)
    print("-" * 40)
    print(f"\n📊 Character count: {len(post_content)}/500")
    print()


async def process_post(
    post_content: str,
    page: NotionPage,
    state: dict,
) -> bool:
    """
    Process a single post through Telegram approval workflow.

    Returns True if post was made, False otherwise.
    """
    # Request approval via Telegram
    context_info = f"📄 Source: {page.title}"
    result = await request_approval(
        content=post_content,
        context_info=context_info,
        content_type="post",
    )

    # Determine which content to post (original or edited)
    if result.decision == Decision.ACCEPT:
        content_to_post = post_content
        print("✅ Post approved!")
    elif result.decision == Decision.EDIT:
        content_to_post = result.edited_content
        print(f"✏️ Post edited! New content: {content_to_post[:100]}...")
    elif result.decision == Decision.REJECT:
        # Store the rejection feedback
        store_rejection(
            original_content=post_content,
            feedback=result.feedback or "No reason provided",
            content_type="post",
            page_title=page.title,
        )
        print(f"❌ Post rejected. Feedback: {result.feedback}")
        return False
    else:
        print("⏭️ Skipped.")
        return False

    # Generate image and post
    try:
        # Generate image prompt based on the content we're posting
        print("\n🎨 Generating image prompt...")
        image_prompt = generate_image_prompt(content_to_post)
        print(f"📝 Image prompt: {image_prompt}")

        # Generate image
        print("🖼️  Generating image...")
        image_url = generate_image(image_prompt)
        print(f"✅ Image generated: {image_url}")

        # Upload to Mastodon
        media_id = upload_media(image_url)

        # Post with media
        result = post_status(content_to_post, media_ids=[media_id])
        print(f"✅ Posted! URL: {result.url}")

        # Update state
        state["pages"][page.id] = {
            "title": page.title,
            "last_edited_time": page.last_edited_time.isoformat(),
            "last_posted_time": datetime.now().isoformat(),
        }
        save_state(state)
        return True

    except Exception as e:
        print(f"❌ Error posting to Mastodon: {e}")
        # If image generation fails, try posting text-only as fallback
        print("⚠️  Attempting to post text-only as fallback...")
        try:
            result = post_status(content_to_post)
            print(f"✅ Posted (text-only)! URL: {result.url}")
            state["pages"][page.id] = {
                "title": page.title,
                "last_edited_time": page.last_edited_time.isoformat(),
                "last_posted_time": datetime.now().isoformat(),
            }
            save_state(state)
            return True
        except Exception as fallback_error:
            print(f"❌ Fallback post also failed: {fallback_error}")
            return False


async def async_main() -> int:
    """
    Async main entry point for generating posts from Notion updates.

    Returns:
        Number of posts made
    """
    print("🔄 Loading Notion pages...")

    # Load business description (parent page)
    try:
        parent_page = fetch_parent_page()
        print(f"✅ Loaded business description: {parent_page.title}")
    except Exception as e:
        print(f"❌ Error loading parent page: {e}")
        return 0

    business_context = parent_page.content

    # Load child pages
    try:
        child_pages = fetch_child_pages()
        print(f"✅ Found {len(child_pages)} child pages")
    except Exception as e:
        print(f"❌ Error loading child pages: {e}")
        return 0

    if not child_pages:
        print("ℹ️  No child pages found.")
        return 0

    # Load state
    state = load_state()

    # Find updated pages
    updated_pages = [p for p in child_pages if is_page_updated(p, state)]

    if not updated_pages:
        print("ℹ️  No new or updated pages since last run.")
        return 0

    print(f"\n📬 Found {len(updated_pages)} page(s) with updates:\n")
    for page in updated_pages:
        print(f"  • {page.title}")

    # Process each updated page
    posts_made = 0

    for page in updated_pages:
        print(f"\n🤖 Generating post for: {page.title}...")

        try:
            post_content = generate_post(
                business_context=business_context,
                page_content=page.content,
                page_title=page.title,
            )
        except Exception as e:
            print(f"❌ Error generating post: {e}")
            continue

        print_preview(post_content, page)

        # Process through Telegram approval
        if await process_post(post_content, page, state):
            posts_made += 1

    print(f"\n🎉 Done! Made {posts_made} post(s).")
    return posts_made


def main() -> None:
    """Main entry point - runs the async main function."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
