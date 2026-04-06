import requests
from amocrm.v2 import Pipeline, tokens
from amocrm.v2.entity.note import COMMON_TYPE
from amocrm.v2.interaction import _session as _amo_session
from .crm_models import Contact, Lead
import config
from config import (
    CRM_TASK_STATUS,
    CRM_VISIT_CARD_STATUS,
    CRM_TEST_STATUS,
    CRM_TEST_IS_IN_PROGRESS_STATUS,
    CRM_PIPELINE,
    CRM_HOMEWORK_PIPELINE,
)
from logger import setup_logger
from rate_limiter import amo_crm_rate_limiter
from async_rate_limiter import async_amo_crm_rate_limiter
from thread_safe_token_manager import ThreadSafeTokenManager
import aiohttp

logger = setup_logger(__name__)


def _amo_response_hook(response, *args, **kwargs):
    logger.debug(
        "AMoCRM %s %s → %d\nResponse: %s",
        response.request.method,
        response.request.url,
        response.status_code,
        response.text[:3000],
    )


def init_amo_crm_integration():
    """Initialize AmoCRM token manager and handle token setup."""
    _amo_session.hooks["response"].append(_amo_response_hook)
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


def update_lead_status_in_pipeline(
    lead: Lead, pipeline_id: int | str, status_id: int | str
) -> Lead:
    """Resolve status within a pipeline and assign it to the lead."""
    pid = str(pipeline_id)

    with amo_crm_rate_limiter.limit():
        pipeline = Pipeline.objects.get(object_id=pipeline_id)

    status = next((s for s in pipeline.statuses if str(s.id) == str(status_id)), None)
    if status is None:
        status = next((s for s in pipeline.statuses if s.name == status_id), None)
    if status is None:
        raise ValueError(f"Status '{status_id}' not found in pipeline")

    with amo_crm_rate_limiter.limit():
        lead.status = status
        lead.save()
    return lead


def update_lead_status_by_lead(lead: Lead, status_id: int | str) -> Lead:
    """Update lead status directly using a Lead object (main CRM pipeline)."""
    return update_lead_status_in_pipeline(lead, config.CRM_PIPELINE, status_id)


def send_note(lead_id: int, note: str):
    lead = get_crm_lead(lead_id)
    if lead:
        with amo_crm_rate_limiter.limit():
            lead.notes.objects.create(text=note, note_type=COMMON_TYPE)
            lead.save()


def get_crm_contact_by_id(crm_id: int | str) -> Contact | None:
    """Fetch a Contact by CRM id without requiring a valid lead in the main pipeline."""
    with amo_crm_rate_limiter.limit():
        contacts = Contact.objects.filter(query=crm_id)
    for c in contacts:
        if str(c.id) == str(crm_id):
            return c
    return None


def get_homework_lead(contact: Contact, status_id: str) -> Lead | None:
    """Return the lead in pipeline 10726418 with the given status, or None."""
    contact_refs = (contact._data.get("_embedded") or {}).get("leads")
    if not contact_refs:
        return None
    for lead in contact.leads:
        if not lead.pipeline or str(lead.pipeline.id) != str(CRM_HOMEWORK_PIPELINE):
            continue
        if lead.status and str(lead.status.id) == status_id:
            return lead
    return None


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


async def force_refresh_access_token() -> str:
    """Принудительно обновляет access token, даже если текущий токен ещё не истёк."""
    try:
        token_manager = ThreadSafeTokenManager.get_instance()
        return await token_manager.force_refresh_access_token()
    except (EnvironmentError, ValueError) as token_error:
        logger.error(f"Force token refresh failed: {token_error}")
        return await get_access_token()


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
        access_token = await get_access_token()
        if not access_token:
            logger.error(f"[upload_video] Failed to get access token!")
            return None, None

        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        # Step 0: Get drive_url from account
        account_url = (
            f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/account?with=drive_url"
        )

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.get(
                    account_url, headers=headers
                ) as account_response:
                    text = await account_response.text()

                    if account_response.status != 200:
                        logger.error(
                            f"[upload_video] Failed to get drive_url: {account_response.status}"
                        )
                        return None, None

                    account_data = (
                        await account_response.json()
                        if account_response.content_type
                        and "json" in account_response.content_type
                        else {}
                    )
                    drive_url = account_data.get(
                        "drive_url", "https://drive-b.amocrm.ru"
                    )

        # Step 1: Create upload session
        file_size = len(file_bytes)
        session_url = f"{drive_url}/v1.0/sessions"
        session_data = {
            "file_name": filename,
            "file_size": file_size,
            "content_type": "video/mp4",
        }

        # TODO: - Убрать костыль, когда AMOCRM исправить баг
        access_token = await force_refresh_access_token()
        if not access_token:
            logger.error(
                f"[upload_video] Failed to get access token for upload session!"
            )
            return None, None

        session_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(
                    session_url,
                    headers=session_headers,
                    json=session_data,
                ) as session_response:
                    text = await session_response.text()

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

        if not upload_url:
            logger.error(
                f"[upload_video] No upload_url in session response: {session_info}"
            )
            return None, None

        # Step 2: Upload file in parts
        total_size = len(file_bytes)
        part_size = min(max_part_size, total_size)
        offset = 0
        part_num = 0

        while offset < total_size:
            part_num += 1
            chunk = file_bytes[offset : offset + part_size]
            chunk_len = len(chunk)

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

            async with aiohttp.ClientSession() as session:
                async with async_amo_crm_rate_limiter.limit():
                    async with session.post(
                        upload_url,
                        headers=part_headers,
                        data=chunk,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as upload_response:
                        text = await upload_response.text()

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

            # Check if this is the last part (contains uuid)
            if "uuid" in upload_data:
                # Get download URL from API response
                download_url = (
                    upload_data.get("_links", {}).get("download", {}).get("href")
                )

                if not download_url:
                    logger.error("[upload_video] No download URL in upload response")
                    return None, None

                return download_url, file_size

            # Get next upload URL for next part
            next_url = upload_data.get("next_url")
            if next_url:
                upload_url = next_url

            offset += chunk_len

        logger.error(
            "[upload_video] ✗ No file UUID or download URL returned after upload"
        )
        return None, None

    except Exception as e:
        logger.error(f"[upload_video] ✗ Exception occurred: {e}", exc_info=True)
        return None, None


async def upload_file(
    file_bytes: bytes, filename: str, content_type: str = "application/octet-stream"
) -> tuple[str, str, int] | tuple[None, None, None]:
    """
    Upload any file to AMoCRM Drive and return the file UUID and version UUID.

    Args:
        file_bytes: File content as bytes
        filename: Name for the uploaded file
        content_type: MIME type of the file (e.g. "audio/ogg", "image/jpeg")

    Returns:
        Tuple of (file_uuid, version_uuid, file_size) if successful, (None, None, None) otherwise
    """
    try:
        access_token = await get_access_token()
        if not access_token:
            logger.error("[upload_file] Failed to get access token!")
            return None, None, None

        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        # Step 0: Get drive_url from account
        account_url = (
            f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/account?with=drive_url"
        )

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.get(
                    account_url, headers=headers
                ) as account_response:
                    if account_response.status != 200:
                        logger.error(
                            f"[upload_file] Failed to get drive_url: {account_response.status}"
                        )
                        return None, None, None

                    account_data = (
                        await account_response.json()
                        if account_response.content_type
                        and "json" in account_response.content_type
                        else {}
                    )
                    drive_url = account_data.get(
                        "drive_url", "https://drive-b.amocrm.ru"
                    )

        # Step 1: Create upload session
        file_size = len(file_bytes)
        session_url = f"{drive_url}/v1.0/sessions"
        session_data = {
            "file_name": filename,
            "file_size": file_size,
            "content_type": content_type,
        }

        # TODO: - Убрать костыль, когда AMOCRM исправить баг
        access_token = await force_refresh_access_token()
        if not access_token:
            logger.error(
                "[upload_file] Failed to get access token for upload session!"
            )
            return None, None, None

        session_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(
                    session_url,
                    headers=session_headers,
                    json=session_data,
                ) as session_response:
                    text = await session_response.text()

                    if session_response.status not in (200, 201):
                        logger.error(
                            f"[upload_file] Failed to create upload session: {session_response.status} - {text}"
                        )
                        return None, None, None

                    session_info = (
                        await session_response.json()
                        if session_response.content_type == "application/json"
                        else {}
                    )
                    upload_url = session_info.get("upload_url")
                    max_part_size = session_info.get("max_part_size", 524288)

        if not upload_url:
            logger.error(
                f"[upload_file] No upload_url in session response: {session_info}"
            )
            return None, None, None

        # Step 2: Upload file in parts
        total_size = len(file_bytes)
        part_size = min(max_part_size, total_size)
        offset = 0
        part_num = 0

        while offset < total_size:
            part_num += 1
            chunk = file_bytes[offset : offset + part_size]
            chunk_len = len(chunk)

            access_token = await get_access_token()
            if not access_token:
                logger.error(
                    "[upload_file] Failed to get access token for part upload!"
                )
                return None, None

            part_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/octet-stream",
                "Content-Range": f"bytes {offset}-{offset + chunk_len - 1}/{total_size}",
            }

            async with aiohttp.ClientSession() as session:
                async with async_amo_crm_rate_limiter.limit():
                    async with session.post(
                        upload_url,
                        headers=part_headers,
                        data=chunk,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as upload_response:
                        text = await upload_response.text()

                        if upload_response.status not in (200, 201, 202):
                            logger.error(
                                f"[upload_file] Failed to upload file part {part_num}: {upload_response.status} - {text}"
                            )
                            return None, None, None

                        upload_data = (
                            await upload_response.json()
                            if upload_response.content_type == "application/json"
                            else {}
                        )

            if "uuid" in upload_data:
                file_uuid = upload_data.get("uuid")
                version_uuid = upload_data.get("version_uuid")
                if not file_uuid or not version_uuid:
                    logger.error("[upload_file] Missing uuid or version_uuid in upload response")
                    return None, None, None
                return file_uuid, version_uuid, file_size

            next_url = upload_data.get("next_url")
            if next_url:
                upload_url = next_url

            offset += chunk_len

        logger.error(
            "[upload_file] ✗ No file UUID returned after upload"
        )
        return None, None, None

    except Exception as e:
        logger.error(f"[upload_file] ✗ Exception occurred: {e}", exc_info=True)
        return None, None, None


async def create_attachment_note(
    lead_id: int,
    file_uuid: str,
    version_uuid: str,
    filename: str,
    text: str | None = None,
) -> bool:
    """
    Create an attachment note on a lead using an already-uploaded Drive file.

    The note (with the file inline) appears in the lead's activity feed/timeline.

    Args:
        lead_id: CRM lead ID
        file_uuid: UUID returned by the Drive upload session
        version_uuid: Version UUID returned by the Drive upload session
        filename: Display name shown in the note
        text: Optional note text shown above the attachment

    Returns:
        True if successful, False otherwise
    """
    try:
        access_token = await get_access_token()
        if not access_token:
            logger.error("[create_attachment_note] Failed to get access token")
            return False

        url = f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/leads/{lead_id}/notes"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        display_name = filename
        if text:
            ext = ""
            dot_idx = filename.rfind(".")
            if dot_idx != -1:
                ext = filename[dot_idx:]
            display_name = f"{text}{ext}"

        body = [
            {
                "note_type": "attachment",
                "params": {
                    "file_uuid": file_uuid,
                    "version_uuid": version_uuid,
                    "file_name": display_name,
                },
            }
        ]

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        return True
                    resp_text = await response.text()
                    logger.error(
                        f"[create_attachment_note] Failed: HTTP {response.status} {resp_text}"
                    )
                    return False

    except Exception as e:
        logger.error(f"[create_attachment_note] Exception occurred: {e}", exc_info=True)
        return False
