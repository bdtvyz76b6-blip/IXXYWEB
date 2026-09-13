import os
import html
import json
import secrets
from datetime import datetime, timezone
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

from database import (
    get_user,
    get_user_by_login,
    register_user,
    get_subscription_content,
    get_subscription_link,
    extend_subscription,
    create_payment,
    get_payment_by_external_id,
    mark_payment_paid,
    payment_processed,
    mark_payment_processed,
    get_stats,
)

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

    if not token.startswith(SUBSCRIPTION_PREFIX):
        return None

    raw = token[len(SUBSCRIPTION_PREFIX):]

    if not raw.isdigit():
        return None

    try:
        return int(raw)
    except Exception:
        return None


def make_token(user_id):
    return f"{SUBSCRIPTION_PREFIX}{int(user_id)}"


def build_subscription_url(token):
    return (
        f"{PUBLIC_SITE_URL}/sub/"
        f"{quote(token, safe='')}"
    )


def build_happ_url(token):
    subscription_url = build_subscription_url(token)

    return (
        "https://happ.vpnbypass.click/"
        "?url="
        + quote(subscription_url, safe="")
    )


def build_incy_url(token):
    subscription_url = build_subscription_url(token)

    return (
        "incy://add/"
        + quote(subscription_url, safe="")
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
                str(value).replace("Z", "+00:00")
            )
        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

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

    return max(1, int(seconds / 86400))


def format_date(value):
    dt = parse_datetime(value)

    if not dt:
        return "—"

    return dt.strftime("%d.%m.%Y")


def safe_text(value, default="—"):
    if value is None:
        return default

    value = str(value).strip()

    if not value:
        return default

    return html.escape(value)


def no_cache(response):
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return response


# ============================================================
# GITHUB
# ============================================================

def github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = (
            f"Bearer {GITHUB_TOKEN}"
        )

    return headers


def github_user_url(user_id):
    return (
        f"https://raw.githubusercontent.com/"
        f"{GITHUB_OWNER}/"
        f"{GITHUB_REPO}/"
        f"{GITHUB_BRANCH}/"
        f"users/{int(user_id)}.txt"
    )


def github_get_file(user_id):
    url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/contents/"
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


def github_save_user(user_id, content):
    if not GITHUB_TOKEN:
        raise RuntimeError(
            "GITHUB_TOKEN не задан"
        )

    path = (
        f"users/{int(user_id)}.txt"
    )

    url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/contents/"
        f"{path}"
    )

    old_file = github_get_file(user_id)

    import base64

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

    if old_file and old_file.get("sha"):
        payload["sha"] = old_file["sha"]

    response = requests.put(
        url,
        headers=github_headers(),
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# SUBSCRIPTION CONTENT
# ============================================================

def active_subscription_content(
    user_id,
    subscription_until,
):
    date_text = format_date(
        subscription_until
    )

    try:
        url = (
            f"https://raw.githubusercontent.com/"
            f"{GITHUB_OWNER}/"
            f"{GITHUB_REPO}/"
            f"{GITHUB_BRANCH}/"
            f"servers.txt"
        )

        response = requests.get(
            url,
            timeout=20,
        )

        response.raise_for_status()

        servers = response.text.strip()

    except Exception:
        servers = ""

    content = (
        'id="1obn2u"\n'
        'id="rsz5kg"\n'
        'id="65uefq"\n'
        'id="f66b5v"\n'
        'id="ps27vy"\n'
        '#profile-title: 𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️\n'
        '#profile-update-interval: 1\n'
        '#subscription-userinfo: '
        'upload=0; download=0; total=0\n'
        '#hide-settings: true\n'
        f'#announce: 🟢 Подписка активна • '
        f'до {date_text} • ☂️ ixxy VPN\n'
    )

    if servers:
        content += "\n" + servers + "\n"

    return content


def inactive_subscription_content():
    return (
        'id="rp03e1"\n'
        'id="kx1hv9"\n'
        'id="zkoq0g"\n'
        'id="67cogr"\n'
        'id="gdiay7"\n'
        '#profile-title: 𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️\n'
        '#profile-update-interval: 1\n'
        '#subscription-userinfo: '
        'upload=0; download=0; total=0\n'
        '#hide-settings: true\n'
        '#announce: 🔴 Подписка не активна • '
        'Продлите подписку на сайте ixxy VPN\n'
    )


def build_current_content(user_id):
    user = get_user(user_id)

    if not user:
        return None

    try:
        subscription_until = user[4]
    except Exception:
        subscription_until = None

    if subscription_active(subscription_until):
        return active_subscription_content(
            user_id,
            subscription_until,
        )

    return inactive_subscription_content()


# ============================================================
# SYNC
# ============================================================

def sync_subscription(user_id):
    content = build_current_content(user_id)

    if content is None:
        return False

    try:
        github_save_user(
            user_id,
            content,
        )
    except Exception:
        pass

    return True


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
        "amount": int(amount * 100),
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
            f"{PUBLIC_SITE_URL}/cashera/webhook"
        ),
        "success_url": (
            f"{PUBLIC_SITE_URL}/cabinet"
        ),
        "fail_url": (
            f"{PUBLIC_SITE_URL}/cabinet"
        ),
    }

    headers = {
        "X-Api-Key": CASHERA_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    response = requests.post(
        f"{CASHERA_URL}/integration/transactions",
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
            f"CasheRa {response.status_code}: "
            f"{message}"
        )

    return external_id, result


def extract_payment_url(data):
    if not isinstance(data, dict):
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

    if isinstance(transaction, dict):
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
        received_secret = request.headers.get(
            "X-Secret",
            "",
        )

        if received_secret != CASHERA_API_SECRET:
            return False

    return True


# ============================================================
# LOGIN / REGISTRATION PAGE
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
      content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#07030d">

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
            rgba(145, 70, 255, .28),
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
    width: min(92%, 470px);
    padding: 38px 25px;
    border-radius: 30px;
    text-align: center;
    background: rgba(20, 10, 32, .78);
    border: 1px solid rgba(180, 100, 255, .18);
    box-shadow:
        0 30px 100px rgba(0, 0, 0, .55),
        0 0 70px rgba(125, 50, 255, .12);
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
    border: 1px solid rgba(255,255,255,.09);
    outline: none;
    background: rgba(255,255,255,.045);
    color: white;
    font-size: 15px;
}}

input::placeholder {{
    color: #756c80;
}}

.buttons {{
    display: grid;
    grid-template-columns: 1fr 1fr;
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
    background: linear-gradient(
        135deg,
        #9b5cff,
        #6d2cff
    );
    color: white;
}}

.secondary {{
    background: rgba(255,255,255,.06);
    color: white;
    border: 1px solid rgba(255,255,255,.08);
}}

.error {{
    margin-top: 16px;
    padding: 12px;
    border-radius: 14px;
    background: rgba(255,70,90,.1);
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
    if session.get("user_id"):
        return redirect("/cabinet")

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
            "Введите Telegram ID или username."
        )

    try:
        user = get_user_by_login(
            login_value
        )
    except Exception:
        user = None

    if not user:
        return auth_page(
            "Пользователь не найден. "
            "Если вы хотите создать аккаунт, "
            "нажмите «Регистрация»."
        )

    try:
        user_id = int(
            user["user_id"]
            if isinstance(user, dict)
            else user[0]
        )
    except Exception:
        return auth_page(
            "Не удалось определить Telegram ID."
        )

    session.clear()
    session["user_id"] = user_id

    return redirect("/cabinet")


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
            "Введите Telegram ID или username."
        )

    try:
        user = register_user(
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
            "Не удалось создать пользователя."
        )

    try:
        user_id = int(
            user["user_id"]
            if isinstance(user, dict)
            else user[0]
        )
    except Exception:
        return auth_page(
            "Не удалось определить Telegram ID."
        )

    session.clear()
    session["user_id"] = user_id

    return redirect("/cabinet")


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
    user_id = session.get("user_id")

    if not user_id:
        return redirect("/")

    user = get_user(user_id)

    if not user:
        session.clear()
        return redirect("/")

    username = (
        user[1]
        if len(user) > 1
        else ""
    )

    first_name = (
        user[2]
        if len(user) > 2
        else ""
    )

    subscription = (
        user[3]
        if len(user) > 3
        else ""
    )

    subscription_until = (
        user[4]
        if len(user) > 4
        else None
    )

    active = subscription_active(
        subscription_until
    )

    days = days_left(
        subscription_until
    )

    token = make_token(user_id)

    subscription_url = build_subscription_url(
        token
    )

    happ_url = build_happ_url(token)
    incy_url = build_incy_url(token)

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

    for tariff_days, price in TARIFFS.items():
        tariffs_html += f"""
        <a class="tariff"
           href="/buy/{tariff_days}">
            <div>
                <b>{tariff_days} дней</b>
                <span>{price} ₽</span>
            </div>
            <strong>›</strong>
        </a>
        """

    page = f"""
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1,
      maximum-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#07030d">

<title>ixxy VPN — Кабинет</title>

<style>
* {{
    box-sizing: border-box;
    -webkit-tap-highlight-color: transparent;
}}

body {{
    margin: 0;
    min-height: 100vh;
    background:
        radial-gradient(
            circle at 50% -10%,
            rgba(145, 70, 255, .25),
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
        calc(35px + env(safe-area-inset-bottom));
}}

.header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
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
    background: rgba(20, 10, 32, .72);
    border: 1px solid rgba(180, 100, 255, .13);
    box-shadow: 0 20px 65px rgba(0,0,0,.28);
}}

.status {{
    display: flex;
    justify-content: space-between;
    align-items: center;
}}

.badge {{
    padding: 8px 11px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 800;
}}

.active {{
    background: rgba(90, 255, 160, .1);
    color: #91ffbd;
}}

.inactive {{
    background: rgba(255, 80, 100, .1);
    color: #ff8997;
}}

.big {{
    margin: 19px 0;
    font-size: 31px;
    font-weight: 900;
}}

.grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
}}

.stat {{
    padding: 14px;
    border-radius: 17px;
    background: rgba(255,255,255,.035);
}}

.label {{
    color: #746c7e;
    font-size: 10px;
    text-transform: uppercase;
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
    background: linear-gradient(
        135deg,
        #9b5cff,
        #6d2cff
    );
    color: white;
    box-shadow:
        0 15px 40px
        rgba(120,50,255,.22);
}}

.secondary {{
    background: rgba(255,255,255,.045);
    color: white;
    border: 1px solid rgba(255,255,255,.08);
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
    justify-content: space-between;
    padding: 15px;
    margin-top: 8px;
    border-radius: 16px;
    background: rgba(255,255,255,.035);
    color: white;
    text-decoration: none;
    border: 1px solid rgba(255,255,255,.06);
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

.support {{
    color: #9c7bca;
    text-decoration: none;
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
        <span class="logo">☂️</span>
        ixxy VPN
    </div>

    <a class="logout" href="/logout">
        Выйти
    </a>

</header>

<section class="hero">

    <div class="small">
        Личный кабинет
    </div>

    <h1>
        Привет,
        {safe_text(first_name, "Пользователь")}
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

        <span class="badge {status_class}">
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
                {safe_text(subscription, "ixxy VPN")}
            </div>

        </div>

        <div class="stat">

            <div class="label">
                Действует до
            </div>

            <div class="value">
                {format_date(subscription_until)}
            </div>

        </div>

    </div>

</section>

<section class="card">

    <div class="label">
        Подключение
    </div>

    <a class="button primary"
       href="{html.escape(happ_url, quote=True)}">
        Подключить через Happ
    </a>

    <a class="button secondary"
       href="{html.escape(incy_url, quote=True)}">
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
            value="{html.escape(subscription_url, quote=True)}"
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
        href="{html.escape(TELEGRAM_URL, quote=True)}">
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
            alert("Ссылка скопирована");
        }})
        .catch(() => {{
            input.select();
            document.execCommand("copy");
            alert("Ссылка скопирована");
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

@app.route("/buy/<int:days>")
def buy(days):
    user_id = session.get("user_id")

    if not user_id:
        return redirect("/")

    if days not in TARIFFS:
        abort(404)

    if not CASHERA_API_KEY:
        return Response(
            "CASHERA_API_KEY не настроен",
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

        create_payment(
            user_id=user_id,
            amount=amount,
            days=days,
            external_id=external_id,
            status="pending",
        )

        payment_url = extract_payment_url(
            result
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
                mimetype="application/json",
            )

        return redirect(payment_url)

    except Exception as e:
        return Response(
            f"Ошибка создания оплаты: "
            f"{html.escape(str(e))}",
            status=500,
            mimetype="text/plain",
        )


# ============================================================
# CASHERA WEBHOOK
# ============================================================

@app.post("/cashera/webhook")
def cashera_webhook():

    if not verify_cashera_webhook():
        return {
            "ok": False,
            "error": "invalid webhook",
        }, 403

    data = request.get_json(
        silent=True
    ) or {}

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
            ""
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
        or data.get("external_id")
    )

    if not external_id:
        return {
            "ok": False,
            "error": "external_id missing",
        }, 400

    if payment_processed(
        external_id
    ):
        return {
            "ok": True,
            "duplicate": True,
        }

    payment = get_payment_by_external_id(
        external_id
    )

    if not payment:
        return {
            "ok": False,
            "error": "payment not found",
        }, 404

    try:
        if isinstance(payment, dict):
            user_id = int(
                payment["user_id"]
            )
            days = int(
                payment["days"]
            )
        else:
            user_id = int(
                payment[1]
            )
            days = int(
                payment[3]
            )
    except Exception:
        return {
            "ok": False,
            "error": "invalid payment data",
        }, 500

    try:
        extend_subscription(
            user_id,
            days,
        )

        mark_payment_paid(
            external_id
        )

        mark_payment_processed(
            external_id
        )

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
# SUBSCRIPTION URL
# ============================================================

@app.route("/sub/<token>")
def subscription(token):
    user_id = parse_token(token)

    if user_id is None:
        abort(404)

    try:
        content = get_subscription_content(
            user_id
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

    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )

    return response


# ============================================================
# OLD /s/ LINK
# ============================================================

@app.route("/s/<token>")
def subscription_page(token):
    user_id = parse_token(token)

    if user_id is None:
        abort(404)

    return redirect(
        f"/cabinet?user={user_id}"
    )


# ============================================================
# ADMIN
# ============================================================

def is_admin():
    # Админ-панель доступна всем
    # авторизованным пользователям.
    return True


@app.route("/admin")
def admin():
    if not is_admin():
        return Response(
            "Forbidden",
            status=403,
        )

    try:
        stats = get_stats()
    except Exception:
        stats = {}

    page = f"""
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">
<title>ixxy VPN — Admin</title>

<style>
body {{
    margin: 0;
    background: #08050d;
    color: white;
    font-family: Arial, sans-serif;
}}

main {{
    width: min(92%, 700px);
    margin: 30px auto;
}}

.card {{
    padding: 20px;
    margin-bottom: 12px;
    border-radius: 20px;
    background: #17111f;
    border: 1px solid #2a1d38;
}}

h1 {{
    margin-top: 0;
}}

.stat {{
    font-size: 30px;
    font-weight: 900;
}}

.muted {{
    color: #918799;
}}
</style>
</head>

<body>

<main>

<h1>☂️ ixxy VPN</h1>

<div class="card">

    <div class="muted">
        Статистика пользователей
    </div>

    <div class="stat">
        {html.escape(str(stats))}
    </div>

</div>

<div class="card">
    Админ-панель сайта работает отдельно
    от Telegram-бота.
</div>

</main>

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
# HEALTH
# ============================================================

@app.route("/health")
def health():
    response = Response(
        '{"service":"ixxyweb","status":"ok"}',
        mimetype="application/json",
    )

    return no_cache(response)


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