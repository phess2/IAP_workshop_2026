from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from datetime import datetime
import sqlite3
from pathlib import Path

from .config import api_settings
from .database import init_db
from .schemas import HealthResponse
from .routes import posts, replies, feedback, state, automation, rag


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    init_db()
    print(f"Database initialized at: {api_settings.database_path}")
    yield
    # Shutdown (if needed in the future)
    pass


# Initialize FastAPI app
app = FastAPI(
    title="IAP 2026 Workshop API",
    description="FastAPI application for IAP 2026 Workshop with SQLite database",
    version="0.1.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(posts.router, prefix=api_settings.api_v1_prefix)
app.include_router(replies.router, prefix=api_settings.api_v1_prefix)
app.include_router(feedback.router, prefix=api_settings.api_v1_prefix)
app.include_router(state.router, prefix=api_settings.api_v1_prefix)
app.include_router(automation.router, prefix=api_settings.api_v1_prefix)
app.include_router(rag.router, prefix=api_settings.api_v1_prefix)


@app.get("/", response_class=JSONResponse)
async def root():
    """Root endpoint."""
    return {
        "message": "IAP 2026 Workshop API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    db_status = "connected"
    try:
        # Check database connection
        db_path = Path(api_settings.database_path)
        if db_path.exists():
            conn = sqlite3.connect(api_settings.database_path)
            conn.close()
            db_status = "connected"
        else:
            db_status = "not_found"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return HealthResponse(
        status="healthy",
        database=db_status,
        timestamp=datetime.now(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=api_settings.host,
        port=api_settings.port,
        reload=False,
    )
