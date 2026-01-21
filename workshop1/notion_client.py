from datetime import datetime

from notion_client import Client
from pydantic import BaseModel

from .config import settings


class NotionPage(BaseModel):
    """Represents a Notion page with its content."""

    id: str
    title: str
    content: str
    last_edited_time: datetime


def _get_client() -> Client:
    """Get authenticated Notion client."""
    return Client(auth=settings.notion_token)


def _extract_text_from_blocks(blocks: list) -> str:
    """Extract plain text from Notion blocks."""
    text_parts = []

    for block in blocks:
        block_type = block.get("type")
        if not block_type:
            continue

        block_content = block.get(block_type, {})

        # Handle rich text blocks (paragraph, heading, bulleted_list_item, etc.)
        if "rich_text" in block_content:
            for text_obj in block_content["rich_text"]:
                text_parts.append(text_obj.get("plain_text", ""))

        # Handle to-do items
        elif block_type == "to_do":
            checked = "✓" if block_content.get("checked") else "○"
            for text_obj in block_content.get("rich_text", []):
                text_parts.append(f"{checked} {text_obj.get('plain_text', '')}")

        # Handle code blocks
        elif block_type == "code":
            for text_obj in block_content.get("rich_text", []):
                text_parts.append(f"```\n{text_obj.get('plain_text', '')}\n```")

        # Handle dividers
        elif block_type == "divider":
            text_parts.append("---")

    return "\n".join(text_parts)


def _get_page_title(page: dict) -> str:
    """Extract title from a Notion page."""
    properties = page.get("properties", {})

    if "title" in properties:
        title_prop = properties["title"]
        if title_prop.get("type") == "title":
            title_arr = title_prop.get("title", [])
            return title_arr[0].get("text", {}).get("content", "Untitled")

    return "Untitled"


def fetch_parent_page() -> NotionPage:
    """
    Fetch the parent page (business description) from Notion.

    Returns:
        NotionPage with the parent page content
    """
    client = _get_client()
    page_id = settings.notion_page_id

    # Get page metadata
    page = client.pages.retrieve(page_id=page_id)
    title = _get_page_title(page)
    last_edited = datetime.fromisoformat(
        page["last_edited_time"].replace("Z", "+00:00")
    )

    # Get page content (blocks)
    blocks_response = client.blocks.children.list(block_id=page_id)
    blocks = blocks_response.get("results", [])
    for block in blocks:
        if block.get("type") == "child_page":
            title = block.get("child_page").get("title")
            if title == "Overall Account Description":
                main_page_id = block.get("id")
                break
    main_blocks_response = client.blocks.children.list(block_id=main_page_id)
    main_blocks = main_blocks_response.get("results", [])
    content = _extract_text_from_blocks(main_blocks)

    return NotionPage(
        id=page_id,
        title=title,
        content=content,
        last_edited_time=last_edited,
    )


def fetch_child_pages() -> list[NotionPage]:
    """
    Fetch all child pages from the parent Notion page.

    Returns:
        List of NotionPage objects for each child page
    """
    client = _get_client()
    page_id = settings.notion_page_id

    # Get child blocks of the parent page
    blocks_response = client.blocks.children.list(block_id=page_id)
    blocks = blocks_response.get("results", [])

    child_pages = []

    for block in blocks:
        if block.get("type") == "child_page":
            if block.get("child_page").get("title") == "Overall Account Description":
                continue

            child_id = block["id"]
            child_title = block["child_page"].get("title", "Untitled")

            # Get the child page's metadata for last_edited_time
            child_page = client.pages.retrieve(page_id=child_id)
            last_edited = datetime.fromisoformat(
                child_page["last_edited_time"].replace("Z", "+00:00")
            )

            # Get the child page's content
            child_blocks_response = client.blocks.children.list(block_id=child_id)
            child_blocks = child_blocks_response.get("results", [])
            content = _extract_text_from_blocks(child_blocks)

            child_pages.append(
                NotionPage(
                    id=child_id,
                    title=child_title,
                    content=content,
                    last_edited_time=last_edited,
                )
            )

    return child_pages
