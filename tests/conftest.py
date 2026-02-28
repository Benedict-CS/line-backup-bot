"""Pytest configuration: load .env so config has values when tests run."""
import os
from pathlib import Path

# Load .env from project root (parent of tests/)
_root = Path(__file__).resolve().parent.parent
_env = _root / ".env"
if _env.exists():
    from dotenv import load_dotenv
    load_dotenv(_env)
