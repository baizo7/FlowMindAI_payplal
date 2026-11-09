from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app import models, schemas, tools

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


@router.get("", response_model=List[schemas.PaymentOut])
def list_payments(db: Session = Depends(get_db)):
    return db.query(models.Payment).order_by(models.Payment.created_at.desc()).all()


@router.post("/capture/{identifier}")
def capture_payment_direct(identifier: str, db: Session = Depends(get_db)):
    """1-Click capture endpoint for the UI dashboard."""
    result = tools.capture_payment(db, identifier)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
