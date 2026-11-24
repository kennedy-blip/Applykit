"""
Security utilities for ApplyKit:
- Supabase JWT verification via python-jose (Authorization: Bearer <token>)
- Strict HTTP Security Headers Middleware (CSP, HSTS, X-Frame-Options, X-Content-Type-Options)
- SlowAPI rate limiter instance
- IP hashing (never store raw IP or raw CV in logs)
- Safe CV file upload validation (PDF / DOCX <= 2 MB) + text extraction
- HTTP Basic Auth guard for /admin manual Till approval panel
"""

import hashlib
import hmac
import io
import logging
import os
import re
import secrets
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request, UploadFile, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from jose import JWTError, jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from lib.supabase_client import get_or_create_profile, get_supabase

logger = logging.getLogger("applykit.security")

# Rate limiter keyed by client IP
limiter = Limiter(key_func=get_remote_address)

http_basic = HTTPBasic()

KENYA_PHONE_REGEX = re.compile(r"^254[17]\d{8}$")
MAX_CV_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB
ALLOWED_CV_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def hash_ip(request: Request) -> str:
    ip = get_client_ip(request)
    salt = os.getenv("IP_HASH_SALT", "applykit_default_salt_2026")
    return hashlib.sha256(f"{salt}:{ip}".encode("utf-8")).hexdigest()[:32]


def hash_text(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def normalize_kenya_phone(raw_phone: str) -> str:
    """Normalize 07xx / +2547xx / 2547xx into strict 254[17]xxxxxxxx format and validate."""
    digits = re.sub(r"[\s\-\(\)\+]", "", raw_phone or "")
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    if not KENYA_PHONE_REGEX.match(digits):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid Safaricom phone number. Use format 2547XXXXXXXX or 2541XXXXXXXX.",
        )
    return digits


def verify_supabase_jwt(token: str) -> Dict[str, Any]:
    """
    Verify a Supabase Bearer JWT using python-jose.
    Rejects expired or malformed tokens with HTTP 401.
    """
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication token.")

    jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    has_live_jwt_secret = bool(jwt_secret and jwt_secret != "your_supabase_jwt_secret_from_project_settings")

    # Local demo token support ONLY when SUPABASE_JWT_SECRET is not set in dev/test
    if token.startswith("dev-demo-token:") and not has_live_jwt_secret:
        parts = token.split(":", 2)
        demo_email = parts[1] if len(parts) > 1 else "demo@applykit.local"
        demo_uid = hashlib.md5(demo_email.encode("utf-8")).hexdigest()
        formatted_uid = f"{demo_uid[:8]}-{demo_uid[8:12]}-{demo_uid[12:16]}-{demo_uid[16:20]}-{demo_uid[20:32]}"
        return {"sub": formatted_uid, "email": demo_email, "role": "authenticated"}

    if has_live_jwt_secret:
        try:
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            if not payload.get("sub"):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject.")
            return payload
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired Supabase JWT: {exc}",
            ) from exc

    # Fallback verification via Supabase Auth API if SUPABASE_URL is set without JWT_SECRET
    sb = get_supabase()
    if sb:
        try:
            user_res = sb.auth.get_user(token)
            if user_res and getattr(user_res, "user", None):
                u = user_res.user
                return {"sub": str(u.id), "email": u.email or ""}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session token.",
            ) from exc

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: valid Bearer JWT required.",
    )


def _extract_bearer_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    cookie_token = request.cookies.get("applykit_token")
    if cookie_token:
        return cookie_token.strip()
    return None


async def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    """
    Returns enriched user profile dict if a valid Bearer/cookie token is present.
    If an Authorization: Bearer header IS explicitly supplied and invalid/expired, rejects with 401!
    """
    auth_header = request.headers.get("Authorization", "")
    explicit_bearer = auth_header.lower().startswith("bearer ")
    token = _extract_bearer_token(request)
    if not token:
        return None
    try:
        claims = verify_supabase_jwt(token)
        uid = claims["sub"]
        email = claims.get("email", "")
        profile = get_or_create_profile(uid, email=email)
        return profile
    except HTTPException:
        if explicit_bearer:
            raise
        return None


async def require_authenticated_user(request: Request) -> Dict[str, Any]:
    """Strict dependency requiring a valid Supabase JWT (401 otherwise)."""
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Sign in with Google to continue.",
        )
    claims = verify_supabase_jwt(token)
    return get_or_create_profile(claims["sub"], email=claims.get("email", ""))


def verify_admin_basic_auth(credentials: HTTPBasicCredentials = Depends(http_basic)) -> str:
    expected_user = os.getenv("ADMIN_USERNAME", "admin")
    expected_pass = os.getenv("ADMIN_PASSWORD", "change_me_strong_password_2026")
    ok_user = secrets.compare_digest(credentials.username.encode("utf-8"), expected_user.encode("utf-8"))
    ok_pass = secrets.compare_digest(credentials.password.encode("utf-8"), expected_pass.encode("utf-8"))
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def verify_lemonsqueezy_hmac(raw_body: bytes, signature_header: str) -> bool:
    secret = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "").strip()
    if not secret or secret == "your_lemonsqueezy_webhook_signing_secret":
        logger.warning("LEMONSQUEEZY_WEBHOOK_SECRET not configured; rejecting unsigned webhook.")
        return False
    if not signature_header:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature_header.strip())


async def extract_validated_cv_upload(file: UploadFile) -> str:
    """Validate CV upload (PDF or DOCX, <=2 MB, magic bytes + MIME) and extract plain text."""
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No CV file selected.")

    content_type = (file.content_type or "").lower()
    fname = file.filename.lower()
    if content_type not in ALLOWED_CV_MIMES and not (fname.endswith(".pdf") or fname.endswith(".docx")):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF and DOCX files are supported.",
        )

    raw = await file.read()
    if len(raw) > MAX_CV_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="CV file exceeds maximum size of 2 MB.",
        )
    if len(raw) < 16:
        raise HTTPException(status_code=400, detail="Uploaded CV file appears empty.")

    # Magic-byte verification + text extraction
    if raw[:4] == b"%PDF" or fname.endswith(".pdf"):
        if raw[:4] != b"%PDF":
            raise HTTPException(status_code=400, detail="Invalid PDF file header.")
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            pages_text = [page.extract_text() or "" for page in reader.pages[:15]]
            extracted = "\n".join(pages_text).strip()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not read PDF text: {exc}") from exc
    elif raw[:2] == b"PK" and fname.endswith(".docx"):
        try:
            import docx

            doc = docx.Document(io.BytesIO(raw))
            extracted = "\n".join(p.text for p in doc.paragraphs if p.text).strip()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not read DOCX text: {exc}") from exc
    else:
        raise HTTPException(status_code=415, detail="File signature does not match PDF or DOCX.")

    if not extracted:
        raise HTTPException(status_code=400, detail="No readable text found in CV (scanned images are not supported).")
    return extracted[:15000]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Production HTTP Security Headers:
    - Content-Security-Policy (self + Tailwind CDN + Google AdSense + Supabase)
    - Strict-Transport-Security (HSTS)
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY (with Arena preview allowance if embedded in e2b preview)
    - Referrer-Policy & Permissions-Policy
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        supabase_url = os.getenv("SUPABASE_URL", "https://*.supabase.co")
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net "
            "https://pagead2.googlesyndication.com https://adservice.google.com https://www.googletagservices.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: https:; "
            f"connect-src 'self' {supabase_url} https://*.supabase.co https://pagead2.googlesyndication.com; "
            "frame-src https://googleads.g.doubleclick.net https://tpc.googlesyndication.com;"
        )
        response.headers["Content-Security-Policy"] = csp
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Respect X-Frame-Options DENY unless served on *.e2b.app live preview proxy
        host = request.headers.get("host", "")
        if not host.endswith(".e2b.app"):
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response
