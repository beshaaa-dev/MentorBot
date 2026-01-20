from database.db_helper import get_db
from database.models import TestResult
from logger import setup_logger

logger = setup_logger(__name__)


def check_if_test_completed(user_id: int) -> bool:
    """
    Проверяет, прошел ли пользователь тест.

    Args:
        user_id: ID пользователя в базе данных

    Returns:
        True если тест пройден, False если нет
    """
    with get_db() as session:
        existing_test = session.query(TestResult).filter(
            TestResult.user_id == user_id
        ).first()
        return existing_test is not None


def save_test_result(
    user_id: int,
    lead_id: str,
    block1_score: int,
    block2_score: int,
    block3_score: int,
    block4_score: int,
    block5_score: int,
    block6_score: int,
    case1_score: int,
    case2_score: int,
    total_score: int,
    profile_type: str,
) -> TestResult:
    """
    Сохраняет результаты теста в базу данных.

    Args:
        user_id: ID пользователя
        lead_id: ID лида в CRM
        block1_score: Баллы за блок 1
        block2_score: Баллы за блок 2
        block3_score: Баллы за блок 3
        block4_score: Баллы за блок 4
        block5_score: Баллы за блок 5
        block6_score: Баллы за блок 6
        case1_score: Баллы за кейс 1
        case2_score: Баллы за кейс 2
        total_score: Общий балл
        profile_type: Тип профиля

    Returns:
        Созданный объект TestResult
    """
    with get_db() as session:
        test_result = TestResult(
            user_id=user_id,
            lead_id=lead_id,
            block1_score=block1_score,
            block2_score=block2_score,
            block3_score=block3_score,
            block4_score=block4_score,
            block5_score=block5_score,
            block6_score=block6_score,
            case1_score=case1_score,
            case2_score=case2_score,
            total_score=total_score,
            profile_type=profile_type,
        )
        session.add(test_result)
        session.commit()
        session.refresh(test_result)
        
        logger.info(f"Saved test result for user_id={user_id}, lead_id={lead_id}, total_score={total_score}")
        return test_result
