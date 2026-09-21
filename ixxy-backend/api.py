import os
import secrets
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS
from itsdangerous import URLSafeTimedSerializer, BadSignature

from database import (
    create_user,
    get_user,
    get_user_by_login,
    get_user_dict,
    get_subscription_link,
    get_subscription_content,
    create_payment,
    get_payment_by_external_id,
    mark_payment_paid,
    payment_processed,
    mark_payment_processed,
    get_user_payments,
    extend_subscription,
    subscription_active,
    days_left,
)

from cashera import (
    create_payment as cashera_create_payment,
    verify_webhook,
)


app = Flask(__name__)

FRONTEND_URL = os.getenv(
    "PUBLIC_SITE_URL",
    "https://ixxyweb-1.onrender.com"
).strip()

API_PUBLIC_URL = os.getenv(
    "API_PUBLIC_URL",
    ""
).strip()

SECRET_KEY = os.getenv(
    "API_SECRET_KEY",
    ""
).strip()

if not SECRET_KEY:
    raise RuntimeError("API_SECRET_KEY не задан")

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": [FRONTEND_URL]
        }
    }
)

serializer = URLSafeTimedSerializer(
    SECRET_KEY,
    salt="ixxy-api"
)

TARIFFS = {
    30: 129,
    90: 379,
    180: 659,
    365: 1089,
}


def make_token(user_id):
    return serializer.dumps({
        "user_id": int(user_id)
    })


def get_token_user():
    header = request.headers.get(
        "Authorization",
        ""
    )

    if not header.startswith("Bearer "):
        return None

    try:
        data = serializer.loads(
            header[7:].strip(),
            max_age=60 * 60 * 24 * 30
        )
        return int(data["user_id"])
    except (
        BadSignature,
        ValueError,
        KeyError,
        TypeError
    ):
        return None


def require_user():
    user_id = get_token_user()

    if not user_id:
        return None, (
            jsonify({
                "ok": False,
                "error": "Необходима авторизация"
            }),
            401
        )

    user = get_user_dict(user_id)

    if not user:
        return None, (
            jsonify({
                "ok": False,
                "error": "Пользователь не найден"
            }),
            404
        )

    return user, None


@app.get("/")
def index():
    return jsonify({
        "ok": True,
        "service": "IXXY VPN API"
    })


@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "service": "ixxy",
        "time": datetime.now(
            timezone.utc
        ).isoformat()
    })


@app.post("/api/auth/register")
def register():
    data = request.get_json(
        silent=True
    ) or {}

    telegram_id = str(
        data.get("telegram_id", "")
    ).strip()

    username = str(
        data.get("username", "")
    ).strip().lstrip("@")

    first_name = str(
        data.get("first_name", "")
    ).strip()

    if not telegram_id:
        return jsonify({
            "ok": False,
            "error": "Введите Telegram ID"
        }), 400

    try:
        user_id = int(telegram_id)
    except ValueError:
        return jsonify({
            "ok": False,
            "error": "Telegram ID должен быть числом"
        }), 400

    user = create_user(
        user_id,
        username or None,
        first_name or None
    )

    return jsonify({
        "ok": True,
        "token": make_token(user_id),
        "user": user
    })


@app.post("/api/auth/login")
def login():
    data = request.get_json(
        silent=True
    ) or {}

    login_value = str(
        data.get("login", "")
    ).strip().lstrip("@")

    if not login_value:
        return jsonify({
            "ok": False,
            "error": "Введите Telegram ID или username"
        }), 400

    user = None

    try:
        user = get_user(
            int(login_value)
        )

        if user:
            user = dict(user)

    except ValueError:
        pass

    if not user:
        user = get_user_by_login(
            login_value
        )

    if not user:
        return jsonify({
            "ok": False,
            "error": "Пользователь не найден"
        }), 404

    return jsonify({
        "ok": True,
        "token": make_token(
            user["user_id"]
        ),
        "user": user
    })


@app.get("/api/me")
def me():
    user, error = require_user()

    if error:
        return error

    return jsonify({
        "ok": True,
        "user": user
    })


@app.get("/api/subscription")
def subscription():
    user, error = require_user()

    if error:
        return error

    until = user.get(
        "subscription_until"
    )

    return jsonify({
        "ok": True,
        "active": subscription_active(until),
        "days_left": days_left(until),
        "subscription_until": (
            until.isoformat()
            if until
            else None
        ),
        "subscription_link":
            get_subscription_link(
                user["user_id"]
            ),
        "subscription_content":
            get_subscription_content(
                user["user_id"]
            )
    })


@app.get("/api/tariffs")
def tariffs():
    return jsonify({
        "ok": True,
        "tariffs": [
            {
                "days": days,
                "amount": amount
            }
            for days, amount in TARIFFS.items()
        ]
    })


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
            data.get("days", 0)
        )
    except (
        ValueError,
        TypeError
    ):
        days = 0

    if days not in TARIFFS:
        return jsonify({
            "ok": False,
            "error": "Неверный тариф"
        }), 400

    if not API_PUBLIC_URL.startswith("https://"):
        return jsonify({
            "ok": False,
            "error": "API_PUBLIC_URL не настроен"
        }), 500

    amount = TARIFFS[days]

    external_id = (
        f"ixxy_{user['user_id']}_"
        f"{days}_{secrets.token_hex(8)}"
    )

    callback_url = (
        API_PUBLIC_URL.rstrip("/")
        + "/api/payment/webhook"
    )

    success_url = (
        FRONTEND_URL.rstrip("/")
        + "/cabinet.html"
    )

    create_payment(
        user_id=user["user_id"],
        amount=amount,
        days=days,
        external_id=external_id
    )

    try:
        result = cashera_create_payment(
            amount_rub=amount,
            external_id=external_id,
            description=f"IXXY VPN — {days} дней",
            callback_url=callback_url,
            success_url=success_url,
            fail_url=success_url,
            user_id=user["user_id"],
            days=days
        )
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 502

    payment_url = None

    if isinstance(result, dict):
        for key in (
            "payment_url",
            "url",
            "checkout_url",
            "pay_url"
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
                "pay_url"
            ):
                if nested.get(key):
                    payment_url = nested[key]
                    break

    if not payment_url:
        return jsonify({
            "ok": False,
            "error": "CasheRa не вернула ссылку на оплату"
        }), 502

    return jsonify({
        "ok": True,
        "external_id": external_id,
        "amount": amount,
        "days": days,
        "payment_url": payment_url
    })


@app.post("/api/payment/webhook")
def payment_webhook():
    if not verify_webhook(
        request.headers
    ):
        return jsonify({
            "ok": False,
            "error": "Invalid webhook"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    external_id = (
        data.get("external_id")
        or data.get("externalId")
    )

    status = str(
        data.get("status", "")
    ).lower()

    nested = data.get("data")

    if isinstance(nested, dict):
        external_id = (
            external_id
            or nested.get("external_id")
            or nested.get("externalId")
        )

        status = str(
            nested.get("status", status)
        ).lower()

    if not external_id:
        return jsonify({
            "ok": False,
            "error": "external_id отсутствует"
        }), 400

    if payment_processed(external_id):
        return jsonify({
            "ok": True,
            "already_processed": True
        })

    payment = get_payment_by_external_id(
        external_id
    )

    if not payment:
        return jsonify({
            "ok": False,
            "error": "Платёж не найден"
        }), 404

    if status not in {
        "paid",
        "success",
        "successful",
        "completed",
        "succeeded"
    }:
        return jsonify({
            "ok": True,
            "ignored": True,
            "status": status
        })

    extend_subscription(
        payment["user_id"],
        payment["days"]
    )

    mark_payment_paid(
        external_id
    )

    mark_payment_processed(
        external_id
    )

    return jsonify({
        "ok": True
    })


@app.get("/api/payments")
def payments():
    user, error = require_user()

    if error:
        return error

    return jsonify({
        "ok": True,
        "payments": get_user_payments(
            user["user_id"]
        )
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv("PORT", "8000")
        ),
        debug=False
    )