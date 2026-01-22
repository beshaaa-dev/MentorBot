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
    first_task = custom_field.TextCustomField("Задание от наставника")
    second_task = custom_field.TextCustomField("Задание 2 от наставника")
    third_task = custom_field.TextCustomField("Задание 3 от наставника")
    mentor_tg_nickname = custom_field.TextCustomField("тг наставника")
    task_deadline = custom_field.TextCustomField("Дедлайн задания")
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
        "Назовите три своих жизненных принципа."
    )
    question_for_mentor = custom_field.TextCustomField(
        "Какой один вопрос вы бы задали своему будущему наставнику?"
    )
    top_5_achievements = custom_field.TextCustomField(
        "Назовите топ-5 своих достижений, которыми вы гордитесь на сегодняшний день."
    )
    olympiad_competition_volunteer_experience = custom_field.TextCustomField(
        "Если у вас есть опыт участия в олимпиадах, конкурсах, волонтерстве или других проектах — расскажите, в каких именно."
    )
    portfolio_link = custom_field.TextCustomField(
        "Если у вас есть портфолио, кейсы или другие материалы, которые показывают ваши достижения и опыт, — поделитесь ссылкой. (Например: сайт, соцсети, видео, презентации или документы.) Это необязательный вопрос, но, если есть, можете отправить — это повысит шансы."
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


__all__ = ["Contact", "Lead"]
