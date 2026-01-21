from datetime import datetime

import httpx
from pydantic import BaseModel

from .config import settings


class MastodonPost(BaseModel):
    """Represents a Mastodon post/status."""

    id: str
    content: str
    author: str
    author_handle: str
    created_at: datetime
    url: str


def _get_headers() -> dict:
    """Get authorization headers for Mastodon API."""
    return {"Authorization": f"Bearer {settings.mastodon_access_token}"}


def _strip_html(html: str) -> str:
    """Strip HTML tags from content (simple implementation)."""
    import re

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def search_posts(keywords: list[str], limit: int = 20) -> list[MastodonPost]:
    """
    Search for posts matching keywords using Mastodon Search API.

    Falls back to hashtag timeline if search returns few results.

    Args:
        keywords: List of keywords to search for
        limit: Maximum number of posts to return

    Returns:
        List of MastodonPost objects
    """
    base_url = settings.mastodon_base_url.rstrip("/")
    headers = _get_headers()
    posts = []
    seen_ids = set()

    # Try search API for each keyword
    for keyword in keywords:
        # try:
        response = httpx.get(
            f"{base_url}/api/v2/search",
            headers=headers,
            params={"q": keyword, "type": "statuses", "limit": limit},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        for status in data.get("statuses", []):
            if status["id"] not in seen_ids:
                seen_ids.add(status["id"])
                posts.append(_parse_status(status))

    # except httpx.HTTPError as e:
    #     print(f"Search API error for '{keyword}': {e}")

    # If we got few results, try hashtag timelines as fallback
    if len(posts) < limit // 2:
        for keyword in keywords:
            # Clean keyword for hashtag use
            hashtag = keyword.strip("#").replace(" ", "")
            try:
                response = httpx.get(
                    f"{base_url}/api/v1/timelines/tag/{hashtag}",
                    headers=headers,
                    params={"limit": limit},
                    timeout=30.0,
                )
                response.raise_for_status()
                statuses = response.json()

                for status in statuses:
                    if status["id"] not in seen_ids:
                        seen_ids.add(status["id"])
                        posts.append(_parse_status(status))

            except httpx.HTTPError as e:
                print(f"Hashtag timeline error for '{hashtag}': {e}")

    return posts[:limit]


def _parse_status(status: dict) -> MastodonPost:
    """Parse a Mastodon status dict into a MastodonPost."""
    account = status.get("account", {})
    created_at = datetime.fromisoformat(status["created_at"].replace("Z", "+00:00"))

    return MastodonPost(
        id=status["id"],
        content=_strip_html(status.get("content", "")),
        author=account.get("display_name", "Unknown"),
        author_handle=f"@{account.get('acct', 'unknown')}",
        created_at=created_at,
        url=status.get("url", ""),
    )


def upload_media(image_url: str, description: str = "") -> str:
    """
    Download an image from a URL and upload it to Mastodon as media.

    Args:
        image_url: URL to the image file (e.g., from Replicate)
        description: Optional alt text/description for accessibility

    Returns:
        The media_id string that can be used when posting a status

    Raises:
        httpx.HTTPError: If download or upload fails
    """
    base_url = settings.mastodon_base_url.rstrip("/")
    headers = _get_headers()

    # Download the image
    print(f"📥 Downloading image from {image_url}...")
    download_response = httpx.get(image_url, timeout=60.0, follow_redirects=True)
    download_response.raise_for_status()
    image_data = download_response.content

    # Determine content type from URL or response headers
    content_type = download_response.headers.get("content-type", "image/webp")
    if not content_type.startswith("image/"):
        content_type = "image/webp"  # Default fallback

    # Upload to Mastodon
    print("📤 Uploading image to Mastodon...")
    files = {"file": ("image.webp", image_data, content_type)}
    data = {}
    if description:
        data["description"] = description

    upload_response = httpx.post(
        f"{base_url}/api/v1/media",
        headers=headers,
        files=files,
        data=data,
        timeout=60.0,
    )
    upload_response.raise_for_status()
    media_attachment = upload_response.json()

    media_id = str(media_attachment["id"])
    print(f"✅ Image uploaded successfully (media_id: {media_id})")
    return media_id


def post_status(content: str, media_ids: list[str] | None = None) -> MastodonPost:
    """
    Create a new Mastodon post.

    Args:
        content: The text content of the post (max 500 chars)
        media_ids: Optional list of media attachment IDs to include

    Returns:
        The created MastodonPost

    Raises:
        httpx.HTTPError: If posting fails
    """
    base_url = settings.mastodon_base_url.rstrip("/")
    headers = _get_headers()

    payload = {"status": f"{content}\n\nPost generated by AI."}
    if media_ids:
        payload["media_ids"] = media_ids

    response = httpx.post(
        f"{base_url}/api/v1/statuses",
        headers=headers,
        json=payload,
        timeout=30.0,
    )
    response.raise_for_status()

    return _parse_status(response.json())


def reply_to_status(status_id: str, content: str) -> MastodonPost:
    """
    Reply to an existing Mastodon post.

    Args:
        status_id: The ID of the post to reply to
        content: The reply text content

    Returns:
        The created reply MastodonPost

    Raises:
        httpx.HTTPError: If posting fails
    """
    base_url = settings.mastodon_base_url.rstrip("/")
    headers = _get_headers()

    response = httpx.post(
        f"{base_url}/api/v1/statuses",
        headers=headers,
        json={
            "status": f"{content}",
            "in_reply_to_id": status_id,
        },
        timeout=30.0,
    )
    response.raise_for_status()

    return _parse_status(response.json())
