import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from .notion_client import fetch_parent_page
from .mastodon_client import search_posts, reply_to_status, MastodonPost
from .llm import generate_reply

# Number of posts to search for and generate replies to
BATCH_SIZE = 5


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


def get_approval() -> str:
    """
    Prompt user for approval.

    Returns:
        'y' for yes, 'n' for no, 's' for skip all remaining
    """
    while True:
        response = input("Reply with this? (y/n/skip all): ").strip().lower()
        if response in ("y", "yes"):
            return "y"
        if response in ("n", "no"):
            return "n"
        if response in ("s", "skip", "skip all"):
            return "s"
        print("Please enter 'y', 'n', or 's' (skip all)")


def parse_keywords(keywords_str: str) -> list[str]:
    """Parse comma-separated keywords string into list."""
    return [k.strip() for k in keywords_str.split(",") if k.strip()]


def generate_replies_batch(
    posts: list[MastodonPost],
    business_context: str,
) -> list[tuple[MastodonPost, str]]:
    """
    Generate replies for multiple posts concurrently using ThreadPoolExecutor.

    Args:
        posts: List of MastodonPost objects to generate replies for
        business_context: Business description for tone/context

    Returns:
        List of (post, reply_content) tuples in the same order as input posts
    """
    results: dict[str, tuple[MastodonPost, str]] = {}

    with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
        future_to_post = {
            executor.submit(
                generate_reply,
                post.content,
                post.author or post.author_handle,
                business_context,
            ): post
            for post in posts
        }

        for future in as_completed(future_to_post):
            post = future_to_post[future]
            try:
                reply = future.result()
                results[post.id] = (post, reply)
            except Exception as e:
                print(f"❌ Error generating reply for post {post.id}: {e}")
                results[post.id] = (post, None)

    # Return in original order
    return [(post, results[post.id][1]) for post in posts if post.id in results]


def main() -> None:
    """Main entry point for searching and replying to posts."""
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

    if not keywords:
        print("❌ Please provide at least one keyword.")
        return

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
        return

    if not posts:
        print("ℹ️  No posts found matching your keywords.")
        return

    print(f"✅ Found {len(posts)} post(s)")

    # Generate replies for all posts concurrently
    print(f"\n🤖 Generating replies for {len(posts)} posts concurrently...")
    post_reply_pairs = generate_replies_batch(posts, business_context)

    # Filter out failed generations
    successful_pairs = [(post, reply) for post, reply in post_reply_pairs if reply]

    if not successful_pairs:
        print("❌ Failed to generate any replies.")
        return

    print(f"✅ Generated {len(successful_pairs)} replies\n")

    # Display all previews
    print("\n" + "=" * 60)
    print("📋 BATCH PREVIEW - All generated replies:")
    print("=" * 60)

    for i, (post, reply) in enumerate(successful_pairs, 1):
        print_post_with_reply(post, reply, i, len(successful_pairs))
        print()

    # Now approve each one individually
    print("\n" + "=" * 60)
    print("✋ APPROVAL PHASE - Review each reply:")
    print("=" * 60)

    replies_made = 0

    for i, (post, reply) in enumerate(successful_pairs, 1):
        print(f"\n[{i}/{len(successful_pairs)}]")
        print(f"👤 {post.author} ({post.author_handle})")
        print(f"📝 Original: {post.content[:100]}..." if len(post.content) > 100 else f"📝 Original: {post.content}")
        print(f"💬 Reply: {reply}")

        approval = get_approval()

        if approval == "y":
            try:
                result = reply_to_status(post.id, reply)
                print(f"✅ Replied! URL: {result.url}")
                replies_made += 1
            except Exception as e:
                print(f"❌ Error posting reply: {e}")

        elif approval == "s":
            print("⏭️  Skipping remaining posts.")
            break

        else:
            print("⏭️  Skipped.")

    print(f"\n🎉 Done! Made {replies_made} reply(ies).")


if __name__ == "__main__":
    main()
