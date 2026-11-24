"""
FastAPI HTML + SEO Pages Router (`routes/pages.py`):
Serves:
- GET `/` (Homepage showing ONLY the 7 visible showcase tools + universal `"⚡ Ask ApplyKit..."` search bar)
- GET `/tools/ats-checker`
- GET `/tools/cover-letter-generator`
- GET `/tools/freelance-rate-calculator`
- GET `/tools/paye-calculator-kenya-2026` (+ `?country=nigeria` / `?country=ghana` variants)
- GET `/tools/scam-detector`
- GET `/tools/invoice-generator`
- GET `/tools/interview-questions-generator`
- GET `/dashboard` (Kanban + Stats + Weekly Goal + Follow-Up Reminders + CSV Export)
- GET `/pricing` (Lemon Squeezy $6/mo & $29 lifetime + M-Pesa STK Push 750 KES + Manual Till + Paystack/Flutterwave)
- GET `/admin` (HTTP Basic Auth manual Till approval & email Pro toggle)
- GET `/privacy`, `/terms`, `/ads.txt`, `/robots.txt`, `/sitemap.xml`
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates

from lib.router import get_visible_tools, load_registry
from lib.security import get_optional_user, verify_admin_basic_auth
from lib.supabase_client import get_public_supabase_config, list_manual_till_submissions

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(tags=["HTML Pages & SEO"])

TOOL_SEO_CATALOG: Dict[str, Dict[str, Any]] = {
    "ats-checker": {
        "template": "tools/ats_checker.html",
        "title": "Free ATS CV Match Checker & Resume Keyword Scanner (2026) | ApplyKit",
        "meta_description": "Instant ATS resume score out of 100, matched vs missing keywords, 1-click AI CV bullet fixes, PDF download & WhatsApp share. Built for Africa & global remote jobs.",
        "h1": "ATS CV Match Score & Keyword Optimizer",
        "faqs": [
            {
                "q": "What is a good ATS CV score before applying?",
                "a": "Aim for 75/100 or higher. ApplyKit highlights exact missing keywords from the job description and rewrites bullets so both ATS filters and human recruiters shortlist you.",
            },
            {
                "q": "Does ApplyKit train AI models on my uploaded CV?",
                "a": "No. ApplyKit never trains AI models on your CV, stores only anonymized hashes for rate-limiting, and lets you delete all account data in one click.",
            },
        ],
    },
    "cover-letter-generator": {
        "template": "tools/cover_letter.html",
        "title": "150-Word AI Cover Letter & Upwork Proposal Generator | ApplyKit",
        "meta_description": "Generate punchy 150-word cover letters and Upwork proposals tailored to your CV and tone in 4 seconds. Free online tool.",
        "h1": "150-Word Cover Letter & Proposal Generator",
        "faqs": [
            {
                "q": "Why 150 words for cover letters and Upwork proposals?",
                "a": "Hiring managers and Upwork clients read on mobile and spend under 20 seconds per pitch. A sharp 150-word hook + proof + CTA converts 2–3x better than generic essays.",
            },
            {
                "q": "Can I choose different tones for corporate vs startup roles?",
                "a": "Yes—pick Professional & Direct, Confident Startup, Warm Storyteller, or Upwork Hook-First Pitch.",
            },
        ],
    },
    "freelance-rate-calculator": {
        "template": "tools/rate_calculator.html",
        "title": "Freelance Hourly Rate Calculator (KES/USD, Upwork 10% Fee & KRA Tax) | ApplyKit",
        "meta_description": "Calculate your true USD/hour freelance rate from desired KES take-home salary factoring Upwork 10% fee, Payoneer/M-Pesa withdrawal spread, billable hours & KRA tax.",
        "h1": "Freelance Hourly Rate Calculator (Africa + Global)",
        "faqs": [
            {
                "q": "How much does Upwork charge freelancers in 2026?",
                "a": "Upwork charges a flat 10% freelancer service fee on earnings across most contracts, plus currency withdrawal spreads of 1.5%–3% when cashing out to M-Pesa or local banks.",
            },
            {
                "q": "Why shouldn't I divide desired salary by 40 hours per week?",
                "a": "Freelancers spend 30%–40% of working hours pitching, invoicing, and upskilling. Base your rate on realistic billable hours (20–28 hrs/week) plus unpaid leave.",
            },
        ],
    },
    "paye-calculator-kenya-2026": {
        "template": "tools/paye_calculator.html",
        "title": "Kenya PAYE Tax Calculator 2026 (SHIF, NSSF, Housing Levy + Nigeria & Ghana) | ApplyKit",
        "meta_description": "Accurate 2026 Kenya net salary PAYE calculator with KRA tax bands, Personal Relief KES 2,400, SHIF 2.75%, NSSF Tier I & II, Affordable Housing Levy 1.5%, plus Nigeria & Ghana variants.",
        "h1": "PAYE Net Salary Calculator 2026 (Kenya, Nigeria & Ghana)",
        "faqs": [
            {
                "q": "How are SHIF and Housing Levy treated in 2026 Kenya PAYE?",
                "a": "SHIF is 2.75% of gross pay (minimum KES 300) and Affordable Housing Levy is 1.5% of gross pay. Both, along with NSSF contributions, are tax-deductible reliefs when computing taxable pay.",
            },
            {
                "q": "Can I switch this calculator to Nigeria (NGN) or Ghana (GHS)?",
                "a": "Yes! Use the country selector or URL query (?country=nigeria or ?country=ghana) to calculate Nigerian PAYE + Pension/CRA or Ghana GRA PAYE + SSNIT instantly.",
            },
        ],
    },
    "scam-detector": {
        "template": "tools/scam_detector.html",
        "title": "Free Job Scam Detector & Upwork Client Risk Checker | ApplyKit",
        "meta_description": "Paste any job post, WhatsApp/Telegram recruiter message, or Upwork listing to detect advance-fee traps, fake checks, and red flags instantly.",
        "h1": "AI Job & Client Scam Detector",
        "faqs": [
            {
                "q": "What are the #1 job scam warning signs in Kenya, Nigeria, and remote boards?",
                "a": "Any request to pay for 'training, medicals, aptitude tests, security clearance, or laptop shipping', moving interviews straight to Telegram, or asking you to process USDT/crypto transfers.",
            },
            {
                "q": "How do I spot risky clients on Upwork?",
                "a": "Watch out for unverified payment methods combined with '20+ jobs posted, 0% hire rate', requests for unpaid full-project 'test tasks', or off-platform Telegram links.",
            },
        ],
    },
    "invoice-generator": {
        "template": "tools/invoice_generator.html",
        "title": "Free Freelance Invoice Generator (M-Pesa Till/Paybill + USD PDF) | ApplyKit",
        "meta_description": "Create professional printable PDF invoices in seconds with M-Pesa Paybill/Till, KCB/Equity USD Wire, Wise, or Paystack details. 100% free in browser.",
        "h1": "Instant Freelance Invoice Generator (PDF + M-Pesa)",
        "faqs": [
            {
                "q": "Is my client billing data stored on ApplyKit servers?",
                "a": "No. The Invoice Generator runs 100% locally in your browser using pure JavaScript and exports directly to crisp A4 PDF via native print layout.",
            },
            {
                "q": "Can I bill international clients in USD and local clients in KES?",
                "a": "Yes—switch between KES, USD, NGN, GHS, EUR, and GBP, and include both M-Pesa Till/Paybill and international SWIFT/Wise details.",
            },
        ],
    },
    "interview-questions-generator": {
        "template": "tools/interview_questions.html",
        "title": "AI Interview Questions & STAR Answers Generator from JD + CV | ApplyKit",
        "meta_description": "Paste any Job Description and your CV to get 10 role-specific technical & behavioral interview questions with tailored STAR sample answers.",
        "h1": "Role-Specific Interview Questions & Sample Answers",
        "faqs": [
            {
                "q": "What is the STAR method for interview answers?",
                "a": "STAR stands for Situation, Task, Action, and Result—a structured storytelling framework that proves measurable impact in under 90 seconds.",
            },
            {
                "q": "How tailored are the 10 generated questions?",
                "a": "ApplyKit analyzes exact tech stacks, seniority signals, and KPIs inside your pasted Job Description and maps sample answers directly to your CV achievements.",
            },
        ],
    },
}


def _common_ctx(request: Request, user: Optional[Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    is_pro = bool(user and user.get("is_pro"))
    user_obj = user or {"is_pro": False, "authenticated": False}
    if user:
        user_obj = {**user, "authenticated": True}
    all_tools = load_registry()
    vault_count = sum(1 for t in all_tools if not t.get("visible"))
    ctx = {
        "request": request,
        "user": user_obj,
        "is_pro": is_pro,
        "ADSENSE_ID": os.getenv("ADSENSE_CLIENT_ID", "ca-pub-XXXX"),
        "BACKEND_URL": os.getenv("BACKEND_URL", str(request.base_url).rstrip("/")),
        "SUPABASE_PUBLIC": get_public_supabase_config(),
        "MPESA_MANUAL_TILL": os.getenv("MPESA_MANUAL_TILL", "4182930"),
        "MPESA_MONTHLY_KES": int(os.getenv("MPESA_MONTHLY_KES", "750")),
        "MPESA_LIFETIME_KES": int(os.getenv("MPESA_LIFETIME_KES", "3750")),
        "LEMONSQUEEZY_MONTHLY_URL": os.getenv(
            "LEMONSQUEEZY_MONTHLY_URL", "https://applykit.lemonsqueezy.com/buy/monthly-6-usd"
        ),
        "LEMONSQUEEZY_LIFETIME_URL": os.getenv(
            "LEMONSQUEEZY_LIFETIME_URL", "https://applykit.lemonsqueezy.com/buy/lifetime-29-usd"
        ),
        "PAYSTACK_PAYMENT_URL": os.getenv("PAYSTACK_PAYMENT_URL", "https://paystack.com/pay/applykit-pro"),
        "FLUTTERWAVE_PAYMENT_URL": os.getenv("FLUTTERWAVE_PAYMENT_URL", "https://flutterwave.com/pay/applykit-pro"),
        "visible_tools": get_visible_tools(),
        "vault_count": max(60, vault_count),
    }
    ctx.update(extra)
    return ctx


@router.get("/healthz")
async def healthcheck() -> Dict[str, str]:
    return {"status": "ok", "service": "applykit"}


@router.get("/", response_class=HTMLResponse)
async def homepage(
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> HTMLResponse:
    ctx = _common_ctx(
        request,
        user,
        page_title="ApplyKit — AI Job Toolkit Hub for Africa & Global Freelancers",
        meta_description="Check ATS CV scores, write 150-word proposals, calculate 2026 Kenya PAYE & freelance USD rates, detect job scams, and unlock 60+ hidden AI career tools via search.",
    )
    return templates.TemplateResponse(request, "index.html", ctx)


@router.get("/tools/{slug}", response_class=HTMLResponse)
async def tool_page(
    slug: str,
    request: Request,
    country: str = Query(default="kenya", max_length=20),
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> HTMLResponse:
    seo = TOOL_SEO_CATALOG.get(slug)
    if not seo:
        raise HTTPException(
            status_code=404,
            detail="This tool has no public page—type your quest into '⚡ Ask ApplyKit...' in the header to run Vault tools on the fly!",
        )
    country_clean = country.lower() if country.lower() in {"kenya", "nigeria", "ghana"} else "kenya"
    ctx = _common_ctx(
        request,
        user,
        tool_slug=slug,
        page_title=seo["title"],
        meta_description=seo["meta_description"],
        h1_title=seo["h1"],
        faqs=seo["faqs"],
        selected_country=country_clean,
        is_tool_page=True,
    )
    return templates.TemplateResponse(request, seo["template"], ctx)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> HTMLResponse:
    ctx = _common_ctx(
        request,
        user,
        page_title="Job Application Tracker & Kanban Dashboard | ApplyKit",
        meta_description="Track Applied, Interview, Offer & Rejected jobs with extension auto-sync, weekly goals, 7-day follow-up alerts & WhatsApp interview reminders.",
    )
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@router.get("/pricing", response_class=HTMLResponse)
async def pricing_page(
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> HTMLResponse:
    ctx = _common_ctx(
        request,
        user,
        page_title="ApplyKit Pro Pricing — 750 KES M-Pesa or $6/mo Global | ApplyKit",
        meta_description="Unlock unlimited Llama-3.3-70B AI executions, all 60+ Hidden Vault tools, Upwork/LinkedIn browser extension deep-dive, Kanban exports, and zero ads.",
    )
    return templates.TemplateResponse(request, "pricing.html", ctx)


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(
    request: Request,
    admin_user: str = Depends(verify_admin_basic_auth),
) -> HTMLResponse:
    submissions = list_manual_till_submissions()
    ctx = _common_ctx(
        request,
        {"is_pro": True, "email": admin_user},
        page_title="ApplyKit Admin — Manual M-Pesa Till & Pro Toggle",
        meta_description="Admin panel for manual Till verification.",
        manual_submissions=submissions,
        admin_user=admin_user,
    )
    return templates.TemplateResponse(request, "admin.html", ctx)


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> HTMLResponse:
    ctx = _common_ctx(
        request,
        user,
        page_title="Privacy Policy, Kenya DPA & Google AdSense Disclosure | ApplyKit",
        meta_description="How ApplyKit protects your CV data under the Kenya Data Protection Act 2019 & GDPR, Google AdSense cookie disclosure, and 1-click Delete My Data.",
    )
    return templates.TemplateResponse(request, "privacy.html", ctx)


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
) -> HTMLResponse:
    ctx = _common_ctx(
        request,
        user,
        page_title="Terms of Service | ApplyKit",
        meta_description="Terms governing ApplyKit web tools, multi-browser extension, M-Pesa & Lemon Squeezy Pro subscriptions.",
    )
    return templates.TemplateResponse(request, "terms.html", ctx)


@router.get("/ads.txt", response_class=PlainTextResponse)
async def ads_txt() -> PlainTextResponse:
    ads_file = BASE_DIR / "ads.txt"
    content = ads_file.read_text(encoding="utf-8") if ads_file.exists() else "google.com, pub-XXXX, DIRECT, f08c47fec0942fa0\n"
    return PlainTextResponse(content)


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt(request: Request) -> PlainTextResponse:
    base = os.getenv("BACKEND_URL", str(request.base_url).rstrip("/"))
    body = f"User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/\nSitemap: {base}/sitemap.xml\n"
    return PlainTextResponse(body)


@router.get("/sitemap.xml")
async def sitemap_xml(request: Request) -> Response:
    base = os.getenv("BACKEND_URL", str(request.base_url).rstrip("/"))
    urls = [
        f"{base}/",
        f"{base}/pricing",
        f"{base}/privacy",
        f"{base}/terms",
    ] + [f"{base}/tools/{slug}" for slug in TOOL_SEO_CATALOG.keys()]
    items = "\n".join(
        f"  <url><loc>{u}</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>"
        for u in urls
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{items}\n</urlset>'
    return Response(content=xml, media_type="application/xml")
