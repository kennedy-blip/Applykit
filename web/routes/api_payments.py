"""
Real Cashflow Payments Routes (`routes/api_payments.py`):
- POST `/api/payments/mpesa/stk-push` (Safaricom Daraja STK Push, ^254[17]\\d{8}$ regex, 3/hour/IP rate limit)
- POST `/api/payments/mpesa/callback` (Safaricom IP verification, ResultCode=0 activates `is_pro=True` +30 days)
- GET  `/api/payments/verify?checkout_id=...` (polled every 3s by frontend modal)
- POST `/api/payments/mpesa/manual-till` (Manual Till fallback submission -> admin approves)
- POST `/api/payments/lemonsqueezy/webhook` (HMAC SHA-256 verified global $6/mo & $29 lifetime webhook)
- POST `/api/payments/admin/toggle-pro` (Basic Auth protected admin manual Pro activation/revocation)
"""

import json
import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from lib.mpesa import (
    get_plan_amount_kes,
    initiate_stk_push,
    parse_stk_callback,
    verify_safaricom_callback_ip,
)
from lib.security import (
    get_client_ip,
    get_optional_user,
    limiter,
    normalize_kenya_phone,
    verify_admin_basic_auth,
    verify_lemonsqueezy_hmac,
)
from lib.supabase_client import (
    get_mpesa_transaction,
    record_webhook_audit,
    save_mpesa_transaction,
    set_pro_status_by_user_or_email,
    update_mpesa_transaction,
)

logger = logging.getLogger("applykit.payments")

router = APIRouter(prefix="/api/payments", tags=["Payments (M-Pesa + Lemon Squeezy)"])


class MpesaStkPushRequest(BaseModel):
    phone: str = Field(..., min_length=9, max_length=16, description="Safaricom number e.g. 254712345678")
    plan: str = Field(default="monthly", pattern="^(monthly|lifetime)$")
    email: Optional[str] = Field(default=None, max_length=160)


class ManualTillSubmitRequest(BaseModel):
    mpesa_code: str = Field(..., min_length=8, max_length=16, description="M-Pesa confirmation code e.g. SJK82LMN4P")
    phone: str = Field(..., min_length=9, max_length=16)
    email: str = Field(..., min_length=5, max_length=160)
    plan: str = Field(default="monthly", pattern="^(monthly|lifetime)$")


class AdminToggleProRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=160)
    is_pro: bool = True
    plan: str = Field(default="monthly", pattern="^(monthly|lifetime)$")
    checkout_id: Optional[str] = None


@router.post("/mpesa/stk-push")
@limiter.limit("3/hour")
async def api_mpesa_stk_push(
    payload: MpesaStkPushRequest,
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> Dict[str, Any]:
    phone = normalize_kenya_phone(payload.phone)
    daraja_res = await initiate_stk_push(phone=phone, plan=payload.plan)
    checkout_id = daraja_res.get("CheckoutRequestID", "")
    merchant_id = daraja_res.get("MerchantRequestID", "")
    amount = get_plan_amount_kes(payload.plan)

    tx = save_mpesa_transaction(
        {
            "user_id": user["id"] if user else None,
            "email": (user.get("email") if user else payload.email) or "",
            "phone": phone,
            "amount": amount,
            "plan": payload.plan,
            "payment_method": "stk_push",
            "merchant_request_id": merchant_id,
            "checkout_request_id": checkout_id,
            "status": "pending",
        }
    )

    return {
        "ok": True,
        "checkout_request_id": checkout_id,
        "merchant_request_id": merchant_id,
        "amount_kes": amount,
        "plan": payload.plan,
        "customer_message": daraja_res.get(
            "CustomerMessage",
            "STK Push sent! Enter your M-Pesa PIN on your phone to unlock ApplyKit Pro.",
        ),
        "simulated": bool(daraja_res.get("simulated")),
        "transaction_id": tx.get("id"),
    }


@router.post("/mpesa/callback")
async def api_mpesa_callback(request: Request) -> Dict[str, Any]:
    client_ip = get_client_ip(request)
    if not verify_safaricom_callback_ip(client_ip):
        logger.warning("Rejected M-Pesa callback from untrusted IP: %s", client_ip)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted callback origin IP.")

    raw_payload = await request.json()
    parsed = parse_stk_callback(raw_payload)
    checkout_id = parsed["checkout_request_id"]
    if not checkout_id:
        raise HTTPException(status_code=400, detail="Missing CheckoutRequestID in callback.")

    existing = get_mpesa_transaction(checkout_id)
    new_status = "success" if parsed["is_success"] else "failed"

    updated_tx = update_mpesa_transaction(
        checkout_id,
        {
            "status": new_status,
            "result_code": parsed["result_code"],
            "result_desc": parsed["result_desc"],
            "mpesa_receipt_number": parsed["mpesa_receipt_number"],
            "raw_callback": raw_payload,
        },
    )

    if parsed["is_success"]:
        tx_ref = updated_tx or existing or {}
        plan = tx_ref.get("plan", "monthly")
        days = 36500 if plan == "lifetime" else 30
        set_pro_status_by_user_or_email(
            user_id=tx_ref.get("user_id"),
            email=tx_ref.get("email"),
            is_pro=True,
            plan=plan,
            days=days,
        )
        logger.info("M-Pesa payment confirmed for checkout_id=%s receipt=%s", checkout_id, parsed["mpesa_receipt_number"])

    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.get("/verify")
async def api_verify_payment(checkout_id: str = Query(..., min_length=4, max_length=120)) -> Dict[str, Any]:
    tx = get_mpesa_transaction(checkout_id)
    if not tx:
        return {"ok": False, "status": "not_found", "is_pro": False}
    return {
        "ok": True,
        "checkout_request_id": checkout_id,
        "status": tx.get("status", "pending"),
        "is_pro": tx.get("status") == "success",
        "receipt": tx.get("mpesa_receipt_number"),
        "plan": tx.get("plan", "monthly"),
    }


@router.post("/mpesa/manual-till")
@limiter.limit("5/hour")
async def api_submit_manual_till(
    payload: ManualTillSubmitRequest,
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> Dict[str, Any]:
    code = re.sub(r"[^A-Z0-9]", "", payload.mpesa_code.upper())
    if len(code) < 8:
        raise HTTPException(status_code=422, detail="Enter a valid 10-character M-Pesa confirmation code (e.g. SJK82LMN4P).")
    phone = normalize_kenya_phone(payload.phone)
    checkout_ref = f"TILL_{code}"

    tx = save_mpesa_transaction(
        {
            "user_id": user["id"] if user else None,
            "email": payload.email.strip().lower(),
            "phone": phone,
            "amount": get_plan_amount_kes(payload.plan),
            "plan": payload.plan,
            "payment_method": "manual_till",
            "checkout_request_id": checkout_ref,
            "manual_till_code": code,
            "status": "manual_review",
        }
    )
    return {
        "ok": True,
        "message": f"M-Pesa code {code} received! Our admin queue verifies manual Till payments shortly.",
        "reference": checkout_ref,
        "transaction_id": tx.get("id"),
    }


@router.post("/lemonsqueezy/webhook")
async def api_lemonsqueezy_webhook(request: Request) -> Dict[str, Any]:
    raw_body = await request.body()
    signature = request.headers.get("X-Signature", "")
    if not verify_lemonsqueezy_hmac(raw_body, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Lemon Squeezy webhook HMAC signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Malformed webhook JSON.") from exc

    meta = payload.get("meta", {})
    event_name = meta.get("event_name", "unknown")
    custom_data = meta.get("custom_data", {}) or {}
    attrs = payload.get("data", {}).get("attributes", {}) or {}

    customer_email = (attrs.get("user_email") or custom_data.get("email") or "").strip().lower()
    user_id = custom_data.get("user_id")
    variant_name = (attrs.get("first_order_item", {}).get("variant_name") or attrs.get("variant_name") or "").lower()
    total_cents = int(attrs.get("total", 600) or 600)
    plan = "lifetime" if ("lifetime" in variant_name or total_cents >= 2500) else "monthly"

    record_webhook_audit(
        {
            "provider": "lemonsqueezy",
            "event_name": event_name,
            "order_id": str(payload.get("data", {}).get("id", "")),
            "customer_email": customer_email,
            "user_id": user_id,
            "amount_cents": total_cents,
            "currency": attrs.get("currency", "USD"),
            "plan": plan,
            "raw_payload": payload,
        }
    )

    if event_name in {"order_created", "subscription_created", "subscription_payment_success"}:
        set_pro_status_by_user_or_email(
            user_id=user_id,
            email=customer_email or None,
            is_pro=True,
            plan=plan,
            days=36500 if plan == "lifetime" else 30,
        )
    elif event_name in {"subscription_expired", "order_refunded"}:
        set_pro_status_by_user_or_email(
            user_id=user_id,
            email=customer_email or None,
            is_pro=False,
            plan="free",
        )

    return {"ok": True, "event": event_name, "plan": plan}


@router.post("/admin/toggle-pro")
async def api_admin_toggle_pro(
    payload: AdminToggleProRequest,
    _admin: str = Depends(verify_admin_basic_auth),
) -> Dict[str, Any]:
    updated = set_pro_status_by_user_or_email(
        email=payload.email.strip().lower(),
        is_pro=payload.is_pro,
        plan=payload.plan,
        days=36500 if payload.plan == "lifetime" else 30,
    )
    if payload.checkout_id:
        update_mpesa_transaction(payload.checkout_id, {"status": "success" if payload.is_pro else "failed"})
    return {
        "ok": True,
        "profile": updated,
        "message": f"Set is_pro={payload.is_pro} ({payload.plan}) for {payload.email}",
    }
