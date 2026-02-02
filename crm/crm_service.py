import requests
from amocrm.v2 import Pipeline, tokens
from amocrm.v2.entity.note import COMMON_TYPE
from .crm_models import Contact, Lead
import config
from config import (
    CRM_TASK_STATUS,
    CRM_VISIT_CARD_STATUS,
    CRM_TEST_STATUS,
    CRM_TEST_IS_IN_PROGRESS_STATUS,
    CRM_PIPELINE,
)
from logger import setup_logger
from rate_limiter import amo_crm_rate_limiter
from async_rate_limiter import async_amo_crm_rate_limiter
from thread_safe_token_manager import ThreadSafeTokenManager
import aiohttp

logger = setup_logger(__name__)


def init_amo_crm_integration():
    """Initialize AmoCRM token manager and handle token setup."""
    tokens.default_token_manager(
        client_id=config.CRM_CLIENT_ID,
        client_secret=config.CRM_CLIENT_SECRET,
        subdomain=config.CRM_SUBDOMAIN,
        redirect_url=config.CRM_REDIRECT_URL,
        storage=tokens.FileTokensStorage(directory_path="tokens"),
    )

    ThreadSafeTokenManager(tokens.default_token_manager)

    try:
        with amo_crm_rate_limiter.limit():
            tokens.default_token_manager.get_access_token()
        logger.info("AmoCRM token is valid")
    except Exception as e:
        logger.warning(f"Failed to get access token: {e}. Initializing new token...")
        init_amo_crm_token()


def init_amo_crm_token():
    try:
        with amo_crm_rate_limiter.limit():
            tokens.default_token_manager.init(
                code=config.CRM_AUTH_CODE,
                skip_error=False,
            )
    except Exception as e:
        logger.error(f"Failed to initialize AmoCRM token: {e}")
        raise e


# Валидные статусы лида для начала работы со студентом
VALID_LEAD_STATUSES = {
    CRM_TEST_STATUS,
    CRM_TEST_IS_IN_PROGRESS_STATUS,
    CRM_TASK_STATUS,
    CRM_VISIT_CARD_STATUS,
}


def get_first_lead(crm_user: Contact) -> Lead | None:
    """
    Get the first lead with correct pipeline and status from CRM user's leads.

    Args:
        crm_user: CRM Contact instance

    Returns:
        First Lead with correct pipeline/status, or None if not found
    """
    if not crm_user.leads:
        return None
    return next(
        (
            lead
            for lead in crm_user.leads
            if lead.pipeline
            and str(lead.pipeline.id) == str(CRM_PIPELINE)
            and lead.status
            and str(lead.status.id) in VALID_LEAD_STATUSES
        ),
        None,
    )


def is_test_lead(lead: Lead) -> bool:
    """Check if lead has test status or test in progress status."""
    return lead.status and str(lead.status.id) in {
        CRM_TEST_STATUS,
        CRM_TEST_IS_IN_PROGRESS_STATUS,
    }


def is_visit_card_lead(lead: Lead) -> bool:
    """Check if lead has visit card status."""
    return lead.status and str(lead.status.id) == CRM_VISIT_CARD_STATUS


def is_task_lead(lead: Lead) -> bool:
    """Check if lead has task status."""
    return lead.status and str(lead.status.id) == CRM_TASK_STATUS


def get_crm_user_by_tg_id(tg_id: int | str | None) -> Contact | None:
    if tg_id is None:
        return None

    with amo_crm_rate_limiter.limit():
        contacts = Contact.objects.filter(query=tg_id)

    tg_id_str = str(tg_id).strip()

    for contact in contacts:
        contact_tg_id = contact.telegram_id
        if contact_tg_id and str(contact_tg_id).strip() == tg_id_str:
            if get_first_lead(contact):
                return contact

    return None


def get_crm_user_by_id(id: int) -> Contact | None:
    with amo_crm_rate_limiter.limit():
        contacts = Contact.objects.filter(query=id)

    for contact in contacts:
        if str(contact.id) == str(id):
            if get_first_lead(contact):
                return contact

    return None


def get_crm_lead(id: int) -> Lead | None:
    with amo_crm_rate_limiter.limit():
        leads = Lead.objects.filter(query=id)
    for lead in leads:
        if str(lead.id) == str(id):
            return lead
    return None


def update_lead_status_by_lead(lead: Lead, status_id: int | str) -> Lead:
    """Update lead status directly using a Lead object."""
    pipeline_id = str(config.CRM_PIPELINE)

    with amo_crm_rate_limiter.limit():
        pipelines = Pipeline.objects.filter(query=pipeline_id)
    pipeline = next((p for p in pipelines if str(p.id) == pipeline_id), None)

    if not pipeline:
        raise ValueError(f"Pipeline with id={pipeline_id} not found")

    status = next((s for s in pipeline.statuses if str(s.id) == str(status_id)), None)
    if status is None:
        status = next((s for s in pipeline.statuses if s.name == status_id), None)
    if status is None:
        raise ValueError(f"Status '{status_id}' not found in pipeline")

    with amo_crm_rate_limiter.limit():
        lead.status = status
        lead.save()
    return lead


def send_note(lead_id: int, note: str):
    lead = get_crm_lead(lead_id)
    if lead:
        with amo_crm_rate_limiter.limit():
            lead.notes.objects.create(text=note, note_type=COMMON_TYPE)
            lead.save()


async def get_access_token() -> str:
    try:
        token_manager = ThreadSafeTokenManager.get_instance()
        return await token_manager.get_access_token()
    except (EnvironmentError, ValueError) as token_error:
        logger.error(f"Token refresh failed: {token_error}")
        logger.info("Re-initializing token manager with auth code...")
        init_amo_crm_token()
        token_manager = ThreadSafeTokenManager.get_instance()
        return await token_manager.get_access_token()


async def upload_video(
    file_bytes: bytes, filename: str
) -> tuple[str, int] | tuple[None, None]:
    """
    Upload a video file to AMoCRM Drive and return the download URL.

    Args:
        file_bytes: File content as bytes
        filename: Name for the uploaded file

    Returns:
        Tuple of (download_url, file_size) if successful, (None, None) otherwise
    """

    try:
        logger.info(f"[upload_video] === STARTING VIDEO UPLOAD ===")
        logger.info(
            f"[upload_video] Filename: {filename}, Size: {len(file_bytes)} bytes ({len(file_bytes) / 1024 / 1024:.2f} MB)"
        )

        access_token = await get_access_token()
        if not access_token:
            logger.error(f"[upload_video] Failed to get access token!")
            return None, None

        logger.debug(f"[upload_video] Access token obtained: {access_token[:20]}...")

        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        # Step 0: Get drive_url from account
        account_url = (
            f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/account?with=drive_url"
        )

        logger.info(f"[upload_video] === STEP 0: GET DRIVE URL ===")
        logger.info(f"[upload_video] URL: {account_url}")
        logger.info(
            f"[upload_video] Headers: Authorization=Bearer {access_token[:20]}..."
        )

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.get(
                    account_url, headers=headers
                ) as account_response:
                    text = await account_response.text()
                    logger.info(f"[upload_video] === STEP 0 RESPONSE ===")
                    logger.info(f"[upload_video] Status: {account_response.status}")
                    logger.info(
                        f"[upload_video] Response headers: {dict(account_response.headers)}"
                    )
                    logger.info(f"[upload_video] Response body: {text}")

                    if account_response.status != 200:
                        logger.error(
                            f"[upload_video] Failed to get drive_url: {account_response.status}"
                        )
                        return None, None

                    account_data = (
                        await account_response.json()
                        if account_response.content_type == "application/json"
                        else {}
                    )
                    drive_url = account_data.get(
                        "drive_url", "https://drive-b.amocrm.ru"
                    )
                    logger.info(f"[upload_video] Got drive_url: {drive_url}")

        # Step 1: Create upload session
        file_size = len(file_bytes)
        session_url = f"{drive_url}/v1.0/sessions"
        session_data = {
            "file_name": filename,
            "file_size": file_size,
            "content_type": "video/mp4",
        }

        logger.info(f"[upload_video] === STEP 1: CREATE UPLOAD SESSION ===")

        access_token = await get_access_token()
        if not access_token:
            logger.error(
                f"[upload_video] Failed to get access token for upload session!"
            )
            return None, None

        logger.info(f"[upload_video] Access token obtained (length: {len(access_token)})")
        logger.info(f"[upload_video] Access token: {access_token}")

        session_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        logger.info(f"[upload_video] === STEP 1 REQUEST ===")
        logger.info(f"[upload_video] Method: POST")
        logger.info(f"[upload_video] URL: {session_url}")
        logger.info(f"[upload_video] Headers: {session_headers}")
        logger.info(f"[upload_video] Body (JSON): {session_data}")

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(
                    session_url,
                    headers=session_headers,
                    json=session_data,
                ) as session_response:
                    text = await session_response.text()
                    logger.info(f"[upload_video] === STEP 1 RESPONSE ===")
                    logger.info(f"[upload_video] Status Code: {session_response.status}")
                    logger.info(f"[upload_video] Response URL: {session_response.url}")
                    logger.info(f"[upload_video] Response Headers: {dict(session_response.headers)}")
                    logger.info(f"[upload_video] Response Body: {text}")

                    if session_response.status not in (200, 201):
                        logger.error(
                            f"[upload_video] Failed to create upload session: {session_response.status} - {text}"
                        )
                        return None, None

                    session_info = (
                        await session_response.json()
                        if session_response.content_type == "application/json"
                        else {}
                    )
                    upload_url = session_info.get("upload_url")
                    max_part_size = session_info.get("max_part_size", 524288)
                    logger.info(
                        f"[upload_video] Upload session created: session_id={session_info.get('session_id')}, max_part_size={max_part_size}"
                    )

        if not upload_url:
            logger.error(
                f"[upload_video] No upload_url in session response: {session_info}"
            )
            return None, None

        # Step 2: Upload file in parts
        logger.info(f"[upload_video] === STEP 2: UPLOAD FILE IN PARTS ===")
        logger.info(f"[upload_video] Upload URL: {upload_url}")
        logger.info(
            f"[upload_video] File size: {len(file_bytes)} bytes, Max part size: {max_part_size} bytes"
        )

        file_uuid = None
        version_uuid = None
        total_size = len(file_bytes)
        part_size = min(max_part_size, total_size)
        offset = 0
        part_num = 0

        while offset < total_size:
            part_num += 1
            chunk = file_bytes[offset : offset + part_size]
            chunk_len = len(chunk)

            logger.info(f"[upload_video] === UPLOADING PART {part_num} ===")
            logger.info(
                f"[upload_video] Part range: bytes {offset}-{offset + chunk_len - 1}/{total_size}"
            )

            access_token = await get_access_token()
            if not access_token:
                logger.error(
                    f"[upload_video] Failed to get access token for part upload!"
                )
                return None, None

            part_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/octet-stream",
                "Content-Range": f"bytes {offset}-{offset + chunk_len - 1}/{total_size}",
            }

            logger.info(
                f"[upload_video] Headers: Authorization=Bearer {access_token[:20]}..., Content-Type=application/octet-stream, Content-Range=bytes {offset}-{offset + chunk_len - 1}/{total_size}"
            )

            async with aiohttp.ClientSession() as session:
                async with async_amo_crm_rate_limiter.limit():
                    async with session.post(
                        upload_url,
                        headers=part_headers,
                        data=chunk,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as upload_response:
                        text = await upload_response.text()
                        logger.info(f"[upload_video] === PART {part_num} RESPONSE ===")
                        logger.info(f"[upload_video] Status: {upload_response.status}")
                        logger.info(
                            f"[upload_video] Response headers: {dict(upload_response.headers)}"
                        )
                        logger.info(f"[upload_video] Response body: {text}")

                        if upload_response.status not in (200, 201, 202):
                            logger.error(
                                f"[upload_video] Failed to upload file part {part_num}: {upload_response.status} - {text}"
                            )
                            return None, None

                        upload_data = (
                            await upload_response.json()
                            if upload_response.content_type == "application/json"
                            else {}
                        )
                        logger.debug(
                            f"[upload_video] Part {part_num} upload data: {upload_data}"
                        )

            # Check if this is the last part (contains uuid)
            if "uuid" in upload_data:
                # Get download URL from API response
                download_url = (
                    upload_data.get("_links", {}).get("download", {}).get("href")
                )
                file_uuid = upload_data.get("uuid")

                logger.info(f"[upload_video] === UPLOAD COMPLETED ===")
                logger.info(f"[upload_video] File UUID: {file_uuid}")
                logger.info(f"[upload_video] Download URL: {download_url}")

                if not download_url:
                    logger.error("[upload_video] No download URL in upload response")
                    return None, None

                logger.info(
                    f"[upload_video] ✓ Successfully uploaded video to Drive: uuid={file_uuid}, size={file_size} bytes ({file_size / 1024 / 1024:.2f} MB)"
                )
                return download_url, file_size

            # Get next upload URL for next part
            next_url = upload_data.get("next_url")
            if next_url:
                logger.debug(
                    f"[upload_video] Moving to next part, next_url: {next_url}"
                )
                upload_url = next_url
            else:
                logger.debug(
                    f"[upload_video] No next_url in response for part {part_num}"
                )

            offset += chunk_len

        logger.error(
            "[upload_video] ✗ No file UUID or download URL returned after upload"
        )
        return None, None

    except Exception as e:
        logger.error(f"[upload_video] ✗ Exception occurred: {e}", exc_info=True)
        return None, None
