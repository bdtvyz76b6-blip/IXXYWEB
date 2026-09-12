import base64
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from flask import Flask, Response, redirect, request, session
from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)

from database import (
    create_payment,
    create_site_user,
    get_user,
    get_user_by_email,
    process_paid_payment,
    save_subscription,
    subscription_active,
    use_promocode,
    use_trial,
)

load_dotenv()


# ============================================================
# CONFIG
# ============================================================

app = Flask(__name__)

app.secret_key = os.getenv(
    "SECRET_KEY",
    secrets.token_hex(32)
)

PUBLIC_SITE_URL = os.getenv(
    "PUBLIC_SITE_URL",
    "http://localhost:10000"
).rstrip("/")

SUBSCRIPTION_PREFIX = os.getenv(
    "SUBSCRIPTION_PREFIX",
    "2ix847xy"
)

# GitHub
GITHUB_TOKEN = os.getenv(
    "GITHUB_TOKEN",
    ""
)

GITHUB_OWNER = os.getenv(
    "GITHUB_OWNER",
    "bdtvyz76b6-blip"
)

GITHUB_REPO = os.getenv(
    "GITHUB_REPO",
    "vpn-sub"
)

GITHUB_BRANCH = os.getenv(
    "GITHUB_BRANCH",
    "main"
)

GITHUB_SERVERS_FILE = os.getenv(
    "GITHUB_SERVERS_FILE",
    "servers.txt"
)

# CasheRa
CASHERA_API_KEY = os.getenv(
    "CASHERA_API_KEY",
    ""
)

CASHERA_URL = (
    "https://api.cashera.cash/api/v1/"
    "integration/transactions"
)

# Тарифы
TARIFFS = {
    30: 129,
    90: 379,
    180: 659,
    365: 1089,
}


# ============================================================
# CSS
# ============================================================

CSS = """
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background:
        radial-gradient(
            circle at top,
            #21113d 0,
            #0b0811 38%,
            #07060a 100%
        );
    color: #ffffff;
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Arial,
        sans-serif;
}

a {
    color: inherit;
    text-decoration: none;
}

.wrap {
    width: 100%;
    max-width: 920px;
    margin: auto;
    padding: 20px;
}

.nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 0 35px;
}

.logo {
    font-size: 22px;
    font-weight: 900;
}

.nav-btn {
    padding: 10px 15px;
    border-radius: 12px;
    border: 1px solid #30243e;
    background: #11101a;
    color: #ddd;
}

.hero {
    text-align: center;
    padding: 45px 10px 55px;
}

.umbrella {
    font-size: 64px;
}

h1 {
    font-size: 54px;
    margin: 12px 0;
    background:
        linear-gradient(
            90deg,
            #ffffff,
            #b779ff
        );
    -webkit-background-clip: text;
    color: transparent;
}

.hero p {
    color: #9994a4;
    line-height: 1.7;
}

.card {
    background: rgba(18, 15, 27, .94);
    border: 1px solid #2c2438;
    border-radius: 22px;
    padding: 24px;
    margin: 16px 0;
    box-shadow: 0 20px 70px rgba(0,0,0,.25);
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(
            auto-fit,
            minmax(180px, 1fr)
        );
    gap: 12px;
}

.tariff {
    background: #11101a;
    border: 1px solid #2d2638;
    border-radius: 18px;
    padding: 20px;
}

.tariff-days {
    color: #9993a3;
}

.price {
    font-size: 29px;
    font-weight: 900;
    margin-top: 8px;
}

.btn {
    display: inline-block;
    border: 0;
    border-radius: 13px;
    padding: 13px 18px;
    background:
        linear-gradient(
            135deg,
            #974cff,
            #5b22d3
        );
    color: #fff;
    font-weight: 800;
    cursor: pointer;
}

.btn-secondary {
    display: inline-block;
    border: 1px solid #342b42;
    border-radius: 13px;
    padding: 13px 18px;
    background: #15121d;
    color: #eee;
    cursor: pointer;
}

.input {
    width: 100%;
    padding: 14px;
    margin: 7px 0 12px;
    border: 1px solid #332a40;
    border-radius: 13px;
    background: #0c0a10;
    color: #fff;
    outline: none;
}

.status {
    font-size: 30px;
    font-weight: 900;
}

.active {
    color: #8dffb4;
}

.expired {
    color: #ff7d8a;
}

.muted {
    color: #8e8998;
}

.error {
    color: #ff7e8b;
    margin: 10px 0;
}

.center {
    text-align: center;
}

.link-box {
    display: flex;
    overflow: hidden;
    border: 1px solid #30283b;
    border-radius: 13px;
    background: #0b0910;
}

.link-box input {
    flex: 1;
    min-width: 0;
    border: 0;
    outline: none;
    padding: 13px;
    background: transparent;
    color: #aaa;
}

.link-box button {
    border: 0;
    padding: 0 16px;
    cursor: pointer;
}

.footer {
    text-align: center;
    color: #4f4a57;
    padding: 35px 0 10px;
}

@media (max-width: 600px) {

    h1 {
        font-size: 40px;
    }

    .wrap {
        padding: 15px;
    }
}
"""


# ============================================================
# HTML
# ============================================================

def page(title, body):

    cabinet = (
        '<a class="nav-btn" href="/cabinet">'
        'Кабинет'
        '</a>'
        if session.get("uid")
        else
        '<a class="nav-btn" href="/login">'
        'Войти'
        '</a>'
    )

    return f"""
<!doctype html>
<html lang="ru">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>{title} — ixxy VPN</title>

<style>
{CSS}
</style>

</head>

<body>

<div class="wrap">

<div class="nav">

<a class="logo" href="/">
☂️ ixxy VPN
</a>

<div>
{cabinet}
</div>

</div>

{body}

<div class="footer">
☂️ ixxy VPN
</div>

</div>

</body>

</html>
"""


# ============================================================
# CSRF
# ============================================================

def csrf_token():

    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)

    return session["csrf"]


def csrf_ok():

    token = request.form.get("csrf", "")

    saved = session.get("csrf", "")

    if not token or not saved:
        return False

    return secrets.compare_digest(
        token,
        saved
    )


# ============================================================
# GITHUB
# ============================================================

def subscription_url(user_id):

    return (
        f"{PUBLIC_SITE_URL}/s/"
        f"{SUBSCRIPTION_PREFIX}{user_id}"
    )


def github_api_url(path):

    return (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    )


def get_servers():

    url = (
        f"https://raw.githubusercontent.com/"
        f"{GITHUB_OWNER}/"
        f"{GITHUB_REPO}/"
        f"{GITHUB_BRANCH}/"
        f"{GITHUB_SERVERS_FILE}"
    )

    try:

        r = requests.get(
            url,
            timeout=15
        )

        if r.ok:
            return r.text.strip()

    except Exception:
        pass

    return ""


def make_subscription_content(user_id):

    user = get_user(user_id)

    if not user:
        return ""

    active = subscription_active(
        user["subscription_until"]
    )

    if active:

        until = (
            user["subscription_until"]
            .astimezone(timezone.utc)
            .strftime("%d.%m.%Y")
        )

        announce = (
            "#announce: "
            f"🟢 Подписка активна • до {until} "
            "• ☂️ ixxy VPN"
        )

        servers = get_servers()

        return f"""#profile-title: 𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️
#profile-update-interval: 1
#subscription-userinfo: upload=0; download=0; total=0
#hide-settings: true
{announce}

{servers}
"""

    return """#profile-title: 𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️
#profile-update-interval: 1
#subscription-userinfo: upload=0; download=0; total=0
#hide-settings: true
#announce: 🔴 Подписка не активна • Продлите подписку на сайте ixxy VPN
"""


def sync_github(user_id):

    if not GITHUB_TOKEN:
        return False

    content = make_subscription_content(
        user_id
    )

    if not content:
        return False

    user = get_user(user_id)

    if (
        user
        and user.get("subscription_content") == content
        and user.get("subscription_link")
    ):
        return True

    path = f"users/{user_id}.txt"

    api_url = github_api_url(path)

    headers = {
        "Authorization":
            f"Bearer {GITHUB_TOKEN}",
        "Accept":
            "application/vnd.github+json",
        "X-GitHub-Api-Version":
            "2022-11-28",
    }

    try:

        sha = None

        existing = requests.get(
            api_url,
            headers=headers,
            timeout=15
        )

        if existing.ok:
            sha = existing.json().get("sha")

        data = {
            "message":
                f"ixxy subscription {user_id}",

            "content":
                base64.b64encode(
                    content.encode("utf-8")
                ).decode("ascii"),

            "branch":
                GITHUB_BRANCH,
        }

        if sha:
            data["sha"] = sha

        response = requests.put(
            api_url,
            headers=headers,
            json=data,
            timeout=20
        )

        if not response.ok:
            print(
                "GitHub error:",
                response.status_code,
                response.text
            )

            return False

        save_subscription(
            user_id,
            subscription_url(user_id),
            content
        )

        return True

    except Exception as e:

        print(
            "GitHub sync error:",
            repr(e)
        )

        return False


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    tariffs = ""

    for days, price in TARIFFS.items():

        tariffs += f"""
<div class="tariff">

<div class="tariff-days">
{days} дней
</div>

<div class="price">
{price} ₽
</div>

<p class="muted">
Полный доступ к ixxy VPN
</p>

</div>
"""

    return page(
        "Главная",
        f"""
<section class="hero">

<div class="umbrella">
☂️
</div>

<h1>
ixxy VPN
</h1>

<p>
Быстрый и простой VPN.<br>
Подключение через Happ без лишних настроек.
</p>

<a class="btn" href="/register">
Создать кабинет
</a>

</section>

<h2>
Тарифы
</h2>

<div class="grid">
{tariffs}
</div>
"""
    )


# ============================================================
# REGISTER
# ============================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    error = ""

    if request.method == "POST":

        if not csrf_ok():
            return "CSRF error", 403

        email = (
            request.form
            .get("email", "")
            .strip()
            .lower()
        )

        password = request.form.get(
            "password",
            ""
        )

        name = (
            request.form
            .get("name", "")
            .strip()
            or "Пользователь"
        )

        if len(password) < 6:

            error = (
                "Пароль должен содержать "
                "минимум 6 символов."
            )

        elif get_user_by_email(email):

            error = (
                "Этот email уже зарегистрирован."
            )

        else:

            user_id = create_site_user(
                email,
                generate_password_hash(password),
                name
            )

            session["uid"] = user_id

            sync_github(user_id)

            return redirect("/cabinet")

    error_html = (
        f'<div class="error">{error}</div>'
        if error
        else ""
    )

    return page(
        "Регистрация",
        f"""
<section class="card">

<h2>
Создание кабинета
</h2>

{error_html}

<form method="post">

<input
    class="input"
    name="email"
    type="email"
    placeholder="Email"
    required
>

<input
    class="input"
    name="name"
    placeholder="Имя"
>

<input
    class="input"
    name="password"
    type="password"
    placeholder="Пароль"
    required
>

<input
    type="hidden"
    name="csrf"
    value="{csrf_token()}"
>

<button class="btn">
Зарегистрироваться
</button>

</form>

</section>

<p class="center muted">
Уже есть аккаунт?
<a href="/login">
Войти
</a>
</p>
"""
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    error = ""

    if request.method == "POST":

        if not csrf_ok():
            return "CSRF error", 403

        email = (
            request.form
            .get("email", "")
            .strip()
            .lower()
        )

        password = request.form.get(
            "password",
            ""
        )

        user = get_user_by_email(email)

        if (
            user
            and user.get("password_hash")
            and check_password_hash(
                user["password_hash"],
                password
            )
        ):

            session["uid"] = int(
                user["user_id"]
            )

            return redirect("/cabinet")

        error = (
            "Неверный email или пароль."
        )

    error_html = (
        f'<div class="error">{error}</div>'
        if error
        else ""
    )

    return page(
        "Вход",
        f"""
<section class="card">

<h2>
Вход
</h2>

{error_html}

<form method="post">

<input
    class="input"
    name="email"
    type="email"
    placeholder="Email"
    required
>

<input
    class="input"
    name="password"
    type="password"
    placeholder="Пароль"
    required
>

<input
    type="hidden"
    name="csrf"
    value="{csrf_token()}"
>

<button class="btn">
Войти
</button>

</form>

</section>

<p class="center muted">
Нет аккаунта?
<a href="/register">
Регистрация
</a>
</p>
"""
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

    user_id = session.get("uid")

    if not user_id:
        return redirect("/login")

    sync_github(user_id)

    user = get_user(user_id)

    if not user:
        session.clear()
        return redirect("/login")

    active = subscription_active(
        user["subscription_until"]
    )

    if user["subscription_until"]:

        until = (
            user["subscription_until"]
            .astimezone(timezone.utc)
            .strftime("%d.%m.%Y %H:%M")
        )

    else:

        until = "—"

    days_left = 0

    if active:

        days_left = max(
            0,
            (
                user["subscription_until"]
                .astimezone(timezone.utc)
                - datetime.now(timezone.utc)
            ).days
        )

    link = (
        user["subscription_link"]
        or subscription_url(user_id)
    )

    tariff_buttons = ""

    for days, price in TARIFFS.items():

        tariff_buttons += f"""
<form method="post" action="/buy">

<input
    type="hidden"
    name="days"
    value="{days}"
>

<input
    type="hidden"
    name="csrf"
    value="{csrf_token()}"
>

<button
    class="btn-secondary"
    style="width:100%"
>
{days} дней — {price} ₽
</button>

</form>
"""

    trial = ""

    if not user["trial_used"]:

        trial = f"""
<section class="card">

<h3>
🎁 Бесплатный пробный период
</h3>

<p class="muted">
1 день бесплатно для нового аккаунта.
</p>

<form method="post" action="/trial">

<input
    type="hidden"
    name="csrf"
    value="{csrf_token()}"
>

<button class="btn-secondary">
Получить 1 день бесплатно
</button>

</form>

</section>
"""

    return page(
        "Кабинет",
        f"""
<section class="hero">

<div class="muted">
Личный кабинет
</div>

<h1>
☂️
</h1>

<p>
{user.get("email", "")}
</p>

</section>

<section class="card">

<div class="muted">
Состояние подписки
</div>

<div class="status {
    "active" if active else "expired"
}">
{
    "Активна"
    if active
    else
    "Не активна"
}
</div>

<p class="muted">
До: {until}
<br>
Осталось: {days_left} дн.
</p>

<a
    class="btn"
    href="happ://add/{quote(link, safe='')}"
>
Открыть в Happ
</a>

</section>

<section class="card">

<h3>
Ссылка подписки
</h3>

<div class="link-box">

<input
    id="sub"
    value="{link}"
    readonly
>

<button
    onclick="
        navigator.clipboard.writeText(
            document.getElementById('sub').value
        )
    "
>
Копировать
</button>

</div>

</section>

<section class="card">

<h3>
Продлить подписку
</h3>

<div class="grid">
{tariff_buttons}
</div>

</section>

<section class="card">

<h3>
Промокод
</h3>

<form method="post" action="/promo">

<input
    class="input"
    name="code"
    placeholder="Введите промокод"
    required
>

<input
    type="hidden"
    name="csrf"
    value="{csrf_token()}"
>

<button class="btn-secondary">
Активировать
</button>

</form>

</section>

{trial}

<br>

<a class="nav-btn" href="/logout">
Выйти
</a>
"""
    )


# ============================================================
# BUY
# ============================================================

@app.route(
    "/buy",
    methods=["POST"]
)
def buy():

    user_id = session.get("uid")

    if not user_id:
        return redirect("/login")

    if not csrf_ok():
        return "Forbidden", 403

    try:
        days = int(
            request.form.get(
                "days",
                "0"
            )
        )
    except ValueError:
        return "Bad tariff", 400

    if days not in TARIFFS:
        return "Bad tariff", 400

    if not CASHERA_API_KEY:

        return (
            "CASHERA_API_KEY не настроен",
            500
        )

    amount = TARIFFS[days]

    external_id = (
        f"ixxy_{user_id}_"
        f"{secrets.token_hex(8)}"
    )

    payload = {
        "amount": amount * 100,
        "currency": "RUB",
        "payment_method": "sbp",
        "external_id": external_id,
        "description":
            f"ixxy VPN — {days} дней",
        "callback_url":
            f"{PUBLIC_SITE_URL}/webhook/cashera",
        "success_url":
            f"{PUBLIC_SITE_URL}/payment/success",
        "fail_url":
            f"{PUBLIC_SITE_URL}/payment/fail",
    }

    try:

        response = requests.post(
            CASHERA_URL,
            headers={
                "X-Api-Key":
                    CASHERA_API_KEY,
                "Content-Type":
                    "application/json",
            },
            json=payload,
            timeout=20
        )

        data = response.json()

        transaction = data.get(
            "transaction",
            data
        )

        payment_id = (
            transaction.get("uuid")
            or transaction.get("id")
        )

        payment_url = (
            transaction.get("payment_url")
            or transaction.get("url")
        )

        if not payment_id:

            print(
                "CasheRa response:",
                data
            )

            return (
                "CasheRa не вернула ID платежа.",
                502
            )

        if not payment_url:

            print(
                "CasheRa response:",
                data
            )

            return (
                "CasheRa не вернула ссылку на оплату.",
                502
            )

        create_payment(
            user_id,
            payment_id,
            external_id,
            amount,
            days
        )

        return redirect(payment_url)

    except Exception as e:

        print(
            "CasheRa error:",
            repr(e)
        )

        return (
            "Ошибка создания платежа.",
            502
        )


# ============================================================
# CASHE RA WEBHOOK
# ============================================================

@app.route(
    "/webhook/cashera",
    methods=["POST"]
)
def cashera_webhook():

    data = request.get_json(
        silent=True
    ) or {}

    transaction = data.get(
        "transaction",
        data
    )

    event = (
        data.get("event")
        or data.get("type")
    )

    payment_id = (
        transaction.get("uuid")
        or transaction.get("id")
    )

    status = str(
        transaction.get(
            "status",
            ""
        )
    ).lower()

    if (
        event
        and event != "transaction.status_updated"
    ):
        return {
            "ok": True
        }

    if (
        status != "paid"
        or not payment_id
    ):
        return {
            "ok": True
        }

    try:

        result = process_paid_payment(
            payment_id
        )

        if result:

            user_id = result[0]

            sync_github(
                user_id
            )

        return {
            "ok": True
        }

    except Exception as e:

        print(
            "Webhook error:",
            repr(e)
        )

        return {
            "ok": False
        }, 500


# ============================================================
# PROMO
# ============================================================

@app.route(
    "/promo",
    methods=["POST"]
)
def promo():

    user_id = session.get("uid")

    if not user_id:
        return redirect("/login")

    if not csrf_ok():
        return "Forbidden", 403

    code = request.form.get(
        "code",
        ""
    )

    until, error = use_promocode(
        user_id,
        code
    )

    if error:

        return page(
            "Промокод",
            f"""
<section class="card">

<div class="error">
{error}
</div>

<a
    class="btn"
    href="/cabinet"
>
Назад
</a>

</section>
"""
        )

    sync_github(
        user_id
    )

    return redirect("/cabinet")


# ============================================================
# TRIAL
# ============================================================

@app.route(
    "/trial",
    methods=["POST"]
)
def trial():

    user_id = session.get("uid")

    if not user_id:
        return redirect("/login")

    if not csrf_ok():
        return "Forbidden", 403

    until = use_trial(
        user_id,
        1
    )

    if until:
        sync_github(
            user_id
        )

    return redirect("/cabinet")


# ============================================================
# SUBSCRIPTION URL
# ============================================================

@app.route(
    "/s/<path:key>"
)
@app.route(
    "/sub/<path:key>"
)
def subscription(key):

    if key.startswith(
        SUBSCRIPTION_PREFIX
    ):

        key = key[
            len(SUBSCRIPTION_PREFIX):
        ]

    try:

        user_id = int(key)

    except ValueError:

        return Response(
            "invalid",
            status=404
        )

    user = get_user(
        user_id
    )

    if not user:

        return Response(
            "not found",
            status=404
        )

    content = make_subscription_content(
        user_id
    )

    if (
        user.get(
            "subscription_content"
        ) != content
    ):

        sync_github(
            user_id
        )

    return Response(
        content,
        mimetype="text/plain"
    )


# ============================================================
# HEALTH
# ============================================================

@app.route("/health")
def health():

    return {
        "ok": True
    }


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )