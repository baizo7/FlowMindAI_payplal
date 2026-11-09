from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app import schemas, models, gemini_agent

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


@router.post("/chat", response_model=schemas.ChatResponse)
def chat(req: schemas.ChatRequest, db: Session = Depends(get_db)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")
    try:
        result = gemini_agent.run_chat(db, req.message)
    except Exception as e:
        # Surface missing GEMINI_API_KEY, quota errors, or network issues clearly
        raise HTTPException(status_code=503, detail=f"AI Assistant Error: {str(e)}")
    return schemas.ChatResponse(
        reply=result["reply"],
        tool_calls=result["tool_calls"],
        run_id=result["run_id"],
    )


@router.get("/runs", response_model=List[schemas.AgentRunOut])
def get_agent_runs(limit: int = 20, db: Session = Depends(get_db)):
    """Retrieve full AI Agent execution audit trail for transparency and evaluation."""
    return db.query(models.AgentRun).order_by(models.AgentRun.created_at.desc()).limit(limit).all()
