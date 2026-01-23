from pydantic import BaseModel
from datetime import datetime
from typing import Optional


# Post schemas
class PostBase(BaseModel):
    notion_page_id: str
    title: str
    content: str
    last_edited_time: datetime


class PostCreate(PostBase):
    pass


class PostUpdate(BaseModel):
    status: Optional[str] = None
    posted_content: Optional[str] = None
    mastodon_url: Optional[str] = None
    posted_at: Optional[datetime] = None


class PostResponse(PostBase):
    id: int
    posted_content: Optional[str] = None
    status: str
    mastodon_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    posted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Reply schemas
class ReplyBase(BaseModel):
    mastodon_post_id: str
    post_author: str
    post_author_handle: Optional[str] = None
    original_post_content: str
    reply_content: str
    post_url: str


class ReplyCreate(ReplyBase):
    pass


class ReplyUpdate(BaseModel):
    status: Optional[str] = None
    posted_reply_content: Optional[str] = None
    mastodon_url: Optional[str] = None
    posted_at: Optional[datetime] = None


class ReplyResponse(ReplyBase):
    id: int
    posted_reply_content: Optional[str] = None
    status: str
    mastodon_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    posted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Feedback schemas
class FeedbackBase(BaseModel):
    content_type: str  # "post" or "reply"
    original_content: str
    feedback_text: str
    page_title: Optional[str] = None
    post_author: Optional[str] = None


class FeedbackCreate(FeedbackBase):
    pass


class FeedbackResponse(FeedbackBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# State schemas
class StateBase(BaseModel):
    key: str
    value: dict


class StateCreate(StateBase):
    pass


class StateUpdate(BaseModel):
    value: dict


class StateResponse(StateBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Health check
class HealthResponse(BaseModel):
    status: str
    database: str
    timestamp: datetime


# Automation schemas
class AutomationResponse(BaseModel):
    status: str  # "success" or "error"
    message: str
    posts_made: int | None = None  # for make-posts endpoint
    replies_made: int | None = None  # for reply-posts endpoint
