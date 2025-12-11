import requests
from amocrm.v2 import Pipeline, tokens
from amocrm.v2.entity.note import COMMON_TYPE
from .crm_models import Contact, Lead
import config
from config import CRM_TASK_STATUS, CRM_VISIT_CARD_STATUS, CRM_PIPELINE
from logger import setup_logger
from rate_limiter import amo_crm_rate_limiter

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


def update_lead_status(id: int, status_id: int | str) -> Lead | None:
    pipeline_id = str(config.CRM_PIPELINE)

    with amo_crm_rate_limiter.limit():
        pipelines = Pipeline.objects.filter(query=pipeline_id)
    pipeline = None
    for p in pipelines:
        if str(p.id) == pipeline_id:
            pipeline = p
            break

    if not pipeline:
        raise ValueError(f"Pipeline with id={pipeline_id} not found")

    status = next((s for s in pipeline.statuses if str(s.id) == str(status_id)), None)
    if status is None:
        status = next((s for s in pipeline.statuses if s.name == status_id), None)
    if status is None:
        raise ValueError(f"Status '{status_id}' not found in pipeline")

    lead = get_crm_lead(id)
    if lead:
        with amo_crm_rate_limiter.limit():
            lead.status = status
            lead.save()
        return lead
    return None


def send_note(lead_id: int, note: str):
    lead = get_crm_lead(lead_id)
    if lead:
        with amo_crm_rate_limiter.limit():
            lead.notes.objects.create(text=note, note_type=COMMON_TYPE)
            lead.save()


def upload_file_to_lead(lead_id: int, file_bytes: bytes, filename: str) -> bool:
    """
    Upload a file as an attachment to a lead via AmoCRM API.

    Args:
        lead_id: CRM lead ID
        file_bytes: File content as bytes
        filename: Name for the uploaded file

    Returns:
        True if upload successful, False otherwise
    """
    try:
        with amo_crm_rate_limiter.limit():
            access_token = tokens.default_token_manager.get_access_token()

        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        # Step 1: Create upload session (must use drive host, not subdomain)
        session_url = "https://drive-b.amocrm.ru/v1.0/sessions"
        session_data = {
            "file_name": filename,
            "file_size": len(file_bytes),
            "content_type": "video/mp4",
        }

        with amo_crm_rate_limiter.limit():
            session_response = requests.post(
                session_url,
                headers={**headers, "Content-Type": "application/json"},
                json=session_data,
            )

        if session_response.status_code not in (200, 201):
            logger.error(
                f"Failed to create upload session: {session_response.status_code} - {session_response.text}"
            )
            return False

        session_info = session_response.json()
        upload_url = session_info.get("upload_url")
        max_part_size = session_info.get("max_part_size", 524288)

        if not upload_url:
            logger.error(f"No upload_url in session response: {session_info}")
            return False

        # Step 2: Upload file in parts (raw bytes, not multipart, to avoid size drift)
        file_uuid = None
        total_size = len(file_bytes)
        part_size = min(max_part_size, total_size)
        offset = 0

        while offset < total_size:
            chunk = file_bytes[offset : offset + part_size]
            chunk_len = len(chunk)

            part_headers = {
                **headers,
                "Content-Type": "application/octet-stream",
                "Content-Range": f"bytes {offset}-{offset + chunk_len - 1}/{total_size}",
            }

            with amo_crm_rate_limiter.limit():
                upload_response = requests.post(
                    upload_url,
                    headers=part_headers,
                    data=chunk,
                    timeout=30,
                )

            if upload_response.status_code not in (200, 201):
                logger.error(
                    f"Failed to upload file part: {upload_response.status_code} - {upload_response.text}"
                )
                return False

            upload_data = upload_response.json()

            # Check if this is the last part (contains uuid)
            if "uuid" in upload_data:
                file_uuid = upload_data.get("uuid")
                break

            # Get next upload URL for next part
            next_url = upload_data.get("next_url")
            if next_url:
                upload_url = next_url

            offset += chunk_len

        if not file_uuid:
            logger.error(f"No file UUID returned after upload")
            return False

        # Step 3: Link file to lead
        link_url = (
            f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/leads/{lead_id}/files"
        )
        link_data = [{"file_uuid": file_uuid}]

        with amo_crm_rate_limiter.limit():
            link_response = requests.put(
                link_url,
                headers={**headers, "Content-Type": "application/json"},
                json=link_data,
            )

        if link_response.status_code not in (200, 201, 202, 204):
            logger.error(
                f"Failed to link file to lead {lead_id}: {link_response.status_code} - {link_response.text}"
            )
            return False

        logger.info(f"Successfully uploaded file '{filename}' to lead {lead_id}")
        return True

    except Exception as e:
        logger.error(f"Error uploading file to lead {lead_id}: {e}")
        return False
