"""
Gemini orchestrator (the "Orchestrator Agent" from the spec).

Uses Gemini's function calling to turn a natural-language instruction into
calls against the tool functions in tools.py (Invoice / Payment /
Reminder / Finance "agents"). This is one process, not five separate
services - see tools.py docstring for why that's the right call for a
solo, few-day build.

IMPORTANT: Google's Gemini SDK surface changes fairly often. This uses
the `google-genai` package (`pip install google-genai`), which is
Google's current unified SDK as of early 2026. If `import google.genai`
fails or the API below has moved, check https://ai.google.dev/gemini-api/docs
for the current quickstart and adjust - this file is the single place
that talks to Gemini, so fixes are localized here.
"""
import json
import uuid as uuid_lib

from google import genai
from google.genai import types
from sqlalchemy.orm import Session

from app import tools, models
from app.config import settings

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Get a free key at "
                "https://aistudio.google.com/apikey and put it in backend/.env"
            )
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


SYSTEM_INSTRUCTION = """You are FlowMind AI, an autonomous payment operations
assistant for freelancers and small businesses. You help manage invoices,
collect payments through PayPal, chase overdue clients, and summarize
finances.

Rules you must follow:
- Only act using the provided tools. Never claim an invoice or payment succeeded
  unless a tool result says so.
- When the user asks to create a payment link or generate a PayPal order for an
  invoice (e.g. "Create a payment link for INV-0001", "Generate PayPal link", or
  "Yes, create payment link for INV-0001"):
  Immediately execute the `create_payment_order` tool for that invoice. A direct
  user command constitutes authorization.
  Always prominently display the returned `approval_url` as a clickable Markdown
  link in your response (e.g., [Click here to pay via PayPal Sandbox](approval_url)).
- If the user says "Yes", "Confirm", or "Proceed" without an invoice number, use
  `list_invoices` to locate the most recent draft or unpaid invoice and create the
  payment link for it immediately.
- When the user asks to capture a payment (e.g. "Capture the payment for INV-0001"):
  Immediately execute `capture_payment`.
- When creating an invoice, call `create_invoice` and clearly confirm the created
  invoice number, client, and amount.
- Be concise and concrete. When you show money, always include the currency (e.g. $150.00 USD).
- If a request is ambiguous, ask a short clarifying question.
"""

# JSON schema function declarations mirroring tools.py. Kept minimal/explicit
# rather than auto-derived from Python type hints, so the contract with the
# model is easy to read and audit.
TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="create_invoice",
        description="Create a new invoice for a client.",
        parameters={
            "type": "object",
            "properties": {
                "client_name": {"type": "string"},
                "client_email": {"type": "string"},
                "company": {"type": "string"},
                "description": {"type": "string", "description": "What the invoice is for"},
                "amount": {"type": "number"},
                "currency": {"type": "string", "description": "3-letter ISO code, e.g. USD"},
                "due_in_days": {"type": "integer", "description": "Days until due, default 7"},
            },
            "required": ["client_name", "client_email", "description", "amount"],
        },
    ),
    types.FunctionDeclaration(
        name="get_invoice",
        description="Look up an invoice by its invoice number (e.g. INV-0001).",
        parameters={
            "type": "object",
            "properties": {"invoice_number": {"type": "string"}},
            "required": ["invoice_number"],
        },
    ),
    types.FunctionDeclaration(
        name="create_payment_order",
        description="Create a real PayPal sandbox payment order for an invoice "
                     "and return the approval link the client uses to pay.",
        parameters={
            "type": "object",
            "properties": {"invoice_number": {"type": "string"}},
            "required": ["invoice_number"],
        },
    ),
    types.FunctionDeclaration(
        name="capture_payment",
        description="Finalize (capture) a PayPal order after the buyer has "
                     "approved it in the sandbox checkout. Accepts either the PayPal order ID or the invoice number (e.g. INV-0001).",
        parameters={
            "type": "object",
            "properties": {"paypal_order_id": {"type": "string", "description": "PayPal Order ID (e.g. 5O19...) or Invoice Number (e.g. INV-0001)"}},
            "required": ["paypal_order_id"],
        },
    ),
    types.FunctionDeclaration(
        name="list_invoices",
        description="List recent invoices, optionally filtered by status (draft, awaiting_payment, paid, overdue, cancelled).",
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status: draft, awaiting_payment, paid, overdue, cancelled"},
                "limit": {"type": "integer", "description": "Maximum number of invoices to return, default 10"},
            },
        },
    ),
    types.FunctionDeclaration(
        name="get_payment_status",
        description="Check the payment status of an invoice.",
        parameters={
            "type": "object",
            "properties": {"invoice_number": {"type": "string"}},
            "required": ["invoice_number"],
        },
    ),
    types.FunctionDeclaration(
        name="send_overdue_reminders",
        description="Find all overdue invoices and send each client a reminder.",
        parameters={"type": "object", "properties": {}},
    ),
    types.FunctionDeclaration(
        name="get_financial_summary",
        description="Get overall revenue, outstanding balance, and invoice counts.",
        parameters={"type": "object", "properties": {}},
    ),
]

_TOOL_IMPL = {
    "create_invoice": tools.create_invoice,
    "get_invoice": tools.get_invoice,
    "list_invoices": tools.list_invoices,
    "create_payment_order": tools.create_payment_order,
    "capture_payment": tools.capture_payment,
    "get_payment_status": tools.get_payment_status,
    "send_overdue_reminders": tools.send_overdue_reminders,
    "get_financial_summary": tools.get_financial_summary,
}

MAX_TOOL_ROUNDS = 4


def run_chat(db: Session, user_message: str) -> dict:
    """Run one turn of the orchestrator: send the message, execute any
    tool calls Gemini requests (against the real DB/PayPal), feed results
    back, and return the final natural-language reply plus an audit trail."""
    client = _get_client()
    tool_config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
    )

    contents = [types.Content(role="user", parts=[types.Part(text=user_message)])]
    tool_call_log = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=contents,
            config=tool_config,
        )
        candidate = response.candidates[0]
        parts = candidate.content.parts

        function_calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
        if not function_calls:
            final_text = "".join(p.text for p in parts if getattr(p, "text", None)).strip() or "I have processed your request."
            run_id = _log_run(db, user_message, final_text, tool_call_log, "completed")
            return {"reply": final_text, "tool_calls": tool_call_log, "run_id": run_id}

        # Append the model's turn (including the function call) to history
        contents.append(candidate.content)

        # Execute each requested tool call for real, against the DB/PayPal
        response_parts = []
        for fc in function_calls:
            fn_name = fc.name
            fn_args = dict(fc.args) if fc.args else {}
            tool_call_log.append(f"{fn_name}({json.dumps(fn_args)})")

            impl = _TOOL_IMPL.get(fn_name)
            if impl is None:
                result = {"error": f"Unknown tool {fn_name}"}
            else:
                try:
                    result = impl(db, **fn_args)
                except TypeError as e:
                    result = {"error": f"Bad arguments for {fn_name}: {e}"}

            response_parts.append(
                types.Part.from_function_response(name=fn_name, response=result)
            )

        contents.append(types.Content(role="user", parts=response_parts))

    # Safety valve: too many tool rounds without a final answer
    fallback = "I ran into trouble completing that in a reasonable number of steps - could you rephrase or split it into smaller requests?"
    run_id = _log_run(db, user_message, fallback, tool_call_log, "error")
    return {"reply": fallback, "tool_calls": tool_call_log, "run_id": run_id}


def _log_run(db: Session, input_text: str, output_text: str, tool_calls: list, status: str):
    run = models.AgentRun(
        id=str(uuid_lib.uuid4()),
        input_text=input_text,
        output_text=output_text,
        tool_calls=json.dumps(tool_calls),
        status=status,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run.id
