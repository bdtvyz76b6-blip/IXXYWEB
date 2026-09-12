import os
import uuid
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.cashera.cash/api/v1"

API_KEY = os.getenv("CASHERA_API_KEY", "").strip()
API_SECRET = os.getenv("CASHERA_API_SECRET", "").strip()


def _headers():
    return {
        "X-Api-Key": API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def create_payment(
    amount_rub,
    external_id,
    description,
    callback_url,
    success_url,
    fail_url,
):
    if not API_KEY:
        raise RuntimeError("CASHERA_API_KEY не задан")

    payload = {
        "amount": int(amount_rub * 100),
        "currency": "RUB",
        "external_id": str(external_id),
        "description": description,
        "callback_url": callback_url,
        "success_url": success_url,
        "fail_url": fail_url,
    }

    response = requests.post(
        f"{API_URL}/integration/transactions",
        json=payload,
        headers=_headers(),
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"CasheRa HTTP {response.status_code}: {response.text}"
        )

    data = response.json()

    if not data:
        raise RuntimeError("CasheRa вернула пустой ответ")

    return data


def get_payment(payment_id):
    response = requests.get(
        f"{API_URL}/integration/transactions/{payment_id}",
        headers=_headers(),
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"CasheRa HTTP {response.status_code}: {response.text}"
        )

    return response.json()


def check_webhook(headers):
    received_key = headers.get("X-Api-Key", "")
    received_secret = headers.get("X-Secret", "")

    if not API_KEY or not API_SECRET:
        return False

    return (
        received_key == API_KEY
        and received_secret == API_SECRET
    )