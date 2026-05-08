"""
GET /api/v4/talks?filter[entity_type]=lead&filter[entity_id]=<id>

Usage:
    python scripts/get_lead_talks.py [lead_id]

Defaults to the lead_id hardcoded below if no argument is given.
"""
import sys
import json
from pathlib import Path
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import config
from amocrm.v2 import tokens

DEFAULT_LEAD_ID = "13530669"

lead_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LEAD_ID

tokens.default_token_manager(
    client_id=config.CRM_CLIENT_ID,
    client_secret=config.CRM_CLIENT_SECRET,
    subdomain=config.CRM_SUBDOMAIN,
    redirect_url=config.CRM_REDIRECT_URL,
    storage=tokens.FileTokensStorage(directory_path="tokens"),
)

access_token = tokens.default_token_manager.get_access_token()

url = f"https://{config.CRM_SUBDOMAIN}.amocrm.ru/api/v4/talks"
headers = {"Authorization": f"Bearer {access_token}"}
params = {
    "filter[entity_type]": "lead",
    "filter[entity_id]": lead_id,
}

print(f"GET {url}?filter[entity_type]=lead&filter[entity_id]={lead_id}\n")

response = requests.get(url, headers=headers, params=params)

print(f"Status: {response.status_code}")
try:
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
except Exception:
    print(response.text)
