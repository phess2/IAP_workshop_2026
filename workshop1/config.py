from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()


class Settings(BaseModel):
    notion_token: str = os.environ.get("NOTION_TOKEN", "")
    notion_page_id: str = os.environ.get("NOTION_PAGE_ID", "")

    openrouter_api_key: str = os.environ.get("OPENROUTER_API_KEY", "")
    openrouter_base_url: str = os.environ.get(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    openrouter_model: str = os.environ.get("OPENROUTER_MODEL", "z-ai/glm-4.5-air:free")

    mastodon_base_url: str = os.environ.get("MASTODON_BASE_URL", "")
    mastodon_access_token: str = os.environ.get("MASTODON_ACCESS_TOKEN", "")

    replicate_api_token: str = os.environ.get("REPLICATE_API_TOKEN", "")


settings = Settings()
