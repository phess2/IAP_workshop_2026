from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Boolean
from sqlalchemy.sql import func
from datetime import datetime

from .database import Base


class Post(Base):
    """Notion post model."""
    
    __tablename__ = "posts"
    
    id = Column(Integer, primary_key=True, index=True)
    notion_page_id = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    posted_content = Column(Text, nullable=True)  # The actual content that was posted
    status = Column(String, default="pending")  # pending, approved, rejected, posted
    mastodon_url = Column(String, nullable=True)
    last_edited_time = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    posted_at = Column(DateTime, nullable=True)


class Reply(Base):
    """Mastodon reply model."""
    
    __tablename__ = "replies"
    
    id = Column(Integer, primary_key=True, index=True)
    mastodon_post_id = Column(String, index=True, nullable=False)
    post_author = Column(String, nullable=False)
    post_author_handle = Column(String, nullable=True)
    original_post_content = Column(Text, nullable=False)
    reply_content = Column(Text, nullable=False)
    posted_reply_content = Column(Text, nullable=True)  # The actual content that was posted
    status = Column(String, default="pending")  # pending, approved, rejected, posted
    mastodon_url = Column(String, nullable=True)
    post_url = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    posted_at = Column(DateTime, nullable=True)


class Feedback(Base):
    """Rejection feedback model."""
    
    __tablename__ = "feedback"
    
    id = Column(Integer, primary_key=True, index=True)
    content_type = Column(String, nullable=False)  # "post" or "reply"
    original_content = Column(Text, nullable=False)
    feedback_text = Column(Text, nullable=False)
    page_title = Column(String, nullable=True)  # For posts
    post_author = Column(String, nullable=True)  # For replies
    created_at = Column(DateTime, server_default=func.now())


class State(Base):
    """Workshop state model."""
    
    __tablename__ = "state"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True, nullable=False)
    value = Column(JSON, nullable=False)  # Store JSON data
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
