"""
Strict Free vs Premium Quota Enforcement (`lib/limits.py`):
FREE (Ad-supported):
- Unlimited discovery search (`/api/router`)
- Unlimited pure-JS tools (Freelance Rate, PAYE 2026, Invoice Generator)
- 1 anonymous AI check per IP -> then Login Wall (`code="LOGIN_REQUIRED"`)
- 5 AI generations/month (+ referral bonus_generations) for logged-in free users -> then UpgradeModal (`code="UPGRADE_REQUIRED"`)
- Free users run fast `llama-3.1-8b-instant` (`prefer_70b=False`); Pro users run `llama-3.3-70b-versatile` (`prefer_70b=True`)
- Dashboard capped at 20 saved applications for Free -> unlimited for Pro
- Abuse guard: auto-block IPs exceeding burst abuse threshold
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status

from lib.security import hash_ip
from lib.supabase_client import (
    get_supabase,
    increment_user_ai_usage,
    list_user_applications,
)

FREE_ANON_AI_LIMIT = 1
FREE_LOGGED_MONTHLY_LIMIT = 5
FREE_DASHBOARD_APP_LIMIT = 20
ABUSE_IP_DAILY_CAP = 80

# Local IP counters for anonymous 1-check wall + anti-abuse
_ANON_IP_USES: Dict[str, int] = {}
_ABUSE_IP_WINDOW: Dict[str, tuple[float, int]] = {}


def _check_ip_abuse(ip_hash: str) -> None:
    now = time.time()
    ts, count = _ABUSE_IP_WINDOW.get(ip_hash, (now, 0))
    if now - ts > 86400:
        ts, count = now, 0
    count += 1
    _ABUSE_IP_WINDOW[ip_hash] = (ts, count)
    if count > ABUSE_IP_DAILY_CAP:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "IP_BLOCKED_ABUSE",
                "message": "Automated abuse threshold reached from this network. Try again tomorrow or sign in to Pro.",
            },
        )


def _get_anon_ip_count(ip_hash: str) -> int:
    sb = get_supabase()
    if sb:
        try:
            res = (
                sb.table("ai_usage_logs")
                .select("id", count="exact")
                .eq("ip_hash", ip_hash)
                .is_("user_id", "null")
                .execute()
            )
            if res.count is not None:
                return int(res.count)
        except Exception:
            pass
    return _ANON_IP_USES.get(ip_hash, 0)


def check_and_consume_ai_quota(
    request: Request,
    user: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Validate quota BEFORE calling AI, and return execution entitlements:
    `{"is_pro": bool, "prefer_70b": bool, "remaining": int | None, "ip_hash": str}`
    Raises HTTP 402 / 401 structured JSON error when Login Wall or UpgradeModal must trigger.
    """
    ip_hashed = hash_ip(request)
    _check_ip_abuse(ip_hashed)

    # 1. Anonymous visitor: allow 1 free check by IP, then trigger Login Wall
    if not user:
        used_anon = _get_anon_ip_count(ip_hashed)
        if used_anon >= FREE_ANON_AI_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "LOGIN_REQUIRED",
                    "message": "You've used your 1 free instant check! Sign in free with Google to unlock 5 AI generations/month + Application Tracker.",
                    "used": used_anon,
                    "limit": FREE_ANON_AI_LIMIT,
                },
            )
        _ANON_IP_USES[ip_hashed] = used_anon + 1
        return {
            "is_pro": False,
            "prefer_70b": False,
            "remaining": 0,
            "ip_hash": ip_hashed,
            "show_ads": True,
        }

    # 2. Pro user: unlimited AI on 70B flagship model, zero ads
    if bool(user.get("is_pro")):
        return {
            "is_pro": True,
            "prefer_70b": True,
            "remaining": None,
            "ip_hash": ip_hashed,
            "show_ads": False,
        }

    # 3. Logged-in Free user: 5 generations/month + referral bonus (+5 per invite)
    used = int(user.get("ai_uses_this_month", 0))
    bonus = int(user.get("bonus_generations", 0))
    allowed = FREE_LOGGED_MONTHLY_LIMIT + bonus
    if used >= allowed:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "UPGRADE_REQUIRED",
                "message": f"You've reached your {allowed} free AI generations this month. Upgrade to ApplyKit Pro (750 KES/mo via M-Pesa or $6/mo Global) for unlimited Llama-3.3-70B access, all 60+ Vault Tools & zero ads!",
                "used": used,
                "limit": allowed,
            },
        )

    new_used = increment_user_ai_usage(user["id"])
    return {
        "is_pro": False,
        "prefer_70b": False,
        "remaining": max(0, allowed - new_used),
        "ip_hash": ip_hashed,
        "show_ads": True,
    }


def check_dashboard_app_limit(user: Dict[str, Any]) -> None:
    """Enforce max 20 saved applications for Free accounts; unlimited for Pro."""
    if bool(user.get("is_pro")):
        return
    existing = list_user_applications(user["id"])
    if len(existing) >= FREE_DASHBOARD_APP_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "UPGRADE_REQUIRED",
                "message": f"Free accounts can track up to {FREE_DASHBOARD_APP_LIMIT} job applications. Upgrade to ApplyKit Pro for unlimited Kanban tracking, CSV export & WhatsApp reminders.",
                "used": len(existing),
                "limit": FREE_DASHBOARD_APP_LIMIT,
            },
        )


def reset_test_anon_limits() -> None:
    """Helper for automated tests."""
    _ANON_IP_USES.clear()
    _ABUSE_IP_WINDOW.clear()
