import os
import json
import hmac
import requests
from dotenv import load_dotenv

load_dotenv()

CASHERA_API_URL = “https://api.cashera.cash/api/v1”
CASHERA_API_KEY = os.getenv(“CASHERA_API_KEY”, “”).strip()
CASHERA_API_SECRET = os.getenv(“CASHERA_API_SECRET”, “”).strip()

class CasheraError(Exception):
def init(self, status_code, message, errors=None, raw=None):
self.status_code = status_code
self.message = message
self.errors = errors
self.raw = raw

    text = f"CasheRa HTTP {status_code}: {message}"
    if errors:
        text += f" | errors={errors}"
    super().__init__(text)

def _headers():
if not CASHERA_API_KEY:
raise RuntimeError(“CASHERA_API_KEY не задан”)

return {
    "X-Api-Key": CASHERA_API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

def _parse_response(response):
try:
data = response.json()
except Exception:
data = response.text

if response.ok:
    return data
if isinstance(data, dict):
    message = data.get("message") or data.get("error") or "Ошибка CasheRa"
    errors = data.get("errors")
else:
    message = str(data)
    errors = None
raise CasheraError(
    response.status_code,
    message,
    errors,
    data,
)

def create_payment(
amount_rub,
external_id,
description,
callback_url,
success_url=None,
fail_url=None,
user_id=None,
days=None,
):
if not CASHERA_API_KEY:
raise RuntimeError(“CASHERA_API_KEY не задан”)

amount_rub = int(amount_rub)
if amount_rub < 100:
    raise ValueError("Сумма платежа должна быть не меньше 100 RUB")
if not callback_url.startswith("https://"):
    raise ValueError("callback_url должен начинаться с https://")
payload = {
    "amount": amount_rub * 100,
    "currency": "RUB",
    "external_id": str(external_id)[:255],
    "description": str(description)[:255],
    "callback_url": callback_url,
}
if success_url:
    payload["success_url"] = success_url
if fail_url:
    payload["fail_url"] = fail_url
metadata = {}
if user_id is not None:
    metadata["user_id"] = str(user_id)
if days is not None:
    metadata["days"] = str(days)
if metadata:
    payload["metadata"] = metadata
response = requests.post(
    f"{CASHERA_API_URL}/integration/transactions",
    json=payload,
    headers=_headers(),
    timeout=30,
)
return _parse_response(response)

def get_payment(payment_id):
response = requests.get(
f”{CASHERA_API_URL}/integration/transactions/{payment_id}”,
headers=_headers(),
timeout=30,
)

return _parse_response(response)

def get_payment_by_external_id(external_id):
response = requests.get(
f”{CASHERA_API_URL}/integration/transactions/by-external-id/{external_id}”,
headers=_headers(),
timeout=30,
)

return _parse_response(response)

def verify_webhook(headers):
if not CASHERA_API_KEY or not CASHERA_API_SECRET:
return False

received_key = headers.get("X-Api-Key", "")
received_secret = headers.get("X-Secret", "")
return (
    hmac.compare_digest(received_key, CASHERA_API_KEY)
    and hmac.compare_digest(received_secret, CASHERA_API_SECRET)
)