from workshop1 import mastodon_client


def test_mastodon_client_helpers_no_posting(monkeypatch):
    """
    Unit test for mastodon_client helpers that do NOT post to Mastodon.

    This intentionally avoids calling:
    - post_status()
    - reply_to_status()
    - search_posts() (network)
    """

    # Ensure headers are formed correctly without relying on real env vars
    monkeypatch.setattr(mastodon_client.settings, "mastodon_access_token", "TEST_TOKEN")
    headers = mastodon_client._get_headers()

    # Exercise HTML stripping
    html = "<p>Hello <strong>world</strong>!<br />Line 2</p>"
    stripped = mastodon_client._strip_html(html)

    # Exercise status parsing with a fake Mastodon API payload
    fake_status = {
        "id": "123",
        "content": "<p>Testing <em>parse</em> ✅</p>",
        "account": {"display_name": "Ada Lovelace", "acct": "ada"},
        "created_at": "2025-01-01T00:00:00.000Z",
        "url": "https://example.social/@ada/123",
    }
    post = mastodon_client._parse_status(fake_status)

    print("\n" + "=" * 80)
    print("MASTODON CLIENT (NO POSTING) HELPERS TEST")
    print("=" * 80)
    print("Headers:", headers)
    print("-" * 80)
    print("Stripped HTML:", stripped)
    print("-" * 80)
    print("Parsed MastodonPost:", post)
    print("=" * 80 + "\n")

    assert headers["Authorization"] == "Bearer TEST_TOKEN"
    assert stripped == "Hello world ! Line 2"
    assert post.id == "123"
    assert post.author == "Ada Lovelace"
    assert post.author_handle == "@ada"
    assert post.content == "Testing parse ✅"
