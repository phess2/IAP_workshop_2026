from pydantic import BaseModel
from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv()


class APISettings(BaseModel):
    """FastAPI application settings."""

    # Database
    database_path: str = os.environ.get("DATABASE_PATH", "data/workshop.db")
    database_dir: str = os.environ.get("DATABASE_DIR", "data")

    # Server
    host: str = os.environ.get("API_HOST", "0.0.0.0")
    port: int = int(os.environ.get("API_PORT", "8000"))

    # API
    api_v1_prefix: str = "/api/v1"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure database directory exists
        Path(self.database_dir).mkdir(parents=True, exist_ok=True)


api_settings = APISettings()
