from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..models import State
from ..schemas import StateCreate, StateUpdate, StateResponse

router = APIRouter(prefix="/state", tags=["state"])


@router.get("", response_model=List[StateResponse])
def list_states(db: Session = Depends(get_db)):
    """List all state entries."""
    states = db.query(State).all()
    return states


@router.get("/{key}", response_model=StateResponse)
def get_state(key: str, db: Session = Depends(get_db)):
    """Get state by key."""
    state = db.query(State).filter(State.key == key).first()
    if not state:
        raise HTTPException(status_code=404, detail=f"State with key '{key}' not found")
    return state


@router.post("", response_model=StateResponse, status_code=201)
def create_state(state: StateCreate, db: Session = Depends(get_db)):
    """Create or update a state entry."""
    # Check if state with this key already exists
    existing = db.query(State).filter(State.key == state.key).first()
    if existing:
        # Update existing state
        existing.value = state.value
        db.commit()
        db.refresh(existing)
        return existing

    db_state = State(**state.model_dump())
    db.add(db_state)
    db.commit()
    db.refresh(db_state)
    return db_state


@router.put("/{key}", response_model=StateResponse)
def update_state(key: str, state_update: StateUpdate, db: Session = Depends(get_db)):
    """Update a state entry."""
    state = db.query(State).filter(State.key == key).first()
    if not state:
        raise HTTPException(status_code=404, detail=f"State with key '{key}' not found")

    state.value = state_update.value
    db.commit()
    db.refresh(state)
    return state


@router.delete("/{key}", status_code=204)
def delete_state(key: str, db: Session = Depends(get_db)):
    """Delete a state entry."""
    state = db.query(State).filter(State.key == key).first()
    if not state:
        raise HTTPException(status_code=404, detail=f"State with key '{key}' not found")

    db.delete(state)
    db.commit()
    return None
