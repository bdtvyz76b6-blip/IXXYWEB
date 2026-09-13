import os
import html
import json
import secrets
import base64
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests
from flask import (
    Flask,
    Response,
    abort,
    redirect,
    request,
    session,
)

import database as db

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# ============================================================
# APP
# ============================================================

app = Flask(__name__)

app.secret_key = os.getenv(
    "WEB_SECRET_KEY",
    secrets.token_hex(32),
)


# ============================================================
# CONFIG
# ============================================================

PUBLIC_SITE_URL = os.getenv(
    "PUBLIC_SITE_URL",
    "https://ixxyweb.onrender.com",
).rstrip("/")

SUBSCRIPTION_PREFIX = os.getenv(
    "SUBSCRIPTION_PREFIX",
    "2ix847xy",
).strip()

TELEGRAM_URL = os.getenv(
    "TELEGRAM_URL",
    "https://t.me/orelvpntopbot",
).strip()

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}


# ============================================================
# GITHUB
# ============================================================

GITHUB_TOKEN = os.getenv(
    "GITHUB_TOKEN",
    "",
).strip()

GITHUB_OWNER = os.getenv(
    "GITHUB_OWNER",
    "bdtvyz76b6-blip",
).strip()

GITHUB_REPO = os.getenv(
    "GITHUB_REPO",
    "vpn-sub",
).strip()

GITHUB_BRANCH = os.getenv(
    "GITHUB_BRANCH",
    "main",
).strip()


# ============================================================
# CASHERA
# ============================================================

CASHERA_API_KEY = os.getenv(
    "CASHERA_API_KEY",
    "",
).strip()

CASHERA_API_SECRET = os.getenv(
    "CASHERA_API_SECRET",
    "",
).strip()

CASHERA_URL = "https://api.cashera.cash/api/v1"

TARIFFS = {
    30: 129,
    90: 379,
    180: 659,
    365: 1089,
}


# ============================================================
# SUBSCRIPTION
# ============================================================

def parse_token(token):
    if not token:
        return None

    if not token.startswith(
        SUBSCRIPTION_PREFIX
    ):
        return None

    raw = token[
        len(SUBSCRIPTION_PREFIX):
    ]

    if not raw.isdigit():
        return None

    try:
        return int(raw)
    except Exception:
        return None


def make_token(user_id):
    return (
        f"{SUBSCRIPTION_PREFIX}"
        f"{int(user_id)}"
    )


def build_subscription_url(token):
    return (
        f"{PUBLIC_SITE_URL}/sub/"
        f"{quote(token, safe='')}"
    )


def build_happ_url(token):
    subscription_url = (
        build_subscription_url(token)
    )

    return (
        "https://happ.vpnbypass.click/"
        "?url="
        + quote(
            subscription_url,
            safe="",
        )
    )


def build_incy_url(token):
    subscription_url = (
        build_subscription_url(token)
    )

    return (
        "incy://add/"
        + quote(
            subscription_url,
            safe="",
        )
    )


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


def parse_datetime(value):
    if not value:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )
        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt


def subscription_active(value):
    dt = parse_datetime(value)

    if not dt:
        return False

    return dt > now_utc()


def days_left(value):
    dt = parse_datetime(value)

    if not dt:
        return 0

    seconds = (
        dt - now_utc()
    ).total_seconds()

    if seconds <= 0:
        return 0

    return max(
        1,
        int(seconds / 86400),
    )


def format_date(value):
    dt = parse_datetime(value)

    if not dt:
        return "—"

    return dt.strftime(
        "%d.%m.%Y"
    )


def format_datetime(value):
    dt = parse_datetime(value)

    if not dt:
        return "—"

    return dt.strftime(
        "%d.%m.%Y %H:%M"
    )


def safe_text(
    value,
    default="—",
):
    if value is None:
        return default

    value = str(value).strip()

    if not value:
        return default

    return html.escape(value)


def no_cache(response):
    response.headers["Cache-Control"] = (
        "no-store, no-cache, "
        "must-revalidate, max-age=0"
    )

    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return response


def user_field(
    user,
    index,
    key,
    default="",
):
    if user is None:
        return default

    if isinstance(user, dict):
        return user.get(
            key,
            default,
        )

    try:
        return user[index]
    except Exception:
        return default


def payment_field(
    payment,
    index,
    key,
    default="",
):
    if payment is None:
        return default

    if isinstance(payment, dict):
        return payment.get(
            key,
            default,
        )

    try:
        return payment[index]
    except Exception:
        return default


# ============================================================
# ADMIN HELPERS
# ============================================================

def is_admin():
    user_id = session.get(
        "user_id"
    )

    if not user_id:
        return False

    try:
        return int(user_id) in ADMIN_IDS
    except Exception:
        return False


def require_admin():
    if not is_admin():
        return Response(
            "Forbidden",
            status=403,
            mimetype="text/plain",
        )

    return None


def get_admin_user_id(user):
    try:
        return int(
            user_field(
                user,
                0,
                "user_id",
            )
        )
    except Exception:
        return None


def get_user_subscription_status(user):
    if not user:
        return (
            "Неизвестно",
            "inactive",
            0,
        )

    subscription_until = user_field(
        user,
        4,
        "subscription_until",
        None,
    )

    active = subscription_active(
        subscription_until
    )

    if active:
        return (
            "🟢 Активна",
            "active",
            days_left(
                subscription_until
            ),
        )

    # ВАЖНО:
    # subscription в БД является BOOLEAN.
    # Поэтому не используем значения
    # trial/vip/ixxy для определения активности.

    return (
        "🔴 Истекла",
        "expired",
        0,
    )


def user_name(user):
    first_name = user_field(
        user,
        2,
        "first_name",
        "",
    )

    username = user_field(
        user,
        1,
        "username",
        "",
    )

    if first_name:
        return str(first_name)

    if username:
        return (
            "@"
            + str(username).lstrip("@")
        )

    return "Пользователь"


def admin_user_url(user_id):
    return (
        f"/admin/user/{int(user_id)}"
    )


def get_admin_users():
    func = getattr(
        db,
        "get_all_users",
        None,
    )

    if not func:
        return []

    try:
        result = func()

        if result is None:
            return []

        return list(result)

    except Exception:
        return []


def get_admin_payments():
    # Сначала пытаемся использовать
    # get_payments(), если он существует.
    func = getattr(
        db,
        "get_payments",
        None,
    )

    if func:
        try:
            result = func()

            if result is not None:
                return list(result)

        except Exception:
            pass

    # В твоей database.py может называться
    # get_all_payments().
    func = getattr(
        db,
        "get_all_payments",
        None,
    )

    if not func:
        return []

    try:
        result = func()

        if result is None:
            return []

        return list(result)

    except Exception:
        return []


def get_admin_user_payments(user_id):
    func = getattr(
        db,
        "get_user_payments",
        None,
    )

    if func:
        try:
            result = func(
                int(user_id)
            )

            if result is not None:
                return list(result)

        except Exception:
            pass

    # Fallback:
    # берём все платежи и фильтруем
    # по user_id.
    payments = get_admin_payments()

    result = []

    for payment in payments:
        try:
            payment_user_id = int(
                payment_field(
                    payment,
                    1,
                    "user_id",
                    0,
                )
            )

            if (
                payment_user_id
                == int(user_id)
            ):
                result.append(payment)

        except Exception:
            continue

    return result


def call_database_function(
    name,
    *args,
    **kwargs,
):
    func = getattr(
        db,
        name,
        None,
    )

    if not func:
        raise RuntimeError(
            f"Функция database.{name} "
            f"не найдена"
        )

    return func(
        *args,
        **kwargs,
    )


# ============================================================
# GITHUB
# ============================================================

def github_headers():
    headers = {
        "Accept": (
            "application/vnd.github+json"
        ),
        "X-GitHub-Api-Version":
            "2022-11-28",
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = (
            f"Bearer {GITHUB_TOKEN}"
        )

    return headers


def github_user_url(user_id):
    return (
        "https://raw.githubusercontent.com/"
        f"{GITHUB_OWNER}/"
        f"{GITHUB_REPO}/"
        f"{GITHUB_BRANCH}/"
        f"users/{int(user_id)}.txt"
    )


def github_get_file(user_id):
    url = (
        "https://api.github.com/repos/"
        f"{GITHUB_OWNER}/"
        f"{GITHUB_REPO}/contents/"
        f"users/{int(user_id)}.txt"
        f"?ref={GITHUB_BRANCH}"
    )

    response = requests.get(
        url,
        headers=github_headers(),
        timeout=20,
    )

    if response.status_code == 404:
        return None

    response.raise_for_status()

    return response.json()


def github_save_user(
    user_id,
    content,
):
    if not GITHUB_TOKEN:
        raise RuntimeError(
            "GITHUB_TOKEN не задан"
        )

    path = (
        f"users/{int(user_id)}.txt"
    )

    url = (
        "https://api.github.com/repos/"
        f"{GITHUB_OWNER}/"
        f"{GITHUB_REPO}/contents/"
        f"{path}"
    )

    old_file = github_get_file(
        user_id
    )

    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("ascii")

    payload = {
        "message": (
            f"Update subscription "
            f"for {int(user_id)}"
        ),
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }

    if (
        old_file
        and old_file.get("sha")
    ):
        payload["sha"] = (
            old_file["sha"]
        )

    response = requests.put(
        url,
        headers=github_headers(),
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def github_raw_file(filename):
    """
    Получает актуальный текстовый файл
    напрямую из GitHub.

    Используются:
      servers.txt
      no_servers.txt

    Timestamp в URL нужен для уменьшения
    вероятности получения старого кеша.
    """

    if filename not in (
        "servers.txt",
        "no_servers.txt",
    ):
        raise ValueError(
            "Разрешены только "
            "servers.txt и no_servers.txt"
        )

    url = (
        "https://raw.githubusercontent.com/"
        f"{GITHUB_OWNER}/"
        f"{GITHUB_REPO}/"
        f"{GITHUB_BRANCH}/"
        f"{filename}"
        f"?_={int(time.time())}"
    )

    response = requests.get(
        url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        timeout=30,
    )

    response.raise_for_status()

    return response.text.strip()


def get_servers_files():
    """
    Одновременно получаем оба источника:

    servers.txt     -> активные
    no_servers.txt  -> неактивные
    """

    servers = github_raw_file(
        "servers.txt"
    )

    no_servers = github_raw_file(
        "no_servers.txt"
    )

    return (
        servers,
        no_servers,
    )


# ============================================================
# SUBSCRIPTION CONTENT
# ============================================================

def active_subscription_content(
    user_id,
    subscription_until,
    servers=None,
):
    date_text = format_date(
        subscription_until
    )

    if servers is None:
        try:
            servers = github_raw_file(
                "servers.txt"
            )
        except Exception:
            servers = ""

    content = (
        'id="1obn2u"\n'
        'id="rsz5kg"\n'
        'id="65uefq"\n'
        'id="f66b5v"\n'
        'id="ps27vy"\n'
        '#profile-title: '
        '𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️\n'
        '#profile-update-interval: 1\n'
        '#subscription-userinfo: '
        'upload=0; download=0; total=0\n'
        '#hide-settings: true\n'
        f'#announce: '
        f'🟢 Подписка активна • '
        f'до {date_text} • '
        f'☂️ ixxy VPN\n'
    )

    if servers:
        content += (
            "\n"
            + servers.strip()
            + "\n"
        )

    return content


def inactive_subscription_content(
    no_servers=None,
):
    if no_servers is None:
        try:
            no_servers = github_raw_file(
                "no_servers.txt"
            )
        except Exception:
            no_servers = ""

    content = (
        'id="rp03e1"\n'
        'id="kx1hv9"\n'
        'id="zkoq0g"\n'
        'id="67cogr"\n'
        'id="gdiay7"\n'
        '#profile-title: '
        '𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️\n'
        '#profile-update-interval: 1\n'
        '#subscription-userinfo: '
        'upload=0; download=0; total=0\n'
        '#hide-settings: true\n'
        '#announce: '
        '🔴 Подписка не активна • '
        'Продлите подписку на сайте '
        'ixxy VPN\n'
    )

    if no_servers:
        content += (
            "\n"
            + no_servers.strip()
            + "\n"
        )

    return content


def build_current_content(
    user_id,
    servers=None,
    no_servers=None,
):
    user = db.get_user(
        user_id
    )

    if not user:
        return None

    subscription_until = user_field(
        user,
        4,
        "subscription_until",
        None,
    )

    # ВАЖНО:
    # Реальное состояние определяется
    # только по subscription_until.

    if subscription_active(
        subscription_until
    ):
        return active_subscription_content(
            user_id,
            subscription_until,
            servers=servers,
        )

    return inactive_subscription_content(
        no_servers=no_servers,
    )


# ============================================================
# SAVE SUBSCRIPTION TO DB
# ============================================================

def save_subscription_to_db(
    user_id,
    content,
):
    """
    Сохраняем актуальное содержимое
    также в БД.

    Это важно, потому что /sub/<token>
    сначала может брать content из БД.
    """

    try:
        save_content = getattr(
            db,
            "save_subscription_content",
            None,
        )

        if save_content:
            save_content(
                user_id,
                content,
            )
    except Exception:
        pass

    try:
        save_link = getattr(
            db,
            "save_subscription_link",
            None,
        )

        if save_link:
            save_link(
                user_id,
                github_user_url(
                    user_id
                ),
            )
    except Exception:
        pass


# ============================================================
# SYNC ONE USER
# ============================================================

def sync_subscription(
    user_id,
    servers=None,
    no_servers=None,
):
    """
    Обновляет один users/<ID>.txt.

    Если servers/no_servers переданы,
    повторно GitHub не запрашивается.
    """

    content = build_current_content(
        user_id,
        servers=servers,
        no_servers=no_servers,
    )

    if content is None:
        return False

    try:
        github_save_user(
            user_id,
            content,
        )
    except Exception:
        return False

    save_subscription_to_db(
        user_id,
        content,
    )

    return True


# ============================================================
# SYNC ALL USERS
# ============================================================

def sync_all_subscriptions():
    """
    Главная массовая синхронизация.

    1. Получаем свежий servers.txt.
    2. Получаем свежий no_servers.txt.
    3. Берём всех пользователей из БД.
    4. Активным выдаём servers.txt.
    5. Истёкшим выдаём no_servers.txt.
    6. Обновляем users/<ID>.txt.
    7. Сохраняем content в БД.
    """

    users = get_admin_users()

    total = len(users)

    success = 0
    failed = 0
    active_count = 0
    inactive_count = 0

    errors = []

    # --------------------------------------------------------
    # Загружаем источники ОДИН раз.
    # --------------------------------------------------------

    try:
        servers, no_servers = (
            get_servers_files()
        )

    except Exception as e:
        return {
            "total": total,
            "success": 0,
            "failed": total,
            "active": 0,
            "inactive": 0,
            "errors": [
                "Не удалось получить "
                f"servers.txt/no_servers.txt: "
                f"{e}"
            ],
        }

    # --------------------------------------------------------
    # Обновляем пользователей.
    # --------------------------------------------------------

    for user in users:
        user_id = get_admin_user_id(
            user
        )

        if user_id is None:
            failed += 1

            errors.append(
                "Не удалось определить "
                "Telegram ID пользователя"
            )

            continue

        subscription_until = user_field(
            user,
            4,
            "subscription_until",
            None,
        )

        active = subscription_active(
            subscription_until
        )

        if active:
            active_count += 1
        else:
            inactive_count += 1

        if active:
            content = (
                active_subscription_content(
                    user_id,
                    subscription_until,
                    servers=servers,
                )
            )
        else:
            content = (
                inactive_subscription_content(
                    no_servers=no_servers,
                )
            )

        try:
            github_save_user(
                user_id,
                content,
            )

            save_subscription_to_db(
                user_id,
                content,
            )

            success += 1

        except Exception as e:
            failed += 1

            errors.append(
                f"{user_id}: {e}"
            )

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "active": active_count,
        "inactive": inactive_count,
        "errors": errors,
    }


# ============================================================
# CASHERA
# ============================================================

def cashera_create_payment(
    user_id,
    days,
    amount,
):
    external_id = (
        f"ixxy-{int(user_id)}-"
        f"{days}-"
        f"{secrets.token_hex(8)}"
    )

    payload = {
        "amount": int(
            amount * 100
        ),
        "currency": "RUB",
        "external_id": external_id,
        "description": (
            f"ixxy VPN — {days} дней"
        ),
        "metadata": {
            "user_id": str(user_id),
            "days": str(days),
        },
        "callback_url": (
            f"{PUBLIC_SITE_URL}"
            f"/cashera/webhook"
        ),
        "success_url": (
            f"{PUBLIC_SITE_URL}"
            "/cabinet"
        ),
        "fail_url": (
            f"{PUBLIC_SITE_URL}"
            "/cabinet"
        ),
    }

    headers = {
        "X-Api-Key": CASHERA_API_KEY,
        "Content-Type": (
            "application/json"
        ),
        "Accept": "application/json",
    }

    response = requests.post(
        f"{CASHERA_URL}"
        "/integration/transactions",
        headers=headers,
        json=payload,
        timeout=30,
    )

    try:
        result = response.json()
    except Exception:
        result = {
            "message": response.text
        }

    if not response.ok:
        message = result.get(
            "message",
            "CasheRa error",
        )

        errors = result.get(
            "errors"
        )

        if errors:
            message += (
                f" | {errors}"
            )

        raise RuntimeError(
            f"CasheRa "
            f"{response.status_code}: "
            f"{message}"
        )

    return (
        external_id,
        result,
    )


def extract_payment_url(data):
    if not isinstance(
        data,
        dict,
    ):
        return None

    possible_keys = [
        "payment_url",
        "checkout_url",
        "url",
        "pay_url",
    ]

    for key in possible_keys:
        value = data.get(key)

        if (
            isinstance(value, str)
            and value.startswith("http")
        ):
            return value

    transaction = data.get(
        "transaction"
    )

    if isinstance(
        transaction,
        dict,
    ):
        for key in possible_keys:
            value = transaction.get(key)

            if (
                isinstance(value, str)
                and value.startswith("http")
            ):
                return value

    return None


def verify_cashera_webhook():
    if not CASHERA_API_KEY:
        return False

    api_key = request.headers.get(
        "X-Api-Key",
        "",
    )

    if api_key != CASHERA_API_KEY:
        return False

    if CASHERA_API_SECRET:
        received_secret = (
            request.headers.get(
                "X-Secret",
                "",
            )
        )

        if (
            received_secret
            != CASHERA_API_SECRET
        ):
            return False

    return True


# ============================================================
# AUTH PAGE
# ============================================================

def auth_page(error=None):
    error_html = ""

    if error:
        error_html = f"""
        <div class="error">
            {html.escape(str(error))}
        </div>
        """

    page = f"""
<!doctype html>
<html lang="ru">

<head>

<meta charset="utf-8">

<meta name="viewport"
      content="width=device-width,
      initial-scale=1">

<meta name="theme-color"
      content="#07030d">

<title>ixxy VPN</title>

<style>

* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;
    min-height: 100vh;

    background:
        radial-gradient(
            circle at 50% -10%,
            rgba(145,70,255,.28),
            transparent 38%
        ),
        #07030d;

    color: white;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "SF Pro Display",
        Arial,
        sans-serif;

    display: grid;
    place-items: center;
}}

.card {{
    width: min(92%,470px);
    padding: 38px 25px;

    border-radius: 30px;

    text-align: center;

    background:
        rgba(20,10,32,.78);

    border:
        1px solid
        rgba(180,100,255,.18);

    box-shadow:
        0 30px 100px
        rgba(0,0,0,.55),

        0 0 70px
        rgba(125,50,255,.12);
}}

.logo {{
    font-size: 60px;
    margin-bottom: 12px;
}}

h1 {{
    margin: 0;
    font-size: 38px;
}}

p {{
    color: #a99fb5;
    line-height: 1.5;
}}

form {{
    margin-top: 25px;
}}

input {{
    width: 100%;
    height: 55px;

    padding: 0 17px;

    border-radius: 16px;

    border:
        1px solid
        rgba(255,255,255,.09);

    outline: none;

    background:
        rgba(255,255,255,.045);

    color: white;
    font-size: 15px;
}}

input::placeholder {{
    color: #756c80;
}}

.buttons {{
    display: grid;

    grid-template-columns:
        1fr 1fr;

    gap: 9px;

    margin-top: 10px;
}}

button {{
    height: 53px;

    border: 0;
    border-radius: 16px;

    font-size: 14px;
    font-weight: 850;

    cursor: pointer;
}}

.primary {{
    background:
        linear-gradient(
            135deg,
            #9b5cff,
            #6d2cff
        );

    color: white;
}}

.secondary {{
    background:
        rgba(255,255,255,.06);

    color: white;

    border:
        1px solid
        rgba(255,255,255,.08);
}}

.error {{
    margin-top: 16px;

    padding: 12px;

    border-radius: 14px;

    background:
        rgba(255,70,90,.1);

    color: #ff9aa6;

    font-size: 13px;
}}

.note {{
    margin-top: 20px;

    color: #746b7d;

    font-size: 12px;
}}

</style>

</head>

<body>

<div class="card">

<div class="logo">☂️</div>

<h1>ixxy VPN</h1>

<p>
Введите Telegram ID или username,
чтобы открыть личный кабинет.
</p>

<form method="post">

<input
    type="text"
    name="login"
    autocomplete="off"
    placeholder="Telegram ID или @username"
    required
>

<div class="buttons">

<button
    class="primary"
    type="submit"
    formaction="/login">
    Войти
</button>

<button
    class="secondary"
    type="submit"
    formaction="/register">
    Регистрация
</button>

</div>

</form>

{error_html}

<div class="note">
Например: 123456789 или @username
</div>

</div>

</body>
</html>
"""

    return no_cache(
        Response(
            page,
            mimetype="text/html",
        )
    )


# ============================================================
# INDEX
# ============================================================

@app.route("/")
def index():
    if session.get(
        "user_id"
    ):
        return redirect(
            "/cabinet"
        )

    return auth_page()


# ============================================================
# LOGIN
# ============================================================

@app.post("/login")
def login():
    login_value = request.form.get(
        "login",
        "",
    ).strip()

    if not login_value:
        return auth_page(
            "Введите Telegram ID "
            "или username."
        )

    try:
        user = db.get_user_by_login(
            login_value
        )
    except Exception:
        user = None

    if not user:
        return auth_page(
            "Пользователь не найден. "
            "Если вы хотите создать "
            "аккаунт, нажмите "
            "«Регистрация»."
        )

    try:
        user_id = int(
            user_field(
                user,
                0,
                "user_id",
            )
        )
    except Exception:
        return auth_page(
            "Не удалось определить "
            "Telegram ID."
        )

    session.clear()
    session["user_id"] = user_id

    return redirect(
        "/cabinet"
    )


# ============================================================
# REGISTRATION
# ============================================================

@app.post("/register")
def register():
    login_value = request.form.get(
        "login",
        "",
    ).strip()

    if not login_value:
        return auth_page(
            "Введите Telegram ID "
            "или username."
        )

    try:
        user = db.register_user(
            login_value
        )

    except ValueError as e:
        return auth_page(
            str(e)
        )

    except Exception as e:
        return auth_page(
            f"Ошибка регистрации: {e}"
        )

    if not user:
        return auth_page(
            "Не удалось создать "
            "пользователя."
        )

    try:
        user_id = int(
            user_field(
                user,
                0,
                "user_id",
            )
        )
    except Exception:
        return auth_page(
            "Не удалось определить "
            "Telegram ID."
        )

    session.clear()
    session["user_id"] = user_id

    return redirect(
        "/cabinet"
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():
    session.clear()

    return redirect("/")


# ============================================================
# CABINET
# ============================================================

@app.route("/cabinet")
def cabinet():
    user_id = session.get(
        "user_id"
    )

    if not user_id:
        return redirect("/")

    user = db.get_user(
        user_id
    )

    if not user:
        session.clear()
        return redirect("/")

    username = user_field(
        user,
        1,
        "username",
        "",
    )

    first_name = user_field(
        user,
        2,
        "first_name",
        "",
    )

    subscription = user_field(
        user,
        3,
        "subscription",
        "",
    )

    subscription_until = user_field(
        user,
        4,
        "subscription_until",
        None,
    )

    active = subscription_active(
        subscription_until
    )

    days = days_left(
        subscription_until
    )

    token = make_token(
        user_id
    )

    subscription_url = (
        build_subscription_url(
            token
        )
    )

    happ_url = build_happ_url(
        token
    )

    incy_url = build_incy_url(
        token
    )

    status = (
        "Активна"
        if active
        else "Неактивна"
    )

    status_class = (
        "active"
        if active
        else "inactive"
    )

    days_text = (
        f"{days} дн."
        if active
        else "Завершена"
    )

    tariffs_html = ""

    for tariff_days, price in (
        TARIFFS.items()
    ):
        tariffs_html += f"""
        <a class="tariff"
           href="/buy/{tariff_days}">

            <div>

                <b>
                    {tariff_days} дней
                </b>

                <span>
                    {price} ₽
                </span>

            </div>

            <strong>
                ›
            </strong>

        </a>
        """

    page = f"""
<!doctype html>

<html lang="ru">

<head>

<meta charset="utf-8">

<meta name="viewport"
      content="width=device-width,
      initial-scale=1,
      maximum-scale=1,
      viewport-fit=cover">

<meta name="theme-color"
      content="#07030d">

<title>
ixxy VPN — Кабинет
</title>

<style>

* {{
    box-sizing: border-box;

    -webkit-tap-highlight-color:
        transparent;
}}

body {{
    margin: 0;
    min-height: 100vh;

    background:
        radial-gradient(
            circle at 50% -10%,
            rgba(145,70,255,.25),
            transparent 35%
        ),
        #07030d;

    color: #fff;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "SF Pro Display",
        Arial,
        sans-serif;
}}

.container {{
    width: min(
        calc(100% - 28px),
        620px
    );

    margin: auto;

    padding:
        20px 0
        calc(
            35px
            + env(safe-area-inset-bottom)
        );
}}

.header {{
    display: flex;

    align-items: center;

    justify-content:
        space-between;

    margin-bottom: 28px;
}}

.brand {{
    font-size: 19px;
    font-weight: 850;
}}

.logo {{
    margin-right: 8px;
}}

.logout {{
    color: #88808f;
    text-decoration: none;
    font-size: 12px;
}}

.hero {{
    text-align: center;
    margin-bottom: 22px;
}}

.hero .small {{
    color: #8d8497;
    font-size: 13px;
}}

.hero h1 {{
    font-size: 39px;
    line-height: 1;

    letter-spacing: -2px;

    margin: 9px 0;
}}

.hero p {{
    color: #918899;
    margin: 0;
}}

.card {{
    margin-top: 13px;

    padding: 20px;

    border-radius: 25px;

    background:
        rgba(20,10,32,.72);

    border:
        1px solid
        rgba(180,100,255,.13);

    box-shadow:
        0 20px 65px
        rgba(0,0,0,.28);
}}

.status {{
    display: flex;

    justify-content:
        space-between;

    align-items: center;
}}

.badge {{
    padding: 8px 11px;

    border-radius: 999px;

    font-size: 12px;
    font-weight: 800;
}}

.active {{
    background:
        rgba(90,255,160,.1);

    color: #91ffbd;
}}

.inactive {{
    background:
        rgba(255,80,100,.1);

    color: #ff8997;
}}

.big {{
    margin: 19px 0;

    font-size: 31px;
    font-weight: 900;
}}

.grid {{
    display: grid;

    grid-template-columns:
        1fr 1fr;

    gap: 10px;
}}

.stat {{
    padding: 14px;

    border-radius: 17px;

    background:
        rgba(255,255,255,.035);
}}

.label {{
    color: #746c7e;

    font-size: 10px;

    text-transform:
        uppercase;

    letter-spacing: 1px;
}}

.value {{
    margin-top: 7px;
    font-weight: 800;
}}

.button {{
    display: flex;

    align-items: center;
    justify-content: center;

    min-height: 53px;

    margin-top: 10px;

    border-radius: 17px;

    text-decoration: none;

    font-weight: 850;
}}

.primary {{
    background:
        linear-gradient(
            135deg,
            #9b5cff,
            #6d2cff
        );

    color: white;
}}

.secondary {{
    background:
        rgba(255,255,255,.045);

    color: white;

    border:
        1px solid
        rgba(255,255,255,.08);
}}

.copybox {{
    display: flex;

    gap: 7px;

    margin-top: 12px;

    padding: 6px;

    background: #09050e;

    border-radius: 15px;
}}

.copybox input {{
    flex: 1;

    min-width: 0;

    border: 0;
    outline: 0;

    background: transparent;

    color: #81798a;

    padding: 9px;

    font-size: 11px;
}}

.copy {{
    border: 0;

    border-radius: 11px;

    padding: 0 13px;

    background: white;
    color: black;

    font-weight: 900;
}}

.tariff {{
    display: flex;

    align-items: center;

    justify-content:
        space-between;

    padding: 15px;

    margin-top: 8px;

    border-radius: 16px;

    background:
        rgba(255,255,255,.035);

    color: white;

    text-decoration: none;

    border:
        1px solid
        rgba(255,255,255,.06);
}}

.tariff b {{
    display: block;
}}

.tariff span {{
    display: block;

    color: #9e93aa;

    font-size: 12px;

    margin-top: 4px;
}}

.tariff strong {{
    font-size: 24px;
    color: #9671c7;
}}

.footer {{
    text-align: center;

    color: #57505f;

    font-size: 11px;

    padding: 25px 0;
}}

</style>

</head>

<body>

<div class="container">

<header class="header">

    <div class="brand">
        <span class="logo">
            ☂️
        </span>

        ixxy VPN
    </div>

    <a
        class="logout"
        href="/logout">
        Выйти
    </a>

</header>

<section class="hero">

    <div class="small">
        Личный кабинет
    </div>

    <h1>
        Привет,
        {safe_text(
            first_name,
            "Пользователь"
        )}
    </h1>

    <p>
        Управление вашей подпиской
    </p>

</section>

<section class="card">

    <div class="status">

        <span>
            Состояние подписки
        </span>

        <span
            class="badge {status_class}">
            {status}
        </span>

    </div>

    <div class="big">
        {days_text}
    </div>

    <div class="grid">

        <div class="stat">

            <div class="label">
                Тариф
            </div>

            <div class="value">
                {safe_text(
                    subscription,
                    "ixxy VPN"
                )}
            </div>

        </div>

        <div class="stat">

            <div class="label">
                Действует до
            </div>

            <div class="value">
                {format_date(
                    subscription_until
                )}
            </div>

        </div>

    </div>

</section>

<section class="card">

    <div class="label">
        Подключение
    </div>

    <a
        class="button primary"
        href="{html.escape(
            happ_url,
            quote=True
        )}">
        Подключить через Happ
    </a>

    <a
        class="button secondary"
        href="{html.escape(
            incy_url,
            quote=True
        )}">
        Открыть в INCY
    </a>

</section>

<section class="card">

    <div class="label">
        Моя подписка
    </div>

    <div class="copybox">

        <input
            id="sub"
            readonly
            value="{html.escape(
                subscription_url,
                quote=True
            )}"
        >

        <button
            class="copy"
            onclick="copySub()">
            COPY
        </button>

    </div>

</section>

<section class="card">

    <div class="label">
        Продление
    </div>

    {tariffs_html}

</section>

<section class="card">

    <div class="label">
        Поддержка
    </div>

    <a
        class="button primary"
        href="{html.escape(
            TELEGRAM_URL,
            quote=True
        )}">
        Поддержка Telegram
    </a>

</section>

<div class="footer">
    ixxy VPN
</div>

</div>

<script>

function copySub() {{

    const input =
        document.getElementById("sub");

    navigator.clipboard
        .writeText(input.value)
        .then(() => {{

            alert(
                "Ссылка скопирована"
            );

        }})
        .catch(() => {{

            input.select();

            document.execCommand(
                "copy"
            );

            alert(
                "Ссылка скопирована"
            );

        }});
}}

</script>

</body>
</html>
"""

    return no_cache(
        Response(
            page,
            mimetype="text/html",
        )
    )


# ============================================================
# BUY
# ============================================================

@app.route(
    "/buy/<int:days>"
)
def buy(days):
    user_id = session.get(
        "user_id"
    )

    if not user_id:
        return redirect("/")

    if days not in TARIFFS:
        abort(404)

    if not CASHERA_API_KEY:
        return Response(
            "CASHERA_API_KEY "
            "не настроен",
            status=500,
            mimetype="text/plain",
        )

    amount = TARIFFS[days]

    try:
        external_id, result = (
            cashera_create_payment(
                user_id,
                days,
                amount,
            )
        )

        db.create_payment(
            user_id=user_id,
            amount=amount,
            days=days,
            external_id=external_id,
            status="pending",
        )

        payment_url = (
            extract_payment_url(
                result
            )
        )

        if not payment_url:
            return Response(
                json.dumps(
                    {
                        "error": (
                            "CasheRa не вернула "
                            "ссылку на оплату"
                        ),
                        "response": result,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                status=502,
                mimetype=(
                    "application/json"
                ),
            )

        return redirect(
            payment_url
        )

    except Exception as e:
        return Response(
            "Ошибка создания оплаты: "
            f"{html.escape(str(e))}",
            status=500,
            mimetype="text/plain",
        )


# ============================================================
# CASHERA WEBHOOK
# ============================================================

@app.post(
    "/cashera/webhook"
)
def cashera_webhook():

    if not verify_cashera_webhook():
        return {
            "ok": False,
            "error": "invalid webhook",
        }, 403

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    transaction = data.get(
        "transaction"
    )

    if not isinstance(
        transaction,
        dict,
    ):
        transaction = data

    status = str(
        transaction.get(
            "status",
            "",
        )
    ).lower()

    if status != "paid":
        return {
            "ok": True,
            "ignored": True,
        }

    external_id = (
        transaction.get(
            "external_id"
        )
        or data.get(
            "external_id"
        )
    )

    if not external_id:
        return {
            "ok": False,
            "error": (
                "external_id missing"
            ),
        }, 400

    try:
        if db.payment_processed(
            external_id
        ):
            return {
                "ok": True,
                "duplicate": True,
            }
    except Exception:
        pass

    payment = (
        db.get_payment_by_external_id(
            external_id
        )
    )

    if not payment:
        return {
            "ok": False,
            "error": "payment not found",
        }, 404

    try:
        user_id = int(
            payment_field(
                payment,
                1,
                "user_id",
            )
        )

        days = int(
            payment_field(
                payment,
                3,
                "days",
            )
        )

    except Exception:
        return {
            "ok": False,
            "error": (
                "invalid payment data"
            ),
        }, 500

    try:
        db.extend_subscription(
            user_id,
            days,
        )

        db.mark_payment_paid(
            external_id
        )

        try:
            db.mark_payment_processed(
                external_id
            )
        except Exception:
            pass

        # После оплаты обязательно
        # обновляем GitHub users/<ID>.txt
        # с новым servers.txt.
        sync_subscription(
            user_id
        )

        return {
            "ok": True
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
        }, 500


# ============================================================
# SUBSCRIPTION
# ============================================================

@app.route(
    "/sub/<token>"
)
def subscription(token):
    user_id = parse_token(
        token
    )

    if user_id is None:
        abort(404)

    # Сначала проверяем актуальное
    # состояние пользователя.
    #
    # Если content есть в БД, после нашей
    # синхронизации он уже актуальный.
    try:
        content = (
            db.get_subscription_content(
                user_id
            )
        )
    except Exception:
        content = None

    if not content:
        content = build_current_content(
            user_id
        )

    if not content:
        abort(404)

    response = Response(
        content,
        mimetype="text/plain",
    )

    response.headers[
        "Cache-Control"
    ] = (
        "no-store, no-cache, "
        "must-revalidate, max-age=0"
    )

    response.headers[
        "Pragma"
    ] = "no-cache"

    return response


# ============================================================
# OLD /s/ LINK
# ============================================================

@app.route(
    "/s/<token>"
)
def subscription_page(token):
    user_id = parse_token(
        token
    )

    if user_id is None:
        abort(404)

    return redirect(
        f"/cabinet?user={user_id}"
    )


# ============================================================
# ADMIN CSS
# ============================================================

ADMIN_CSS = """
<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    min-height: 100vh;

    background:
        radial-gradient(
            circle at 50% -10%,
            rgba(145,70,255,.25),
            transparent 35%
        ),
        #07030d;

    color: #fff;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "SF Pro Display",
        Arial,
        sans-serif;
}

a {
    color: inherit;
}

.container {
    width: min(
        calc(100% - 26px),
        900px
    );

    margin: auto;

    padding:
        20px 0 50px;
}

.header {
    display: flex;

    align-items: center;

    justify-content:
        space-between;

    gap: 10px;

    margin-bottom: 20px;
}

.brand {
    font-size: 22px;
    font-weight: 900;
}

.nav {
    display: flex;

    gap: 7px;

    flex-wrap: wrap;
}

.nav a {
    padding: 9px 12px;

    border-radius: 12px;

    background:
        rgba(255,255,255,.05);

    text-decoration: none;

    color: #b6adbf;

    font-size: 12px;
}

.card {
    padding: 18px;

    margin-bottom: 12px;

    border-radius: 22px;

    background:
        rgba(20,10,32,.78);

    border:
        1px solid
        rgba(180,100,255,.13);

    box-shadow:
        0 18px 60px
        rgba(0,0,0,.2);
}

.grid {
    display: grid;

    grid-template-columns:
        repeat(
            auto-fit,
            minmax(150px,1fr)
        );

    gap: 9px;
}

.stat {
    padding: 15px;

    border-radius: 17px;

    background:
        rgba(255,255,255,.035);
}

.stat .num {
    font-size: 26px;

    font-weight: 900;

    margin-top: 6px;
}

.muted {
    color: #82788d;
}

.small {
    font-size: 12px;
}

.search {
    display: flex;

    gap: 8px;
}

input,
select {
    width: 100%;

    height: 48px;

    padding: 0 13px;

    border-radius: 14px;

    border:
        1px solid
        rgba(255,255,255,.09);

    outline: none;

    background:
        rgba(255,255,255,.045);

    color: white;
}

button,
.button {
    min-height: 46px;

    padding: 0 15px;

    border: 0;

    border-radius: 14px;

    background:
        linear-gradient(
            135deg,
            #9b5cff,
            #6d2cff
        );

    color: white;

    font-weight: 850;

    text-decoration: none;

    display: inline-flex;

    align-items: center;

    justify-content: center;

    cursor: pointer;
}

.button.secondary {
    background:
        rgba(255,255,255,.06);

    border:
        1px solid
        rgba(255,255,255,.08);
}

.button.danger {
    background:
        rgba(255,65,85,.13);

    color: #ff9aa6;
}

.user {
    display: flex;

    align-items: center;

    justify-content:
        space-between;

    gap: 12px;

    padding: 14px;

    margin-top: 8px;

    border-radius: 16px;

    background:
        rgba(255,255,255,.035);

    text-decoration: none;
}

.user:hover {
    background:
        rgba(255,255,255,.065);
}

.user-main {
    min-width: 0;
}

.user-name {
    font-weight: 850;
}

.user-id {
    margin-top: 4px;

    color: #766d7e;

    font-size: 11px;
}

.badge {
    white-space: nowrap;

    padding: 7px 10px;

    border-radius: 999px;

    font-size: 11px;

    font-weight: 800;
}

.badge.active {
    color: #91ffbd;

    background:
        rgba(90,255,160,.1);
}

.badge.trial {
    color: #d9a5ff;

    background:
        rgba(160,80,255,.12);
}

.badge.expired {
    color: #ff8997;

    background:
        rgba(255,80,100,.1);
}

.badge.none {
    color: #aaa1ae;

    background:
        rgba(255,255,255,.05);
}

.actions {
    display: flex;

    flex-wrap: wrap;

    gap: 8px;

    margin-top: 10px;
}

.actions form {
    margin: 0;
}

.pagination {
    display: flex;

    gap: 8px;

    justify-content: center;

    margin-top: 16px;
}

table {
    width: 100%;

    border-collapse:
        collapse;
}

td,
th {
    padding: 10px 6px;

    border-bottom:
        1px solid
        rgba(255,255,255,.06);

    text-align: left;

    font-size: 12px;
}

th {
    color: #7d7386;
}

.notice {
    padding: 13px;

    margin-bottom: 12px;

    border-radius: 14px;

    background:
        rgba(90,255,160,.08);

    color: #9dffc1;
}

.error {
    padding: 13px;

    margin-bottom: 12px;

    border-radius: 14px;

    background:
        rgba(255,70,90,.1);

    color: #ff9aa6;
}

.sync-source {
    margin-top: 8px;

    padding: 11px;

    border-radius: 12px;

    background:
        rgba(255,255,255,.035);

    color: #8e8497;

    font-size: 11px;

    word-break: break-all;
}

@media(max-width:600px) {

    .search {
        flex-direction:
            column;
    }

    table {
        font-size: 11px;
    }

    td,
    th {
        padding: 8px 4px;
    }

}

</style>
"""


def admin_page(
    title,
    body,
):
    page = f"""
<!doctype html>

<html lang="ru">

<head>

<meta charset="utf-8">

<meta name="viewport"
      content="width=device-width,
      initial-scale=1">

<title>
ixxy VPN —
{html.escape(title)}
</title>

{ADMIN_CSS}

</head>

<body>

<div class="container">

<div class="header">

    <div class="brand">
        ☂️ ixxy VPN
    </div>

    <div class="nav">

        <a href="/admin">
            📊 Статистика
        </a>

        <a href="/admin/users">
            👥 Пользователи
        </a>

        <a href="/admin/payments">
            💳 Платежи
        </a>

        <a href="/cabinet">
            Кабинет
        </a>

        <a href="/logout">
            Выйти
        </a>

    </div>

</div>

{body}

</div>

</body>
</html>
"""

    return no_cache(
        Response(
            page,
            mimetype="text/html",
        )
    )


# ============================================================
# ADMIN DASHBOARD / STATS
# ============================================================

@app.route("/admin")
def admin():
    denied = require_admin()

    if denied:
        return denied

    users = get_admin_users()
    payments = get_admin_payments()

    total_users = len(users)

    active_users = 0
    trial_users = 0
    expired_users = 0
    none_users = 0
    vip_users = 0

    now = now_utc()

    registrations_today = 0
    registrations_7 = 0
    registrations_30 = 0

    for user in users:

        (
            status,
            status_type,
            _days,
        ) = get_user_subscription_status(
            user
        )

        if status_type == "active":
            active_users += 1

        elif status_type == "trial":
            trial_users += 1

        elif status_type == "expired":
            expired_users += 1

        elif status_type == "none":
            none_users += 1

        # Оставляем статистику VIP,
        # если старые данные её используют.
        subscription = str(
            user_field(
                user,
                3,
                "subscription",
                "",
            )
            or ""
        ).lower()

        if (
            subscription == "vip"
            and status_type == "active"
        ):
            vip_users += 1

        created_at = user_field(
            user,
            11,
            "created_at",
            None,
        )

        created_dt = parse_datetime(
            created_at
        )

        if created_dt:

            age = (
                now - created_dt
            ).total_seconds()

            if age <= 86400:
                registrations_today += 1

            if age <= 7 * 86400:
                registrations_7 += 1

            if age <= 30 * 86400:
                registrations_30 += 1

    payment_total = len(
        payments
    )

    payment_pending = 0
    payment_paid = 0
    payment_failed = 0

    total_days = 0
    total_income = 0

    for payment in payments:

        status = str(
            payment_field(
                payment,
                5,
                "status",
                "",
            )
            or ""
        ).lower()

        if status in (
            "pending",
            "created",
            "waiting",
        ):
            payment_pending += 1

        elif status in (
            "paid",
            "success",
            "successful",
            "completed",
        ):
            payment_paid += 1

        elif status in (
            "failed",
            "cancelled",
            "canceled",
        ):
            payment_failed += 1

        try:
            total_days += int(
                payment_field(
                    payment,
                    3,
                    "days",
                    0,
                )
                or 0
            )
        except Exception:
            pass

        if status in (
            "paid",
            "success",
            "successful",
            "completed",
        ):
            try:
                total_income += int(
                    payment_field(
                        payment,
                        2,
                        "amount",
                        0,
                    )
                    or 0
                )
            except Exception:
                pass

    body = f"""
<h1>
📊 Админ-панель
</h1>

<div class="grid">

<div class="stat">
    <div class="muted small">
        Всего пользователей
    </div>

    <div class="num">
        {total_users}
    </div>
</div>

<div class="stat">
    <div class="muted small">
        🟢 Активные
    </div>

    <div class="num">
        {active_users}
    </div>
</div>

<div class="stat">
    <div class="muted small">
        🎁 Trial
    </div>

    <div class="num">
        {trial_users}
    </div>
</div>

<div class="stat">
    <div class="muted small">
        👑 VIP
    </div>

    <div class="num">
        {vip_users}
    </div>
</div>

<div class="stat">
    <div class="muted small">
        🔴 Истекшие
    </div>

    <div class="num">
        {expired_users}
    </div>
</div>

<div class="stat">
    <div class="muted small">
        ⚪ Без подписки
    </div>

    <div class="num">
        {none_users}
    </div>
</div>

</div>

<div class="card">

<h2>
👥 Регистрации
</h2>

<div class="grid">

<div class="stat">
    Сегодня

    <div class="num">
        {registrations_today}
    </div>
</div>

<div class="stat">
    7 дней

    <div class="num">
        {registrations_7}
    </div>
</div>

<div class="stat">
    30 дней

    <div class="num">
        {registrations_30}
    </div>
</div>

</div>

</div>

<div class="card">

<h2>
💳 Платежи
</h2>

<div class="grid">

<div class="stat">
    Всего

    <div class="num">
        {payment_total}
    </div>
</div>

<div class="stat">
    Успешные

    <div class="num">
        {payment_paid}
    </div>
</div>

<div class="stat">
    Ожидают

    <div class="num">
        {payment_pending}
    </div>
</div>

<div class="stat">
    Ошибки

    <div class="num">
        {payment_failed}
    </div>
</div>

<div class="stat">
    Дней оплачено

    <div class="num">
        {total_days}
    </div>
</div>

<div class="stat">
    Доход

    <div class="num">
        {total_income} ₽
    </div>
</div>

</div>

</div>

<div class="card">

<h2>
🔄 Серверы
</h2>

<p class="muted">
Кнопка ниже заново получает
актуальные servers.txt и
no_servers.txt с GitHub и
обновляет подписки всех
пользователей.
</p>

<div class="actions">

<a
    class="button"
    href="/admin/sync">
    🔄 Обновить серверы
</a>

<a
    class="button secondary"
    href="/admin/users">
    👥 Пользователи
</a>

<a
    class="button secondary"
    href="/admin/payments">
    💳 Платежи
</a>

</div>

</div>

<div class="actions">

<a
    class="button secondary"
    href="/admin">
    🔃 Обновить статистику
</a>

</div>
"""

    return admin_page(
        "Статистика",
        body,
    )


# ============================================================
# ADMIN USERS
# ============================================================

@app.route(
    "/admin/users"
)
def admin_users():
    denied = require_admin()

    if denied:
        return denied

    query = request.args.get(
        "q",
        "",
    ).strip()

    try:
        page_number = max(
            1,
            int(
                request.args.get(
                    "page",
                    "1",
                )
            ),
        )
    except Exception:
        page_number = 1

    users = get_admin_users()

    if query:
        query_lower = (
            query.lower()
        )

        filtered = []

        for user in users:

            user_id = str(
                user_field(
                    user,
                    0,
                    "user_id",
                    "",
                )
            )

            username = str(
                user_field(
                    user,
                    1,
                    "username",
                    "",
                )
            )

            first_name = str(
                user_field(
                    user,
                    2,
                    "first_name",
                    "",
                )
            )

            if (
                query_lower
                in user_id.lower()
                or query_lower
                in username.lower()
                or query_lower
                in first_name.lower()
            ):
                filtered.append(user)

        users = filtered

    per_page = 15

    total_pages = max(
        1,
        (
            len(users)
            + per_page
            - 1
        )
        // per_page,
    )

    if (
        page_number
        > total_pages
    ):
        page_number = total_pages

    start = (
        page_number - 1
    ) * per_page

    current_users = users[
        start:
        start + per_page
    ]

    users_html = ""

    for user in current_users:

        user_id = (
            get_admin_user_id(
                user
            )
        )

        if user_id is None:
            continue

        name = user_name(
            user
        )

        (
            status,
            status_type,
            days,
        ) = (
            get_user_subscription_status(
                user
            )
        )

        if (
            status_type
            == "active"
        ):
            badge_class = "active"

        elif (
            status_type
            == "trial"
        ):
            badge_class = "trial"

        elif (
            status_type
            == "expired"
        ):
            badge_class = "expired"

        else:
            badge_class = "none"

        username = user_field(
            user,
            1,
            "username",
            "",
        )

        username_text = ""

        if username:
            username_text = (
                "@"
                + str(
                    username
                ).lstrip("@")
            )

        users_html += f"""
<a
    class="user"
    href="{admin_user_url(user_id)}">

    <div class="user-main">

        <div class="user-name">
            {safe_text(name)}
        </div>

        <div class="user-id">
            ID: {user_id}

            {
                " • "
                + safe_text(
                    username_text
                )
                if username_text
                else ""
            }
        </div>

    </div>

    <span
        class="badge {badge_class}">

        {html.escape(status)}

        {
            f" • {days}д"
            if days
            else ""
        }

    </span>

</a>
"""

    search_value = html.escape(
        query,
        quote=True,
    )

    pagination_html = ""

    if page_number > 1:
        pagination_html += f"""
<a
    class="button secondary"
    href="/admin/users?q={quote(query)}&page={page_number-1}">
    ← Назад
</a>
"""

    if (
        page_number
        < total_pages
    ):
        pagination_html += f"""
<a
    class="button secondary"
    href="/admin/users?q={quote(query)}&page={page_number+1}">
    Далее →
</a>
"""

    body = f"""
<h1>
👥 Пользователи
</h1>

<div class="card">

<form
    class="search"
    method="get"
    action="/admin/users">

    <input
        name="q"
        value="{search_value}"
        placeholder="ID, username или имя"
    >

    <button type="submit">
        🔎 Найти
    </button>

</form>

</div>

<div class="card">

<div class="muted small">
    Найдено: {len(users)}
</div>

{users_html}

<div class="pagination">

{pagination_html}

</div>

</div>
"""

    return admin_page(
        "Пользователи",
        body,
    )


# ============================================================
# ADMIN USER PROFILE
# ============================================================

@app.route(
    "/admin/user/<int:user_id>"
)
def admin_user_profile(
    user_id
):
    denied = require_admin()

    if denied:
        return denied

    user = db.get_user(
        user_id
    )

    if not user:
        return admin_page(
            "Ошибка",
            """
            <div class="error">
                Пользователь не найден.
            </div>
            """,
        )

    (
        status,
        status_type,
        days,
    ) = (
        get_user_subscription_status(
            user
        )
    )

    subscription_until = (
        user_field(
            user,
            4,
            "subscription_until",
            None,
        )
    )

    username = user_field(
        user,
        1,
        "username",
        "",
    )

    first_name = user_field(
        user,
        2,
        "first_name",
        "",
    )

    subscription = user_field(
        user,
        3,
        "subscription",
        "",
    )

    token = make_token(
        user_id
    )

    subscription_url = (
        build_subscription_url(
            token
        )
    )

    payments = (
        get_admin_user_payments(
            user_id
        )
    )

    payments_html = ""

    for payment in payments:

        payment_id = (
            payment_field(
                payment,
                0,
                "id",
                "—",
            )
        )

        amount = (
            payment_field(
                payment,
                2,
                "amount",
                "—",
            )
        )

        days_paid = (
            payment_field(
                payment,
                3,
                "days",
                "—",
            )
        )

        payment_status = (
            payment_field(
                payment,
                5,
                "status",
                "—",
            )
        )

        created_at = (
            payment_field(
                payment,
                6,
                "created_at",
                None,
            )
        )

        payments_html += f"""
<tr>

<td>
{safe_text(payment_id)}
</td>

<td>
{safe_text(amount)} ₽
</td>

<td>
{safe_text(days_paid)}
</td>

<td>
{safe_text(payment_status)}
</td>

<td>
{format_datetime(created_at)}
</td>

</tr>
"""

    if not payments_html:
        payments_html = """
<tr>

<td colspan="5">

<span class="muted">
Платежей нет
</span>

</td>

</tr>
"""

    safe_subscription_url = (
        html.escape(
            subscription_url,
            quote=True,
        )
    )

    body = f"""
<h1>
👤 Пользователь
</h1>

<div class="card">

<div class="grid">

<div class="stat">

    <div class="muted small">
        Telegram ID
    </div>

    <div class="num">
        {user_id}
    </div>

</div>

<div class="stat">

    <div class="muted small">
        Статус
    </div>

    <div class="num">
        {html.escape(status)}
    </div>

</div>

<div class="stat">

    <div class="muted small">
        Осталось
    </div>

    <div class="num">
        {days} дн.
    </div>

</div>

<div class="stat">

    <div class="muted small">
        До
    </div>

    <div class="num">
        {format_date(
            subscription_until
        )}
    </div>

</div>

</div>

</div>

<div class="card">

<h2>
{safe_text(
    first_name,
    "Пользователь"
)}
</h2>

<p class="muted">
Username:
{safe_text(username)}
</p>

<p class="muted">
Тариф:
{safe_text(subscription)}
</p>

<div
    class="copybox"
    style="
        display:flex;
        gap:7px;
        padding:6px;
        background:#09050e;
        border-radius:15px;
    ">

<input
    style="
        flex:1;
        min-width:0;
        background:transparent;
        border:0;
        color:#aaa;
    "

    readonly

    value="{safe_subscription_url}"
>

</div>

<div class="actions">

<a
    class="button"
    href="{safe_subscription_url}">
    🔗 Открыть подписку
</a>

<a
    class="button secondary"
    href="/admin/user/{user_id}/extend">
    ⏳ Продлить
</a>

<a
    class="button secondary"
    href="/admin/user/{user_id}/disable">
    ❌ Отключить
</a>

<a
    class="button secondary"
    href="/admin/users">
    ← Пользователи
</a>

</div>

</div>

<div class="card">

<h2>
💳 Платежи пользователя
</h2>

<table>

<thead>

<tr>
<th>ID</th>
<th>Сумма</th>
<th>Дни</th>
<th>Статус</th>
<th>Дата</th>
</tr>

</thead>

<tbody>

{payments_html}

</tbody>

</table>

</div>
"""

    return admin_page(
        f"Пользователь {user_id}",
        body,
    )


# ============================================================
# ADMIN EXTEND
# ============================================================

@app.route(
    "/admin/user/<int:user_id>/extend",
    methods=[
        "GET",
        "POST",
    ],
)
def admin_extend(
    user_id
):
    denied = require_admin()

    if denied:
        return denied

    user = db.get_user(
        user_id
    )

    if not user:
        return admin_page(
            "Ошибка",
            """
            <div class="error">
                Пользователь не найден.
            </div>
            """,
        )

    error = ""

    if request.method == "POST":

        raw_days = request.form.get(
            "days",
            "",
        ).strip()

        try:
            days = int(
                raw_days
            )

            if days <= 0:
                raise ValueError

            if days > 999999999:
                raise ValueError

            db.extend_subscription(
                user_id,
                days,
            )

            # После ручного продления
            # обновляем его GitHub-файл.
            sync_subscription(
                user_id
            )

            return redirect(
                f"/admin/user/{user_id}"
            )

        except Exception as e:
            error = str(e)

    error_html = ""

    if error:
        error_html = f"""
        <div class="error">
            Ошибка:
            {html.escape(error)}
        </div>
        """

    body = f"""
<h1>
⏳ Продление подписки
</h1>

{error_html}

<div class="card">

<p>
Пользователь:
<b>{user_id}</b>
</p>

<div class="actions">

<form method="post">

<input
    type="hidden"
    name="days"
    value="30">

<button>
+30 дней
</button>

</form>

<form method="post">

<input
    type="hidden"
    name="days"
    value="90">

<button>
+90 дней
</button>

</form>

<form method="post">

<input
    type="hidden"
    name="days"
    value="180">

<button>
+180 дней
</button>

</form>

<form method="post">

<input
    type="hidden"
    name="days"
    value="365">

<button>
+365 дней
</button>

</form>

</div>

</div>

<div class="card">

<h2>
✏️ Свой срок
</h2>

<form method="post">

<input
    type="number"
    name="days"
    min="1"
    max="999999999"
    placeholder="Количество дней"
    required
>

<div class="actions">

<button type="submit">
Продлить
</button>

<a
    class="button secondary"
    href="/admin/user/{user_id}">
    Отмена
</a>

</div>

</form>

</div>
"""

    return admin_page(
        "Продление",
        body,
    )


# ============================================================
# ADMIN DISABLE
# ============================================================

@app.route(
    "/admin/user/<int:user_id>/disable",
    methods=[
        "GET",
        "POST",
    ],
)
def admin_disable(
    user_id
):
    denied = require_admin()

    if denied:
        return denied

    user = db.get_user(
        user_id
    )

    if not user:
        return admin_page(
            "Ошибка",
            """
            <div class="error">
                Пользователь не найден.
            </div>
            """,
        )

    if request.method == "POST":

        try:

            # Сначала пробуем старое имя.
            disable_func = getattr(
                db,
                "disable_subscription",
                None,
            )

            # В твоей текущей database.py
            # функция может называться
            # deactivate_subscription.
            if not disable_func:
                disable_func = getattr(
                    db,
                    "deactivate_subscription",
                    None,
                )

            if not disable_func:
                raise RuntimeError(
                    "В database.py нет "
                    "disable_subscription() "
                    "или "
                    "deactivate_subscription()"
                )

            disable_func(
                user_id
            )

            sync_subscription(
                user_id
            )

            return redirect(
                f"/admin/user/{user_id}"
            )

        except Exception as e:

            return admin_page(
                "Ошибка",
                f"""
                <div class="error">
                    {html.escape(
                        str(e)
                    )}
                </div>
                """,
            )

    body = f"""
<h1>
❌ Отключение подписки
</h1>

<div class="card">

<p>
Вы действительно хотите отключить
подписку пользователя
<b>{user_id}</b>?
</p>

<div class="actions">

<form method="post">

<button
    class="button danger"
    type="submit">

    Да, отключить

</button>

</form>

<a
    class="button secondary"
    href="/admin/user/{user_id}">

    Отмена

</a>

</div>

</div>
"""

    return admin_page(
        "Отключение",
        body,
    )


# ============================================================
# ADMIN PAYMENTS
# ============================================================

@app.route(
    "/admin/payments"
)
def admin_payments():
    denied = require_admin()

    if denied:
        return denied

    payments = (
        get_admin_payments()
    )

    rows = ""

    for payment in reversed(
        payments[-100:]
    ):

        payment_id = (
            payment_field(
                payment,
                0,
                "id",
                "—",
            )
        )

        user_id = (
            payment_field(
                payment,
                1,
                "user_id",
                "—",
            )
        )

        amount = (
            payment_field(
                payment,
                2,
                "amount",
                "—",
            )
        )

        days = (
            payment_field(
                payment,
                3,
                "days",
                "—",
            )
        )

        status = (
            payment_field(
                payment,
                5,
                "status",
                "—",
            )
        )

        created_at = (
            payment_field(
                payment,
                6,
                "created_at",
                None,
            )
        )

        safe_user_id = html.escape(
            str(user_id)
        )

        rows += f"""
<tr>

<td>
{safe_text(payment_id)}
</td>

<td>

<a
    href="/admin/user/{safe_user_id}">
    {safe_text(user_id)}
</a>

</td>

<td>
{safe_text(amount)} ₽
</td>

<td>
{safe_text(days)}
</td>

<td>
{safe_text(status)}
</td>

<td>
{format_datetime(created_at)}
</td>

</tr>
"""

    if not rows:
        rows = """
<tr>

<td colspan="6">

<span class="muted">
Платежей пока нет.
</span>

</td>

</tr>
"""

    body = f"""
<h1>
💳 Платежи
</h1>

<div class="card">

<table>

<thead>

<tr>
<th>ID</th>
<th>Пользователь</th>
<th>Сумма</th>
<th>Дни</th>
<th>Статус</th>
<th>Дата</th>
</tr>

</thead>

<tbody>

{rows}

</tbody>

</table>

</div>
"""

    return admin_page(
        "Платежи",
        body,
    )


# ============================================================
# ADMIN SYNC
# ============================================================

@app.route(
    "/admin/sync"
)
def admin_sync():
    denied = require_admin()

    if denied:
        return denied

    # ========================================================
    # ГЛАВНОЕ ИЗМЕНЕНИЕ
    # ========================================================
    #
    # Здесь больше НЕ вызывается sync_subscription()
    # отдельно для каждого пользователя.
    #
    # Вместо этого:
    #
    # 1. Загружается актуальный servers.txt.
    # 2. Загружается актуальный no_servers.txt.
    # 3. Все пользователи получают правильный файл.
    #
    # Активные:
    #   users/<ID>.txt = servers.txt
    #
    # Истёкшие:
    #   users/<ID>.txt = no_servers.txt
    #
    # URL пользователя при этом НЕ меняется.
    # ========================================================

    result = (
        sync_all_subscriptions()
    )

    total = result.get(
        "total",
        0,
    )

    success = result.get(
        "success",
        0,
    )

    failed = result.get(
        "failed",
        0,
    )

    active_count = result.get(
        "active",
        0,
    )

    inactive_count = result.get(
        "inactive",
        0,
    )

    errors = result.get(
        "errors",
        [],
    )

    if failed == 0:
        notice = """
        <div class="notice">
            ✅ Все подписки успешно
            синхронизированы.
        </div>
        """
    else:
        notice = f"""
        <div class="error">
            ⚠️ Синхронизация завершена
            с ошибками.
            Ошибок: {failed}
        </div>
        """

    errors_html = ""

    if errors:

        shown_errors = errors[:30]

        error_items = ""

        for error in shown_errors:
            error_items += (
                "<li>"
                + html.escape(
                    str(error)
                )
                + "</li>"
            )

        more = ""

        if len(errors) > 30:
            more = (
                f"<li>И ещё "
                f"{len(errors) - 30} "
                f"ошибок...</li>"
            )

        errors_html = f"""
<div class="card">

<h2>
⚠️ Ошибки
</h2>

<ul>
{error_items}
{more}
</ul>

</div>
"""

    body = f"""
<h1>
🔄 Синхронизация серверов
</h1>

{notice}

<div class="card">

<div class="grid">

<div class="stat">

    <div class="muted small">
        Всего пользователей
    </div>

    <div class="num">
        {total}
    </div>

</div>

<div class="stat">

    <div class="muted small">
        🟢 Активных
    </div>

    <div class="num">
        {active_count}
    </div>

</div>

<div class="stat">

    <div class="muted small">
        🔴 Неактивных
    </div>

    <div class="num">
        {inactive_count}
    </div>

</div>

<div class="stat">

    <div class="muted small">
        ✅ Обновлено
    </div>

    <div class="num">
        {success}
    </div>

</div>

<div class="stat">

    <div class="muted small">
        ❌ Ошибок
    </div>

    <div class="num">
        {failed}
    </div>

</div>

</div>

</div>

<div class="card">

<h2>
📡 Источники
</h2>

<div class="sync-source">
https://raw.githubusercontent.com/
{html.escape(GITHUB_OWNER)}/
{html.escape(GITHUB_REPO)}/
{html.escape(GITHUB_BRANCH)}/
servers.txt
</div>

<div class="sync-source">
https://raw.githubusercontent.com/
{html.escape(GITHUB_OWNER)}/
{html.escape(GITHUB_REPO)}/
{html.escape(GITHUB_BRANCH)}/
no_servers.txt
</div>

<p class="muted small">
Активные пользователи получают
servers.txt.
Истёкшие и неактивные —
no_servers.txt.
</p>

</div>

{errors_html}

<div class="actions">

<a
    class="button"
    href="/admin">
    ← Админка
</a>

<a
    class="button secondary"
    href="/admin/sync">
    🔄 Повторить
</a>

<a
    class="button secondary"
    href="/admin/users">
    👥 Пользователи
</a>

</div>
"""

    return admin_page(
        "Синхронизация",
        body,
    )


# ============================================================
# HEALTH
# ============================================================

@app.route(
    "/health"
)
def health():
    response = Response(
        '{"service":"ixxyweb","status":"ok"}',
        mimetype="application/json",
    )

    return no_cache(
        response
    )


# ============================================================
# 404
# ============================================================

@app.errorhandler(404)
def not_found(error):
    return Response(
        "Not Found",
        status=404,
        mimetype="text/plain",
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "10000",
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
    )