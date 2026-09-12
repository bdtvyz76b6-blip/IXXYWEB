import os
import uuid
import requests
from dotenv import load_dotenv
load_dotenv()
CASHERA_API_KEY = os.getenv("CASHERA_API_KEY", "").strip()
CASHERA_API_SECRET = os.getenv("CASHERA_API_SECRET", "").strip()
CASHERA_MERCHANT_ID = os.getenv("CASHERA_MERCHANT_ID", "").strip()
CASHERA_BASE_URL = "https://api.cashera.cash/api/v1"
def create_cashera_payment(
    amount,
    external_id=None,
    description="Подписка ixxy VPN",
    callback_url=None,
    success_url=None,
    fail_url=None,
    user_id=None,
    plan=None,
):
    """
    Создание платежа Cashera.
    amount:
        RUB, например 129
    external_id:
        уникальный ID заказа.
    Возвращает:
        dict с данными платежа Cashera.
    """
    if not CASHERA_API_KEY:
        raise RuntimeError(
            "CASHERA_API_KEY не установлен"
        )
    try:
        amount_rub = int(amount)
    except (TypeError, ValueError):
        raise ValueError(
            "amount должен быть целым числом в рублях"
        )
    if amount_rub <= 0:
        raise ValueError(
            "Сумма платежа должна быть больше 0"
        )
    if not external_id:
        external_id = (
            f"ixxy_{user_id or 'user'}_"
            f"{uuid.uuid4().hex[:16]}"
        )
    payload = {
        "amount": amount_rub * 100,
        "currency": "RUB",
        "external_id": str(external_id),
        "description": str(description)[:255],
    }
    if user_id is not None or plan is not None:
        payload["metadata"] = {}
        if user_id is not None:
            payload["metadata"]["user_id"] = int(user_id)
        if plan is not None:
            payload["metadata"]["plan"] = str(plan)
    if callback_url:
        payload["callback_url"] = callback_url
    if success_url:
        payload["success_url"] = success_url
    if fail_url:
        payload["fail_url"] = fail_url
    headers = {
        "X-Api-Key": CASHERA_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    response = requests.post(
        f"{CASHERA_BASE_URL}/integration/transactions",
        headers=headers,
        json=payload,
        timeout=30,
    )
    try:
        data = response.json()
    except ValueError:
        data = {
            "message": response.text
        }
    if response.status_code not in (200, 201):
        message = data.get("message")
        if not message:
            message = (
                f"Cashera HTTP {response.status_code}"
            )
        raise RuntimeError(
            f"Cashera error: {message}"
        )
    return data
def get_cashera_payment(uuid_value):
    """
    Получить статус платежа по UUID.
    """
    if not CASHERA_API_KEY:
        raise RuntimeError(
            "CASHERA_API_KEY не установлен"
        )
    if not uuid_value:
        raise ValueError(
            "Не указан UUID платежа"
        )
    headers = {
        "X-Api-Key": CASHERA_API_KEY,
        "Accept": "application/json",
    }
    response = requests.get(
        f"{CASHERA_BASE_URL}/integration/transactions/"
        f"{uuid_value}",
        headers=headers,
        timeout=30,
    )
    try:
        data = response.json()
    except ValueError:
        data = {
            "message": response.text
        }
    if response.status_code != 200:
        raise RuntimeError(
            f"Cashera HTTP {response.status_code}: "
            f"{data.get('message', 'Unknown error')}"
        )
    return data
def get_cashera_payment_by_external_id(
    external_id
):
    """
    Получить платеж по external_id.
    """
    if not CASHERA_API_KEY:
        raise RuntimeError(
            "CASHERA_API_KEY не установлен"
        )
    if not external_id:
        raise ValueError(
            "Не указан external_id"
        )
    headers = {
        "X-Api-Key": CASHERA_API_KEY,
        "Accept": "application/json",
    }
    response = requests.get(
        f"{CASHERA_BASE_URL}/integration/"
        f"transactions/by-external-id/"
        f"{external_id}",
        headers=headers,
        timeout=30,
    )
    try:
        data = response.json()
    except ValueError:
        data = {
            "message": response.text
        }
    if response.status_code != 200:
        raise RuntimeError(
            f"Cashera HTTP {response.status_code}: "
            f"{data.get('message', 'Unknown error')}"
        )
    return data
# Совместимость со старым кодом
create_payment = create_cashera_payment