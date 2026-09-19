import os
import time
import hmac
import hashlib
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from flask import Flask, request, jsonify, Response
from dotenv import load_dotenv

import database as db
import cashera

load_dotenv()

app = Flask(__name__)

PUBLIC_SITE_URL = os.getenv(
    "PUBLIC_SITE_URL",
    "https://ixxyweb.onrender.com"
).rstrip("/")

FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "https://ixxyweb.onrender.com"
).rstrip("/")

SUBSCRIPTION_PREFIX = os.getenv(
    "SUBSCRIPTION_PREFIX",
    "2ix847xy"
)

TELEGRAM_URL = os.getenv(
    "TELEGRAM_URL",
    "https://t.me/orelvpntopbot"
)

WEB_SECRET_KEY = os.getenv("WEB_SECRET_KEY", "").strip()

if not WEB_SECRET_KEY:
    WEB_SECRET_KEY = secrets.token_hex(32)

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "bdtvyz76b6-blip")
GITHUB_REPO = os.getenv("GITHUB_REPO", "vpn-sub")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

TARIFFS = {
    30: 129,
    90: 379,
    180: 659,
    365: 1089,
}


# =========================================================
# CORS
# =========================================================

@app.after_request
def cors(response):
    origin = request.headers.get("Origin")

    if origin == FRONTEND_URL:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization"
        )
        response.headers["Access-Control-Allow-Methods"] = (
            "GET, POST, PUT, OPTIONS"
        )

    return response


@app.route("/api/<path:path>", methods=["OPTIONS"])
def options_api(path):
    return ("", 204)


# =========================================================
# HELPERS
# =========================================================

def now_utc():
    return datetime.now(timezone.utc)


def make_token(user_id):
    payload = f"{user_id}:{int(time.time())}"

    signature = hmac.new(
        WEB_SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    raw = f"{payload}:{signature}"
    return raw.encode().hex()


def parse_auth_token(token):
    try:
        raw = bytes.fromhex(token).decode()

        user_part, timestamp, signature = raw.split(":", 2)

        payload = f"{user_part}:{timestamp}"

        expected = hmac.new(
            WEB_SECRET_KEY.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            return None

        ts = int(timestamp)

        # 30 дней
        if time.time() - ts > 30 * 86400:
            return None

        return int(user_part)

    except Exception:
        return None


def get_current_user_id():
    header = request.headers.get("Authorization", "")

    if not header.startswith("Bearer "):
        return None

    return parse_auth_token(header[7:].strip())


def require_user():
    user_id = get_current_user_id()

    if not user_id:
        return None, jsonify({
            "ok": False,
            "error": "Не авторизован"
        }), 401

    user = db.get_user_dict(user_id)

    if not user:
        return None, jsonify({
            "ok": False,
            "error": "Пользователь не найден"
        }), 404

    return user, None, None


def require_admin():
    user_id = get_current_user_id()

    if not user_id or user_id not in ADMIN_IDS:
        return None, jsonify({
            "ok": False,
            "error": "Доступ запрещён"
        }), 403

    user = db.get_user_dict(user_id)

    if not user:
        return None, jsonify({
            "ok": False,
            "error": "Пользователь не найден"
        }), 404

    return user, None, None


def make_subscription_url(user_id):
    return (
        f"{PUBLIC_SITE_URL}/sub/"
        f"{SUBSCRIPTION_PREFIX}{user_id}"
    )


def make_happ_url(user_id):
    url = make_subscription_url(user_id)
    return "https://happ.vpnbypass.click/?url=" + quote(url, safe="")


def make_incy_url(user_id):
    url = make_subscription_url(user_id)
    return "incy://add/" + quote(url, safe="")


def subscription_active(user):
    value = user.get("subscription_until")

    if not value:
        return False

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except Exception:
            return False

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value > now_utc()


def days_left(user):
    value = user.get("subscription_until")

    if not value:
        return 0

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except Exception:
            return 0

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    seconds = (value - now_utc()).total_seconds()

    if seconds <= 0:
        return 0

    return int((seconds + 86399) // 86400)


def serialize_user(user):
    active = subscription_active(user)

    until = user.get("subscription_until")

    if until:
        if hasattr(until, "isoformat"):
            until = until.isoformat()

    return {
        "user_id": user.get("user_id"),
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "active": active,
        "days_left": days_left(user),
        "subscription_until": until,
        "subscription_link": make_subscription_url(
            user["user_id"]
        ),
        "happ_url": make_happ_url(
            user["user_id"]
        ),
        "incy_url": make_incy_url(
            user["user_id"]
        ),
        "telegram_url": TELEGRAM_URL,
    }


# =========================================================
# GITHUB
# =========================================================

def github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "IXXY-VPN",
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    return headers


def github_file_url(filename):
    return (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/contents/"
        f"{filename}?ref={GITHUB_BRANCH}"
    )


def github_get_file(filename):
    response = requests.get(
        github_file_url(filename),
        headers=github_headers(),
        timeout=20
    )

    if response.status_code == 404:
        return ""

    response.raise_for_status()

    data = response.json()

    import base64

    content = data.get("content", "")
    content = content.replace("\n", "")

    return base64.b64decode(content).decode("utf-8")


def github_save_file(filename, content):
    import base64

    url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/contents/"
        f"{filename}"
    )

    existing = requests.get(
        url,
        headers=github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=20
    )

    sha = None

    if existing.status_code == 200:
        sha = existing.json().get("sha")

    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode()

    payload = {
        "message": f"Update {filename}",
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        url,
        headers=github_headers(),
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


def get_servers_files():
    active = github_get_file("servers.txt")
    inactive = github_get_file("no_servers.txt")

    return active, inactive


# =========================================================
# SUBSCRIPTION
# =========================================================

ACTIVE_HEADER = """id="1obn2u"
id="rsz5kg"
id="65uefq"
id="f66b5v"
id="ps27vy"
#profile-title: 𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️
#profile-update-interval: 1
#subscription-userinfo: upload=0; download=0; total=0
#hide-settings: true
"""

INACTIVE_HEADER = """id="rp03e1"
id="kx1hv9"
id="zkoq0g"
id="67cogr"
id="gdiay7"
#profile-title: 𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️
#profile-update-interval: 1
#subscription-userinfo: upload=0; download=0; total=0
#hide-settings: true
"""


def build_subscription_content(user_id):
    user = db.get_user_dict(user_id)

    if not user:
        return None

    active_servers, inactive_servers = get_servers_files()

    if subscription_active(user):
        until = user.get("subscription_until")

        if hasattr(until, "strftime"):
            date_text = until.strftime("%d.%m.%Y")
        else:
            date_text = str(until)

        header = (
            ACTIVE_HEADER +
            f"#announce: 🟢 Подписка активна • "
            f"до {date_text} • ☂️ ixxy VPN\n"
        )

        content = header + active_servers
    else:
        header = (
            INACTIVE_HEADER +
            "#announce: 🔴 Подписка не активна • "
            "Продлите подписку на сайте ixxy VPN\n"
        )

        content = header + inactive_servers

    return content


def sync_subscription(user_id):
    content = build_subscription_content(user_id)

    if content is None:
        return False

    filename = f"users/{user_id}.txt"

    github_save_file(filename, content)

    link = make_subscription_url(user_id)

    db.update_subscription_data(
        user_id,
        subscription_link=link,
        subscription_content=content
    )

    return True


# =========================================================
# AUTH
# =========================================================

@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}

    login_value = str(
        data.get("login", "")
    ).strip()

    if not login_value:
        return jsonify({
            "ok": False,
            "error": "Введите Telegram ID или username"
        }), 400

    user = db.get_user_by_login(login_value)

    if not user and login_value.isdigit():
        user = db.get_user_dict(int(login_value))

    if not user:
        return jsonify({
            "ok": False,
            "error": "Пользователь не найден"
        }), 404

    token = make_token(user["user_id"])

    return jsonify({
        "ok": True,
        "token": token,
        "user": serialize_user(user)
    })


@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}

    telegram_id = str(
        data.get("telegram_id", "")
    ).strip()

    username = str(
        data.get("username", "")
    ).strip().lstrip("@")

    first_name = str(
        data.get("first_name", "")
    ).strip()

    if not telegram_id.isdigit():
        return jsonify({
            "ok": False,
            "error": "Для регистрации нужен Telegram ID"
        }), 400

    user_id = int(telegram_id)

    user = db.create_user(
        user_id,
        username=username or None,
        first_name=first_name or None
    )

    token = make_token(user_id)

    return jsonify({
        "ok": True,
        "token": token,
        "user": serialize_user(
            db.get_user_dict(user_id)
        )
    })


@app.get("/api/me")
def me():
    user, error, status = require_user()

    if error:
        return error, status

    return jsonify({
        "ok": True,
        "user": serialize_user(user)
    })


# =========================================================
# PAYMENTS
# =========================================================

@app.post("/api/buy/<int:days>")
def buy(days):
    user, error, status = require_user()

    if error:
        return error, status

    if days not in TARIFFS:
        return jsonify({
            "ok": False,
            "error": "Такого тарифа нет"
        }), 400

    amount = TARIFFS[days]

    external_id = (
        f"ixxy-{user['user_id']}-"
        f"{days}-{secrets.token_hex(8)}"
    )

    callback_url = (
        f"{PUBLIC_SITE_URL}/api/cashera/webhook"
    )

    success_url = (
        f"{FRONTEND_URL}/cabinet.html"
    )

    fail_url = (
        f"{FRONTEND_URL}/cabinet.html"
    )

    try:
        result = cashera.create_payment(
            amount_rub=amount,
            external_id=external_id,
            description=f"IXXY VPN — {days} дней",
            callback_url=callback_url,
            success_url=success_url,
            fail_url=fail_url,
            user_id=user["user_id"],
            days=days
        )

        payment_url = (
            result.get("payment_url")
            or result.get("checkout_url")
            or result.get("url")
            or result.get("pay_url")
        )

        transaction = result.get("transaction")

        if isinstance(transaction, dict):
            payment_url = (
                payment_url
                or transaction.get("payment_url")
                or transaction.get("checkout_url")
                or transaction.get("url")
                or transaction.get("pay_url")
            )

        if not payment_url:
            return jsonify({
                "ok": False,
                "error": "CasheRa не вернула ссылку на оплату",
                "response": result
            }), 502

        db.create_payment(
            user_id=user["user_id"],
            amount=amount,
            days=days,
            external_id=external_id
        )

        return jsonify({
            "ok": True,
            "payment_url": payment_url
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@app.post("/api/cashera/webhook")
def cashera_webhook():
    if not cashera.verify_webhook(request.headers):
        return jsonify({
            "ok": False,
            "error": "Invalid signature"
        }), 403

    data = request.get_json(silent=True) or {}

    transaction = data.get("transaction")

    if isinstance(transaction, dict):
        source = transaction
    else:
        source = data

    status = str(
        source.get("status", "")
    ).lower()

    if status not in ("paid", "success", "completed"):
        return jsonify({
            "ok": True,
            "ignored": True
        })

    external_id = (
        source.get("external_id")
        or data.get("external_id")
    )

    if not external_id:
        return jsonify({
            "ok": False,
            "error": "external_id missing"
        }), 400

    if db.payment_processed(external_id):
        return jsonify({
            "ok": True,
            "already_processed": True
        })

    payment = db.get_payment_by_external_id(
        external_id
    )

    if not payment:
        return jsonify({
            "ok": False,
            "error": "Payment not found"
        }), 404

    user_id = payment["user_id"]
    days = payment["days"]

    db.extend_subscription(user_id, days)

    db.mark_payment_paid(external_id)
    db.mark_payment_processed(external_id)

    try:
        sync_subscription(user_id)
    except Exception as e:
        print("Subscription sync error:", e)

    return jsonify({
        "ok": True
    })


# =========================================================
# SUBSCRIPTION URL
# =========================================================

@app.get("/sub/<token>")
def subscription(token):
    prefix = SUBSCRIPTION_PREFIX

    if not token.startswith(prefix):
        return Response(
            "Invalid subscription",
            status=404,
            mimetype="text/plain"
        )

    raw_id = token[len(prefix):]

    if not raw_id.isdigit():
        return Response(
            "Invalid subscription",
            status=404,
            mimetype="text/plain"
        )

    user_id = int(raw_id)

    content = db.get_subscription_content(user_id)

    if not content:
        try:
            content = build_subscription_content(user_id)
        except Exception:
            content = None

    if not content:
        return Response(
            "Subscription not found",
            status=404,
            mimetype="text/plain"
        )

    response = Response(
        content,
        mimetype="text/plain; charset=utf-8"
    )

    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )

    return response


# =========================================================
# ADMIN
# =========================================================

@app.get("/api/admin/stats")
def admin_stats():
    _, error, status = require_admin()

    if error:
        return error, status

    return jsonify({
        "ok": True,
        "stats": db.get_stats()
    })


@app.get("/api/admin/users")
def admin_users():
    _, error, status = require_admin()

    if error:
        return error, status

    users = db.get_all_users()

    return jsonify({
        "ok": True,
        "users": [
            serialize_user(u)
            if isinstance(u, dict)
            else serialize_user(
                db.get_user_dict(
                    u["user_id"]
                    if isinstance(u, dict)
                    else u[0]
                )
            )
            for u in users
        ]
    })


@app.post("/api/admin/user/<int:user_id>/extend")
def admin_extend(user_id):
    _, error, status = require_admin()

    if error:
        return error, status

    data = request.get_json(silent=True) or {}

    days = int(data.get("days", 0))

    if days <= 0 or days > 999999999:
        return jsonify({
            "ok": False,
            "error": "Неверное количество дней"
        }), 400

    if not db.get_user_dict(user_id):
        return jsonify({
            "ok": False,
            "error": "Пользователь не найден"
        }), 404

    db.extend_subscription(user_id, days)

    try:
        sync_subscription(user_id)
    except Exception as e:
        print("Admin sync error:", e)

    return jsonify({
        "ok": True,
        "user": serialize_user(
            db.get_user_dict(user_id)
        )
    })


@app.post("/api/admin/user/<int:user_id>/disable")
def admin_disable(user_id):
    _, error, status = require_admin()

    if error:
        return error, status

    db.disable_subscription(user_id)

    try:
        sync_subscription(user_id)
    except Exception as e:
        print("Admin sync error:", e)

    return jsonify({
        "ok": True
    })


@app.post("/api/admin/sync")
def admin_sync():
    _, error, status = require_admin()

    if error:
        return error, status

    users = db.get_all_users()

    total = 0
    success = 0
    errors = []

    for item in users:
        if isinstance(item, dict):
            user_id = item["user_id"]
        else:
            user_id = item[0]

        total += 1

        try:
            sync_subscription(user_id)
            success += 1
        except Exception as e:
            errors.append({
                "user_id": user_id,
                "error": str(e)
            })

    return jsonify({
        "ok": True,
        "total": total,
        "success": success,
        "errors": errors
    })


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():
    return jsonify({
        "service": "ixxy-api",
        "status": "ok"
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))

    app.run(
        host="0.0.0.0",
        port=port
    )