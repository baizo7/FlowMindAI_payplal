"""
FLOWMIND AI - configuration

All secrets/config come from environment variables (.env in local dev,
environment variables in Render/production). Never commit real keys.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present (local dev). In Render, real env vars are injected
# directly and this is a no-op.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Settings:
    # --- PayPal (sandbox) ---
    PAYPAL_CLIENT_ID: str = os.getenv("PAYPAL_CLIENT_ID", "")
    PAYPAL_CLIENT_SECRET: str = os.getenv("PAYPAL_CLIENT_SECRET", "")
    # Sandbox base URL. Switch to https://api-m.paypal.com only for a
    # production (live) app with live credentials.
    PAYPAL_BASE_URL: str = os.getenv(
        "PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"
    )
    # Where PayPal should send the buyer back after approving the order.
    # Automatically picks up Render's RENDER_EXTERNAL_URL or hostname, or defaults to production Render / localhost.
    _render_url: str = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not _render_url and os.getenv("RENDER_EXTERNAL_HOSTNAME"):
        _render_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}".rstrip("/")
    if not _render_url and (os.getenv("RENDER") or os.getenv("PORT")):
        _render_url = "https://flowmindai-payplal.onrender.com"

    PAYPAL_RETURN_URL: str = os.getenv(
        "PAYPAL_RETURN_URL",
        f"{_render_url}/payment-complete" if _render_url else "http://localhost:8000/payment-complete"
    )
    PAYPAL_CANCEL_URL: str = os.getenv(
        "PAYPAL_CANCEL_URL",
        f"{_render_url}/payment-cancelled" if _render_url else "http://localhost:8000/payment-cancelled"
    )
    PAYPAL_WEBHOOK_ID: str = os.getenv("PAYPAL_WEBHOOK_ID", "")

    # --- Gemini ---
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    # NOTE: model names change over time - check https://ai.google.dev for
    # the current list and swap this if the one below is no longer served.
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

    # --- App / DB ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./flowmind.db")
    APP_SECRET: str = os.getenv("APP_SECRET", "dev-secret-change-me")
    DEFAULT_CURRENCY: str = os.getenv("DEFAULT_CURRENCY", "USD")


settings = Settings()
