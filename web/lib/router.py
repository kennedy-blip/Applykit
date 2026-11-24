"""
Universal Discovery Router (`lib/router.py`):
Resolves `"⚡ Ask ApplyKit..."` queries + extension page context into the top 3 tools from `tools/registry.json`.

Strict 3-Tier Routing Priority:
1. Fast deterministic keyword/token match against `tools/registry.json` (7 visible + hidden vault tools).
2. Context rules (e.g., `platform="upwork_job"` -> `[ats-checker, cover-letter-generator, scam-detector]`;
   `platform="linkedin_job"` -> `[ats-checker, cover-letter-generator, interview-questions-generator]`).
3. Groq `llama-3.1-8b-instant` AI intent routing ONLY as fallback when keyword + context yield weak/empty match.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from lib.ai_client import generate
from lib.prompts import sanitize_prompt_field
from lib.supabase_client import get_supabase

logger = logging.getLogger("applykit.router")

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "tools" / "registry.json"

_REGISTRY_CACHE: Optional[List[Dict[str, Any]]] = None


def load_registry(force_reload: bool = False) -> List[Dict[str, Any]]:
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None and not force_reload:
        return _REGISTRY_CACHE
    with REGISTRY_PATH.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    _REGISTRY_CACHE = payload.get("tools", [])
    return _REGISTRY_CACHE


def get_visible_tools() -> List[Dict[str, Any]]:
    return [t for t in load_registry() if t.get("visible") is True]


def get_tool_by_id(tool_id: str) -> Optional[Dict[str, Any]]:
    for tool in load_registry():
        if tool["id"] == tool_id:
            return tool
    return None


def _public_tool_card(tool: Dict[str, Any], match_reason: str = "Keyword match") -> Dict[str, Any]:
    """Strip internal prompt_template when returning discovery cards to frontend/extension."""
    return {
        "id": tool["id"],
        "name": tool["name"],
        "icon": tool.get("icon", "⚡"),
        "category": tool.get("category", "Vault"),
        "visible": bool(tool.get("visible", False)),
        "url": tool.get("url"),
        "requires_ai": bool(tool.get("requires_ai", True)),
        "description": tool.get("description", ""),
        "input_label": tool.get("input_label", "Describe your situation or paste job/CV details"),
        "input_placeholder": tool.get("input_placeholder", "Paste details here..."),
        "match_reason": match_reason,
    }


def _detect_platform(context: str = "", url: str = "") -> str:
    ctx = (context or "").lower().strip()
    u = (url or "").lower()
    if ctx in {"upwork_job", "linkedin_job", "upwork_profile", "generic_job"}:
        return ctx
    if "upwork.com/jobs" in u or "upwork.com/freelance-jobs" in u or "upwork.com/nx/search/jobs" in u:
        return "upwork_job"
    if "linkedin.com/jobs" in u:
        return "linkedin_job"
    if "fuzu.com" in u or "brightermonday" in u or "indeed.com" in u or "wellfound.com" in u:
        return "generic_job"
    return ctx or "web"


def _keyword_score(tool: Dict[str, Any], query_lower: str, tokens: List[str]) -> int:
    score = 0
    tid = tool["id"].lower()
    name_l = tool["name"].lower()
    desc_l = tool.get("description", "").lower()
    keywords = [k.lower() for k in tool.get("keywords", [])]

    if query_lower == tid or query_lower == name_l:
        score += 100

    for kw in keywords:
        if kw in query_lower:
            score += 40
        elif query_lower in kw and len(query_lower) >= 4:
            score += 32

    for tok in tokens:
        if len(tok) < 3:
            continue
        if any(tok == kw or kw.startswith(tok) or tok in kw for kw in keywords):
            score += 18
        if tok in name_l:
            score += 15
        if tok in tid:
            score += 14
        if tok in desc_l:
            score += 5
    return score


def route_tools(
    query: str = "",
    context: str = "",
    url: str = "",
    user_id: Optional[str] = None,
    limit: int = 3,
) -> Dict[str, Any]:
    """
    Universal router returning top `limit` (default 3) recommended tools.
    """
    tools = load_registry()
    clean_query = sanitize_prompt_field(query or "", max_len=240).strip()
    q_lower = clean_query.lower()
    tokens = re.findall(r"[a-z0-9]+", q_lower)
    platform = _detect_platform(context=context, url=url)

    matched_cards: List[Dict[str, Any]] = []
    strategy = "context"

    # Tier 1: Keyword matching when user typed a query
    if q_lower:
        scored = []
        for t in tools:
            sc = _keyword_score(t, q_lower, tokens)
            if sc > 0:
                scored.append((sc, t))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if scored and scored[0][0] >= 14:
            strategy = "keyword"
            matched_cards = [
                _public_tool_card(
                    t,
                    match_reason="Hidden Vault Tool" if not t.get("visible") else "Showcase Tool",
                )
                for _, t in scored[:limit]
            ]

    # Tier 2: Platform / Page Context rules (Upwork / LinkedIn / Job page or empty query)
    if not matched_cards and platform in {"upwork_job", "linkedin_job", "generic_job"}:
        strategy = "context"
        if platform == "upwork_job":
            preferred_ids = ["ats-checker", "cover-letter-generator", "scam-detector"]
        elif platform == "linkedin_job":
            preferred_ids = ["ats-checker", "cover-letter-generator", "interview-questions-generator"]
        else:
            preferred_ids = ["ats-checker", "scam-detector", "cover-letter-generator"]

        by_id = {t["id"]: t for t in tools}
        matched_cards = [
            _public_tool_card(by_id[tid], match_reason=f"Recommended for {platform.replace('_', ' ').title()}")
            for tid in preferred_ids
            if tid in by_id
        ][:limit]

    # Tier 3: Groq 8B AI intent routing fallback when user typed an unusual natural-language quest
    if not matched_cards and q_lower:
        strategy = "ai_fallback"
        catalog = [
            {"id": t["id"], "name": t["name"], "desc": t["description"][:90]}
            for t in tools
        ]
        router_prompt = (
            "Select the top 3 best tool IDs from this ApplyKit catalog for the user's career quest.\n"
            f"Catalog: {json.dumps(catalog)}\n"
            f"<UNTRUSTED_USER_INPUT>{clean_query} (platform={platform})</UNTRUSTED_USER_INPUT>\n"
            'Return ONLY JSON: {"tool_ids": ["id1", "id2", "id3"]}'
        )
        try:
            res = generate(router_prompt, json_mode=True, prefer_70b=False, use_cache=True)
            picked_ids = res.get("tool_ids", []) if isinstance(res, dict) else []
            by_id = {t["id"]: t for t in tools}
            matched_cards = [
                _public_tool_card(by_id[tid], match_reason="AI Smart Recommendation")
                for tid in picked_ids
                if tid in by_id
            ][:limit]
        except Exception as exc:
            logger.warning("AI router fallback error: %s", exc)

    # Default showcase fallback if empty query on generic web page
    if not matched_cards:
        strategy = "default_showcase"
        default_ids = ["ats-checker", "cover-letter-generator", "paye-calculator-kenya-2026"]
        by_id = {t["id"]: t for t in tools}
        matched_cards = [
            _public_tool_card(by_id[tid], match_reason="Popular Tool")
            for tid in default_ids
            if tid in by_id
        ][:limit]

    # Log sanitized search query without PII
    if clean_query:
        sb = get_supabase()
        if sb:
            try:
                sb.table("search_logs").insert(
                    {
                        "user_id": user_id,
                        "query_sanitized": clean_query[:120],
                        "platform_context": platform,
                        "matched_tool_ids": [c["id"] for c in matched_cards],
                    }
                ).execute()
            except Exception:
                pass

    return {
        "query": clean_query,
        "platform": platform,
        "strategy": strategy,
        "tools": matched_cards,
        "vault_total": len(tools),
    }
