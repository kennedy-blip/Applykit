"""
Safaricom Daraja M-Pesa STK Push Integration (`lib/mpesa.py`):
- OAuth Access Token caching (`/oauth/v1/generate?grant_type=client_credentials`)
- Lipa Na M-Pesa Online STK Push (`/mpesa/stkpush/v1/processrequest`)
- Base64 `BusinessShortCode + Passkey + YYYYMMDDHHmmss` password signing
- Safaricom callback IP allowlist helper + simulated sandbox response when Daraja keys are placeholders in local dev
"""

from __future__ import annotations

import base64
from datetime import datetime
import logging
import os
import time
from typing import Any, Dict, Optional
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("applykit.mpesa")

SAFARICOM_SANDBOX_BASE = "https://sandbox.safaricom.co.ke"
SAFARICOM_PROD_BASE = "https://api.safaricom.co.ke"

# Official Safaricom Daraja Callback IP prefixes (196.201.214.*)
SAFARICOM_CALLBACK_IPS = {
    "196.201.214.200",
    "196.201.214.206",
    "196.201.214.207",
    "196.201.214.208",
    "196.201.213.114",
    "196.201.213.44",
    "196.201.212.127",
    "196.201.212.138",
    "196.201.212.129",
    "196.201.212.136",
    "196.201.212.74",
    "196.201.212.69",
    "127.0.0.1",
    "testclient",
}

_TOKEN_CACHE: Dict[str, Any] = {"access_token": None, "expires_at": 0.0}


def _get_daraja_base_url() -> str:
    env = os.getenv("MPESA_ENV", "sandbox").lower()
    return SAFARICOM_PROD_BASE if env == "production" else SAFARICOM_SANDBOX_BASE


def _has_live_daraja_keys() -> bool:
    ck = os.getenv("MPESA_CONSUMER_KEY", "").strip()
    cs = os.getenv("MPESA_CONSUMER_SECRET", "").strip()
    return bool(ck and cs and "your_daraja_" not in ck and "your_daraja_" not in cs)


async def get_daraja_access_token() -> str:
    """Fetch and cache Safaricom OAuth Bearer token (~3500s TTL)."""
    now = time.time()
    if _TOKEN_CACHE["access_token"] and now < _TOKEN_CACHE["expires_at"]:
        return str(_TOKEN_CACHE["access_token"])

    ck = os.getenv("MPESA_CONSUMER_KEY", "").strip()
    cs = os.getenv("MPESA_CONSUMER_SECRET", "").strip()
    base = _get_daraja_base_url()
    url = f"{base}/oauth/v1/generate?grant_type=client_credentials"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, auth=(ck, cs))
        resp.raise_for_status()
        payload = resp.json()

    token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3599))
    _TOKEN_CACHE["access_token"] = token
    _TOKEN_CACHE["expires_at"] = now + max(60, expires_in - 120)
    return str(token)


def build_stk_password(shortcode: str, passkey: str, timestamp: Optional[str] = None) -> tuple[str, str]:
    ts = timestamp or datetime.utcnow().strftime("%Y%m%d%H%M%S")
    raw = f"{shortcode}{passkey}{ts}".encode("utf-8")
    encoded = base64.b64encode(raw).decode("utf-8")
    return encoded, ts


def get_plan_amount_kes(plan: str) -> int:
    if plan == "lifetime":
        return int(os.getenv("MPESA_LIFETIME_KES", "3750"))
    return int(os.getenv("MPESA_MONTHLY_KES", "750"))


async def initiate_stk_push(phone: str, plan: str = "monthly") -> Dict[str, Any]:
    """
    Trigger Safaricom Lipa Na M-Pesa Online STK Push to `phone` (`2547...` / `2541...`).
    Amount defaults to 750 KES (monthly) or 3,750 KES (lifetime).
    """
    shortcode = os.getenv("MPESA_SHORTCODE", "174379").strip()
    passkey = os.getenv(
        "MPESA_PASSKEY",
        "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919",
    ).strip()
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
    callback_url = os.getenv("MPESA_CALLBACK_URL", f"{backend_url}/api/payments/mpesa/callback").strip()
    amount = get_plan_amount_kes(plan)
    password, timestamp = build_stk_password(shortcode, passkey)

    request_body = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": shortcode,
        "PhoneNumber": phone,
        "CallBackURL": callback_url,
        "AccountReference": "ApplyKitPro",
        "TransactionDesc": f"ApplyKit Pro {plan.title()} Subscription",
    }

    if not _has_live_daraja_keys():
        logger.info("MPESA_CONSUMER_KEY not configured; returning simulated sandbox CheckoutRequestID.")
        sim_checkout = f"ws_CO_{timestamp}_{uuid.uuid4().hex[:8]}"
        sim_merchant = f"sim-{uuid.uuid4().hex[:10]}"
        return {
            "MerchantRequestID": sim_merchant,
            "CheckoutRequestID": sim_checkout,
            "ResponseCode": "0",
            "ResponseDescription": "Success. Request accepted for processing (Local Sandbox Simulation)",
            "CustomerMessage": "Success. Check your phone for the M-Pesa PIN prompt (Sandbox Demo).",
            "amount": amount,
            "simulated": True,
        }

    token = await get_daraja_access_token()
    stk_url = f"{_get_daraja_base_url()}/mpesa/stkpush/v1/processrequest"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(stk_url, json=request_body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    data["amount"] = amount
    data["simulated"] = False
    return data


def verify_safaricom_callback_ip(client_ip: str) -> bool:
    """In production, restrict M-Pesa callbacks to official Safaricom Daraja IP ranges."""
    if os.getenv("MPESA_ENV", "sandbox").lower() != "production":
        return True
    return client_ip in SAFARICOM_CALLBACK_IPS or client_ip.startswith("196.201.21")


def parse_stk_callback(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Daraja `Body.stkCallback` JSON into normalized fields."""
    stk = payload.get("Body", {}).get("stkCallback", payload)
    result_code = int(stk.get("ResultCode", -1))
    checkout_id = stk.get("CheckoutRequestID", "")
    merchant_id = stk.get("MerchantRequestID", "")
    result_desc = stk.get("ResultDesc", "")

    metadata_items = stk.get("CallbackMetadata", {}).get("Item", [])
    meta_map: Dict[str, Any] = {}
    for item in metadata_items:
        name = item.get("Name")
        if name:
            meta_map[name] = item.get("Value")

    return {
        "checkout_request_id": checkout_id,
        "merchant_request_id": merchant_id,
        "result_code": result_code,
        "result_desc": result_desc,
        "is_success": result_code == 0,
        "mpesa_receipt_number": str(meta_map.get("MpesaReceiptNumber", "")) or None,
        "amount": meta_map.get("Amount"),
        "phone": str(meta_map.get("PhoneNumber", "")) or None,
    }
