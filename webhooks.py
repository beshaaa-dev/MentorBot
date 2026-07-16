import asyncio
import hmac
import hashlib
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from config import (
    CRM_HOMEWORK_PIPELINE,
    CRM_HW_ASSIGNED_STATUS,
    CRM_HW_EDIT_STATUS,
    CRM_HW_EDIT_FROM_MENTOR_STATUS,
    CRM_HW_FOR_MENTOR_STATUS,
    CRM_HW_APPROVED_STATUS,
    CRM_SELECTION_PIPELINE,
    CRM_TASK_ASSIGNED_STATUS,
    CRM_TASK_VALIDATED_STATUS,
    CRM_TASK_EDIT_STATUS,
)
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

# --- Дедупликация вебхуков ---
_DEDUP_TTL = 60  # секунды
_dedup_cache: dict[str, float] = {}


def _is_duplicate(key: str) -> bool:
    """Возвращает True, если вебхук с данным ключом уже обработан в пределах TTL."""
    now = time.monotonic()
    # Очистка устаревших записей
    expired = [k for k, ts in _dedup_cache.items() if now - ts > _DEDUP_TTL]
    for k in expired:
        del _dedup_cache[k]
    if key in _dedup_cache:
        return True
    _dedup_cache[key] = now
    return False


_background_tasks: set[asyncio.Task] = set()


def _create_background_task(coro) -> None:
    """Создаёт фоновую задачу с корректной обработкой ошибок и prevent GC."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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


async def _process_homework_assigned(lead_id: str) -> None:
    """Фоновая обработка вебхука назначения ДЗ."""
    try:
        from repositories.homework_repository import save_homework_from_webhook

        loop = asyncio.get_running_loop()
        homework, student_tg_id = await loop.run_in_executor(
            None, save_homework_from_webhook, lead_id
        )
    except Exception as e:
        logger.error("homework_assigned: failed to save homework: %s", e, exc_info=True)
        return

    if not student_tg_id:
        logger.warning("homework_assigned: no student tg_id for lead_id=%s", lead_id)
        return

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


@app.post("/homework/assigned")
async def homework_assigned(request: Request):
    form = await request.form()

    pipeline_id = form.get("leads[status][0][pipeline_id]", "")
    status_id = form.get("leads[status][0][status_id]", "")
    lead_id = form.get("leads[status][0][id]", "")

    if pipeline_id != str(CRM_HOMEWORK_PIPELINE) or status_id != CRM_HW_ASSIGNED_STATUS:
        return JSONResponse({"status": "ignored"})

    if not lead_id:
        raise HTTPException(status_code=400, detail="Missing lead id")

    dedup_key = f"assigned:{lead_id}"
    if _is_duplicate(dedup_key):
        logger.info("homework_assigned: duplicate webhook for lead_id=%s — skipping", lead_id)
        return JSONResponse({"status": "ok"})

    logger.info("homework_assigned: scheduling background processing for lead_id=%s", lead_id)
    _create_background_task(_process_homework_assigned(lead_id))
    return JSONResponse({"status": "ok"})


async def _process_homework_edit(lead_id: str) -> None:
    """Фоновая обработка вебхука редактирования ДЗ."""
    try:
        from repositories.homework_repository import process_homework_edit

        loop = asyncio.get_running_loop()
        homework, student_tg_id, edit_reason = await loop.run_in_executor(
            None, process_homework_edit, lead_id
        )
    except Exception as e:
        logger.error("homework_edit: failed to process: %s", e, exc_info=True)
        return

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


@app.post("/homework/edit")
async def homework_edit(request: Request):
    form = await request.form()

    pipeline_id = form.get("leads[status][0][pipeline_id]", "")
    status_id = form.get("leads[status][0][status_id]", "")
    lead_id = form.get("leads[status][0][id]", "")

    if pipeline_id != str(CRM_HOMEWORK_PIPELINE) or status_id != CRM_HW_EDIT_STATUS:
        return JSONResponse({"status": "ignored"})

    if not lead_id:
        raise HTTPException(status_code=400, detail="Missing lead id")

    dedup_key = f"edit:{lead_id}"
    if _is_duplicate(dedup_key):
        logger.info("homework_edit: duplicate webhook for lead_id=%s — skipping", lead_id)
        return JSONResponse({"status": "ok"})

    logger.info("homework_edit: scheduling background processing for lead_id=%s", lead_id)
    _create_background_task(_process_homework_edit(lead_id))
    return JSONResponse({"status": "ok"})


async def _process_homework_edit_from_mentor(lead_id: str) -> None:
    """Фоновая обработка вебхука возврата ДЗ от ментора."""
    try:
        from repositories.homework_repository import process_homework_edit_from_mentor

        loop = asyncio.get_running_loop()
        homework, student_tg_id, edit_reason = await loop.run_in_executor(
            None, process_homework_edit_from_mentor, lead_id
        )
    except Exception as e:
        logger.error("homework_edit_from_mentor: failed to process: %s", e, exc_info=True)
        return

    try:
        from telegram import Bot
        from keyboards import get_edit_homework_keyboard
        from messages import HW_EDIT_NOTIFICATION

        text = HW_EDIT_NOTIFICATION.format(reason=edit_reason) if edit_reason else HW_EDIT_NOTIFICATION.split("\n\n")[0]
        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(
                chat_id=student_tg_id,
                text=text,
                reply_markup=get_edit_homework_keyboard(homework.id),
            )
        logger.info(
            "homework_edit_from_mentor: sent notification to student tg_id=%s for hw_id=%s",
            student_tg_id,
            homework.id,
        )
    except Exception as e:
        logger.error(
            "homework_edit_from_mentor: failed to send Telegram message: %s", e, exc_info=True
        )


@app.post("/homework/edit_from_mentor")
async def homework_edit_from_mentor(request: Request):
    form = await request.form()

    pipeline_id = form.get("leads[status][0][pipeline_id]", "")
    status_id = form.get("leads[status][0][status_id]", "")
    lead_id = form.get("leads[status][0][id]", "")

    if pipeline_id != str(CRM_HOMEWORK_PIPELINE) or status_id != CRM_HW_EDIT_FROM_MENTOR_STATUS:
        return JSONResponse({"status": "ignored"})

    if not lead_id:
        raise HTTPException(status_code=400, detail="Missing lead id")

    dedup_key = f"edit_from_mentor:{lead_id}"
    if _is_duplicate(dedup_key):
        logger.info("homework_edit_from_mentor: duplicate webhook for lead_id=%s — skipping", lead_id)
        return JSONResponse({"status": "ok"})

    logger.info("homework_edit_from_mentor: scheduling background processing for lead_id=%s", lead_id)
    _create_background_task(_process_homework_edit_from_mentor(lead_id))
    return JSONResponse({"status": "ok"})


async def _process_homework_validated(lead_id: str) -> None:
    """Фоновая обработка вебхука отправки ДЗ ментору."""
    try:
        from repositories.homework_repository import process_homework_for_mentor

        loop = asyncio.get_running_loop()
        homework, mentor_tg_id, mentor_db_id = await loop.run_in_executor(
            None, process_homework_for_mentor, lead_id
        )
    except Exception as e:
        logger.error("homework_validated: failed to process: %s", e, exc_info=True)
        return

    try:
        from telegram import Bot
        from keyboards import get_check_homework_keyboard
        from messages import HW_FOR_MENTOR_NOTIFICATION
        from database.homework_service import get_mentor_hw_notification, upsert_mentor_hw_notification

        old_notification = await loop.run_in_executor(None, get_mentor_hw_notification, mentor_db_id)

        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            if old_notification:
                try:
                    await bot.delete_message(
                        chat_id=old_notification.chat_id,
                        message_id=old_notification.message_id,
                    )
                except Exception:
                    pass

            sent = await bot.send_message(
                chat_id=mentor_tg_id,
                text=HW_FOR_MENTOR_NOTIFICATION,
                reply_markup=get_check_homework_keyboard(homework.id),
            )

        await loop.run_in_executor(
            None, upsert_mentor_hw_notification, mentor_db_id, sent.message_id, mentor_tg_id
        )
        logger.info(
            "homework_validated: sent notification to mentor tg_id=%s for hw_id=%s",
            mentor_tg_id,
            homework.id,
        )
    except Exception as e:
        logger.error(
            "homework_validated: failed to send Telegram message: %s", e, exc_info=True
        )


@app.post("/homework/validated")
async def homework_validated(request: Request):
    form = await request.form()

    pipeline_id = form.get("leads[status][0][pipeline_id]", "")
    status_id = form.get("leads[status][0][status_id]", "")
    lead_id = form.get("leads[status][0][id]", "")

    if pipeline_id != str(CRM_HOMEWORK_PIPELINE) or status_id != CRM_HW_FOR_MENTOR_STATUS:
        return JSONResponse({"status": "ignored"})

    if not lead_id:
        raise HTTPException(status_code=400, detail="Missing lead id")

    dedup_key = f"validated:{lead_id}"
    if _is_duplicate(dedup_key):
        logger.info("homework_validated: duplicate webhook for lead_id=%s — skipping", lead_id)
        return JSONResponse({"status": "ok"})

    logger.info("homework_validated: scheduling background processing for lead_id=%s", lead_id)
    _create_background_task(_process_homework_validated(lead_id))
    return JSONResponse({"status": "ok"})


async def _process_homework_accepted(lead_id: str) -> None:
    """Фоновая обработка вебхука принятия ДЗ."""
    try:
        from repositories.homework_repository import process_homework_accepted

        loop = asyncio.get_running_loop()
        homework, student_tg_id = await loop.run_in_executor(
            None, process_homework_accepted, lead_id
        )
    except Exception as e:
        logger.error("homework_accepted: failed to process: %s", e, exc_info=True)
        return

    if not student_tg_id:
        logger.warning("homework_accepted: no student tg_id for lead_id=%s", lead_id)
        return

    try:
        from telegram import Bot
        from messages import HW_ACCEPTED_NOTIFICATION, HW_ACCEPTED_RATING, HW_ACCEPTED_FEEDBACK

        text = HW_ACCEPTED_NOTIFICATION
        if homework.rating is not None:
            text += HW_ACCEPTED_RATING.format(rating=homework.rating)
        if homework.feedback:
            text += HW_ACCEPTED_FEEDBACK.format(feedback=homework.feedback)

        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(
                chat_id=student_tg_id,
                text=text,
            )
        logger.info(
            "homework_accepted: sent notification to student tg_id=%s for hw_id=%s",
            student_tg_id,
            homework.id,
        )
    except Exception as e:
        logger.error(
            "homework_accepted: failed to send Telegram message: %s", e, exc_info=True
        )


@app.post("/homework/accepted")
async def homework_accepted(request: Request):
    form = await request.form()

    pipeline_id = form.get("leads[status][0][pipeline_id]", "")
    status_id = form.get("leads[status][0][status_id]", "")
    lead_id = form.get("leads[status][0][id]", "")

    if pipeline_id != str(CRM_HOMEWORK_PIPELINE) or status_id != CRM_HW_APPROVED_STATUS:
        return JSONResponse({"status": "ignored"})

    if not lead_id:
        raise HTTPException(status_code=400, detail="Missing lead id")

    dedup_key = f"accepted:{lead_id}"
    if _is_duplicate(dedup_key):
        logger.info("homework_accepted: duplicate webhook for lead_id=%s — skipping", lead_id)
        return JSONResponse({"status": "ok"})

    logger.info("homework_accepted: scheduling background processing for lead_id=%s", lead_id)
    _create_background_task(_process_homework_accepted(lead_id))
    return JSONResponse({"status": "ok"})


async def _process_task_assigned(lead_id: str) -> None:
    try:
        from repositories.task_repository import save_task_from_webhook

        loop = asyncio.get_running_loop()
        task, student_tg_id = await loop.run_in_executor(
            None, save_task_from_webhook, lead_id
        )
    except Exception as e:
        logger.error("task_assigned: failed to save task: %s", e, exc_info=True)
        return

    if not student_tg_id:
        logger.warning("task_assigned: no student tg_id for lead_id=%s", lead_id)
        return

    try:
        from telegram import Bot
        from handlers.answer_utils import with_deadline
        from keyboards import get_start_task_keyboard
        from messages import TASK_NEW_ASSIGNMENT

        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(
                chat_id=student_tg_id,
                text=with_deadline(TASK_NEW_ASSIGNMENT, task.deadline),
                reply_markup=get_start_task_keyboard(task.id),
            )
        logger.info(
            "task_assigned: sent notification to student tg_id=%s for task_id=%s",
            student_tg_id,
            task.id,
        )
    except Exception as e:
        logger.error(
            "task_assigned: failed to send Telegram message: %s", e, exc_info=True
        )


@app.post("/task/assigned")
async def task_assigned(request: Request):
    form = await request.form()

    pipeline_id = form.get("leads[status][0][pipeline_id]", "")
    status_id = form.get("leads[status][0][status_id]", "")
    lead_id = form.get("leads[status][0][id]", "")

    if pipeline_id != str(CRM_SELECTION_PIPELINE) or status_id != CRM_TASK_ASSIGNED_STATUS:
        return JSONResponse({"status": "ignored"})

    if not lead_id:
        raise HTTPException(status_code=400, detail="Missing lead id")

    dedup_key = f"task_assigned:{lead_id}"
    if _is_duplicate(dedup_key):
        logger.info("task_assigned: duplicate webhook for lead_id=%s — skipping", lead_id)
        return JSONResponse({"status": "ok"})

    logger.info("task_assigned: scheduling background processing for lead_id=%s", lead_id)
    _create_background_task(_process_task_assigned(lead_id))
    return JSONResponse({"status": "ok"})


async def _process_task_edit(lead_id: str) -> None:
    try:
        from repositories.task_repository import process_task_edit

        loop = asyncio.get_running_loop()
        task, student_tg_id, edit_reason = await loop.run_in_executor(
            None, process_task_edit, lead_id
        )
    except Exception as e:
        logger.error("task_edit: failed to process: %s", e, exc_info=True)
        return

    try:
        from telegram import Bot
        from handlers.answer_utils import with_deadline
        from keyboards import get_edit_task_keyboard
        from messages import TASK_EDIT_NOTIFICATION

        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            await bot.send_message(
                chat_id=student_tg_id,
                text=with_deadline(
                    TASK_EDIT_NOTIFICATION.format(reason=edit_reason), task.deadline
                ),
                reply_markup=get_edit_task_keyboard(task.id),
            )
        logger.info(
            "task_edit: sent notification to student tg_id=%s for task_id=%s",
            student_tg_id,
            task.id,
        )
    except Exception as e:
        logger.error("task_edit: failed to send Telegram message: %s", e, exc_info=True)


@app.post("/task/edit")
async def task_edit(request: Request):
    form = await request.form()

    pipeline_id = form.get("leads[status][0][pipeline_id]", "")
    status_id = form.get("leads[status][0][status_id]", "")
    lead_id = form.get("leads[status][0][id]", "")

    if pipeline_id != str(CRM_SELECTION_PIPELINE) or status_id != CRM_TASK_EDIT_STATUS:
        return JSONResponse({"status": "ignored"})

    if not lead_id:
        raise HTTPException(status_code=400, detail="Missing lead id")

    dedup_key = f"task_edit:{lead_id}"
    if _is_duplicate(dedup_key):
        logger.info("task_edit: duplicate webhook for lead_id=%s — skipping", lead_id)
        return JSONResponse({"status": "ok"})

    logger.info("task_edit: scheduling background processing for lead_id=%s", lead_id)
    _create_background_task(_process_task_edit(lead_id))
    return JSONResponse({"status": "ok"})


async def _process_task_validated(lead_id: str) -> None:
    try:
        from repositories.task_repository import process_task_for_mentor

        loop = asyncio.get_running_loop()
        task, mentor_tg_id, mentor_db_id = await loop.run_in_executor(
            None, process_task_for_mentor, lead_id
        )
    except Exception as e:
        logger.error("task_validated: failed to process: %s", e, exc_info=True)
        return

    try:
        from telegram import Bot
        from keyboards import get_check_task_keyboard
        from messages import MENTOR_NEW_TASK_NOTIFICATION
        from database.task_service import (
            get_mentor_task_notification,
            upsert_mentor_task_notification,
        )

        old_notification = await loop.run_in_executor(
            None, get_mentor_task_notification, mentor_db_id
        )

        async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
            if old_notification:
                try:
                    await bot.delete_message(
                        chat_id=old_notification.chat_id,
                        message_id=old_notification.message_id,
                    )
                except Exception:
                    pass

            sent = await bot.send_message(
                chat_id=mentor_tg_id,
                text=MENTOR_NEW_TASK_NOTIFICATION,
                reply_markup=get_check_task_keyboard(task.id),
            )

        await loop.run_in_executor(
            None, upsert_mentor_task_notification, mentor_db_id, sent.message_id, mentor_tg_id
        )
        logger.info(
            "task_validated: sent notification to mentor tg_id=%s for task_id=%s",
            mentor_tg_id,
            task.id,
        )
    except Exception as e:
        logger.error(
            "task_validated: failed to send Telegram message: %s", e, exc_info=True
        )


@app.post("/task/validated")
async def task_validated(request: Request):
    form = await request.form()

    pipeline_id = form.get("leads[status][0][pipeline_id]", "")
    status_id = form.get("leads[status][0][status_id]", "")
    lead_id = form.get("leads[status][0][id]", "")

    if pipeline_id != str(CRM_SELECTION_PIPELINE) or status_id != CRM_TASK_VALIDATED_STATUS:
        return JSONResponse({"status": "ignored"})

    if not lead_id:
        raise HTTPException(status_code=400, detail="Missing lead id")

    dedup_key = f"task_validated:{lead_id}"
    if _is_duplicate(dedup_key):
        logger.info("task_validated: duplicate webhook for lead_id=%s — skipping", lead_id)
        return JSONResponse({"status": "ok"})

    logger.info("task_validated: scheduling background processing for lead_id=%s", lead_id)
    _create_background_task(_process_task_validated(lead_id))
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    # For local runs: uvicorn webhooks:app --reload --host 0.0.0.0 --port 8000
    import uvicorn

    uvicorn.run("webhooks:app", host="0.0.0.0", port=8000, reload=False)
