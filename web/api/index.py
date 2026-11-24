"""Vercel Serverless Python Entrypoint for ApplyKit FastAPI Hub."""

from pathlib import Path
import sys

WEB_DIR = Path(__file__).resolve().parent.parent
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from main import app  # noqa: E402, F401
