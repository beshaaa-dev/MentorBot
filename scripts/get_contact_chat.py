"""
GET /api/v4/contacts/chats?chat_id=<id>

Usage:
    python scripts/get_contact_chat.py [chat_id]

Defaults to the chat_id hardcoded below if no argument is given.
"""
import sys
import json
import requests
from dotenv import load_dotenv

load_dotenv()

import config
from amocrm.v2 import tokens

DEFAULT_CHAT_ID = "458adc76-677e-471d-80f5-22209df67b65"

chat_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CHAT_ID

tokens.default_token_manager(
    client_id=config.CRM_CLIENT_ID,
    client_secret=config.CRM_CLIENT_SECRET,
    subdomain=config.CRM_SUBDOMAIN,
    redirect_url=config.CRM_REDIRECT_URL,
    storage=tokens.FileTokensStorage(directory_path="tokens"),
)

access_token = tokens.default_token_manager.get_access_token()

url = f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/contacts/chats"
headers = {"Authorization": f"Bearer {access_token}"}
params = {"chat_id": chat_id}

print(f"GET {url}?chat_id={chat_id}\n")

response = requests.get(url, headers=headers, params=params)

print(f"Status: {response.status_code}")
try:
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
except Exception:
    print(response.text)
