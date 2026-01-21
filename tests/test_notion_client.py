"""Tests for the Notion client functionality."""

from workshop1.notion_client import fetch_parent_page


def test_fetch_and_print_master_page():
    """Test loading and printing the master page content from Notion."""
    page = fetch_parent_page()

    print("\n" + "=" * 80)
    print("MASTER PAGE CONTENT")
    print("=" * 80)
    print(f"\nPage ID: {page.id}")
    print(f"Title: {page.title}")
    print(f"Last Edited: {page.last_edited_time}")
    print("\n" + "-" * 80)
    print("CONTENT:")
    print("-" * 80)
    print(page.content)
    print("=" * 80 + "\n")

    # Assert that we got a page with content
    assert page.id is not None
    assert page.title is not None
    assert page.content is not None
