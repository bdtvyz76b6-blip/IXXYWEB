import os
import secrets
from datetime import datetime, date, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS
from itsdangerous import URLSafeTimedSerializer, BadSignature
from database import (
    create_user,
    get_user,
    get_all_users,
    get_subscription_link,
    get_subscription_content,
    create_payment,
    get_all_payments,
    update_payment_status,
    extend_subscription,
    now_utc,
)
from cashera import (
    create_payment as cashera_create_payment,
    verify_webhook,
)
# =========================================================
# APP
# =========================================================
app = Flask(__name__)
# =========================================================
# НАСТРОЙКИ
# =========================================================
FRONTEND_URL = os.getenv(
    "PUBLIC_SITE_URL",
    "https://ixxyweb-1.onrender.com",
).strip().rstrip("/")
API_PUBLIC_URL = os.getenv(
    "API_PUBLIC_URL",
    "",
).strip().rstrip("/")
SECRET_KEY = os.getenv(
    "API_SECRET_KEY",
    "",
).strip()
if not SECRET_KEY:
    raise RuntimeError("API_SECRET_KEY не задан")
# =========================================================
# CORS
# =========================================================
CORS(
    app,
    resources={
        r"/api/*": {
            "origins": [
                FRONTEND_URL,
                "https://ixxyweb-1.onrender.com",
            ]
        }
    },
)
# =========================================================
# АВТОРИЗАЦИЯ
# =========================================================
serializer = URLSafeTimedSerializer(
    SECRET_KEY,
    salt="ixxy-api",
)
def make_token(user_id: int) -> str:
    return serializer.dumps(
        {
            "user_id": int(user_id)
        }
    )
def get_token_user():
    header = request.headers.get(
        "Authorization",
        "",
    )
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    if not token:
        return None
    try:
        data = serializer.loads(
            token,
            max_age=60 * 60 * 24 * 30,
        )
        return int(data["user_id"])
    except (
        BadSignature,
        ValueError,
        KeyError,
        TypeError,
    ):
        return None
def require_user():
    user_id = get_token_user()
    if not user_id:
        return None, (
            jsonify(
                {
                    "ok": False,
                    "error": "Необходима авторизация",
                }
            ),
            401,
        )
    user = get_user(user_id)
    if not user:
        return None, (
            jsonify(
                {
                    "ok": False,
                    "error": "Пользователь не найден",
                }
            ),
            404,
        )
    return user, None
# =========================================================
# JSON
# =========================================================
def serialize_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            key: serialize_value(val)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [
            serialize_value(item)
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            serialize_value(item)
            for item in value
        ]
    return value
def serialize_datetime(value):
    if not value:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
# =========================================================
# ПОДПИСКА
# =========================================================
def subscription_active(subscription_until) -> bool:
    if not subscription_until:
        return False
    if isinstance(subscription_until, str):
        try:
            subscription_until = subscription_until.replace(
                "Z",
                "+00:00",
            )
            subscription_until = datetime.fromisoformat(
                subscription_until
            )
        except Exception:
            return False
    if isinstance(subscription_until, datetime):
        if subscription_until.tzinfo is None:
            subscription_until = subscription_until.replace(
                tzinfo=timezone.utc
            )
        return subscription_until > datetime.now(
            timezone.utc
        )
    return False
def days_left(subscription_until) -> int:
    if not subscription_until:
        return 0
    if isinstance(subscription_until, str):
        try:
            subscription_until = subscription_until.replace(
                "Z",
                "+00:00",
            )
            subscription_until = datetime.fromisoformat(
                subscription_until
            )
        except Exception:
            return 0
    if isinstance(subscription_until, datetime):
        if subscription_until.tzinfo is None:
            subscription_until = subscription_until.replace(
                tzinfo=timezone.utc
            )
        seconds = (
            subscription_until
            - datetime.now(timezone.utc)
        ).total_seconds()
        if seconds <= 0:
            return 0
        return int(
            seconds // 86400
        )
    return 0
# =========================================================
# ПОИСК ПОЛЬЗОВАТЕЛЯ
# =========================================================
def find_user_by_login(login_value: str):
    login_value = (
        str(login_value)
        .strip()
        .lstrip("@")
        .lower()
    )
    if not login_value:
        return None
    # Сначала Telegram ID
    try:
        user_id = int(login_value)
        user = get_user(user_id)
        if user:
            return user
    except (
        ValueError,
        TypeError,
    ):
        pass
    # Затем username
    users = get_all_users()
    for user in users:
        username = str(
            user.get("username") or ""
        ).strip().lstrip("@").lower()
        if username == login_value:
            return user
    return None
# =========================================================
# ГЛАВНАЯ
# =========================================================
@app.get("/")
def index():
    return jsonify(
        {
            "ok": True,
            "service": "IXXY VPN API",
        }
    )
# =========================================================
# HEALTH
# =========================================================
@app.get("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "service": "ixxy",
            "time": datetime.now(
                timezone.utc
            ).isoformat(),
        }
    )
# =========================================================
# РЕГИСТРАЦИЯ
# =========================================================
@app.post("/api/auth/register")
def register():
    data = request.get_json(
        silent=True
    ) or {}
    telegram_id = str(
        data.get(
            "telegram_id",
            "",
        )
    ).strip()
    username = str(
        data.get(
            "username",
            "",
        )
    ).strip().lstrip("@")
    first_name = str(
        data.get(
            "first_name",
            "",
        )
    ).strip()
    if not telegram_id:
        return jsonify(
            {
                "ok": False,
                "error": "Введите Telegram ID",
            }
        ), 400
    try:
        user_id = int(telegram_id)
    except (
        ValueError,
        TypeError,
    ):
        return jsonify(
            {
                "ok": False,
                "error": "Telegram ID должен быть числом",
            }
        ), 400
    create_user(
        user_id,
        username or None,
        first_name or None,
    )
    user = get_user(user_id)
    return jsonify(
        {
            "ok": True,
            "token": make_token(user_id),
            "user": serialize_value(user),
        }
    )
# =========================================================
# ВХОД
# =========================================================
@app.post("/api/auth/login")
def login():
    data = request.get_json(
        silent=True
    ) or {}
    login_value = str(
        data.get(
            "login",
            "",
        )
    ).strip()
    if not login_value:
        return jsonify(
            {
                "ok": False,
                "error": "Введите Telegram ID или username",
            }
        ), 400
    user = find_user_by_login(
        login_value
    )
    if not user:
        return jsonify(
            {
                "ok": False,
                "error": "Пользователь не найден",
            }
        ), 404
    user_id = int(
        user["user_id"]
    )
    return jsonify(
        {
            "ok": True,
            "token": make_token(user_id),
            "user": serialize_value(user),
        }
    )
# =========================================================
# МОЙ ПРОФИЛЬ
# =========================================================
@app.get("/api/me")
def me():
    user, error = require_user()
    if error:
        return error
    return jsonify(
        {
            "ok": True,
            "user": serialize_value(user),
        }
    )
# =========================================================
# МОЯ ПОДПИСКА
# =========================================================
@app.get("/api/subscription")
def subscription():
    user, error = require_user()
    if error:
        return error
    until = user.get(
        "subscription_until"
    )
    active = (
        bool(user.get("subscription"))
        and subscription_active(until)
    )
    remaining_days = days_left(
        until
    )
    subscription_link = get_subscription_link(
        user["user_id"]
    )
    subscription_content = get_subscription_content(
        user["user_id"]
    )
    return jsonify(
        {
            "ok": True,
            "active": active,
            "days_left": remaining_days,
            "subscription_until": serialize_datetime(
                until
            ),
            "subscription_link": subscription_link,
            "subscription_content": subscription_content,
        }
    )
# =========================================================
# ТАРИФЫ
# =========================================================
TARIFFS = {
    30: 129,
    90: 379,
    180: 659,
    365: 1089,
}
@app.get("/api/tariffs")
def tariffs():
    return jsonify(
        {
            "ok": True,
            "tariffs": [
                {
                    "days": days,
                    "amount": amount,
                }
                for days, amount in TARIFFS.items()
            ],
        }
    )
# =========================================================
# СОЗДАНИЕ ПЛАТЕЖА
# =========================================================
@app.post("/api/payment/create")
def payment_create():
    user, error = require_user()
    if error:
        return error
    data = request.get_json(
        silent=True
    ) or {}
    try:
        days = int(
            data.get(
                "days",
                0,
            )
        )
    except (
        ValueError,
        TypeError,
    ):
        days = 0
    if days not in TARIFFS:
        return jsonify(
            {
                "ok": False,
                "error": "Неверный тариф",
            }
        ), 400
    if not API_PUBLIC_URL.startswith(
        "https://"
    ):
        return jsonify(
            {
                "ok": False,
                "error": "API_PUBLIC_URL не настроен",
            }
        ), 500
    amount = TARIFFS[days]
    external_id = (
        f"ixxy_"
        f"{user['user_id']}_"
        f"{days}_"
        f"{secrets.token_hex(8)}"
    )
    callback_url = (
        API_PUBLIC_URL
        + "/api/payment/webhook"
    )
    success_url = (
        FRONTEND_URL
        + "/cabinet.html"
    )
    fail_url = success_url
    # Сначала записываем платёж
    # в PostgreSQL сайта.
    create_payment(
        user_id=user["user_id"],
        payment_id=external_id,
        amount=amount,
        days=days,
        status="pending",
        provider="cashera",
        external_id=external_id,
    )
    try:
        result = cashera_create_payment(
            amount_rub=amount,
            external_id=external_id,
            description=(
                f"IXXY VPN — {days} дней"
            ),
            callback_url=callback_url,
            success_url=success_url,
            fail_url=fail_url,
            user_id=user["user_id"],
            days=days,
        )
    except Exception as e:
        return jsonify(
            {
                "ok": False,
                "error": str(e),
            }
        ), 502
    payment_url = None
    if isinstance(result, dict):
        for key in (
            "payment_url",
            "url",
            "checkout_url",
            "pay_url",
        ):
            if result.get(key):
                payment_url = result[key]
                break
        nested = result.get("data")
        if isinstance(nested, dict):
            for key in (
                "payment_url",
                "url",
                "checkout_url",
                "pay_url",
            ):
                if nested.get(key):
                    payment_url = nested[key]
                    break
    if not payment_url:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "CasheRa не вернула "
                    "ссылку на оплату"
                ),
            }
        ), 502
    return jsonify(
        {
            "ok": True,
            "external_id": external_id,
            "amount": amount,
            "days": days,
            "payment_url": payment_url,
        }
    )
# =========================================================
# WEBHOOK CASHERA
# =========================================================
@app.post("/api/payment/webhook")
def payment_webhook():
    if not verify_webhook(
        request.headers
    ):
        return jsonify(
            {
                "ok": False,
                "error": "Invalid webhook",
            }
        ), 401
    data = request.get_json(
        silent=True
    ) or {}
    external_id = (
        data.get("external_id")
        or data.get("externalId")
    )
    status = str(
        data.get(
            "status",
            "",
        )
    ).lower()
    nested = data.get("data")
    if isinstance(
        nested,
        dict,
    ):
        external_id = (
            external_id
            or nested.get("external_id")
            or nested.get("externalId")
        )
        status = str(
            nested.get(
                "status",
                status,
            )
        ).lower()
    if not external_id:
        return jsonify(
            {
                "ok": False,
                "error": "external_id отсутствует",
            }
        ), 400
    # Ищем платёж по external_id.
    payments = get_all_payments()
    payment = None
    for item in payments:
        if (
            str(item.get("external_id") or "")
            == str(external_id)
        ):
            payment = item
            break
        if (
            str(item.get("payment_id") or "")
            == str(external_id)
        ):
            payment = item
            break
    if not payment:
        return jsonify(
            {
                "ok": False,
                "error": "Платёж не найден",
            }
        ), 404
    # Если уже оплачен — повторно не продлеваем.
    if str(
        payment.get("status") or ""
    ).lower() == "paid":
        return jsonify(
            {
                "ok": True,
                "already_processed": True,
            }
        )
    if status not in {
        "paid",
        "success",
        "successful",
        "completed",
        "succeeded",
    }:
        return jsonify(
            {
                "ok": True,
                "ignored": True,
                "status": status,
            }
        )
    # Реально продлеваем подписку.
    extend_subscription(
        int(payment["user_id"]),
        int(payment["days"]),
    )
    # Помечаем платёж оплаченным.
    update_payment_status(
        str(payment["payment_id"]),
        "paid",
    )
    return jsonify(
        {
            "ok": True,
        }
    )
# =========================================================
# МОИ ПЛАТЕЖИ
# =========================================================
@app.get("/api/payments")
def payments():
    user, error = require_user()
    if error:
        return error
    all_payments = get_all_payments()
    user_payments = [
        payment
        for payment in all_payments
        if int(payment["user_id"])
        == int(user["user_id"])
    ]
    return jsonify(
        {
            "ok": True,
            "payments": serialize_value(
                user_payments
            ),
        }
    )
# =========================================================
# ЗАПУСК
# =========================================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "8000",
            )
        ),
        debug=False,
    )

Теперь этот api.py не импортирует функции, которых нет в твоём текущем database.py вроде get_user_by_login, get_user_dict, payment_processed, days_left и т.д. Для поиска пользователя он использует твою реальную таблицу users, а платежи — твою реальную таблицу payments.

Следующим файлом лучше проверить database.py, потому что там я уже вижу один обязательный момент: старый PUBLIC_SITE_URL нужно заменить на https://ixxyweb-1.onrender.com.