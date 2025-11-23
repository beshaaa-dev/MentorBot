from amocrm.v2 import Pipeline, tokens
from amocrm.v2.entity.note import COMMON_TYPE
from .crm_models import Contact, Lead
import config
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


def get_crm_user_by_tg_id(tg_id: int | str | None) -> Contact | None:
    if tg_id is None:
        return None

    with amo_crm_rate_limiter.limit():
        contacts = Contact.objects.filter(query=tg_id)

    tg_id_str = str(tg_id).strip()

    for contact in contacts:
        contact_tg_id = contact.telegram_id
        if contact_tg_id and str(contact_tg_id).strip() == tg_id_str:
            for contact_lead in contact.leads:
                if contact_lead.status.id != 143 and contact_lead.status.id != 142:
                    return contact

    return None


def get_crm_user_by_id(id: int) -> Contact | None:
    with amo_crm_rate_limiter.limit():
        contacts = Contact.objects.filter(query=id)

    for contact in contacts:
        if str(contact.id) == str(id):
            for contact_lead in contact.leads:
                if contact_lead.status.id != 143 and contact_lead.status.id != 142:
                    return contact

    return None


def get_crm_lead(id: int) -> Lead | None:
    with amo_crm_rate_limiter.limit():
        leads = Lead.objects.filter(query=id)
    if leads:
        return next(iter(leads), None)
    return None


def update_lead_status(id: int, status_id: int | str) -> Lead | None:
    pipeline_id = str(config.CRM_PIPELINE_ID)

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
    with amo_crm_rate_limiter.limit():
        leads = Lead.objects.filter(query=lead_id)
    lead = next(iter(leads), None)
    if lead:
        with amo_crm_rate_limiter.limit():
            lead.notes.objects.create(text=note, note_type=COMMON_TYPE)
            lead.save()
