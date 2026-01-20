from dataclasses import dataclass
from database.test_service import save_test_result as _save_test_result
from crm.crm_service import get_crm_lead, update_lead_status_by_lead, send_note, get_crm_user_by_id
from crm.crm_models import Contact
from config import CRM_TEST_IS_IN_PROGRESS_STATUS, CRM_VISIT_CARD_STATUS
from logger import setup_logger
from rate_limiter import amo_crm_rate_limiter

logger = setup_logger(__name__)


@dataclass
class TestScores:
    block1_score: int
    block2_score: int
    block3_score: int
    block4_score: int
    block5_score: int
    block6_score: int
    case1_score: int
    case2_score: int
    total_score: int
    profile_type: str


def save_test_results(
    user_id: int,
    lead_id: str,
    scores: TestScores
) -> None:
    """Сохраняет результаты теста в базу данных."""
    _save_test_result(
        user_id=user_id,
        lead_id=lead_id,
        block1_score=scores.block1_score,
        block2_score=scores.block2_score,
        block3_score=scores.block3_score,
        block4_score=scores.block4_score,
        block5_score=scores.block5_score,
        block6_score=scores.block6_score,
        case1_score=scores.case1_score,
        case2_score=scores.case2_score,
        total_score=scores.total_score,
        profile_type=scores.profile_type,
    )


def update_lead_status_to_in_progress(lead_id: str) -> None:
    lead = get_crm_lead(int(lead_id))
    if lead and CRM_TEST_IS_IN_PROGRESS_STATUS:
        try:
            update_lead_status_by_lead(lead, CRM_TEST_IS_IN_PROGRESS_STATUS)
            logger.info(f"Updated lead {lead_id} status to TEST_IN_PROGRESS")
        except Exception as e:
            logger.error(f"Failed to update lead status to in progress: {e}")
            raise


def send_test_results_to_crm(
    user_id: int,
    lead_id: str,
    scores: TestScores,
    answers: list[str],
    case1_answer: str,
    case2_answer: str
) -> None:
    crm_note = (
        f"Результаты теста\n"
        f"Блок 1 (Честность): {scores.block1_score}/6\n"
        f"Блок 2 (Мотивация): {scores.block2_score}/6\n"
        f"Блок 3 (Ответственность): {scores.block3_score}/5\n"
        f"Блок 4 (Командность): {scores.block4_score}/5\n"
        f"Блок 5 (Эмоциональная устойчивость): {scores.block5_score}/3\n"
        f"Блок 6 (Надёжность): {scores.block6_score}/5\n"
        f"Кейс 1: {case1_answer} ({scores.case1_score}/4)\n"
        f"Кейс 2: {case2_answer} ({scores.case2_score}/4)\n"
        f"Общий балл: {scores.total_score}/38\n\n"
        f"Ответы на вопросы:\n"
    )
    
    for i, answer in enumerate(answers[:30], 1):
        crm_note += f"{i}. {answer}\n"
    
    crm_note += f"Кейс 1: {case1_answer}\n"
    crm_note += f"Кейс 2: {case2_answer}\n"
    
    try:
        send_note(int(lead_id), crm_note)
        logger.info(f"Test results sent to CRM for user_id={user_id}, lead_id={lead_id}")
    except Exception as e:
        logger.error(f"Failed to send test results to CRM: {e}")
        raise


def update_contact_test_scores(contact_id: int, scores: TestScores) -> None:
    """Обновляет поля контакта с результатами теста в CRM."""
    try:
        contact = get_crm_user_by_id(contact_id)
        if not contact:
            logger.error(f"Contact {contact_id} not found in CRM")
            return
        
        contact.honesty = str(scores.block1_score)
        contact.motivation = str(scores.block2_score)
        contact.responsibility = str(scores.block3_score)
        contact.teamwork = str(scores.block4_score)
        contact.emotional_stability = str(scores.block5_score)
        contact.reliability = str(scores.block6_score)
        contact.case1 = str(scores.case1_score)
        contact.case2 = str(scores.case2_score)
        contact.total_score = str(scores.total_score)
        
        with amo_crm_rate_limiter.limit():
            contact.save()
        
        logger.info(f"Updated contact {contact_id} with test scores: total={scores.total_score}")
    except Exception as e:
        logger.error(f"Failed to update contact test scores: {e}")
        raise


def update_lead_status_to_visit_card(lead_id: str) -> None:
    lead = get_crm_lead(int(lead_id))
    if lead and CRM_VISIT_CARD_STATUS:
        try:
            update_lead_status_by_lead(lead, CRM_VISIT_CARD_STATUS)
            logger.info(f"Updated lead {lead_id} status to VISIT_CARD after test completion")
        except Exception as e:
            logger.error(f"Failed to update lead status after test: {e}")
            raise
