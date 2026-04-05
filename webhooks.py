import asyncio
import hmac
import hashlib
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from config import CRM_HOMEWORK_PIPELINE, CRM_HW_ASSIGNED_STATUS
from logger import setup_logger


def _load_env() -> None:
    """Load .env next to this file (project root), regardless of absolute path."""
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path, override=True)


_load_env()

logger = setup_logger(__name__)

app = FastAPI(title="amoCRM Webhook")

WEBHOOK_SECRET = os.getenv("AMO_CHAT_WEBHOOK_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


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
    raw_body = await request.body()
    verify_signature(raw_body, x_signature)

    try:
        payload = await request.json()
    except Exception:
        logger.warning("amoCRM webhook: failed to parse JSON body")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event")
    logger.info(
        "amoCRM webhook received",
        extra={"scope_id": scope_id, "event": event, "payload": payload},
    )

    return JSONResponse({"status": "ok"})


@app.post("/homework/assigned")
async def homework_assigned(request: Request):
    form = await request.form()

    pipeline_id = form.get("leads[status][0][pipeline_id]", "")
    status_id = form.get("leads[status][0][status_id]", "")
    lead_id = form.get("leads[status][0][id]", "")

    if pipeline_id != str(CRM_HOMEWORK_PIPELINE) or status_id != CRM_HW_ASSIGNED_STATUS:
        logger.warning(
            "homework_assigned: unexpected pipeline_id=%s status_id=%s — ignoring",
            pipeline_id,
            status_id,
        )
        return JSONResponse({"status": "ignored"})

    if not lead_id:
        logger.warning("homework_assigned: missing lead id in form payload")
        raise HTTPException(status_code=400, detail="Missing lead id")

    logger.info("homework_assigned: processing lead_id=%s", lead_id)

    try:
        from repositories.homework_repository import save_homework_from_webhook

        loop = asyncio.get_running_loop()
        homework, student_tg_id = await loop.run_in_executor(
            None, save_homework_from_webhook, lead_id
        )
    except Exception as e:
        logger.error("homework_assigned: failed to save homework: %s", e, exc_info=True)
        return JSONResponse({"status": "error"}, status_code=500)

    if not student_tg_id:
        logger.warning("homework_assigned: no student tg_id for lead_id=%s", lead_id)
        return JSONResponse({"status": "ok"})

    try:
        from telegram import Bot
        from keyboards import get_start_homework_keyboard
        from messages import HW_NEW_ASSIGNMENT

        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(
                chat_id=student_tg_id,
                text=HW_NEW_ASSIGNMENT,
                reply_markup=get_start_homework_keyboard(homework.id),
            )
        logger.info(
            "homework_assigned: sent notification to student tg_id=%s for hw_id=%s",
            student_tg_id,
            homework.id,
        )
    except Exception as e:
        logger.error(
            "homework_assigned: failed to send Telegram message: %s", e, exc_info=True
        )

    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    # For local runs: uvicorn webhooks:app --reload --host 0.0.0.0 --port 8000
    import uvicorn

    uvicorn.run("webhooks:app", host="0.0.0.0", port=8000, reload=False)
