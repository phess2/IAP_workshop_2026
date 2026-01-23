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

    telegram_bot_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.environ.get("TELEGRAM_CHAT_ID", "")

    # Database configuration
    database_path: str = os.environ.get("DATABASE_PATH", "data/workshop.db")
    database_dir: str = os.environ.get("DATABASE_DIR", "data")

    # Vector database configuration
    vector_db_path: str = os.environ.get("VECTOR_DB_PATH", "data/vector.db")

    # RAG configuration
    rag_keyword_weight: float = float(os.environ.get("RAG_KEYWORD_WEIGHT", "0.4"))
    rag_semantic_weight: float = float(os.environ.get("RAG_SEMANTIC_WEIGHT", "0.6"))

    # Listener configuration
    notion_poll_interval: int = int(os.environ.get("NOTION_POLL_INTERVAL", "300"))
    mastodon_poll_interval: int = int(os.environ.get("MASTODON_POLL_INTERVAL", "60"))


settings = Settings()
