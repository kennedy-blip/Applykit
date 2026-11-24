"""
Dynamic On-The-Fly Vault Tool Runner (`lib/dynamic_runner.py`):
Executes any hidden vault tool (or showcase AI tool via unified `/api/execute`) directly inside
the command palette / browser extension widget without needing a dedicated HTML page.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import HTTPException, Request, status

from lib.ai_client import generate, get_last_ai_meta
from lib.limits import check_and_consume_ai_quota
from lib.prompts import (
    build_ats_prompt,
    build_cover_letter_prompt,
    build_interview_qs_prompt,
    build_scam_check_prompt,
    build_vault_tool_prompt,
)
from lib.router import get_tool_by_id
from lib.security import hash_text
from lib.supabase_client import log_ai_audit


def execute_tool(
    *,
    request: Request,
    user: Optional[Dict[str, Any]],
    tool_id: str,
    user_input: str,
    cv_text: str = "",
    page_context: str = "",
    tone: str = "Professional & Direct",
) -> Dict[str, Any]:
    tool = get_tool_by_id(tool_id)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown ApplyKit tool '{tool_id}'.",
        )

    if not tool.get("requires_ai", True) and tool.get("url"):
        return {
            "tool": {"id": tool["id"], "name": tool["name"], "url": tool.get("url")},
            "redirect_url": tool["url"],
            "result": None,
        }

    # Strictly enforce Free vs Pro limits BEFORE calling AI
    quota = check_and_consume_ai_quota(request, user)
    prefer_70b = quota["prefer_70b"]

    # Route specialized showcase AI tools or generic hidden vault prompt_template
    if tool_id == "ats-checker":
        prompt = build_ats_prompt(cv_text=cv_text or user_input, jd_text=page_context or user_input)
    elif tool_id == "cover-letter-generator":
        prompt = build_cover_letter_prompt(cv_text=cv_text or user_input, jd_text=page_context or user_input, tone=tone)
    elif tool_id == "scam-detector":
        prompt = build_scam_check_prompt(job_text=user_input or page_context, client_meta=page_context)
    elif tool_id == "interview-questions-generator":
        prompt = build_interview_qs_prompt(jd_text=user_input or page_context, cv_text=cv_text)
    else:
        template = tool.get("prompt_template") or "Provide concise actionable career guidance in JSON."
        combined_input = f"{user_input}\n\n{cv_text}".strip()
        prompt = build_vault_tool_prompt(
            tool_name=tool["name"],
            prompt_template=template,
            user_input=combined_input,
            page_context=page_context,
        )

    ai_result = generate(prompt=prompt, json_mode=True, prefer_70b=prefer_70b, use_cache=True)
    meta = get_last_ai_meta()

    log_ai_audit(
        user_id=user["id"] if user else None,
        ip_hash=quota["ip_hash"],
        tool_id=tool_id,
        input_hash=hash_text(f"{user_input}:{cv_text}:{page_context}"),
        provider=meta["provider"],
        model=meta["model"],
        cached=meta["cached"],
    )

    share_summary = (
        ai_result.get("summary")
        or ai_result.get("verdict_headline")
        or ai_result.get("opening_hook")
        or f"Just ran {tool['name']} on ApplyKit!"
    )
    wa_text = f"⚡ {tool['name']} (ApplyKit): {share_summary[:180]} — Try free at https://applykit.onrender.com"
    whatsapp_url = f"https://wa.me/?text={quote(wa_text)}"

    return {
        "tool": {
            "id": tool["id"],
            "name": tool["name"],
            "icon": tool.get("icon", "⚡"),
            "visible": bool(tool.get("visible", False)),
        },
        "result": ai_result,
        "whatsapp_share_url": whatsapp_url,
        "quota": {
            "is_pro": quota["is_pro"],
            "remaining": quota["remaining"],
            "show_ads": quota["show_ads"],
            "model_tier": "Llama-3.3-70B Pro" if prefer_70b else "Llama-3.1-8B Free",
        },
    }
