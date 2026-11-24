"""
ApplyKit — Professional AI Job Toolkit Hub for Africa + Global Freelancers.
Single Python 3.11 + FastAPI backend serving SEO Jinja2 HTML pages + JSON APIs
for both the Micro-Tool Website and Multi-Browser Extension (Chrome, Edge, Brave, Opera, Firefox).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from lib.security import SecurityHeadersMiddleware, limiter
from routes.api_ai import router as api_ai_router
from routes.api_apps import router as api_apps_router
from routes.api_payments import router as api_payments_router
from routes.api_router import router as api_universal_router
from routes.pages import router as pages_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="ApplyKit Hub API & Web",
    description="AI Career & Freelance Toolkit Hub for Africa + Global Freelancers",
    version="1.0.0",
)

# Attach SlowAPI rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Strict CORS allowing configured BACKEND_URL + multi-browser extensions (chrome-extension://, moz-extension://, edge)
backend_url = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
allowed_origins = [
    backend_url,
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"^(chrome-extension|moz-extension|safari-web-extension|extension)://.*$|^https://.*\.e2b\.app$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Signature"],
)

# Attach strict HTTP security headers middleware (CSP, HSTS, X-Frame-Options, nosniff)
app.add_middleware(SecurityHeadersMiddleware)

# Mount static assets
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Include JSON API & HTML SEO routers
app.include_router(api_ai_router)
app.include_router(api_universal_router)
app.include_router(api_apps_router)
app.include_router(api_payments_router)
app.include_router(pages_router)
