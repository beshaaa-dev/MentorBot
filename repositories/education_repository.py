"""
Education pipeline (AmoCRM): kicked/banned member handling.
"""

from amocrm.v2 import Pipeline
from amocrm.v2.entity.note import COMMON_TYPE

from config import CRM_EDUCATION_PIPELINE
from crm.crm_models import Contact, Lead
from crm.crm_service import update_lead_status_in_pipeline
from logger import setup_logger
from rate_limiter import amo_crm_rate_limiter

logger = setup_logger(__name__)

KICKED_MEMBER_STATUS_ID = 84497014
KICKED_MEMBER_EXCLUDED_LEAD_STATUSES = {"142", "143"}
TAG_KICK_CONTACT_ERROR = "ошибка_контакта"
TAG_KICK_LEAD_ERROR = "ошибка_сделки"
NOTE_KICK_CONTACT_CREATED = "Не нашел контакт и создал"
NOTE_KICK_LEAD_CREATED = "Не нашел сделку и создал"


def handle_kicked_member(tg_id: int, username: str | None = None) -> None:
    """
    При кике участника в чате: найти контакт по Telegram id, взять первую сделку в воронке
    со статусом, отличным от 142 и 143; при отсутствии контакта или сделки — создать,
    проставить теги/заметки об ошибке, затем перевести сделку в статус 84497014.
    """
    try:
        contact = _find_contact_by_telegram_id(tg_id)
        if contact is None:
            contact = _create_contact(tg_id, username)

        lead = find_lead(contact)
        if lead is None:
            _create_lead(contact, with_error_metadata=True)
            logger.info(
                "Kicked member tg_id=%s: created Education lead, status=%s",
                tg_id,
                KICKED_MEMBER_STATUS_ID,
            )
            return

        update_lead_status_in_pipeline(
            lead, CRM_EDUCATION_PIPELINE, KICKED_MEMBER_STATUS_ID
        )
        logger.info(
            "Kicked member tg_id=%s: updated lead %s to status %s",
            tg_id,
            getattr(lead, "id", "?"),
            KICKED_MEMBER_STATUS_ID,
        )
    except Exception as e:
        logger.error(
            "handle_kicked_member failed for tg_id=%s: %s",
            tg_id,
            e,
            exc_info=True,
        )


def _contact_display_name_for_kick(username: str | None, tg_id: int) -> str:
    if username:
        return username if username.startswith("@") else f"@{username}"
    return str(tg_id)


def _append_entity_tag(entity: Contact | Lead, tag: str) -> None:
    for t in entity.tags:
        if getattr(t, "name", None) == tag:
            return
    entity.tags.append(tag)


def _find_contact_by_telegram_id(tg_id: int | str) -> Contact | None:
    with amo_crm_rate_limiter.limit():
        contacts = Contact.objects.filter(query=tg_id)

    tg_id_str = str(tg_id).strip()
    for c in contacts:
        tid = c.telegram_id
        if tid is not None and str(tid).strip() == tg_id_str:
            return c
    return None


def find_lead(contact: Contact) -> Lead | None:
    # Amo returns _ListData(data=None) when there are no leads; it is truthy but __iter__ crashes.
    lead_refs = (contact._data.get("_embedded") or {}).get("leads")
    if not lead_refs:
        return None
    pid = str(CRM_EDUCATION_PIPELINE)
    for lead in contact.leads:
        if not lead.pipeline or str(lead.pipeline.id) != pid:
            continue
        sid = str(lead.status.id) if lead.status else None
        if sid not in KICKED_MEMBER_EXCLUDED_LEAD_STATUSES:
            return lead
    return None


def _create_contact(tg_id: int, username: str | None) -> Contact:
    name = _contact_display_name_for_kick(username, tg_id)
    with amo_crm_rate_limiter.limit():
        contact = Contact(name=name, telegram_id=str(tg_id))
        contact.save()

    _append_entity_tag(contact, TAG_KICK_CONTACT_ERROR)
    with amo_crm_rate_limiter.limit():
        contact.save()

    with amo_crm_rate_limiter.limit():
        contact.notes.objects.create(
            text=NOTE_KICK_CONTACT_CREATED, note_type=COMMON_TYPE
        )
        contact.save()
    return contact


def _create_lead(contact: Contact, *, with_error_metadata: bool) -> Lead:
    pipeline_id = CRM_EDUCATION_PIPELINE
    pid = str(pipeline_id)
    with amo_crm_rate_limiter.limit():
        pipeline = Pipeline.objects.get(object_id=pipeline_id)

    status = next(
        (s for s in pipeline.statuses if str(s.id) == str(KICKED_MEMBER_STATUS_ID)),
        None,
    )
    if status is None:
        raise ValueError(
            f"Status '{KICKED_MEMBER_STATUS_ID}' not found in pipeline {pid}"
        )

    with amo_crm_rate_limiter.limit():
        lead = Lead(pipeline=pipeline, status=status)
        lead.save()
    # contacts= in __init__ is not supported (_EmbeddedLinkListField.on_set raises TypeError)
    with amo_crm_rate_limiter.limit():
        lead.contacts.append(contact, main=True)

    if with_error_metadata:
        _append_entity_tag(lead, TAG_KICK_LEAD_ERROR)
        with amo_crm_rate_limiter.limit():
            lead.save()
        with amo_crm_rate_limiter.limit():
            lead.notes.objects.create(
                text=NOTE_KICK_LEAD_CREATED, note_type=COMMON_TYPE
            )
            lead.save()
    return lead
