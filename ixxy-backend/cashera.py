import os
import hmac
import requests

from dotenv import load_dotenv

load_dotenv()

API_URL = “https://api.cashera.cash/api/v1”

API_KEY = os.getenv(
“CASHERA_API_KEY”,
“”
).strip()

API_SECRET = os.getenv(
“CASHERA_API_SECRET”,
“”
).strip()

class CasheraError(Exception):
def init(
self,
status_code,
message,
errors=None,
raw=None
):
self.status_code = status_code
self.message = message
self.errors = errors
self.raw = raw

    super().__init__(message)

def headers():
if not API_KEY:
raise RuntimeError(
“CASHERA_API_KEY не задан”
)

return {
    "X-Api-Key": API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

def parse_response(response):
try:
data = response.json()

except Exception:
    data = {
        "message": response.text
    }
if response.ok:
    return data
message = None
if isinstance(data, dict):
    message = data.get("message")
if not message:
    message = response.text
errors = None
if isinstance(data, dict):
    errors = data.get("errors")
raise CasheraError(
    response.status_code,
    message,
    errors,
    data
)

def create_payment(
amount_rub,
external_id,
description,
callback_url,
success_url,
fail_url,
user_id,
days
):
if not API_KEY:
raise RuntimeError(
“CASHERA_API_KEY не задан”
)

if not callback_url.startswith(
    "https://"
):
    raise ValueError(
        "callback_url должен использовать HTTPS"
    )
payload = {
    "amount": int(amount_rub) * 100,
    "currency": "RUB",
    "external_id": str(external_id),
    "description": str(description)[:255],
    "callback_url": callback_url,
    "success_url": success_url,
    "fail_url": fail_url,
    "metadata": {
        "user_id": str(user_id),
        "days": str(days),
    },
}
response = requests.post(
    f"{API_URL}/integration/transactions",
    headers=headers(),
    json=payload,
    timeout=30
)
return parse_response(response)

def verify_webhook(request_headers):
if not API_KEY:
return False

received_key = request_headers.get(
    "X-Api-Key",
    ""
)
if not hmac.compare_digest(
    received_key,
    API_KEY
):
    return False
if API_SECRET:
    received_secret = request_headers.get(
        "X-Secret",
        ""
    )
    return hmac.compare_digest(
        received_secret,
        API_SECRET
    )
return True