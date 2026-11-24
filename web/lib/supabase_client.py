"""
Supabase client singleton & safe fallback in-memory store for local dev / CI.
Uses SUPABASE_SERVICE_KEY strictly on the backend — never exposed to frontend or extension.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import uuid

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("applykit.supabase")

_supabase_client = None


def is_supabase_configured() -> bool:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    return bool(
        url
        and key
        and "your-project-ref" not in url
        and "example_" not in key
        and url.startswith("https://")
    )


def get_supabase():
    """Return initialized Supabase service-role client, or None if unconfigured."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    if not is_supabase_configured():
        return None
    try:
        from supabase import create_client

        _supabase_client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
        return _supabase_client
    except Exception as exc:
        logger.warning("Supabase client init skipped/failed: %s", exc)
        return None


def get_public_supabase_config() -> Dict[str, str]:
    """Return ONLY safe public anon config for browser Google OAuth."""
    url = os.getenv("SUPABASE_URL", "")
    anon = os.getenv("SUPABASE_ANON_KEY", "")
    configured = bool(
        url
        and anon
        and "your-project-ref" not in url
        and "example_" not in anon
        and url.startswith("https://")
    )
    return {
        "url": url if configured else "",
        "anon_key": anon if configured else "",
        "configured": "true" if configured else "false",
    }


# ---------------------------------------------------------------------------
# Local In-Memory Fallback Store (when SUPABASE_URL is not yet configured,
# ensuring `uvicorn main:app --reload` runs cleanly out-of-the-box)
# ---------------------------------------------------------------------------
_LOCAL_PROFILES: Dict[str, Dict[str, Any]] = {}
_LOCAL_APPS: Dict[str, List[Dict[str, Any]]] = {}
_LOCAL_MPESA: Dict[str, Dict[str, Any]] = {}
_LOCAL_WEBHOOKS: List[Dict[str, Any]] = []


def get_or_create_profile(user_id: str, email: str = "", full_name: str = "") -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    if sb:
        try:
            res = sb.table("profiles").select("*").eq("id", user_id).limit(1).execute()
            if res.data:
                profile = res.data[0]
                return _normalize_pro_expiry(profile, sb)
            payload = {
                "id": user_id,
                "email": email or f"{user_id[:8]}@applykit.user",
                "full_name": full_name or "ApplyKit Member",
                "is_pro": False,
                "pro_plan": "free",
                "ai_uses_this_month": 0,
                "bonus_generations": 0,
            }
            created = sb.table("profiles").insert(payload).execute()
            if created.data:
                return created.data[0]
        except Exception as exc:
            logger.warning("Supabase profile fetch failed, using fallback: %s", exc)

    if user_id not in _LOCAL_PROFILES:
        _LOCAL_PROFILES[user_id] = {
            "id": user_id,
            "email": email or f"{user_id[:8]}@applykit.local",
            "full_name": full_name or "ApplyKit User",
            "is_pro": False,
            "pro_plan": "free",
            "pro_expires_at": None,
            "ai_uses_this_month": 0,
            "ai_usage_reset_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "bonus_generations": 0,
            "referral_code": user_id[:8],
            "weekly_goal": 10,
            "created_at": now_iso,
        }
    return _normalize_pro_expiry(_LOCAL_PROFILES[user_id], None)


def _normalize_pro_expiry(profile: Dict[str, Any], sb: Any) -> Dict[str, Any]:
    """Automatically downgrade expired monthly Pro subscriptions on check."""
    if not profile.get("is_pro"):
        return profile
    if profile.get("pro_plan") == "lifetime":
        return profile
    expires_raw = profile.get("pro_expires_at")
    if expires_raw:
        try:
            exp = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                profile["is_pro"] = False
                profile["pro_plan"] = "free"
                if sb:
                    sb.table("profiles").update({"is_pro": False, "pro_plan": "free"}).eq("id", profile["id"]).execute()
        except ValueError:
            pass
    return profile


def set_pro_status_by_user_or_email(
    *,
    user_id: Optional[str] = None,
    email: Optional[str] = None,
    is_pro: bool = True,
    plan: str = "monthly",
    days: int = 30,
) -> Optional[Dict[str, Any]]:
    """Activate or revoke Pro status (+30 days for monthly, or null/far-future for lifetime)."""
    expires_at = (
        None
        if not is_pro
        else (
            (datetime.now(timezone.utc) + timedelta(days=36500)).isoformat()
            if plan == "lifetime"
            else (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        )
    )
    update_fields = {
        "is_pro": is_pro,
        "pro_plan": plan if is_pro else "free",
        "pro_expires_at": expires_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    sb = get_supabase()
    if sb:
        try:
            query = sb.table("profiles").update(update_fields)
            if user_id:
                res = query.eq("id", user_id).execute()
            elif email:
                res = query.eq("email", email.strip().lower()).execute()
            else:
                return None
            if res.data:
                return res.data[0]
        except Exception as exc:
            logger.error("Failed updating Supabase Pro status: %s", exc)

    # Fallback local store
    if user_id and user_id in _LOCAL_PROFILES:
        _LOCAL_PROFILES[user_id].update(update_fields)
        return _LOCAL_PROFILES[user_id]
    if email:
        target = email.strip().lower()
        for prof in _LOCAL_PROFILES.values():
            if prof.get("email", "").lower() == target:
                prof.update(update_fields)
                return prof
        # Pre-provision local profile by email for admin/webhook testing
        uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, target))
        prof = get_or_create_profile(uid, email=target)
        prof.update(update_fields)
        return prof
    return None


def increment_user_ai_usage(user_id: str) -> int:
    sb = get_supabase()
    prof = get_or_create_profile(user_id)
    new_count = int(prof.get("ai_uses_this_month", 0)) + 1
    if sb:
        try:
            sb.table("profiles").update({"ai_uses_this_month": new_count}).eq("id", user_id).execute()
            return new_count
        except Exception as exc:
            logger.warning("Supabase usage increment fallback: %s", exc)
    prof["ai_uses_this_month"] = new_count
    return new_count


def log_ai_audit(
    *,
    user_id: Optional[str],
    ip_hash: str,
    tool_id: str,
    input_hash: str,
    provider: str,
    model: str,
    cached: bool = False,
) -> None:
    sb = get_supabase()
    if sb:
        try:
            sb.table("ai_usage_logs").insert(
                {
                    "user_id": user_id,
                    "ip_hash": ip_hash,
                    "tool_id": tool_id,
                    "input_hash": input_hash,
                    "provider": provider,
                    "model": model,
                    "cached": cached,
                }
            ).execute()
        except Exception as exc:
            logger.debug("AI audit log skipped: %s", exc)


def delete_all_user_data(user_id: str) -> bool:
    """GDPR & Kenya DPA 'Delete My Data': purge profile, applications, logs & stored CVs."""
    sb = get_supabase()
    if sb:
        try:
            # Remove stored CV files under `{user_id}/`
            try:
                files = sb.storage.from_("cvs").list(user_id)
                if files:
                    paths = [f"{user_id}/{f['name']}" for f in files if f.get("name")]
                    if paths:
                        sb.storage.from_("cvs").remove(paths)
            except Exception:
                pass
            sb.table("applications").delete().eq("user_id", user_id).execute()
            sb.table("ai_usage_logs").delete().eq("user_id", user_id).execute()
            sb.table("profiles").delete().eq("id", user_id).execute()
        except Exception as exc:
            logger.error("Error deleting Supabase user data: %s", exc)
    _LOCAL_PROFILES.pop(user_id, None)
    _LOCAL_APPS.pop(user_id, None)
    return True


# ---------------------------------------------------------------------------
# Applications Helpers (Supabase + Local Dev Fallback)
# ---------------------------------------------------------------------------
def list_user_applications(user_id: str) -> List[Dict[str, Any]]:
    sb = get_supabase()
    if sb:
        try:
            res = (
                sb.table("applications")
                .select("*")
                .eq("user_id", user_id)
                .order("applied_at", desc=True)
                .execute()
            )
            return res.data or []
        except Exception as exc:
            logger.warning("Fallback list_user_applications: %s", exc)
    return list(_LOCAL_APPS.get(user_id, []))


def create_user_application(user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    record = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "job_title": data.get("job_title", "Untitled Role")[:200],
        "company": (data.get("company") or "Unknown Client")[:160],
        "platform": (data.get("platform") or "Manual")[:60],
        "job_url": (data.get("job_url") or "")[:1000],
        "salary": (data.get("salary") or "")[:120],
        "status": data.get("status") if data.get("status") in {"Saved", "Applied", "Interview", "Offer", "Rejected"} else "Applied",
        "match_score": data.get("match_score"),
        "scam_risk": data.get("scam_risk") if data.get("scam_risk") in {"Low", "Medium", "High"} else None,
        "private_notes": (data.get("private_notes") or "")[:2000],
        "applied_at": data.get("applied_at") or now.isoformat(),
        "interview_at": data.get("interview_at"),
        "followup_due_at": (now + timedelta(days=7)).isoformat(),
        "followup_done": False,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    sb = get_supabase()
    if sb:
        try:
            res = sb.table("applications").insert(record).execute()
            if res.data:
                return res.data[0]
        except Exception as exc:
            logger.warning("Fallback create_user_application: %s", exc)
    _LOCAL_APPS.setdefault(user_id, []).insert(0, record)
    return record


def update_user_application(user_id: str, app_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {
        "job_title",
        "company",
        "platform",
        "job_url",
        "salary",
        "status",
        "match_score",
        "scam_risk",
        "private_notes",
        "interview_at",
        "followup_done",
    }
    clean = {k: v for k, v in updates.items() if k in allowed}
    clean["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    if sb:
        try:
            res = (
                sb.table("applications")
                .update(clean)
                .eq("id", app_id)
                .eq("user_id", user_id)
                .execute()
            )
            if res.data:
                return res.data[0]
        except Exception as exc:
            logger.warning("Fallback update_user_application: %s", exc)

    for item in _LOCAL_APPS.get(user_id, []):
        if item["id"] == app_id:
            item.update(clean)
            return item
    return None


def delete_user_application(user_id: str, app_id: str) -> bool:
    sb = get_supabase()
    if sb:
        try:
            sb.table("applications").delete().eq("id", app_id).eq("user_id", user_id).execute()
            return True
        except Exception as exc:
            logger.warning("Fallback delete_user_application: %s", exc)
    apps = _LOCAL_APPS.get(user_id, [])
    before = len(apps)
    _LOCAL_APPS[user_id] = [a for a in apps if a["id"] != app_id]
    return len(_LOCAL_APPS[user_id]) < before


# ---------------------------------------------------------------------------
# M-Pesa & Webhook Persistence Helpers
# ---------------------------------------------------------------------------
def save_mpesa_transaction(tx: Dict[str, Any]) -> Dict[str, Any]:
    tx.setdefault("id", str(uuid.uuid4()))
    tx.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    sb = get_supabase()
    if sb:
        try:
            res = sb.table("mpesa_transactions").insert(tx).execute()
            if res.data:
                tx = res.data[0]
        except Exception as exc:
            logger.warning("Fallback save_mpesa_transaction: %s", exc)
    key = tx.get("checkout_request_id") or tx["id"]
    _LOCAL_MPESA[key] = tx
    return tx


def update_mpesa_transaction(checkout_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    if sb:
        try:
            res = (
                sb.table("mpesa_transactions")
                .update(updates)
                .eq("checkout_request_id", checkout_id)
                .execute()
            )
            if res.data:
                _LOCAL_MPESA[checkout_id] = res.data[0]
                return res.data[0]
        except Exception as exc:
            logger.warning("Fallback update_mpesa_transaction: %s", exc)
    if checkout_id in _LOCAL_MPESA:
        _LOCAL_MPESA[checkout_id].update(updates)
        return _LOCAL_MPESA[checkout_id]
    return None


def get_mpesa_transaction(checkout_id: str) -> Optional[Dict[str, Any]]:
    sb = get_supabase()
    if sb:
        try:
            res = (
                sb.table("mpesa_transactions")
                .select("*")
                .eq("checkout_request_id", checkout_id)
                .limit(1)
                .execute()
            )
            if res.data:
                return res.data[0]
        except Exception as exc:
            logger.warning("Fallback get_mpesa_transaction: %s", exc)
    return _LOCAL_MPESA.get(checkout_id)


def list_manual_till_submissions() -> List[Dict[str, Any]]:
    sb = get_supabase()
    if sb:
        try:
            res = (
                sb.table("mpesa_transactions")
                .select("*")
                .eq("payment_method", "manual_till")
                .order("created_at", desc=True)
                .limit(50)
                .execute()
            )
            if res.data is not None:
                return res.data
        except Exception:
            pass
    return [t for t in _LOCAL_MPESA.values() if t.get("payment_method") == "manual_till"]


def record_webhook_audit(entry: Dict[str, Any]) -> None:
    sb = get_supabase()
    if sb:
        try:
            sb.table("payment_webhooks").insert(entry).execute()
            return
        except Exception:
            pass
    _LOCAL_WEBHOOKS.append(entry)
