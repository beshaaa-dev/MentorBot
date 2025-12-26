import hmac
import hashlib
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from logger import setup_logger


def _load_env() -> None:
    """Load .env next to this file (project root), regardless of absolute path."""
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path, override=True)


_load_env()

logger = setup_logger(__name__)

app = FastAPI(title="amoCRM Chat Webhook")

# Optional shared secret to verify that requests come from amoCRM
WEBHOOK_SECRET = os.getenv("AMO_CHAT_WEBHOOK_SECRET")


def verify_signature(body: bytes, signature: str | None) -> None:
    """Simple HMAC-SHA256 check if secret provided."""
    if not WEBHOOK_SECRET:
        return
    if not signature:
        raise HTTPException(status_code=401, detail="Missing signature")
    digest = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")


@app.post("/location/{scope_id}")
async def handle_chat_webhook(
    scope_id: str, request: Request, x_signature: str | None = Header(default=None)
):
    # Read raw body once to allow signature verification and JSON parsing
    raw_body = await request.body()

    # Verify signature if secret configured
    verify_signature(raw_body, x_signature)

    try:
        payload = await request.json()
    except Exception:
        logger.warning("amoCRM webhook: failed to parse JSON body")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Log key fields; replace with domain logic as needed
    event = payload.get("event")
    logger.info(
        "amoCRM webhook received",
        extra={"scope_id": scope_id, "event": event, "payload": payload},
    )

    # TODO: route payload by scope_id to account-specific handlers
    # e.g., dispatch to queue, map scope_id -> account -> CRM actions/Telegram bot

    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    # For local runs: uvicorn chat_webhook:app --reload --host 0.0.0.0 --port 8000
    import uvicorn

    uvicorn.run("chat_webhook:app", host="0.0.0.0", port=8000, reload=False)
