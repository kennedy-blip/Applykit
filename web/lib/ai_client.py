"""
Unified AI Layer for ApplyKit (`lib/ai_client.py`):
- Primary: Groq SDK (`llama-3.3-70b-versatile` for Pro / primary, fallback `llama-3.1-8b-instant` for Free/fast)
- Secondary Fallback on HTTP 429 / 5xx / network error: OpenRouter via OpenAI SDK
  (`base_url="https://openrouter.ai/api/v1"`, models `meta-llama/llama-3.3-70b-instruct:free`, `mistralai/mistral-7b-instruct:free`)
- 24-hour in-memory hash cache to prevent duplicate quota burn on identical CV+JD inputs
- Strict JSON mode parsing (`json.loads`), output truncation, zero secret leakage
- Deterministic local heuristic fallback ONLY when neither GROQ_API_KEY nor OPENROUTER_API_KEY is configured in `.env`,
  so local development / QA smoke tests work immediately while production uses live Groq/OpenRouter.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv
from groq import Groq
from openai import OpenAI

from lib.prompts import PROMPT_INJECTION_SYSTEM_GUARD

load_dotenv()

logger = logging.getLogger("applykit.ai")

GROQ_MODEL_PRIMARY_70B = "llama-3.3-70b-versatile"
GROQ_MODEL_FAST_8B = "llama-3.1-8b-instant"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL_70B = "meta-llama/llama-3.3-70b-instruct:free"
OPENROUTER_MODEL_MISTRAL = "mistralai/mistral-7b-instruct:free"

CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h cache for identical input hash
MAX_OUTPUT_CHARS = 16000

_RESPONSE_CACHE: Dict[str, Tuple[float, Any, Dict[str, Any]]] = {}

# Track last execution metadata for audit logging without changing simple `generate(prompt, json_mode)` return contract
_LAST_META: Dict[str, Any] = {"provider": "none", "model": "none", "cached": False}


def get_last_ai_meta() -> Dict[str, Any]:
    return dict(_LAST_META)


def _is_valid_key(val: Optional[str], placeholder_prefix: str) -> bool:
    if not val:
        return False
    v = val.strip()
    return bool(v and placeholder_prefix not in v and "your_" not in v)


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Parse JSON safely, stripping optional markdown fences if a free model wraps output."""
    truncated = (raw_text or "").strip()[:MAX_OUTPUT_CHARS]
    # Scrub accidental key echo patterns
    truncated = re.sub(r"(gsk_[A-Za-z0-9]{16,}|sk-or-v1-[A-Za-z0-9]{16,})", "[REDACTED]", truncated)

    try:
        parsed = json.loads(truncated)
        if isinstance(parsed, dict):
            return parsed
        return {"result": parsed}
    except json.JSONDecodeError:
        pass

    # Extract first {...} block
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", truncated, flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        parsed = json.loads(fenced)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = fenced.find("{")
    end = fenced.rfind("}")
    if start != -1 and end != -1 and end > start:
        parsed = json.loads(fenced[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Model response did not contain valid JSON.")


def _call_groq(prompt: str, json_mode: bool, prefer_70b: bool) -> Tuple[str, str]:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    client = Groq(api_key=api_key)
    models = (
        [GROQ_MODEL_PRIMARY_70B, GROQ_MODEL_FAST_8B]
        if prefer_70b
        else [GROQ_MODEL_FAST_8B, GROQ_MODEL_PRIMARY_70B]
    )

    last_err: Optional[Exception] = None
    for model_name in models:
        try:
            kwargs: Dict[str, Any] = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": PROMPT_INJECTION_SYSTEM_GUARD},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.35,
                "max_tokens": 2048,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            completion = client.chat.completions.create(**kwargs)
            text = (completion.choices[0].message.content or "").strip()
            logger.info("AI generation succeeded via provider=groq model=%s", model_name)
            return text, model_name
        except Exception as exc:
            last_err = exc
            logger.warning("Groq model=%s error (%s), trying next fallback...", model_name, exc)
    raise RuntimeError(f"Groq failed across models: {last_err}") from last_err


def _call_openrouter(prompt: str, json_mode: bool, prefer_70b: bool) -> Tuple[str, str]:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    client = OpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": os.getenv("BACKEND_URL", "https://applykit.africa"),
            "X-Title": "ApplyKit Career Hub",
        },
    )
    models = (
        [OPENROUTER_MODEL_70B, OPENROUTER_MODEL_MISTRAL]
        if prefer_70b
        else [OPENROUTER_MODEL_MISTRAL, OPENROUTER_MODEL_70B]
    )

    sys_prompt = PROMPT_INJECTION_SYSTEM_GUARD
    if json_mode:
        sys_prompt += " Respond strictly with valid raw JSON object only, no prose outside JSON."

    last_err: Optional[Exception] = None
    for model_name in models:
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.35,
                max_tokens=2048,
            )
            text = (completion.choices[0].message.content or "").strip()
            logger.info("AI generation succeeded via provider=openrouter model=%s", model_name)
            return text, model_name
        except Exception as exc:
            last_err = exc
            logger.warning("OpenRouter model=%s error (%s), trying next...", model_name, exc)
    raise RuntimeError(f"OpenRouter failed across models: {last_err}") from last_err


def _offline_heuristic_fallback(prompt: str, json_mode: bool) -> str:
    """
    Deterministic offline analyzer used ONLY when no GROQ_API_KEY / OPENROUTER_API_KEY
    is set in `.env` (e.g., fresh clone test), ensuring zero crashes while computing
    real keyword diffs, scam heuristics, and structured responses from the input.
    """
    cv_match = re.search(r"<UNTRUSTED_CV>(.*?)</UNTRUSTED_CV>", prompt, re.DOTALL)
    jd_match = re.search(r"<UNTRUSTED_JD>(.*?)</UNTRUSTED_JD>", prompt, re.DOTALL)
    user_match = re.search(r"<UNTRUSTED_USER_INPUT>(.*?)</UNTRUSTED_USER_INPUT>", prompt, re.DOTALL)
    cv_txt = (cv_match.group(1) if cv_match else "").strip()
    jd_txt = (jd_match.group(1) if jd_match else "").strip()
    usr_txt = (user_match.group(1) if user_match else "").strip()

    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "your", "will", "have", "are",
        "you", "our", "who", "can", "all", "has", "not", "but", "able", "work", "team", "role",
        "experience", "years", "using", "strong", "looking", "join", "must", "plus", "good",
    }
    extract_words = lambda s: [
        w for w in dict.fromkeys(re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{2,}", s.lower())) if w not in stopwords
    ]

    if '"matched_keywords"' in prompt and '"missing_keywords"' in prompt:
        jd_kw = extract_words(jd_txt)[:22]
        cv_set = set(extract_words(cv_txt))
        matched = [k for k in jd_kw if k in cv_set][:12]
        missing = [k for k in jd_kw if k not in cv_set][:10]
        total = max(len(matched) + len(missing), 1)
        score = min(96, max(28, int(round((len(matched) / total) * 85 + 15))))
        verdict = (
            "Strong Match" if score >= 75 else "Good Potential" if score >= 55 else "Needs Tailoring"
        )
        top_missing = ", ".join(missing[:3]) if missing else "quantified metrics"
        data = {
            "score": score,
            "verdict": verdict,
            "summary": f"Your CV aligns with {len(matched)} core keywords from the job post. Add {top_missing} with measurable outcomes to push above 85/100.",
            "matched_keywords": matched or ["communication", "problem-solving"],
            "missing_keywords": missing or ["kpi-metrics", "stakeholder-reporting"],
            "ai_fixes": [
                f"Delivered production solutions incorporating {missing[0] if missing else 'core workflows'}, improving team throughput by 28% across Q1–Q3.",
                f"Collaborated cross-functionally using {matched[0] if matched else 'modern tooling'} to cut turnaround time from 5 days to under 36 hours.",
                f"Automated recurring reporting and QA checks for {missing[1] if len(missing) > 1 else 'client deliverables'}, maintaining 99.4% accuracy.",
            ],
            "tailored_summary": f"Results-driven specialist skilled in {', '.join((matched + missing)[:4]) or 'modern delivery'}, focused on measurable business impact and reliable remote execution.",
        }
        return json.dumps(data)

    if '"cover_letter"' in prompt and '"word_count"' in prompt:
        jd_kw = extract_words(jd_txt)[:4]
        cv_kw = extract_words(cv_txt)[:3]
        focus = ", ".join(jd_kw[:3]) if jd_kw else "high-impact execution and fast turnaround"
        proof = ", ".join(cv_kw[:2]) if cv_kw else "end-to-end delivery"
        letter = (
            f"Shipping reliable results in {focus} without hand-holding is exactly where I add immediate value to your team. "
            f"In my recent work leading {proof} initiatives, I streamlined core workflows, eliminated recurring bottlenecks, and consistently hit tight client milestones ahead of schedule.\n\n"
            f"What caught my eye about your brief is the focus on practical execution rather than theory. I have already mapped out how I would approach your first two weeks—starting with a quick audit of current deliverables, aligning on measurable KPIs, and shipping a clean first milestone within 72 hours.\n\n"
            f"I work seamlessly across EAT/EU/US overlap hours with crisp async updates. Would you be open to a brief 10-minute chat this week—or shall I send over a 2-bullet action plan tailored to your immediate priority?"
        )
        words = len(letter.split())
        return json.dumps(
            {
                "cover_letter": letter,
                "word_count": words,
                "opening_hook": letter.split(".")[0] + ".",
                "key_selling_points": [
                    f"Direct alignment with {focus}",
                    "Concrete 72-hour first-milestone commitment",
                ],
            }
        )

    if '"risk_level"' in prompt and '"red_flags"' in prompt:
        combined = f"{jd_txt} {usr_txt}".lower()
        flags = []
        scam_patterns = [
            (r"telegram|whatsapp only|signal app", "Moves communication off-platform to Telegram/WhatsApp immediately"),
            (r"registration fee|training fee|equipment fee|security deposit|pay .* kes|send money", "Requests upfront fee / deposit from applicant (classic advance-fee scam)"),
            (r"crypto|usdt|check cashing|wire transfer agent|bank drop", "Suspicious payment rail or money-mule / USDT transfer request"),
            (r"no experience.*\$[5-9]\d+/hr|earn \$\d{3,}/day", "Unrealistic pay promised for zero-skill tasks"),
            (r"hired\s*0|0%\s*hire|unverified payment", "Client has unverified payment method or zero historical hires"),
            (r"gmail\.com|yahoo\.com", "Uses free personal email domain instead of verified company domain"),
        ]
        for pat, desc in scam_patterns:
            if re.search(pat, combined):
                flags.append(desc)
        risk_score = min(98, 12 + len(flags) * 28)
        risk_level = "High" if risk_score >= 65 else "Medium" if risk_score >= 38 else "Low"
        return json.dumps(
            {
                "risk_level": risk_level,
                "risk_score": risk_score,
                "verdict_headline": (
                    "High Fraud Risk — Do NOT pay fees or move off-platform!"
                    if risk_level == "High"
                    else "Proceed with Caution — Verify client milestones before starting"
                    if risk_level == "Medium"
                    else "Looks Legitimate — Standard freelance/job precautions apply"
                ),
                "red_flags": flags or ["No obvious advance-fee or off-platform scam triggers detected."],
                "green_flags": [
                    "Clear role deliverables inspected",
                    "Always require funded Upwork Escrow or signed milestone contract before working",
                ],
                "safety_advice": "Never pay for training, medicals, IDs, or equipment, and keep all chat + payments inside escrow until verified.",
            }
        )

    if '"questions"' in prompt and '"sample_answer"' in prompt:
        kws = extract_words(jd_txt)[:5] or ["API architecture", "prioritization", "stakeholder communication", "debugging", "quality assurance"]
        questions = []
        categories = ["Technical", "Behavioral", "Situational", "Technical", "Behavioral", "Situational", "Culture", "Technical", "Behavioral", "Situational"]
        for idx in range(10):
            topic = kws[idx % len(kws)]
            questions.append(
                {
                    "number": idx + 1,
                    "category": categories[idx],
                    "question": f"Tell me about a challenging project involving {topic} and how you ensured measurable impact.",
                    "why_they_ask": f"Tests hands-on ownership and real-world problem solving in {topic}.",
                    "sample_answer": f"Situation: Our team faced tight delivery timelines around {topic}. Task: I owned end-to-end redesign and reliability. Action: I broke deliverables into milestones, automated validation, and aligned stakeholders early. Result: Reduced errors by 35% and delivered 2 days ahead of deadline.",
                }
            )
        return json.dumps({"role_summary": "Target Role Interview Prep Pack (10 Q&As)", "questions": questions})

    # Generic Hidden Vault Tool response
    title_m = re.search(r'Execute the ApplyKit tool:\s*"([^"]+)"', prompt)
    tool_title = title_m.group(1) if title_m else "ApplyKit Vault Output"
    snippet = (usr_txt or jd_txt or "your career request")[:140]
    copy_body = (
        f"Here is your tailored {tool_title} built from your context ({snippet}):\n\n"
        f"1. Lead with measurable outcomes and clear timeline ownership.\n"
        f"2. Anchor communication around the employer/client's #1 business bottleneck.\n"
        f"3. Confirm concrete next steps in writing to maintain momentum."
    )
    return json.dumps(
        {
            "title": tool_title,
            "summary": "Generated via ApplyKit Vault Engine (set GROQ_API_KEY in .env for Llama-3.3-70B live generation).",
            "sections": [
                {
                    "heading": "Tailored Actionable Output",
                    "items": [
                        f"Customized for: {snippet}",
                        "Structured for immediate copy-paste into email, Upwork, or LinkedIn.",
                        "Quantifies value, protects scope, and keeps tone concise & professional.",
                    ],
                },
                {
                    "heading": "Pro Execution Checklist",
                    "items": [
                        "Personalize names, dates, and exact KES/USD figures before sending.",
                        "Save this opportunity to your ApplyKit Kanban Dashboard for 7-day follow-up.",
                    ],
                },
            ],
            "copy_text": copy_body,
        }
    )


def generate(prompt: str, json_mode: bool = True, prefer_70b: bool = True, use_cache: bool = True) -> Any:
    """
    Core AI entry point required by ApplyKit architecture:
    1. Checks 24h SHA-256 prompt cache to prevent quota waste.
    2. Tries Groq SDK (`llama-3.3-70b-versatile` / `llama-3.1-8b-instant`).
    3. Auto-switches to OpenRouter (`meta-llama/llama-3.3-70b-instruct:free` / `mistralai/mistral-7b-instruct:free`) on 429/500/error.
    4. Logs active provider & model. Never exposes API keys.
    """
    global _LAST_META
    cache_key = hashlib.sha256(f"{json_mode}:{prefer_70b}:{prompt}".encode("utf-8")).hexdigest()
    now = time.time()

    if use_cache and cache_key in _RESPONSE_CACHE:
        ts, cached_val, cached_meta = _RESPONSE_CACHE[cache_key]
        if now - ts < CACHE_TTL_SECONDS:
            _LAST_META = {**cached_meta, "cached": True}
            logger.info("AI cache HIT provider=%s model=%s", cached_meta["provider"], cached_meta["model"])
            return cached_val
        _RESPONSE_CACHE.pop(cache_key, None)

    has_groq = _is_valid_key(os.getenv("GROQ_API_KEY"), "gsk_your_")
    has_openrouter = _is_valid_key(os.getenv("OPENROUTER_API_KEY"), "sk-or-v1-your_")

    raw_output: Optional[str] = None
    provider_used = "none"
    model_used = "none"

    if has_groq:
        try:
            raw_output, model_used = _call_groq(prompt, json_mode=json_mode, prefer_70b=prefer_70b)
            provider_used = "groq"
        except Exception as groq_exc:
            logger.warning("Groq primary failed (%s); auto-switching to OpenRouter fallback.", groq_exc)
            if has_openrouter:
                raw_output, model_used = _call_openrouter(prompt, json_mode=json_mode, prefer_70b=prefer_70b)
                provider_used = "openrouter"
            else:
                raise
    elif has_openrouter:
        raw_output, model_used = _call_openrouter(prompt, json_mode=json_mode, prefer_70b=prefer_70b)
        provider_used = "openrouter"
    else:
        logger.info("No GROQ_API_KEY or OPENROUTER_API_KEY configured; using local heuristic fallback.")
        raw_output = _offline_heuristic_fallback(prompt, json_mode=json_mode)
        provider_used = "local-fallback"
        model_used = "heuristic-v1"

    if json_mode:
        result: Any = _extract_json_object(raw_output)
    else:
        result = (raw_output or "")[:MAX_OUTPUT_CHARS]

    _LAST_META = {"provider": provider_used, "model": model_used, "cached": False}
    if use_cache:
        _RESPONSE_CACHE[cache_key] = (now, result, {"provider": provider_used, "model": model_used})
    return result
