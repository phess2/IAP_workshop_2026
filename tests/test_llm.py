from workshop1.llm import generate_post, generate_reply


def test_generate_post():
    """Test generating a Mastodon post."""
    business_context = (
        "A small coffee shop focused on sustainable sourcing and community building."
    )
    page_content = "We just launched our new seasonal blend featuring beans from Colombia and Ethiopia. The blend has notes of chocolate and citrus, perfect for the winter months."
    page_title = "New Seasonal Blend Launch"

    post = generate_post(
        business_context=business_context,
        page_content=page_content,
        page_title=page_title,
    )

    print("\n" + "=" * 80)
    print("GENERATED POST")
    print("=" * 80)
    print(post)
    print("=" * 80 + "\n")

    # Assert that we got a post
    assert post is not None
    assert len(post) > 0


def test_generate_reply():
    """Test generating a Mastodon reply."""
    post_content = "Just finished reading an amazing book about sustainable agriculture. The future of farming is so exciting!"
    post_author = "@sustainable_farmer"
    business_context = (
        "A small coffee shop focused on sustainable sourcing and community building."
    )

    reply = generate_reply(
        post_content=post_content,
        post_author=post_author,
        business_context=business_context,
    )

    print("\n" + "=" * 80)
    print("GENERATED REPLY")
    print("=" * 80)
    print(f"Replying to: {post_author}")
    print(f"Original post: {post_content}")
    print("-" * 80)
    print("Reply:")
    print(reply)
    print("=" * 80 + "\n")

    # Assert that we got a reply
    assert reply is not None
    assert len(reply) > 0
