import argparse
import asyncio

from pydantic import BaseModel

from .notion_client import fetch_parent_page
from .mastodon_client import search_posts, reply_to_status, MastodonPost
from .llm import generate_replies_batch, LLMReplyResponse
from .telegram_client import request_approval, store_rejection, Decision

# Number of posts to search for and generate replies to
BATCH_SIZE = 5

# Minimum relevance score to include a reply for approval
MIN_RELEVANCE_SCORE = 0.3


class GeneratedReply(BaseModel):
    """Full reply with original post data and LLM response metadata."""

    post: MastodonPost
    response_text: str
    is_company_related: bool
    relevance_score: float
    reasoning: str

    @classmethod
    def from_post_and_llm_response(
        cls, post: MastodonPost, llm_response: LLMReplyResponse
    ) -> "GeneratedReply":
        """Create a GeneratedReply from a post and LLM response."""
        return cls(
            post=post,
            response_text=llm_response.response_text,
            is_company_related=llm_response.is_company_related,
            relevance_score=llm_response.relevance_score,
            reasoning=llm_response.reasoning,
        )


def print_post(post: MastodonPost, index: int = None, total: int = None) -> None:
    """Print a formatted view of a Mastodon post."""
    header = f"[{index}/{total}] " if index and total else ""
    print("\n" + "=" * 60)
    print(f"{header}👤 {post.author} ({post.author_handle})")
    print(f"🕐 {post.created_at.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print(f"\n{post.content}\n")
    print(f"🔗 {post.url}")


def print_reply_preview(reply_content: str) -> None:
    """Print a formatted preview of the generated reply."""
    print("-" * 40)
    print("💬 Generated Reply:")
    print("-" * 40)
    print(f"\n{reply_content}\n")
    print(f"📊 Character count: {len(reply_content)}/500")
    print("-" * 40)


def print_post_with_reply(
    post: MastodonPost, reply_content: str, index: int, total: int
) -> None:
    """Print a post and its generated reply together."""
    print_post(post, index, total)
    print_reply_preview(reply_content)


def parse_keywords(keywords_str: str) -> list[str]:
    """Parse comma-separated keywords string into list."""
    return [k.strip() for k in keywords_str.split(",") if k.strip()]


def create_generated_replies(
    posts: list[MastodonPost],
    business_context: str,
) -> list[GeneratedReply]:
    """
    Generate replies for multiple posts using a single batch LLM call.

    Args:
        posts: List of MastodonPost objects to generate replies for
        business_context: Business description for tone/context

    Returns:
        List of GeneratedReply objects with full metadata
    """
    if not posts:
        return []

    # Convert posts to the format expected by the LLM batch function
    posts_for_llm = [
        {
            "content": post.content,
            "author": post.author or post.author_handle,
        }
        for post in posts
    ]

    try:
        llm_responses = generate_replies_batch(posts_for_llm, business_context)
    except Exception as e:
        print(f"❌ Error in batch LLM call: {e}")
        return []

    # Combine posts with their LLM responses
    generated_replies = []
    for post, llm_response in zip(posts, llm_responses):
        generated_replies.append(
            GeneratedReply.from_post_and_llm_response(post, llm_response)
        )

    return generated_replies


async def process_single_reply(
    generated_reply: GeneratedReply,
    index: int,
    total: int,
) -> bool:
    """
    Process a single reply through Telegram approval workflow.

    Args:
        generated_reply: The GeneratedReply with post data and LLM response metadata
        index: Current reply index (1-based)
        total: Total number of replies

    Returns:
        True if reply was posted, False otherwise
    """
    post = generated_reply.post
    reply_content = generated_reply.response_text
    author = post.author or post.author_handle

    # Build context info with metadata for Telegram approval
    original_preview = post.content[:150] + ("..." if len(post.content) > 150 else "")
    company_indicator = "Yes" if generated_reply.is_company_related else "No"

    context_info = (
        f"[{index}/{total}] 👤 Replying to: {author}\n"
        f"📝 Original: {original_preview}\n"
        f"📊 Relevance: {generated_reply.relevance_score:.0%} | Company mention: {company_indicator}\n"
        f"💭 Reasoning: {generated_reply.reasoning[:100]}{'...' if len(generated_reply.reasoning) > 100 else ''}"
    )

    # Request approval via Telegram
    result = await request_approval(
        content=reply_content,
        context_info=context_info,
        content_type="reply",
    )

    # Determine which content to post (original or edited)
    if result.decision == Decision.ACCEPT:
        content_to_post = reply_content
        print(f"✅ Reply to {author} approved!")
    elif result.decision == Decision.EDIT:
        content_to_post = result.edited_content
        print(f"✏️ Reply to {author} edited! New content: {content_to_post[:100]}...")
    elif result.decision == Decision.REJECT:
        # Store the rejection feedback
        store_rejection(
            original_content=reply_content,
            feedback=result.feedback or "No reason provided",
            content_type="reply",
            post_author=author,
        )
        print(f"❌ Reply to {author} rejected. Feedback: {result.feedback}")
        return False
    else:
        print(f"⏭️ Reply to {author} skipped.")
        return False

    # Post the reply
    try:
        result = reply_to_status(post.id, content_to_post)
        print(f"✅ Reply posted! URL: {result.url}")
        return True
    except Exception as e:
        print(f"❌ Error posting reply to {author}: {e}")
        return False


async def async_main_with_keywords(keywords: list[str]) -> int:
    """
    Async main entry point for searching and replying to posts.

    Args:
        keywords: List of keywords to search for

    Returns:
        Number of replies made
    """
    if not keywords:
        print("❌ Please provide at least one keyword.")
        return 0

    print(f"🔍 Searching for posts with keywords: {', '.join(keywords)}")

    # Load business context (for tone, not for promotion)
    print("📄 Loading business context from Notion...")
    try:
        parent_page = fetch_parent_page()
        business_context = parent_page.content
        print(f"✅ Loaded: {parent_page.title}")
    except Exception as e:
        print(f"⚠️  Could not load Notion page: {e}")
        print("   Continuing without business context...")
        business_context = (
            "General friendly person interested in technology and community."
        )

    # Search for top 5 posts
    print(f"\n🔎 Searching Mastodon for top {BATCH_SIZE} posts...")
    try:
        posts = search_posts(keywords, limit=BATCH_SIZE)
    except Exception as e:
        print(f"❌ Error searching Mastodon: {e}")
        return 0

    if not posts:
        print("ℹ️  No posts found matching your keywords.")
        return 0

    print(f"✅ Found {len(posts)} post(s)")

    # Generate replies for all posts in a single batch LLM call
    print(f"\n🤖 Generating replies for {len(posts)} posts in batch...")
    generated_replies = create_generated_replies(posts, business_context)

    if not generated_replies:
        print("❌ Failed to generate any replies.")
        return 0

    print(f"✅ Generated {len(generated_replies)} replies")

    # Filter by relevance score
    relevant_replies = [
        reply
        for reply in generated_replies
        if reply.relevance_score >= MIN_RELEVANCE_SCORE
    ]

    filtered_count = len(generated_replies) - len(relevant_replies)
    if filtered_count > 0:
        print(
            f"🔍 Filtered out {filtered_count} low-relevance replies (score < {MIN_RELEVANCE_SCORE})"
        )

    if not relevant_replies:
        print("ℹ️  No replies passed the relevance threshold.")
        return 0

    print(f"📊 {len(relevant_replies)} replies ready for approval\n")

    # Process each reply one at a time via Telegram
    print("\n" + "=" * 60)
    print("✋ TELEGRAM APPROVAL PHASE - Processing one at a time")
    print("=" * 60)

    replies_made = 0

    for i, generated_reply in enumerate(relevant_replies, 1):
        print(f"\n[{i}/{len(relevant_replies)}] Processing reply...")
        if await process_single_reply(generated_reply, i, len(relevant_replies)):
            replies_made += 1

    print(f"\n🎉 Done! Made {replies_made} reply(ies).")
    return replies_made


async def async_main() -> None:
    """Async main entry point for CLI usage - parses arguments and calls async_main_with_keywords."""
    parser = argparse.ArgumentParser(
        description="Search Mastodon for posts and generate replies"
    )
    parser.add_argument(
        "--keywords",
        "-k",
        type=str,
        required=True,
        help="Comma-separated keywords to search for (e.g., 'AI,startup,tech')",
    )

    args = parser.parse_args()
    keywords = parse_keywords(args.keywords)

    await async_main_with_keywords(keywords)


def main() -> None:
    """Main entry point - runs the async main function."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
