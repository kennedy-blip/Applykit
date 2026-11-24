"""
Showcase AI Tool JSON Endpoints (`routes/api_ai.py`):
- POST `/api/ai/ats-score`
- POST `/api/ai/cover-letter`
- POST `/api/ai/scam-check`
- POST `/api/ai/interview-qs`
- POST `/api/ai/extract-cv` (validated PDF/DOCX <=2MB upload -> extracted plain text)
- POST `/api/auth/demo-session` & DELETE `/api/account/delete-my-data` (GDPR / Kenya DPA)
"""

import os
from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from lib.ai_client import generate, get_last_ai_meta
from lib.limits import check_and_consume_ai_quota
from lib.prompts import (
    build_ats_prompt,
    build_cover_letter_prompt,
    build_interview_qs_prompt,
    build_scam_check_prompt,
)
from lib.security import (
    extract_validated_cv_upload,
    get_optional_user,
    hash_text,
    limiter,
    require_authenticated_user,
)
from lib.supabase_client import (
    delete_all_user_data,
    get_or_create_profile,
    is_supabase_configured,
    log_ai_audit,
)

router = APIRouter(prefix="/api", tags=["AI Tools & Account"])


class AtsScoreRequest(BaseModel):
    cv_text: str = Field(..., min_length=20, max_length=15000)
    jd_text: str = Field(..., min_length=20, max_length=15000)


class CoverLetterRequest(BaseModel):
    cv_text: str = Field(..., min_length=20, max_length=15000)
    jd_text: str = Field(..., min_length=20, max_length=15000)
    tone: str = Field(default="Professional & Direct", max_length=60)


class ScamCheckRequest(BaseModel):
    job_text: str = Field(..., min_length=15, max_length=15000)
    client_meta: str = Field(default="", max_length=2000)


class InterviewQsRequest(BaseModel):
    jd_text: str = Field(..., min_length=20, max_length=15000)
    cv_text: str = Field(default="", max_length=15000)


class DemoLoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=160)


@router.post("/ai/ats-score")
@limiter.limit("10/minute")
async def api_ats_score(
    payload: AtsScoreRequest,
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> Dict[str, Any]:
    quota = check_and_consume_ai_quota(request, user)
    prompt = build_ats_prompt(payload.cv_text, payload.jd_text)
    result = generate(prompt, json_mode=True, prefer_70b=quota["prefer_70b"], use_cache=True)
    meta = get_last_ai_meta()

    log_ai_audit(
        user_id=user["id"] if user else None,
        ip_hash=quota["ip_hash"],
        tool_id="ats-checker",
        input_hash=hash_text(f"{payload.cv_text}:{payload.jd_text}"),
        provider=meta["provider"],
        model=meta["model"],
        cached=meta["cached"],
    )

    score = result.get("score", 0)
    wa_msg = f"🎯 I scored {score}/100 on ApplyKit's Free ATS CV Checker! Check your CV match score free: https://applykit.onrender.com/tools/ats-checker"
    return {
        "ok": True,
        "result": result,
        "whatsapp_share_url": f"https://wa.me/?text={quote(wa_msg)}",
        "quota": {
            "is_pro": quota["is_pro"],
            "remaining": quota["remaining"],
            "show_ads": quota["show_ads"],
        },
    }


@router.post("/ai/cover-letter")
@limiter.limit("10/minute")
async def api_cover_letter(
    payload: CoverLetterRequest,
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> Dict[str, Any]:
    quota = check_and_consume_ai_quota(request, user)
    prompt = build_cover_letter_prompt(payload.cv_text, payload.jd_text, payload.tone)
    result = generate(prompt, json_mode=True, prefer_70b=quota["prefer_70b"], use_cache=True)
    meta = get_last_ai_meta()

    log_ai_audit(
        user_id=user["id"] if user else None,
        ip_hash=quota["ip_hash"],
        tool_id="cover-letter-generator",
        input_hash=hash_text(f"{payload.cv_text}:{payload.jd_text}:{payload.tone}"),
        provider=meta["provider"],
        model=meta["model"],
        cached=meta["cached"],
    )

    wa_msg = "✍️ Generated a tailored 150-word cover letter in 4 seconds with ApplyKit: https://applykit.onrender.com/tools/cover-letter-generator"
    return {
        "ok": True,
        "result": result,
        "whatsapp_share_url": f"https://wa.me/?text={quote(wa_msg)}",
        "quota": {
            "is_pro": quota["is_pro"],
            "remaining": quota["remaining"],
            "show_ads": quota["show_ads"],
        },
    }


@router.post("/ai/scam-check")
@limiter.limit("10/minute")
async def api_scam_check(
    payload: ScamCheckRequest,
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> Dict[str, Any]:
    quota = check_and_consume_ai_quota(request, user)
    prompt = build_scam_check_prompt(payload.job_text, payload.client_meta)
    result = generate(prompt, json_mode=True, prefer_70b=quota["prefer_70b"], use_cache=True)
    meta = get_last_ai_meta()

    log_ai_audit(
        user_id=user["id"] if user else None,
        ip_hash=quota["ip_hash"],
        tool_id="scam-detector",
        input_hash=hash_text(f"{payload.job_text}:{payload.client_meta}"),
        provider=meta["provider"],
        model=meta["model"],
        cached=meta["cached"],
    )

    risk = result.get("risk_level", "Medium")
    wa_msg = f"🛡️ Job Scam Alert Check ({risk} Risk) via ApplyKit Scam Detector — verify job posts free: https://applykit.onrender.com/tools/scam-detector"
    return {
        "ok": True,
        "result": result,
        "whatsapp_share_url": f"https://wa.me/?text={quote(wa_msg)}",
        "quota": {
            "is_pro": quota["is_pro"],
            "remaining": quota["remaining"],
            "show_ads": quota["show_ads"],
        },
    }


@router.post("/ai/interview-qs")
@limiter.limit("10/minute")
async def api_interview_qs(
    payload: InterviewQsRequest,
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> Dict[str, Any]:
    quota = check_and_consume_ai_quota(request, user)
    prompt = build_interview_qs_prompt(payload.jd_text, payload.cv_text)
    result = generate(prompt, json_mode=True, prefer_70b=quota["prefer_70b"], use_cache=True)
    meta = get_last_ai_meta()

    log_ai_audit(
        user_id=user["id"] if user else None,
        ip_hash=quota["ip_hash"],
        tool_id="interview-questions-generator",
        input_hash=hash_text(f"{payload.jd_text}:{payload.cv_text}"),
        provider=meta["provider"],
        model=meta["model"],
        cached=meta["cached"],
    )

    wa_msg = "🎤 Practising 10 tailored STAR interview questions generated from my CV on ApplyKit: https://applykit.onrender.com/tools/interview-questions-generator"
    return {
        "ok": True,
        "result": result,
        "whatsapp_share_url": f"https://wa.me/?text={quote(wa_msg)}",
        "quota": {
            "is_pro": quota["is_pro"],
            "remaining": quota["remaining"],
            "show_ads": quota["show_ads"],
        },
    }


@router.post("/ai/extract-cv")
@limiter.limit("10/minute")
async def api_extract_cv_file(
    request: Request,
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    """Validate uploaded PDF/DOCX CV (<= 2 MB, strict MIME/header check) and return extracted text."""
    extracted_text = await extract_validated_cv_upload(file)
    return {
        "ok": True,
        "filename": file.filename,
        "char_count": len(extracted_text),
        "cv_text": extracted_text,
    }


@router.get("/me")
async def api_current_user(user: Optional[Dict[str, Any]] = Depends(get_optional_user)) -> Dict[str, Any]:
    if not user:
        return {"authenticated": False, "user": None}
    return {
        "authenticated": True,
        "user": {
            "id": user["id"],
            "email": user.get("email"),
            "full_name": user.get("full_name"),
            "is_pro": bool(user.get("is_pro")),
            "pro_plan": user.get("pro_plan", "free"),
            "pro_expires_at": user.get("pro_expires_at"),
            "ai_uses_this_month": int(user.get("ai_uses_this_month", 0)),
            "bonus_generations": int(user.get("bonus_generations", 0)),
            "referral_code": user.get("referral_code"),
        },
    }


@router.post("/auth/demo-session")
async def api_dev_demo_session(payload: DemoLoginRequest, response: Response) -> Dict[str, Any]:
    """
    Dev-mode instant sign-in helper active ONLY when SUPABASE_JWT_SECRET is not set,
    allowing full end-to-end testing of Free (5/mo) vs Pro flows locally before Supabase keys are added.
    """
    jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    if is_supabase_configured() and jwt_secret and jwt_secret != "your_supabase_jwt_secret_from_project_settings":
        raise HTTPException(status_code=403, detail="Use Google OAuth via Supabase in production.")

    email = payload.email.strip().lower()
    token = f"dev-demo-token:{email}"
    from lib.security import verify_supabase_jwt

    claims = verify_supabase_jwt(token)
    prof = get_or_create_profile(claims["sub"], email=email)
    response.set_cookie(
        key="applykit_token",
        value=token,
        httponly=False,
        samesite="lax",
        max_age=86400 * 14,
    )
    return {"ok": True, "token": token, "user": prof}


@router.post("/auth/logout")
async def api_logout(response: Response) -> Dict[str, Any]:
    response.delete_cookie("applykit_token")
    return {"ok": True}


@router.delete("/account/delete-my-data")
async def api_delete_my_data(
    response: Response,
    user: Dict[str, Any] = Depends(require_authenticated_user),
) -> Dict[str, Any]:
    """GDPR & Kenya Data Protection Act (DPA) 1-click erasure of profile, applications, logs & CVs."""
    delete_all_user_data(user["id"])
    response.delete_cookie("applykit_token")
    return {
        "ok": True,
        "message": "Your profile, saved job applications, AI logs, and stored CVs have been permanently deleted.",
    }
