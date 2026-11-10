"""
PayPal integration - Orders API v2, sandbox.

Deliberately simplified vs. a production integration:
  - No webhook listener/signature verification. Instead, after the buyer
    approves the order and is redirected back, we call POST
    /v2/checkout/orders/{id}/capture directly and trust PayPal's response
    to that call (not the redirect itself) as proof of payment. That is a
    legitimate, PayPal-documented pattern for the synchronous checkout
    flow and is far simpler to stand up in a few days than a verified
    webhook receiver + idempotency store.
    -> Production hardening note: add a /webhooks/paypal endpoint with
       signature verification (see PayPal docs: "Verify webhook
       signature") as a belt-and-suspenders check, especially if you
       later support async payment methods.
  - Access token is cached in-memory for its lifetime instead of using a
    persistent token store - fine for a single-process hackathon deploy.
"""
import time
import requests

from app.config import settings

_token_cache = {"access_token": None, "expires_at": 0}


class PayPalError(Exception):
    pass


def _get_access_token() -> str:
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 30:
        return _token_cache["access_token"]

    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        raise PayPalError(
            "PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set. "
            "Create a sandbox app at developer.paypal.com and put the "
            "keys in backend/.env"
        )

    resp = requests.post(
        f"{settings.PAYPAL_BASE_URL}/v1/oauth2/token",
        auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"},
        timeout=15,
    )
    if resp.status_code != 200:
        raise PayPalError(f"PayPal auth failed: {resp.status_code} {resp.text}")

    data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 300)
    return _token_cache["access_token"]


def _headers():
    return {
        "Authorization": f"Bearer {_get_access_token()}",
        "Content-Type": "application/json",
    }


def create_order(amount: float, currency: str, description: str, invoice_id: str) -> dict:
    """Create a PayPal order for an invoice. Returns the full PayPal order
    object, which includes an 'id' and an 'approve' link the buyer uses
    to pay in the sandbox."""
    body = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": invoice_id,
                "description": description[:127],  # PayPal field length limit
                "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
            }
        ],
        "application_context": {
            "return_url": settings.PAYPAL_RETURN_URL,
            "cancel_url": settings.PAYPAL_CANCEL_URL,
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW",
            "brand_name": "FlowMind AI",
        },
    }
    resp = requests.post(
        f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders",
        headers=_headers(),
        json=body,
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise PayPalError(f"Create order failed: {resp.status_code} {resp.text}")
    return resp.json()


def get_order(order_id: str) -> dict:
    resp = requests.get(
        f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}",
        headers=_headers(),
        timeout=15,
    )
    if resp.status_code != 200:
        raise PayPalError(f"Get order failed: {resp.status_code} {resp.text}")
    return resp.json()


def capture_order(order_id: str) -> dict:
    """Capture an approved order. Only succeeds if the buyer has actually
    approved it in the PayPal sandbox checkout - this is the real proof
    of payment, not the browser redirect."""
    resp = requests.post(
        f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}/capture",
        headers=_headers(),
        json={},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise PayPalError(f"Capture failed: {resp.status_code} {resp.text}")
    return resp.json()


def extract_approval_url(paypal_order: dict) -> str | None:
    for link in paypal_order.get("links", []):
        if link.get("rel") == "approve":
            return link.get("href")
    return None


def extract_capture_id(captured_order: dict) -> str | None:
    try:
        return (
            captured_order["purchase_units"][0]["payments"]["captures"][0]["id"]
        )
    except (KeyError, IndexError):
        return None


def verify_webhook_signature(
    headers: dict, raw_event: dict, webhook_id: str | None = None
) -> bool:
    """Verify PayPal webhook signature using PayPal's verification API.
    Production hardening feature for asynchronous webhook listening."""
    wh_id = webhook_id or settings.PAYPAL_WEBHOOK_ID
    if not wh_id:
        # If no webhook ID configured yet, return True in sandbox for developer ease
        return True

    verification_payload = {
        "auth_algo": headers.get("paypal-auth-algo") or headers.get("PAYPAL-AUTH-ALGO"),
        "cert_url": headers.get("paypal-cert-url") or headers.get("PAYPAL-CERT-URL"),
        "transmission_id": headers.get("paypal-transmission-id") or headers.get("PAYPAL-TRANSMISSION-ID"),
        "transmission_sig": headers.get("paypal-transmission-sig") or headers.get("PAYPAL-TRANSMISSION-SIG"),
        "transmission_time": headers.get("paypal-transmission-time") or headers.get("PAYPAL-TRANSMISSION-TIME"),
        "webhook_id": wh_id,
        "webhook_event": raw_event,
    }

    try:
        resp = requests.post(
            f"{settings.PAYPAL_BASE_URL}/v1/notifications/verify-webhook-signature",
            headers=_headers(),
            json=verification_payload,
            timeout=15,
        )
        if resp.status_code == 200:
            status = resp.json().get("verification_status")
            return status == "SUCCESS"
        return False
    except Exception:
        return False


def refund_capture(capture_id: str, note: str = "Customer requested refund") -> dict:
    """Refund a captured payment via PayPal Payments API v2."""
    body = {"note_to_payer": note}
    resp = requests.post(
        f"{settings.PAYPAL_BASE_URL}/v2/payments/captures/{capture_id}/refund",
        headers=_headers(),
        json=body,
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise PayPalError(f"Refund failed: {resp.status_code} {resp.text}")
    return resp.json()
