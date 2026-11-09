from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.database import init_db, get_db
from app.routers import invoices, payments, ai, analytics
from app import tools, paypal_client, schemas


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="FlowMind AI", version="0.1.0", lifespan=lifespan)

# Permissive CORS for the hackathon demo. Lock this down to your real
# frontend origin before/if this ever goes beyond a demo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/dev/reset", response_model=schemas.ResetResponse)
def reset_database(db: Session = Depends(get_db)):
    """Reset all tables to start from a clean slate ($0 revenue) for demo takes."""
    res = tools.reset_demo_database(db)
    return schemas.ResetResponse(status=res["status"], message=res["message"])


@app.post("/api/v1/webhooks/paypal")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)):
    """Asynchronous PayPal Webhook Receiver with signature verification.
    Tier 2 Enterprise Hardening."""
    headers = dict(request.headers)
    try:
        raw_event = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Cryptographic signature verification check
    verified = paypal_client.verify_webhook_signature(headers, raw_event)
    if not verified:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    result = tools.process_webhook_event(db, raw_event)
    return {"status": "ok", "result": result}


@app.get("/payment-complete", response_class=HTMLResponse)
def payment_complete(request: Request, token: str = "", PayerID: str = ""):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>PayPal Sandbox Approval — FlowMind AI</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f6f4ee;
    color: #16211b;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    margin: 0;
    padding: 20px;
    box-sizing: border-box;
  }}
  .card {{
    background: #ffffff;
    border: 1px solid #dfe3da;
    border-radius: 12px;
    padding: 36px 40px;
    max-width: 480px;
    width: 100%;
    text-align: center;
    box-shadow: 0 4px 18px rgba(0,0,0,0.04);
  }}
  .badge {{
    display: inline-block;
    background: #e4efe8;
    color: #0b5d3b;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 99px;
    margin-bottom: 14px;
  }}
  h1 {{ font-size: 22px; margin: 0 0 10px; color: #16211b; }}
  p {{ color: #4b5a51; font-size: 14.5px; line-height: 1.5; margin: 0 0 20px; }}
  .order-id {{
    font-family: ui-monospace, monospace;
    background: #f1ede1;
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 13.5px;
    display: inline-block;
    margin-bottom: 24px;
    word-break: break-all;
  }}
  .btn {{
    display: block;
    background: #0b5d3b;
    color: #ffffff;
    text-decoration: none;
    padding: 12px 20px;
    border-radius: 8px;
    font-size: 14.5px;
    font-weight: 500;
    transition: background 0.15s ease;
  }}
  .btn:hover {{ background: #08492e; }}
</style>
</head>
<body>
<div class="card">
  <div class="badge">PayPal Sandbox Approved</div>
  <h1>Payment Approved by Buyer</h1>
  <p>The buyer has authorized this transaction. To complete the settlement, return to FlowMind AI and ask the agent to capture the order.</p>
  <div class="order-id">Order ID: {token or "N/A"}</div>
  <a class="btn" href="/?approved_order={token}">Return to FlowMind AI to Capture</a>
</div>
</body>
</html>"""


@app.get("/payment-cancelled", response_class=HTMLResponse)
def payment_cancelled():
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>PayPal Checkout Cancelled — FlowMind AI</title>
<style>
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f6f4ee;
    color: #16211b;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    margin: 0;
    padding: 20px;
    box-sizing: border-box;
  }
  .card {
    background: #ffffff;
    border: 1px solid #dfe3da;
    border-radius: 12px;
    padding: 36px 40px;
    max-width: 440px;
    width: 100%;
    text-align: center;
    box-shadow: 0 4px 18px rgba(0,0,0,0.04);
  }
  h1 { font-size: 20px; margin: 0 0 10px; color: #a9480f; }
  p { color: #4b5a51; font-size: 14.5px; line-height: 1.5; margin: 0 0 24px; }
  .btn {
    display: block;
    background: #0b5d3b;
    color: #ffffff;
    text-decoration: none;
    padding: 12px 20px;
    border-radius: 8px;
    font-size: 14.5px;
  }
</style>
</head>
<body>
<div class="card">
  <h1>Checkout Cancelled</h1>
  <p>The PayPal sandbox checkout session was cancelled. No charges were made.</p>
  <a class="btn" href="/">Return to FlowMind AI</a>
</div>
</body>
</html>"""


# API routers first, so they take priority over the static file mount below.
app.include_router(invoices.router)
app.include_router(invoices.clients_router)
app.include_router(payments.router)
app.include_router(ai.router)
app.include_router(analytics.router)

# Serve the single-page frontend from the same service so the whole app is
# one Render web service - no separate frontend deploy/build step to manage
# with three days left.
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
