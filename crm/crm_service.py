import requests
from amocrm.v2 import Pipeline, tokens
from amocrm.v2.entity.note import COMMON_TYPE
from .crm_models import Contact, Lead
import config
from config import CRM_TASK_STATUS, CRM_VISIT_CARD_STATUS, CRM_PIPELINE
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
VALID_LEAD_STATUSES = {CRM_TASK_STATUS, CRM_VISIT_CARD_STATUS}


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


async def upload_video(file_bytes: bytes, filename: str) -> tuple[str, int] | tuple[None, None]:
    """
    Upload a video file to AMoCRM Drive and return the download URL.
    
    Args:
        file_bytes: File content as bytes
        filename: Name for the uploaded file
        
    Returns:
        Tuple of (download_url, file_size) if successful, (None, None) otherwise
    """
    
    logger.info(f"Starting video upload: filename={filename}, size={len(file_bytes)} bytes")
    
    try:
        logger.debug("Getting access token...")
        access_token = await get_access_token()
        logger.debug(f"Access token obtained: {access_token[:20]}...")

        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        # Step 0: Get drive_url from account
        account_url = (
            f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/account?with=drive_url"
        )
        logger.info(f"="*80)
        logger.info(f"STEP 0: GET DRIVE URL")
        logger.info(f"REQUEST URL: {account_url}")
        logger.info(f"REQUEST METHOD: GET")
        logger.info(f"REQUEST HEADERS: {headers}")
        
        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.get(account_url, headers=headers) as account_response:
                    logger.info(f"RESPONSE STATUS: {account_response.status}")
                    logger.info(f"RESPONSE HEADERS: {dict(account_response.headers)}")
                    
                    if account_response.status != 200:
                        text = await account_response.text()
                        logger.error(f"RESPONSE BODY: {text}")
                        logger.error(f"Failed to get account info: {account_response.status} - {text}")
                        return None, None
                    
                    account_data = await account_response.json()
                    logger.info(f"RESPONSE BODY: {account_data}")
                    drive_url = account_data.get("drive_url", "https://drive-b.amocrm.ru")
                    logger.info(f"Drive URL extracted: {drive_url}")
                    logger.info(f"="*80)

        # Step 1: Create upload session
        file_size = len(file_bytes)
        session_url = f"{drive_url}/v1.0/sessions"
        session_data = {
            "file_name": filename,
            "file_size": file_size,
            "content_type": "video/mp4"
        }
        access_token = await get_access_token()
        session_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        logger.info(f"="*80)
        logger.info(f"STEP 1: CREATE UPLOAD SESSION")
        logger.info(f"REQUEST URL: {session_url}")
        logger.info(f"REQUEST METHOD: POST")
        logger.info(f"REQUEST HEADERS: {session_headers}")
        logger.info(f"REQUEST BODY: {session_data}")

        async with aiohttp.ClientSession() as session:
            async with async_amo_crm_rate_limiter.limit():
                async with session.post(
                    session_url,
                    headers=session_headers,
                    json=session_data,
                ) as session_response:
                    logger.info(f"RESPONSE STATUS: {session_response.status}")
                    logger.info(f"RESPONSE HEADERS: {dict(session_response.headers)}")
                    
                    if session_response.status not in (200, 201):
                        text = await session_response.text()
                        logger.error(f"RESPONSE BODY: {text}")
                        logger.error(f"Failed to create upload session: {session_response.status}")
                        logger.info(f"="*80)
                        return None, None

                    session_info = await session_response.json()
                    logger.info(f"RESPONSE BODY: {session_info}")
                    upload_url = session_info.get("upload_url")
                    max_part_size = session_info.get("max_part_size", 524288)
                    logger.info(f"Session created - ID: {session_info.get('session_id')}, Upload URL: {upload_url}, Max part size: {max_part_size}")
                    logger.info(f"="*80)

        if not upload_url:
            logger.error(f"No upload_url in session response: {session_info}")
            return None, None

        # Step 2: Upload file in parts
        logger.info(f"="*80)
        logger.info(f"STEP 2: UPLOAD FILE IN PARTS")
        file_uuid = None
        version_uuid = None
        total_size = len(file_bytes)
        part_size = min(max_part_size, total_size)
        offset = 0
        logger.info(f"Upload parameters: total_size={total_size}, part_size={part_size}")
        logger.info(f"="*80)

        part_number = 0
        while offset < total_size:
            part_number += 1
            chunk = file_bytes[offset : offset + part_size]
            chunk_len = len(chunk)
            
            part_headers = {
                **headers,
                "Content-Type": "application/octet-stream",
                "Content-Range": f"bytes {offset}-{offset + chunk_len - 1}/{total_size}",
            }
            
            logger.info(f"="*80)
            logger.info(f"UPLOADING PART {part_number}")
            logger.info(f"REQUEST URL: {upload_url}")
            logger.info(f"REQUEST METHOD: POST")
            logger.info(f"REQUEST HEADERS: {part_headers}")
            logger.info(f"REQUEST BODY: <binary data {chunk_len} bytes>")
            logger.info(f"Byte range: {offset}-{offset + chunk_len - 1}/{total_size}")

            async with aiohttp.ClientSession() as session:
                async with async_amo_crm_rate_limiter.limit():
                    async with session.post(
                        upload_url,
                        headers=part_headers,
                        data=chunk,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as upload_response:
                        logger.info(f"RESPONSE STATUS: {upload_response.status}")
                        logger.info(f"RESPONSE HEADERS: {dict(upload_response.headers)}")
                        
                        if upload_response.status not in (200, 201, 202):
                            text = await upload_response.text()
                            logger.error(f"RESPONSE BODY: {text}")
                            logger.error(f"Failed to upload file part {part_number}")
                            logger.info(f"="*80)
                            return None, None

                        upload_data = await upload_response.json()
                        logger.info(f"RESPONSE BODY: {upload_data}")
                        logger.info(f"="*80)

            # Check if this is the last part (contains uuid)
            if "uuid" in upload_data:
                # Get download URL from API response
                download_url = upload_data.get("_links", {}).get("download", {}).get("href")
                file_uuid = upload_data.get("uuid")
                logger.info(f"="*80)
                logger.info(f"UPLOAD COMPLETE!")
                logger.info(f"File UUID: {file_uuid}")
                logger.info(f"Download URL: {download_url}")
                logger.info(f"File size: {file_size} bytes")
                logger.info(f"="*80)
                
                if not download_url:
                    logger.error(f"No download URL in upload response")
                    return None, None
                
                return download_url, file_size

            # Get next upload URL for next part
            next_url = upload_data.get("next_url")
            if next_url:
                logger.info(f"Next upload URL for part {part_number + 1}: {next_url}")
                upload_url = next_url
            else:
                logger.warning(f"No next_url in response for part {part_number}")

            offset += chunk_len

        logger.error(f"No file UUID or download URL returned after upload. Total parts uploaded: {part_number}")
        return None, None

    except Exception as e:
        logger.error(f"Error uploading video to Drive: {e}", exc_info=True)
        return None, None

