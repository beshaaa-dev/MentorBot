from amocrm.v2 import Pipeline, tokens, custom_field, Contact as _Contact, Lead as _Lead
import config
from logger import setup_logger

logger = setup_logger(__name__)


class Contact(_Contact):
    telegram_id = custom_field.TextCustomField("TelegramUsername_WZ")


class Lead(_Lead):
    task = custom_field.TextCustomField("Задание от наставника")
    mentor_tg_nickname = custom_field.TextCustomField("Ник тг наставника")


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


def get_crm_user(nickname: str) -> Contact | None:
    contacts = Contact.objects.filter(query=nickname)

    if contacts:
        return next(iter(contacts), None)

    return None


def get_crm_lead(id: int) -> Lead | None:
    leads = Lead.objects.filter(query=id)
    if leads:
        return next(iter(leads), None)
    return None
