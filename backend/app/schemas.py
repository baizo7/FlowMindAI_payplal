from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    email: str
    company: Optional[str] = None


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    invoice_number: str
    client_id: str
    client_name: Optional[str] = None
    description: str
    amount: float
    currency: str
    status: str
    due_date: Optional[datetime] = None
    created_at: datetime


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    invoice_id: str
    invoice_number: Optional[str] = None
    paypal_order_id: Optional[str] = None
    paypal_capture_id: Optional[str] = None
    amount: float
    currency: str
    status: str
    approval_url: Optional[str] = None
    created_at: datetime
    captured_at: Optional[datetime] = None


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    tool_calls: List[str] = []
    run_id: str


class AnalyticsOverview(BaseModel):
    total_revenue: float
    outstanding_balance: float
    paid_invoices: int
    pending_invoices: int
    overdue_invoices: int


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    input_text: str
    output_text: Optional[str] = None
    tool_calls: Optional[str] = None
    status: str
    created_at: datetime


class InvoiceDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    invoice_number: str
    client_name: str
    client_email: str
    company: Optional[str] = None
    description: str
    amount: float
    currency: str
    status: str
    due_date: Optional[datetime] = None
    created_at: datetime
    payments: List[PaymentOut] = []


class ResetResponse(BaseModel):
    status: str
    message: str
