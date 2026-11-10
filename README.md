# FlowMind AI

> **Autonomous payment operations assistant for freelancers and small businesses.**  
> Talk to it in plain English — it creates invoices, generates PayPal (sandbox) payment links, checks payment status, chases overdue clients, and summarizes your finances.

Built for the **PayPal AI Hackathon 2026 — "Build What's Next with PayPal and AI."**

---

## 🚀 Live Demo

- **Live Deployed Web App:** [https://flowmindai-payplal.onrender.com/](https://flowmindai-payplal.onrender.com/)
- **GitHub Repository:** [https://github.com/baizo7/FlowMindAI_payplal](https://github.com/baizo7/FlowMindAI_payplal)

---

## What it does

> *"Create an invoice for Priya at priya@example.com for $150 for logo design, due in 3 days."*

FlowMind AI (powered by Google Gemini function calling) parses the prompt, creates the invoice in the database, and immediately generates a live PayPal sandbox checkout link. Once approved in sandbox, the assistant captures the funds, settles the invoice to **Paid**, and updates the live revenue dashboard with verified settlements — never fake claims.

### Key Features

- 🤖 **Autonomous AI Agent**: Google Gemini (`gemini-3.5-flash-lite`) function-calling orchestrator controlling 8 backend tools.
- 💳 **PayPal Orders API v2**: Real sandbox OAuth2 authentication, order creation with `NO_SHIPPING` optimization, buyer approval, and capture.
- ⚡ **Auto-Capture & 1-Click Capture**: Seamless return flow captures funds automatically upon return or via a 1-click dashboard button.
- 🖨️ **Printable Invoice Modal**: Click any invoice ID to open a professional, printable invoice preview with `window.print()` / PDF export.
- 🔍 **AI Execution Audit Trail**: Transparent log showing judges and users every tool call, argument, timestamp, and status.
- 🔄 **1-Click Demo Reset**: Reset database back to clean $0.00 revenue anytime for clean demo video takes.

## Why it's simple on purpose

This was built solo in a few days, so the architecture deliberately trades
production completeness for something that is small, correct, and runnable
end-to-end:

| Full production version | This build | Why |
|---|---|---|
| Postgres + Alembic migrations | SQLite + `create_all()` | zero infra to stand up |
| 5 separate agent microservices | 1 FastAPI process, 4 tool modules | same multi-agent behavior, no deploy complexity |
| Scheduled background worker for reminders | reminders sent on-demand ("send overdue reminders") | demoable without cron infra |
| Verified PayPal webhook receiver | direct `capture` API call after buyer approval | still real, PayPal-confirmed payment; webhook verification noted as a follow-up in `paypal_client.py` |
| Full auth system | single-tenant, no login | the point being demoed is the agent + payments, not auth |
| React + TypeScript frontend | one static HTML/JS page served by FastAPI | no build step, one Render service instead of three |

Everything in the left column is a reasonable next step, not a thing that was
missed — see the comments in `backend/app/*.py` for notes on what a
production version would add.

## Architecture

```
flowmind-ai/
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI app, wires routers + serves frontend
│   │   ├── config.py          env-based settings
│   │   ├── database.py        SQLite/SQLAlchemy setup
│   │   ├── models.py          Client, Invoice, Payment, Reminder, AgentRun
│   │   ├── schemas.py         Pydantic response models
│   │   ├── paypal_client.py   PayPal Orders API v2 (sandbox)
│   │   ├── tools.py           Invoice / Payment / Reminder / Finance "agent" logic
│   │   ├── gemini_agent.py    Gemini function-calling orchestrator
│   │   └── routers/           REST endpoints
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── index.html             chat UI + live dashboard, vanilla JS
├── LICENSE (MIT)
└── README.md
```

**Request flow:** user message → `gemini_agent.run_chat()` → Gemini decides
which tool(s) to call → `tools.py` executes real logic against SQLite and
`paypal_client.py` (real PayPal sandbox calls) → results go back to Gemini →
natural-language reply + an audit trail of exactly which tools ran, shown in
the UI and stored in `agent_runs`.

**Security principle:** Gemini never touches the database or PayPal
directly — it can only request one of a fixed set of named tools with
validated arguments. It cannot fabricate a "payment succeeded" state; only a
real PayPal `COMPLETED` capture response can set an invoice to `paid`.

## Setup (local)

Requires Python 3.11+.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

1. **PayPal sandbox credentials** — create an app at
   [developer.paypal.com/dashboard/applications](https://developer.paypal.com/dashboard/applications),
   copy the sandbox **Client ID** and **Secret** into `PAYPAL_CLIENT_ID` /
   `PAYPAL_CLIENT_SECRET`.
2. **Gemini API key** — get a free key at
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey), put it
   in `GEMINI_API_KEY`. The default model configured is `gemini-3.5-flash-lite`.

Run it:

```bash
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** — the chat UI and dashboard are both there.

## Trying the full payment loop

1. In the chat: `Create an invoice for Priya at priya@example.com for $150
   for logo design`
2. `Create a payment link for INV-0001` — the assistant returns a PayPal
   sandbox approval URL.
3. Open that URL, log in with a PayPal **sandbox buyer** account (create one
   under [developer.paypal.com → Sandbox → Accounts](https://developer.paypal.com/dashboard/accounts)),
   approve the payment.
4. Back in chat: `Capture the payment for that order` (or give the PayPal
   order ID). The invoice flips to `paid` and the dashboard's revenue number
   updates — this is a real sandbox transaction, not a mocked one.
5. Try: `What's my financial summary?` or `Send reminders for overdue
   invoices` (backdate a due date via the API to see this fire).

## Deployment (Render)

The application is deployed on Render as a single unified service:

- **Live URL:** [https://flowmindai-payplal.onrender.com/](https://flowmindai-payplal.onrender.com/)
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Environment variables:**
  - `PAYPAL_CLIENT_ID`
  - `PAYPAL_CLIENT_SECRET`
  - `PAYPAL_BASE_URL` (`https://api-m.sandbox.paypal.com`)
  - `GEMINI_API_KEY`
  - `GEMINI_MODEL` (`gemini-3.5-flash-lite`)
  - `RENDER_EXTERNAL_URL` (automatically detected by Render for instant redirect capture)

## AI tools used

- **Google Gemini** (`gemini-3.5-flash-lite` via the `google-genai` SDK) — natural
  language understanding and function-calling orchestration. Gemini decides
  *which* of the backend tools to call and with what arguments; it never
  executes financial logic itself.
- **APIMatic Context Plugin** *(optional sponsor tool)* — used during
  development to give the AI coding assistant accurate PayPal API context
  while building `paypal_client.py`.

## PayPal integration

- **Orders API v2** (sandbox): `POST /v2/checkout/orders`,
  `POST /v2/checkout/orders/{id}/capture`, `GET /v2/checkout/orders/{id}`.
- OAuth2 client-credentials token flow, cached in memory.
- See `backend/app/paypal_client.py` for the full implementation and notes
  on the webhook-verification simplification.

## License

MIT — see [LICENSE](./LICENSE).
