"""
Tool functions callable by the Gemini orchestrator.

Each function here corresponds to one of the "agent" responsibilities from
the project spec (Invoice / Payment / Reminder / Finance). They are plain,
testable Python functions rather than separate services - that's the
80/20 simplification that makes this buildable solo in a few days while
keeping the multi-agent *behavior* fully real and demoable.

Security principle preserved from the original spec: Gemini never touches
the database or PayPal directly. It can only request one of these named
functions with validated arguments; everything here does real validation
and returns real, DB-backed data. Gemini cannot fabricate a "payment
succeeded" state - only capture_payment() talking to PayPal can set that.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import models, paypal_client
from app.config import settings


def _invoice_number(db: Session) -> str:
    count = db.query(models.Invoice).count() + 1
    return f"INV-{count:04d}"


def _find_or_create_client(db: Session, name: str, email: str, company: str | None = None) -> models.Client:
    client = db.query(models.Client).filter(models.Client.email == email).first()
    if client:
        return client
    client = models.Client(name=name, email=email, company=company)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


# ---------------------------------------------------------------------------
# Invoice Agent
# ---------------------------------------------------------------------------
def create_invoice(db: Session, client_name: str, client_email: str, description: str,
                    amount: float, currency: str = None, due_in_days: int = 7,
                    company: str = None) -> dict:
    if amount <= 0:
        return {"error": "Amount must be greater than zero."}

    currency = currency or settings.DEFAULT_CURRENCY
    client = _find_or_create_client(db, client_name, client_email, company)

    invoice = models.Invoice(
        invoice_number=_invoice_number(db),
        client_id=client.id,
        description=description,
        amount=round(amount, 2),
        currency=currency,
        status="draft",
        due_date=datetime.now(timezone.utc) + timedelta(days=due_in_days),
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "client": client.name,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "due_date": invoice.due_date.isoformat(),
        "status": invoice.status,
    }


def get_invoice(db: Session, invoice_number: str) -> dict:
    invoice = db.query(models.Invoice).filter(
        models.Invoice.invoice_number == invoice_number
    ).first()
    if not invoice:
        return {"error": f"No invoice found with number {invoice_number}"}
    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "client": invoice.client.name if invoice.client else None,
        "description": invoice.description,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "status": invoice.status,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
    }


def list_invoices(db: Session, status: str = None, limit: int = 10) -> dict:
    """List recent invoices, optionally filtered by status (draft, awaiting_payment, paid, overdue, cancelled)."""
    query = db.query(models.Invoice)
    if status:
        query = query.filter(models.Invoice.status == status)
    invoices = query.order_by(models.Invoice.created_at.desc()).limit(limit).all()
    return {
        "count": len(invoices),
        "invoices": [
            {
                "invoice_number": inv.invoice_number,
                "client": inv.client.name if inv.client else None,
                "description": inv.description,
                "amount": inv.amount,
                "currency": inv.currency,
                "status": inv.status,
                "due_date": inv.due_date.isoformat() if inv.due_date else None,
            }
            for inv in invoices
        ],
    }


# ---------------------------------------------------------------------------
# Payment Agent
# ---------------------------------------------------------------------------
def create_payment_order(db: Session, invoice_number: str) -> dict:
    invoice = db.query(models.Invoice).filter(
        models.Invoice.invoice_number == invoice_number
    ).first()
    if not invoice:
        return {"error": f"No invoice found with number {invoice_number}"}
    if invoice.status == "paid":
        return {"error": f"Invoice {invoice_number} is already paid."}

    try:
        order = paypal_client.create_order(
            amount=invoice.amount,
            currency=invoice.currency,
            description=invoice.description,
            invoice_id=invoice.id,
        )
    except paypal_client.PayPalError as e:
        return {"error": str(e)}

    approval_url = paypal_client.extract_approval_url(order)
    payment = models.Payment(
        invoice_id=invoice.id,
        paypal_order_id=order["id"],
        amount=invoice.amount,
        currency=invoice.currency,
        status="created",
        approval_url=approval_url,
    )
    invoice.status = "awaiting_payment"
    db.add(payment)
    db.commit()

    return {
        "invoice_number": invoice_number,
        "paypal_order_id": order["id"],
        "approval_url": approval_url,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "instructions": "Open approval_url to complete sandbox checkout, "
                         "then ask me to capture the payment.",
    }


def capture_payment(db: Session, paypal_order_id: str) -> dict:
    target_id = paypal_order_id.strip()
    payment = db.query(models.Payment).filter(
        models.Payment.paypal_order_id == target_id
    ).first()

    # Fallback: if caller passed an invoice number like "INV-0001" instead of the PayPal order ID
    if not payment:
        inv = db.query(models.Invoice).filter(models.Invoice.invoice_number == target_id).first()
        if inv:
            payment = (
                db.query(models.Payment)
                .filter(models.Payment.invoice_id == inv.id)
                .order_by(models.Payment.created_at.desc())
                .first()
            )
            if payment and payment.paypal_order_id:
                target_id = payment.paypal_order_id

    if not payment:
        return {"error": f"No payment record found for '{paypal_order_id}'"}

    try:
        result = paypal_client.capture_order(target_id)
    except paypal_client.PayPalError as e:
        err_msg = str(e)
        if "ORDER_NOT_APPROVED" in err_msg:
            return {
                "error": "The buyer has not approved this order on PayPal yet. "
                         "Please open the checkout link, log in to PayPal Sandbox, "
                         "and click 'Complete Purchase' before capturing."
            }
        payment.status = "failed"
        db.commit()
        return {"error": err_msg}

    status = result.get("status")
    if status == "COMPLETED":
        payment.status = "captured"
        payment.paypal_capture_id = paypal_client.extract_capture_id(result)
        payment.captured_at = datetime.now(timezone.utc)
        invoice = db.get(models.Invoice, payment.invoice_id)
        if invoice:
            invoice.status = "paid"
        db.commit()
        return {
            "status": "captured",
            "paypal_capture_id": payment.paypal_capture_id,
            "amount": payment.amount,
            "currency": payment.currency,
        }
    else:
        payment.status = "failed"
        db.commit()
        return {"status": status, "note": "Order was not approved/captured yet."}


def get_payment_status(db: Session, invoice_number: str) -> dict:
    invoice = db.query(models.Invoice).filter(
        models.Invoice.invoice_number == invoice_number
    ).first()
    if not invoice:
        return {"error": f"No invoice found with number {invoice_number}"}
    payment = (
        db.query(models.Payment)
        .filter(models.Payment.invoice_id == invoice.id)
        .order_by(models.Payment.created_at.desc())
        .first()
    )
    if not payment:
        return {"invoice_number": invoice_number, "status": "no_payment_attempted"}
    return {
        "invoice_number": invoice_number,
        "payment_status": payment.status,
        "paypal_order_id": payment.paypal_order_id,
        "paypal_capture_id": payment.paypal_capture_id,
        "approval_url": payment.approval_url,
    }


# ---------------------------------------------------------------------------
# Reminder Agent (on-demand & automated dispatch)
# ---------------------------------------------------------------------------
def send_overdue_reminders(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    overdue = db.query(models.Invoice).filter(
        models.Invoice.status.in_(["awaiting_payment", "draft"]),
        models.Invoice.due_date < now,
    ).all()

    sent = []
    for invoice in overdue:
        client = db.get(models.Client, invoice.client_id)
        client_name = client.name if client else "Client"
        client_email = client.email if client else ""
        message = (
            f"Hi {client_name}, this is an automated reminder that invoice "
            f"{invoice.invoice_number} for {invoice.amount} {invoice.currency} "
            f"is overdue. Please complete payment at your earliest convenience."
        )
        reminder = models.Reminder(
            invoice_id=invoice.id,
            recipient_email=client_email,
            channel="email",
            message=message,
            status="sent",
        )
        db.add(reminder)
        invoice.status = "overdue"
        sent.append({"invoice_number": invoice.invoice_number, "client": client_name, "email": client_email})
    db.commit()
    return {"reminders_sent": len(sent), "details": sent}


# ---------------------------------------------------------------------------
# Finance Agent (Multi-Currency Normalized & Currency Breakdown)
# ---------------------------------------------------------------------------
# Standard FX conversion rates to USD (for multi-currency portfolio estimation)
FX_RATES_TO_USD = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.28,
    "INR": 0.012,
    "CAD": 0.74,
    "AUD": 0.65,
    "SGD": 0.76,
    "JPY": 0.0067,
}


def _to_usd(amount: float, currency: str) -> float:
    rate = FX_RATES_TO_USD.get((currency or "USD").upper(), 1.0)
    return round(amount * rate, 2)


def get_financial_summary(db: Session) -> dict:
    invoices = db.query(models.Invoice).all()
    paid = [i for i in invoices if i.status == "paid"]
    pending = [i for i in invoices if i.status in ("draft", "awaiting_payment")]
    overdue = [i for i in invoices if i.status == "overdue"]

    # Calculate USD-normalized sums
    total_rev_usd = sum(_to_usd(i.amount, i.currency) for i in paid)
    outstanding_usd = sum(_to_usd(i.amount, i.currency) for i in pending + overdue)

    # Breakdown by native currency
    by_currency = {}
    for i in invoices:
        ccy = (i.currency or "USD").upper()
        if ccy not in by_currency:
            by_currency[ccy] = {"paid": 0.0, "pending": 0.0}
        if i.status == "paid":
            by_currency[ccy]["paid"] = round(by_currency[ccy]["paid"] + i.amount, 2)
        elif i.status in ("draft", "awaiting_payment", "overdue"):
            by_currency[ccy]["pending"] = round(by_currency[ccy]["pending"] + i.amount, 2)

    return {
        "total_revenue": round(total_rev_usd, 2),
        "outstanding_balance": round(outstanding_usd, 2),
        "paid_invoices": len(paid),
        "pending_invoices": len(pending),
        "overdue_invoices": len(overdue),
        "total_invoices": len(invoices),
        "by_currency": by_currency,
    }


# ---------------------------------------------------------------------------
# Asynchronous Webhook Operations (Tier 2 Enterprise Hardening)
# ---------------------------------------------------------------------------
def process_webhook_event(db: Session, event: dict) -> dict:
    """Handle PayPal webhook events asynchronously to guarantee financial consistency."""
    event_type = event.get("event_type")
    resource = event.get("resource", {})

    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        capture_id = resource.get("id")
        # Try to find corresponding payment via invoice ID or custom_id
        invoice_id = resource.get("custom_id")
        payment = None
        if invoice_id:
            payment = db.query(models.Payment).filter(models.Payment.invoice_id == invoice_id).first()

        if not payment and "supplementary_data" in resource:
            order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
            if order_id:
                payment = db.query(models.Payment).filter(models.Payment.paypal_order_id == order_id).first()

        if payment:
            payment.status = "captured"
            payment.paypal_capture_id = capture_id
            payment.captured_at = datetime.now(timezone.utc)
            invoice = db.get(models.Invoice, payment.invoice_id)
            if invoice:
                invoice.status = "paid"
            db.commit()
            return {"status": "processed", "event": event_type, "invoice": invoice.invoice_number if invoice else None}

    elif event_type == "CHECKOUT.ORDER.APPROVED":
        order_id = resource.get("id")
        payment = db.query(models.Payment).filter(models.Payment.paypal_order_id == order_id).first()
        if payment:
            payment.status = "approved"
            db.commit()
            return {"status": "processed", "event": event_type, "order_id": order_id}

    return {"status": "ignored", "event": event_type}


# ---------------------------------------------------------------------------
# Developer & Demo Utilities
# ---------------------------------------------------------------------------
def reset_demo_database(db: Session) -> dict:
    """Reset all application tables to a pristine state for demo recording."""
    db.query(models.Reminder).delete()
    db.query(models.Payment).delete()
    db.query(models.Invoice).delete()
    db.query(models.Client).delete()
    db.query(models.AgentRun).delete()
    db.commit()
    return {"status": "success", "message": "Demo database wiped clean."}
