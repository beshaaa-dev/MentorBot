from amocrm.v2 import Contact as _Contact, Lead as _Lead, custom_field


class Contact(_Contact):
    telegram_id = custom_field.TextCustomField("TelegramId_WZ")
    honesty = custom_field.NumericCustomField("Честность")
    motivation = custom_field.NumericCustomField("Мотивация")
    responsibility = custom_field.NumericCustomField("Ответственность")
    teamwork = custom_field.NumericCustomField("Командность")
    emotional_stability = custom_field.NumericCustomField("Эмоциональная устойчивость")
    reliability = custom_field.NumericCustomField("Надежность")
    case1 = custom_field.NumericCustomField("Кейс 1")
    case2 = custom_field.NumericCustomField("Кейс 2")
    total_score = custom_field.NumericCustomField("Общий бал")


class Lead(_Lead):
    fio = custom_field.TextCustomField("ФИО")
    age = custom_field.TextCustomField("Возраст")
    city = custom_field.TextCustomField("Город проживания")
    first_task = custom_field.TextCustomField("Задание от наставника")
    second_task = custom_field.TextCustomField("Задание 2 от наставника")
    third_task = custom_field.TextCustomField("Задание 3 от наставника")
    mentor_tg_nickname = custom_field.TextCustomField("тг наставника")
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


__all__ = ["Contact", "Lead"]
