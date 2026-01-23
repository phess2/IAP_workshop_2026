from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from ..database import get_db
from ..models import Reply
from ..schemas import ReplyCreate, ReplyUpdate, ReplyResponse

router = APIRouter(prefix="/replies", tags=["replies"])


@router.get("", response_model=List[ReplyResponse])
def list_replies(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all replies."""
    replies = db.query(Reply).offset(skip).limit(limit).all()
    return replies


@router.get("/{reply_id}", response_model=ReplyResponse)
def get_reply(reply_id: int, db: Session = Depends(get_db)):
    """Get a specific reply by ID."""
    reply = db.query(Reply).filter(Reply.id == reply_id).first()
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    return reply


@router.post("", response_model=ReplyResponse, status_code=201)
def create_reply(reply: ReplyCreate, db: Session = Depends(get_db)):
    """Create a new reply."""
    db_reply = Reply(**reply.model_dump())
    db.add(db_reply)
    db.commit()
    db.refresh(db_reply)
    return db_reply


@router.put("/{reply_id}", response_model=ReplyResponse)
def update_reply(
    reply_id: int, reply_update: ReplyUpdate, db: Session = Depends(get_db)
):
    """Update a reply."""
    reply = db.query(Reply).filter(Reply.id == reply_id).first()
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")

    update_data = reply_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(reply, key, value)

    reply.updated_at = datetime.now()
    db.commit()
    db.refresh(reply)
    return reply


@router.delete("/{reply_id}", status_code=204)
def delete_reply(reply_id: int, db: Session = Depends(get_db)):
    """Delete a reply."""
    reply = db.query(Reply).filter(Reply.id == reply_id).first()
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")

    db.delete(reply)
    db.commit()
    return None
