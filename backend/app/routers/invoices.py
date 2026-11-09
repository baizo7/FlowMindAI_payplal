from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/api/v1/invoices", tags=["invoices"])


@router.get("", response_model=List[schemas.InvoiceOut])
def list_invoices(db: Session = Depends(get_db)):
    return db.query(models.Invoice).order_by(models.Invoice.created_at.desc()).all()


@router.get("/{invoice_id}", response_model=schemas.InvoiceOut)
def get_invoice(invoice_id: str, db: Session = Depends(get_db)):
    invoice = db.get(models.Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.get("/{invoice_id}/detail", response_model=schemas.InvoiceDetailOut)
def get_invoice_detail(invoice_id: str, db: Session = Depends(get_db)):
    """Fetch complete invoice details with client and payments for the preview modal."""
    invoice = db.get(models.Invoice, invoice_id)
    if not invoice:
        # Also check by invoice number
        invoice = db.query(models.Invoice).filter(models.Invoice.invoice_number == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    client = invoice.client
    return schemas.InvoiceDetailOut(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        client_name=client.name if client else "Client",
        client_email=client.email if client else "",
        company=client.company if client else None,
        description=invoice.description,
        amount=invoice.amount,
        currency=invoice.currency,
        status=invoice.status,
        due_date=invoice.due_date,
        created_at=invoice.created_at,
        payments=invoice.payments,
    )


@router.get("/{invoice_id}/payments", response_model=List[schemas.PaymentOut])
def get_invoice_payments(invoice_id: str, db: Session = Depends(get_db)):
    return db.query(models.Payment).filter(models.Payment.invoice_id == invoice_id).all()


clients_router = APIRouter(prefix="/api/v1/clients", tags=["clients"])


@clients_router.get("", response_model=List[schemas.ClientOut])
def list_clients(db: Session = Depends(get_db)):
    return db.query(models.Client).order_by(models.Client.created_at.desc()).all()
