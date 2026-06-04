from amocrm.v2 import Contact as _Contact, Lead as _Lead, custom_field


class Contact(_Contact):
    telegram_id = custom_field.TextCustomField("TelegramId_WZ")
    telegram_nickname = custom_field.TextCustomField(
        "TelegramUsername_WZ", field_id=536049
    )
    honesty = custom_field.NumericCustomField("Честность")
    motivation = custom_field.NumericCustomField("Мотивация")
    responsibility = custom_field.NumericCustomField("Ответственность")
    teamwork = custom_field.NumericCustomField("Командность")
    emotional_stability = custom_field.NumericCustomField("Эмоциональная устойчивость")
    reliability = custom_field.NumericCustomField("Надежность")
    case1 = custom_field.NumericCustomField("Кейс 1")
    case2 = custom_field.NumericCustomField("Кейс 2")
    total_score = custom_field.NumericCustomField("Общий бал")
    referral_link = custom_field.TextCustomField("Рефералка", field_id=563780)


class Lead(_Lead):
    fio = custom_field.TextCustomField("ФИО")
    age = custom_field.TextCustomField("Возраст")
    city = custom_field.TextCustomField("Город проживания")
    first_task = custom_field.TextCustomField("Задание от наставника")
    second_task = custom_field.TextCustomField("Задание 2 от наставника")
    third_task = custom_field.TextCustomField("Задание 3 от наставника")
    mentor_tg_nickname = custom_field.TextCustomField("тг наставника", field_id=550463)
    task_deadline = custom_field.TextCustomField("Дедлайн задания")
    current_study = custom_field.TextCustomField("Где ты сейчас учишься?")
    most_important_now = custom_field.TextCustomField(
        "Что для тебя сейчас важнее всего из этого?"
    )
    direction_2_3_years = custom_field.TextCustomField(
        "Если смотреть на ближайшие 2–3 года, в каком направлении ты хочешь двигаться?"
    )
    multiple_tasks_behavior = custom_field.TextCustomField(
        "Когда у тебя одновременно несколько задач и дедлайнов, что обычно происходит?"
    )
    activities_besides_study = custom_field.TextCustomField(
        "Чем ты занимаешься помимо учёбы регулярно?"
    )
    top_achievements = custom_field.TextCustomField(
        "Назови до 3–5 достижений / результатов, которыми ты действительно гордишься"
    )
    failure_situation = custom_field.TextCustomField(
        "Опиши ситуацию, где у тебя не получилось, хотя ты старался(лась)"
    )
    strong_qualities = custom_field.TextCustomField(
        "Какие свои качества ты считаешь сильными — и как они могут быть полезны другим участникам группы?"
    )
    qualities_to_change = custom_field.TextCustomField(
        "Какие качества или привычки ты хотел(а) бы изменить в себе?"
    )
    why_this_mentor = custom_field.TextCustomField(
        "Почему вы хотите в группу именно к этому наставнику?", field_id=550469
    )
    # Homework fields (pipeline 10726418)
    hw_question_1 = custom_field.TextCustomField("Д/З №1", field_id=560085)
    hw_question_2 = custom_field.TextCustomField("Д/З №2", field_id=560087)
    hw_question_3 = custom_field.TextCustomField("Д/З №3", field_id=560089)
    hw_question_4 = custom_field.TextCustomField("Д/З №4", field_id=560091)
    hw_question_5 = custom_field.TextCustomField("Д/З №5", field_id=560093)
    hw_deadline = custom_field.DateCustomField("Дедлайн", field_id=560201)
    hw_answer_1 = custom_field.TextCustomField("Ответ на Д/З №1", field_id=560189)
    hw_answer_2 = custom_field.TextCustomField("Ответ на Д/З №2", field_id=560191)
    hw_answer_3 = custom_field.TextCustomField("Ответ на Д/З №3", field_id=560193)
    hw_answer_4 = custom_field.TextCustomField("Ответ на Д/З №4", field_id=560195)
    hw_answer_5 = custom_field.TextCustomField("Ответ на Д/З №5", field_id=560197)
    hw_db_record_id = custom_field.TextCustomField("homework_id", field_id=560199)
    hw_completion_date = custom_field.DateCustomField(
        "Время сдачи Д/З", field_id=560203
    )
    hw_deadline_missed = custom_field.TextCustomField("Просрочено", field_id=560205)
    hw_edit_reason = custom_field.TextCustomField("Причина возврата. Куратор", field_id=560207)
    hw_edit_reason_mentor = custom_field.TextCustomField(
        "Причина возврата. Наставник", field_id=560533
    )
    hw_rating = custom_field.NumericCustomField("Оценка наставника", field_id=560359)
    hw_feedback = custom_field.TextCustomField("Фидбек ментора", field_id=560361)
    # Поля для проекта с опросами
    survey_date = custom_field.DateCustomField("Дата опроса", field_id=559061)
    chat_name = custom_field.TextCustomField("Название чата", field_id=559059)
    survey_q1 = custom_field.TextCustomField("1 вопрос", field_id=559093)
    survey_q2 = custom_field.TextCustomField("2 вопрос", field_id=559095)
    survey_q3 = custom_field.TextCustomField("3 вопрос", field_id=559097)
    survey_q4 = custom_field.TextCustomField("4 вопрос", field_id=559099)
    survey_q1_addition = custom_field.TextCustomField(
        "Дополнение к 1 вопросу", field_id=559427
    )
    survey_q2_addition = custom_field.TextCustomField(
        "Дополнение ко 2 вопросу", field_id=559429
    )
    survey_q3_addition = custom_field.TextCustomField(
        "Дополнение к 3 вопросу", field_id=559431
    )
    survey_id = custom_field.NumericCustomField("survey_id", field_id=559435)


__all__ = ["Contact", "Lead"]
