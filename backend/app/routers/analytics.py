from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import tools, schemas

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/overview", response_model=schemas.AnalyticsOverview)
def overview(db: Session = Depends(get_db)):
    return tools.get_financial_summary(db)
