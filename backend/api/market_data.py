from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from core.market_data import resolve_stock_match
from db.database import get_db


router = APIRouter(tags=["market-data"])


@router.get("/stocks/resolve")
async def resolve_stock(
    field: str = Query(..., pattern="^(code|stock_code|name)$"),
    q: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    lookup_field = "code" if field == "stock_code" else field
    result = await run_in_threadpool(resolve_stock_match, lookup_field, q)
    if not result:
        raise HTTPException(status_code=404, detail="stock not found")
    return result
