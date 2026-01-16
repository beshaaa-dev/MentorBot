# Visit Card Video Processing - AMoCRM API Requests

## Обзор

Документация описывает флоу отправки видео визитки в чат с с админом в AMO CRM.

После получения видео от пользователя (ограничение в 20 МБ - больше телеграм не позволяет скачать) мы загружаем его в карточку контакта пользователя (видео хранится в хранилище AMO CRM), вытаскиваем ссылку на видео и отправляем в чат с админом с помощью API Чатов.

Для работы с API Чатов нам нужно [зарегистрировать канал в AMO CRM](https://www.amocrm.ru/developers/content/chats/chat-start).

Все запросы выполняются ассинхроно с учетом RPS в 7 запросов/секунду. 

## Детальное описание флоу

### 1. Загрузка видео в AMoCRM Drive

**Эндпоинты:**

**1.1. Получение drive_url**
```http
GET https://{subdomain}.amocrm.ru/api/v4/account?with=drive_url
Authorization: Bearer {access_token}
```

**1.2. Создание сессии загрузки**
```http
POST {drive_url}/v1.0/sessions
Authorization: Bearer {access_token}
Content-Type: application/json

{
    "file_name": "visit_2024-01-09.mp4",
    "file_size": 1234567,
    "content_type": "video/mp4"
}
```

**Ответ:**
```json
{
    "upload_url": "https://...",
    "max_part_size": 524288
}
```

**1.3. Загрузка файла частями**
```http
POST {upload_url}
Authorization: Bearer {access_token}
Content-Type: application/octet-stream
Content-Range: bytes {offset}-{end}/{total}

<binary data>
```

**Последний чанк возвращает:**
```json
{
    "uuid": "file-uuid",
    "_links": {
        "download": {
            "href": "https://drive-b.amocrm.ru/..."
        }
    }
}
```

---

### 2. Отправка видео в чат с админом

**2.1. Получение или использование кэшированного scope_id**

`scope_id` кэшируется в памяти на время работы бота.

**Если scope_id уже в кэше:**
- Используем кэшированное значение
- Пропускаем шаги 2.1.1 и 2.1.2

**Если scope_id НЕ в кэше:**

**2.1.1. Получение amojo_id**
```http
GET https://{subdomain}.amocrm.ru/api/v4/account?with=amojo_id
Authorization: Bearer {access_token}
```

**2.1.2. Подключение канала**
```http
POST https://amojo.amocrm.ru/v2/origin/custom/{channel_id}/connect
Date: {RFC2822_date}
Content-Type: application/json
Content-MD5: {md5_hash}
X-Signature: {hmac_sha1_signature}

{
    "account_id": "{amojo_id}",
    "title": "TG BOT",
    "hook_api_version": "v2"
}
```

**Ответ:**
```json
{
    "scope_id": "{channel_id}_{amojo_id}"
}
```

**Важно:** После получения `scope_id` сохраняется в `_cached_scope_id` и используется для всех последующих запросов до перезапуска бота.

**2.3. Создание чата**
```http
POST https://amojo.amocrm.ru/v2/origin/custom/{scope_id}/chats
Date: {RFC2822_date}
Content-Type: application/json
Content-MD5: {md5_hash}
X-Signature: {hmac_sha1_signature}

{
    "conversation_id": "tgbot-{contact_id}",
    "user": {
        "id": "tgbot-user-{contact_id}",
        "name": "Иван Иванов"
    }
}
```

**Ответ:**
```json
{
    "id": "chat-uuid"
}
```

**2.4. Привязка чата к контакту**
```http
POST https://{subdomain}.amocrm.ru/api/v4/contacts/chats
Authorization: Bearer {access_token}
Content-Type: application/json

[{
    "contact_id": 12345,
    "chat_id": "chat-uuid"
}]
```

**2.5. Отправка видео сообщения**
```http
POST https://amojo.amocrm.ru/v2/origin/custom/{scope_id}
Date: {RFC2822_date}
Content-Type: application/json
Content-MD5: {md5_hash}
X-Signature: {hmac_sha1_signature}

{
    "event_type": "new_message",
    "payload": {
        "timestamp": 1704758400,
        "msec_timestamp": 1704758400000,
        "msgid": "tgbot-video-1704758400000",
        "conversation_ref_id": "chat-uuid",
        "sender": {
            "id": "tgbot-contact-1704758400",
            "name": "Иван Иванов"
        },
        "message": {
            "type": "video",
            "media": "https://drive-b.amocrm.ru/.../video.mp4",
            "file_name": "visit_2024-01-09.mp4",
            "file_size": 1234567
        },
        "silent": false,
        "source": {
            "external_id": "67890"
        }
    }
}
```
