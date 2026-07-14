"""
Survey pipeline (AmoCRM): update lead status during survey flow.
"""

from datetime import date as date_type
from datetime import datetime
from datetime import timezone

from amocrm.v2 import Pipeline
from amocrm.v2.entity.note import COMMON_TYPE

from config import CRM_SURVEY_PIPELINE
from crm.crm_models import Contact, Lead
from crm.crm_service import save_entity, update_lead_status_in_pipeline
from logger import setup_logger
from rate_limiter import amo_crm_rate_limiter

logger = setup_logger(__name__)

EXCLUDED_LEAD_STATUSES = {"142", "143"}
SURVEY_LEAD_STATUS_ID = 84499058
SURVEY_LEAD_STATUS_STARTED_ID = 84499062
SURVEY_LEAD_STATUS_SUBMITTED_ID = 84499066
TAG_SURVEY_CONTACT_ERROR = "контакт_ошибка"
NOTE_SURVEY_CONTACT_CREATED = "Контакт не найден, создан новый"
TAG_SURVEY_LEAD_ERROR = "сделка_ошибка"
NOTE_SURVEY_LEAD_CREATED = "Сделка не найдена, создана новая"


def update_survey_lead_by_conducting(
    survey_date: datetime | date_type | str | int | float,
    chat_name: str,
    tg_id: int,
    tg_nickname: str | None,
    survey_id: int,
) -> None:
    """
    Update CRM lead after survey: status + survey fields + lead tag.
    """
    contact, lead = _get_contact_and_lead_for_survey(
        tg_id=tg_id,
        username=tg_nickname,
        survey_id=survey_id,
        missing_lead_with_error_metadata=False,
    )

    lead.survey_date = _normalize_survey_date(survey_date)
    lead.chat_name = chat_name
    _append_entity_tag(lead, chat_name)

    lead = update_lead_status_in_pipeline(
        lead, CRM_SURVEY_PIPELINE, SURVEY_LEAD_STATUS_ID
    )


def update_survey_lead_status_on_start(
    tg_id: int, tg_nickname: str | None, survey_id: int
) -> None:
    """
    Update existing (or create-and-link) lead status when the user starts
    the survey. Does not modify survey custom fields.
    """
    contact, lead = _get_contact_and_lead_for_survey(
        tg_id=tg_id,
        username=tg_nickname,
        survey_id=survey_id,
        missing_lead_with_error_metadata=True,
    )
    lead = update_lead_status_in_pipeline(
        lead, CRM_SURVEY_PIPELINE, SURVEY_LEAD_STATUS_STARTED_ID
    )


def update_survey_lead_on_submit(
    tg_id: int,
    tg_nickname: str | None,
    survey_id: int,
    q1_text: str | None,
    q2_text: str | None,
    q3_text: str | None,
    q4_text: str | None,
    q1_addition_text: str | None,
    q2_addition_text: str | None,
    q3_addition_text: str | None,
) -> None:
    """
    Update CRM lead after survey submission:
    - status=84499066
    - write answers into lead custom fields survey_q1..survey_q4
    - write additions into lead custom fields survey_q1_addition..survey_q3_addition
    """
    contact, lead = _get_contact_and_lead_for_survey(
        tg_id=tg_id,
        username=tg_nickname,
        survey_id=survey_id,
        missing_lead_with_error_metadata=True,
    )

    if q1_text:
        lead.survey_q1 = q1_text
    if q2_text:
        lead.survey_q2 = q2_text
    if q3_text:
        lead.survey_q3 = q3_text
    if q4_text:
        lead.survey_q4 = q4_text
    if q1_addition_text:
        lead.survey_q1_addition = q1_addition_text
    if q2_addition_text:
        lead.survey_q2_addition = q2_addition_text
    if q3_addition_text:
        lead.survey_q3_addition = q3_addition_text

    update_lead_status_in_pipeline(
        lead, CRM_SURVEY_PIPELINE, SURVEY_LEAD_STATUS_SUBMITTED_ID
    )


def _get_contact_and_lead_for_survey(
    tg_id: int,
    username: str | None,
    survey_id: int,
    missing_lead_with_error_metadata: bool,
) -> tuple[Contact, Lead]:
    """
    Find contact by Telegram id (strict telegram_id match), then find lead in
    survey pipeline whose status is not 142/143 and whose survey_id equals the
    current survey id.

    If contact missing — create with error tag/note. If lead missing — create a
    new lead in the survey pipeline with provided survey_id and configurable
    error metadata.
    """
    try:
        contact = _find_contact_by_telegram_id(tg_id)
        if contact is None:
            contact = _create_contact(tg_id, username)

        lead = find_survey_lead(contact, survey_id)
        if lead is None:
            lead = _create_lead(
                contact,
                survey_id=survey_id,
                with_error_metadata=missing_lead_with_error_metadata,
            )
            logger.info(
                "Survey tg_id=%s survey_id=%s: created lead in pipeline %s",
                tg_id,
                survey_id,
                CRM_SURVEY_PIPELINE,
            )

        return contact, lead
    except Exception as e:
        logger.error(
            "_get_contact_and_lead_for_survey failed for tg_id=%s survey_id=%s: %s",
            tg_id,
            survey_id,
            e,
            exc_info=True,
        )
        raise


def _normalize_survey_date(
    survey_date: datetime | date_type | str | int | float,
) -> str:
    def _to_amo_iso(dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds")

    if isinstance(survey_date, datetime):
        return _to_amo_iso(survey_date)
    if isinstance(survey_date, date_type):
        dt = datetime(survey_date.year, survey_date.month, survey_date.day)
        return _to_amo_iso(dt)
    if isinstance(survey_date, (int, float)):
        dt = datetime.fromtimestamp(survey_date, tz=timezone.utc)
        return _to_amo_iso(dt)
    if isinstance(survey_date, str):
        try:
            dt = datetime.fromisoformat(survey_date)
            return _to_amo_iso(dt)
        except ValueError:
            dt = datetime.strptime(survey_date, "%Y-%m-%d")
            return _to_amo_iso(dt)
    raise ValueError("Unsupported survey_date type")


def _normalize_survey_id(value: object) -> int | None:
    if value is None:
        return None
    try:
        # Amo numeric custom fields may be returned as float (e.g. 63.0).
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _contact_display_name(username: str | None, tg_id: int) -> str:
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


def find_survey_lead(contact: Contact, survey_id: int) -> Lead | None:
    # Amo returns _ListData(data=None) when there are no leads; it is truthy but __iter__ crashes.
    lead_refs = (contact._data.get("_embedded") or {}).get("leads")
    if not lead_refs:
        return None
    pid = str(CRM_SURVEY_PIPELINE)
    normalized_survey_id = _normalize_survey_id(survey_id)
    if normalized_survey_id is None:
        return None
    for lead in _iter_contact_leads(contact):
        with amo_crm_rate_limiter.limit():
            lead_pipeline = lead.pipeline
        if not lead_pipeline or str(lead_pipeline.id) != pid:
            continue
        with amo_crm_rate_limiter.limit():
            lead_status = lead.status
        sid = str(lead_status.id) if lead_status else None
        if sid not in EXCLUDED_LEAD_STATUSES:
            lead_survey_id = _normalize_survey_id(getattr(lead, "survey_id", None))
            if lead_survey_id is not None and lead_survey_id == normalized_survey_id:
                return lead
    return None


def _iter_contact_leads(contact: Contact):
    """Итерация по лидам контакта с rate-limiting для каждого API-запроса."""
    for lead_ref in contact.leads._data or []:
        with amo_crm_rate_limiter.limit():
            yield contact.leads._manager.get(lead_ref["id"])


def _create_contact(tg_id: int, username: str | None) -> Contact:
    name = _contact_display_name(username, tg_id)
    with amo_crm_rate_limiter.limit():
        contact = Contact(name=name, telegram_id=str(tg_id), telegram_nickname=username)
        save_entity(contact)

    _append_entity_tag(contact, TAG_SURVEY_CONTACT_ERROR)
    with amo_crm_rate_limiter.limit():
        save_entity(contact)

    with amo_crm_rate_limiter.limit():
        contact.notes.objects.create(
            text=NOTE_SURVEY_CONTACT_CREATED, note_type=COMMON_TYPE
        )
        save_entity(contact)
    return contact


def _create_lead(
    contact: Contact, *, survey_id: int, with_error_metadata: bool
) -> Lead:
    pipeline_id = CRM_SURVEY_PIPELINE
    pid = str(pipeline_id)
    with amo_crm_rate_limiter.limit():
        pipeline = Pipeline.objects.get(object_id=pipeline_id)

    # Pick a status that we know belongs to this pipeline to satisfy AmoCRM validation.
    status = next(
        (
            s
            for s in pipeline.statuses
            if str(s.id) == str(SURVEY_LEAD_STATUS_STARTED_ID)
        ),
        None,
    )
    if status is None:
        status = next(iter(pipeline.statuses), None)
    if status is None:
        raise ValueError(f"No statuses found in pipeline {pid}")

    with amo_crm_rate_limiter.limit():
        lead = Lead(pipeline=pipeline, status=status)
        lead.survey_id = survey_id
        save_entity(lead)
    with amo_crm_rate_limiter.limit():
        lead.contacts.append(contact, main=True)

    if with_error_metadata:
        _append_entity_tag(lead, TAG_SURVEY_LEAD_ERROR)
        with amo_crm_rate_limiter.limit():
            save_entity(lead)
        with amo_crm_rate_limiter.limit():
            lead.notes.objects.create(
                text=NOTE_SURVEY_LEAD_CREATED, note_type=COMMON_TYPE
            )
            save_entity(lead)
    return lead
