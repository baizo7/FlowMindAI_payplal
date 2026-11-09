"""
Data model - trimmed on purpose.

Simplifications vs. a production system (call these out in the README/demo
so judges see they're deliberate, not accidental):
  - Single-tenant: no users/auth table. Fine for a hackathon demo; a real
    product would add a users table + auth middleware here.
  - Reminders are sent on-demand when asked ("send overdue reminders"),
    not by a scheduled background worker. Still demonstrates the agent
    behavior; just no cron infra to deploy.
  - payment_attempts folded into a single `payments` table.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class Client(Base):
    __tablename__ = "clients"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    company = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now)

    invoices = relationship("Invoice", back_populates="client")


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(String, primary_key=True, default=_uuid)
    invoice_number = Column(String, unique=True, nullable=False)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    description = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    # draft | awaiting_payment | paid | cancelled | overdue
    status = Column(String, default="draft")
    due_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)

    client = relationship("Client", back_populates="invoices")
    payments = relationship("Payment", back_populates="invoice")

    @property
    def client_name(self) -> str:
        return self.client.name if self.client else ""


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String, primary_key=True, default=_uuid)
    invoice_id = Column(String, ForeignKey("invoices.id"), nullable=False)
    paypal_order_id = Column(String, nullable=True)
    paypal_capture_id = Column(String, nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    # created | approved | captured | failed
    status = Column(String, default="created")
    approval_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now)
    captured_at = Column(DateTime, nullable=True)

    invoice = relationship("Invoice", back_populates="payments")

    @property
    def invoice_number(self) -> str:
        return self.invoice.invoice_number if self.invoice else ""


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(String, primary_key=True, default=_uuid)
    invoice_id = Column(String, ForeignKey("invoices.id"), nullable=False)
    recipient_email = Column(String, nullable=True)
    channel = Column(String, default="email")  # email | notification
    message = Column(Text, nullable=False)
    status = Column(String, default="sent")  # sent | failed
    created_at = Column(DateTime, default=_now)

    invoice = relationship("Invoice")


class AgentRun(Base):
    """Execution log for every AI tool call - makes the agent's reasoning
    visible in the UI/demo, which is cheap to build and great for judges."""
    __tablename__ = "agent_runs"

    id = Column(String, primary_key=True, default=_uuid)
    input_text = Column(Text, nullable=False)
    output_text = Column(Text, nullable=True)
    tool_calls = Column(Text, nullable=True)  # JSON-encoded list
    status = Column(String, default="completed")  # completed | error
    created_at = Column(DateTime, default=_now)
