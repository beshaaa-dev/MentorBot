import asyncio
import hmac
import hashlib
import os
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from config import CRM_HOMEWORK_PIPELINE, CRM_HW_ASSIGNED_STATUS, CRM_HW_EDIT_STATUS
from logger import setup_logger

logger = setup_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from crm.crm_service import init_amo_crm_integration

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, init_amo_crm_integration)
    yield


app = FastAPI(title="amoCRM Webhook", lifespan=lifespan)

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


@app.post("/homework/edit")
async def homework_edit(request: Request):
    form = await request.form()

    pipeline_id = form.get("leads[status][0][pipeline_id]", "")
    status_id = form.get("leads[status][0][status_id]", "")
    lead_id = form.get("leads[status][0][id]", "")

    if pipeline_id != str(CRM_HOMEWORK_PIPELINE) or status_id != CRM_HW_EDIT_STATUS:
        logger.warning(
            "homework_edit: unexpected pipeline_id=%s status_id=%s — ignoring",
            pipeline_id,
            status_id,
        )
        return JSONResponse({"status": "ignored"})

    if not lead_id:
        logger.warning("homework_edit: missing lead id in form payload")
        raise HTTPException(status_code=400, detail="Missing lead id")

    logger.info("homework_edit: processing lead_id=%s", lead_id)

    try:
        from crm.crm_service import get_crm_lead
        from database.homework_service import get_homework_by_lead_id, update_homework_status
        from database.models import HomeworkStatus

        loop = asyncio.get_running_loop()

        lead = await loop.run_in_executor(None, get_crm_lead, lead_id)
        if not lead:
            logger.warning("homework_edit: CRM lead %s not found", lead_id)
            return JSONResponse({"status": "error"}, status_code=404)

        edit_reason = getattr(lead, "hw_edit_reason", None) or ""

        student_tg_id: int | None = None
        contact_refs = (lead._data.get("_embedded") or {}).get("contacts")
        if contact_refs:
            for contact in lead.contacts:
                raw_tg_id = contact.telegram_id
                if raw_tg_id:
                    try:
                        student_tg_id = int(str(raw_tg_id).strip())
                    except ValueError:
                        continue
                    break

        if not student_tg_id:
            logger.warning("homework_edit: no student tg_id for lead_id=%s", lead_id)
            return JSONResponse({"status": "ok"})

        homework = await loop.run_in_executor(None, get_homework_by_lead_id, lead_id)
        if not homework:
            logger.warning("homework_edit: no homework record for lead_id=%s", lead_id)
            return JSONResponse({"status": "error"}, status_code=404)

        await loop.run_in_executor(
            None, update_homework_status, homework.id, HomeworkStatus.EDIT
        )
    except Exception as e:
        logger.error("homework_edit: failed to process: %s", e, exc_info=True)
        return JSONResponse({"status": "error"}, status_code=500)

    try:
        from telegram import Bot
        from keyboards import get_edit_homework_keyboard
        from messages import HW_EDIT_NOTIFICATION

        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(
                chat_id=student_tg_id,
                text=HW_EDIT_NOTIFICATION.format(reason=edit_reason),
                reply_markup=get_edit_homework_keyboard(homework.id),
            )
        logger.info(
            "homework_edit: sent notification to student tg_id=%s for hw_id=%s",
            student_tg_id,
            homework.id,
        )
    except Exception as e:
        logger.error(
            "homework_edit: failed to send Telegram message: %s", e, exc_info=True
        )

    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    # For local runs: uvicorn webhooks:app --reload --host 0.0.0.0 --port 8000
    import uvicorn

    uvicorn.run("webhooks:app", host="0.0.0.0", port=8000, reload=False)
