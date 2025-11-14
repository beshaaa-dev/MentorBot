from amocrm.v2 import Pipeline, tokens, custom_field, Contact as _Contact, Lead as _Lead
import config
from logger import setup_logger

logger = setup_logger(__name__)


class Contact(_Contact):
    telegram_id = custom_field.TextCustomField("TelegramUsername_WZ")


class Lead(_Lead):
    task = custom_field.TextCustomField("Задание от наставника")
    mentor_tg_nickname = custom_field.TextCustomField("Ник тг наставника")
    city = custom_field.TextCustomField("В каком городе вы живете?")
    source = custom_field.TextCustomField("Откуда вы узнали о Поколении?")
    why_this_mentor = custom_field.TextCustomField(
        "Почему вы хотите в группу именно к этому наставнику?"
    )
    life_goals = custom_field.TextCustomField(
        "Какие жизненные цели вы хотите достичь с помощью наставничества?"
    )
    what_ready_to_do_for_team = custom_field.TextCustomField(
        "Что вы готовы сделать для команды, даже если это выходит за пределы вашей зоны комфорта?"
    )
    three_life_principles = custom_field.TextCustomField(
        "Назовите три своих жизненных принципа"
    )
    question_for_mentor = custom_field.TextCustomField(
        "Какой один вопрос вы бы задали своему будущему наставнику?"
    )
    top_5_achievements = custom_field.TextCustomField(
        "Назовите топ-5 своих достижений, которыми вы гордитесь на сегодняшний день."
    )
    olympiad_competition_volunteer_experience = custom_field.TextCustomField(
        "Если у вас есть опыт участия в олимпиадах, конкурсах, волонтерстве или других проектах — расскажите, в каких именно"
    )
    portfolio_link = custom_field.TextCustomField(
        "Если у вас есть портфолио, кейсы или другие материалы, которые показывают ваши достижения и опыт, — поделитесь ссылкой. (Например: сайт, соцсети, видео, презентации или документы.) Это необязательный вопрос, но, если есть, можете отправить — это повысит ш"
    )
    strong_qualities = custom_field.TextCustomField(
        "Какие свои качества вы считаете сильными?"
    )
    qualities_to_change = custom_field.TextCustomField(
        "Какие качества вы хотели бы изменить в себе?"
    )
    qualities_to_realize_in_project = custom_field.TextCustomField(
        "Какие свои качества, сильные стороны, таланты или способности вы хотите реализовать в проекте?"
    )
    what_you_do_well = custom_field.TextCustomField(
        "Что у вас получается хорошо и чем вы могли бы быть полезны другим?"
    )


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
        tokens.default_token_manager.get_access_token()
        logger.info("AmoCRM token is valid")
    except Exception as e:
        logger.warning(f"Failed to get access token: {e}. Initializing new token...")
        init_amo_crm_token()


def init_amo_crm_token():
    try:
        tokens.default_token_manager.init(
            code=config.CRM_AUTH_CODE,
            skip_error=False,
        )
    except Exception as e:
        logger.error(f"Failed to initialize AmoCRM token: {e}")
        raise e


def get_crm_user_by_tg_nickname(nickname: str) -> Contact | None:
    contacts = Contact.objects.filter(query=nickname)
    for contact in contacts:
        if contact.telegram_id == nickname:
            return contact

    return None


def get_crm_user_by_id(id: int) -> Contact | None:
    contacts = Contact.objects.filter(query=id)

    for contact in contacts:
        if str(contact.id) == str(id):
            return contact

    return None


def get_crm_lead(id: int) -> Lead | None:
    leads = Lead.objects.filter(query=id)
    if leads:
        return next(iter(leads), None)
    return None


def update_lead_status(id: int, status: str) -> Lead | None:
    pipelines = Pipeline.objects.filter(query="Тестовая_Андрей")
    pipeline = next((p for p in pipelines if "Тестовая_Андрей" in p.name), None)

    if not pipeline:
        raise ValueError(f"Pipeline with id=10254214 not found")

    status = next((s for s in pipeline.statuses if s.name == status), None)
    if status is None:
        raise ValueError(f"Status '{status}' not found in pipeline")

    lead = get_crm_lead(id)
    if lead:
        lead.status = status
        lead.save()
        return lead
    return None
