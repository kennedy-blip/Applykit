"""
Universal Hub Discovery & Vault Execution Routes (`routes/api_router.py`):
- POST `/api/router` -> returns top 3 matching tools (visible showcase OR hidden vault)
- POST `/api/execute` -> executes any vault/AI tool on-the-fly with Free/Pro quota enforcement
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from lib.dynamic_runner import execute_tool
from lib.router import route_tools
from lib.security import get_optional_user, limiter

router = APIRouter(prefix="/api", tags=["Universal Hub Router"])


class RouterQueryRequest(BaseModel):
    query: str = Field(default="", max_length=240)
    context: str = Field(default="", max_length=120)
    url: str = Field(default="", max_length=1000)


class ExecuteToolRequest(BaseModel):
    tool_id: str = Field(..., min_length=2, max_length=80)
    input: str = Field(..., min_length=5, max_length=15000)
    cv_text: str = Field(default="", max_length=15000)
    page_context: str = Field(default="", max_length=8000)
    tone: str = Field(default="Professional & Direct", max_length=60)


@router.post("/router")
@limiter.limit("60/minute")
async def api_universal_router(
    payload: RouterQueryRequest,
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> Dict[str, Any]:
    result = route_tools(
        query=payload.query,
        context=payload.context,
        url=payload.url,
        user_id=user["id"] if user else None,
        limit=3,
    )
    return {"ok": True, **result}


@router.post("/execute")
@limiter.limit("10/minute")
async def api_execute_vault_tool(
    payload: ExecuteToolRequest,
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> Dict[str, Any]:
    output = execute_tool(
        request=request,
        user=user,
        tool_id=payload.tool_id,
        user_input=payload.input,
        cv_text=payload.cv_text,
        page_context=payload.page_context,
        tone=payload.tone,
    )
    return {"ok": True, **output}
