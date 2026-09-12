import os
import secrets
import hashlib
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from flask import (
    Flask,
    request,
    redirect,
    session,
    render_template_string,
    abort,
    jsonify,
)
from dotenv import load_dotenv

import database
from database import (
    get_user,
    get_user_by_username,
    create_user,
    login_user,
    activate_subscription,
    subscription_active,
    use_trial,
    create_payment,
    get_payment_by_external_id,
    mark_payment_paid,
    get_payment_history,
    use_promo,
    create_promo,
    delete_promo,
    get_promos,
    get_all_users,
    search_users,
    set_blocked,
    stats,
    revoke_subscription,
)
from cashera_api import create_payment as cashera_create_payment
from cashera_api import check_webhook


load_dotenv()

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Стабильный секрет без отдельной переменной.
app.secret_key = hashlib.sha256(
    DATABASE_URL.encode()
).hexdigest()

PUBLIC_URL = "https://ixxyweb.onrender.com"
SUB_PREFIX = "2ix847xy"

GITHUB_OWNER = "bdtvyz76b6-blip"
GITHUB_REPO = "vpn-sub"
GITHUB_BRANCH = "main"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

SUPPORT = "https://t.me/rusrodyyya"

ADMIN_IDS = [
    x.strip()
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip()
]

TARIFFS = {
    30: 129,
    90: 379,
    180: 659,
    365: 1089,
}


# ============================================================
# HTML
# ============================================================

CSS = """
<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background:
        radial-gradient(
            circle at top,
            #32145f 0,
            #10091d 45%,
            #07050d 100%
        );
    color: #fff;
    font-family: Inter, Arial, sans-serif;
    min-height: 100vh;
}

a {
    color: inherit;
    text-decoration: none;
}

.container {
    width: min(1050px, calc(100% - 30px));
    margin: auto;
}

.nav {
    padding: 22px 0;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.logo {
    font-size: 25px;
    font-weight: 900;
}

.card {
    background: rgba(24, 15, 40, .88);
    border: 1px solid rgba(173, 91, 255, .25);
    border-radius: 24px;
    padding: 25px;
    box-shadow: 0 15px 60px rgba(0,0,0,.35);
    backdrop-filter: blur(15px);
}

.hero {
    text-align: center;
    padding: 70px 20px;
}

.hero h1 {
    font-size: clamp(40px, 8vw, 75px);
    margin: 0 0 15px;
}

.hero p {
    color: #bcaecb;
    font-size: 18px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(220px, 1fr));
    gap: 15px;
}

.btn {
    display: inline-block;
    width: 100%;
    padding: 14px 18px;
    border-radius: 14px;
    border: 0;
    background: linear-gradient(
        135deg,
        #9b4dff,
        #6c27d9
    );
    color: white;
    font-size: 15px;
    font-weight: 800;
    cursor: pointer;
    text-align: center;
}

.btn.secondary {
    background: #21152f;
    border: 1px solid #49305e;
}

.btn.danger {
    background: #7e2439;
}

input, select {
    width: 100%;
    padding: 14px;
    margin: 7px 0 14px;
    border-radius: 13px;
    border: 1px solid #49305e;
    background: #100a18;
    color: white;
    outline: none;
}

label {
    color: #c9b8d7;
    font-size: 14px;
}

h1, h2, h3 {
    margin-top: 0;
}

.muted {
    color: #a999b5;
}

.success {
    color: #5dffae;
}

.error {
    color: #ff718b;
}

.stat {
    font-size: 31px;
    font-weight: 900;
}

.price {
    font-size: 28px;
    font-weight: 900;
}

table {
    width: 100%;
    border-collapse: collapse;
}

td, th {
    padding: 12px 8px;
    border-bottom: 1px solid #33223f;
    text-align: left;
}

.small {
    font-size: 13px;
    word-break: break-all;
}

.space {
    height: 16px;
}

.footer {
    text-align: center;
    padding: 45px 0;
    color: #81748d;
}

.badge {
    display: inline-block;
    padding: 7px 11px;
    border-radius: 99px;
    background: #241536;
    color: #c99cff;
    font-size: 13px;
}
</style>
"""


def page(title, body):
    return render_template_string(
        f"""
        <!doctype html>
        <html lang="ru">
        <head>
            <meta charset="utf-8">
            <meta
                name="viewport"
                content="width=device-width, initial-scale=1"
            >
            <title>{title} — ixxy VPN</title>
            {CSS}
        </head>
        <body>
            <div class="container">
                <div class="nav">
                    <a class="logo" href="/">☂️ ixxy VPN</a>
                    <div>
                        {
                            '<a href="/cabinet">Кабинет</a>'
                            if session.get("user_id")
                            else
                            '<a href="/login">Войти</a>'
                        }
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
    )


def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    user = get_user(user_id)

    if not user:
        session.clear()
        return None

    return user


def require_login():
    user = current_user()

    if not user:
        return redirect("/login")

    return user


def is_admin():
    user = current_user()

    if not user:
        return False

    return (
        str(user["id"]) in ADMIN_IDS
        or user["username"] in ADMIN_IDS
    )


def require_admin():
    if not is_admin():
        abort(403)

    return current_user()


# ============================================================
# GITHUB
# ============================================================

def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_get(path):
    url = (
        "https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    )

    response = requests.get(
        url,
        headers=github_headers(),
        params={"ref": GITHUB_BRANCH},
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"GitHub GET {response.status_code}: "
            f"{response.text}"
        )

    return response.json()


def github_file(path):
    data = github_get(path)

    content = requests.get(
        data["download_url"],
        timeout=30,
    )

    if not content.ok:
        raise RuntimeError("Не удалось скачать файл GitHub")

    return content.text


def github_put(path, content, message):
    import base64

    url = (
        "https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    )

    try:
        old = github_get(path)
        sha = old.get("sha")
    except Exception:
        sha = None

    payload = {
        "message": message,
        "content": base64.b64encode(
            content.encode("utf-8")
        ).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }

    if sha:
        payload["sha"] = sha

    response = requests.put(
        url,
        headers=github_headers(),
        json=payload,
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"GitHub PUT {response.status_code}: "
            f"{response.text}"
        )

    return response.json()


def sync_subscription(user_id):
    user = get_user(user_id)

    if not user:
        return

    active = subscription_active(user_id)

    if active:
        try:
            servers = github_file("servers.txt")
        except Exception:
            servers = ""

        until = user["subscription_until"]

        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)

        date = until.strftime("%d.%m.%Y")

        content = (
            "#profile-title: 𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️\n"
            "#profile-update-interval: 1\n"
            "#subscription-userinfo: "
            "upload=0; download=0; total=0\n"
            "#hide-settings: true\n"
            f"#announce: 🟢 Подписка активна "
            f"• до {date} • ☂️ ixxy VPN\n\n"
            f"{servers.strip()}\n"
        )

    else:
        content = (
            "#profile-title: 𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️\n"
            "#profile-update-interval: 1\n"
            "#subscription-userinfo: "
            "upload=0; download=0; total=0\n"
            "#hide-settings: true\n"
            "#announce: 🔴 Подписка не активна "
            "• Продлите подписку на сайте ixxy VPN\n"
        )

    path = f"users/{user_id}.txt"

    github_put(
        path,
        content,
        f"ixxy subscription update {user_id}",
    )

    database.save_subscription = getattr(
        database,
        "save_subscription",
        None,
    )

    with database.conn() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE site_users
                SET subscription_content = %s,
                    subscription_link = %s
                WHERE id = %s
                """,
                (
                    content,
                    f"{PUBLIC_URL}/sub/{SUB_PREFIX}{user_id}",
                    user_id,
                ),
            )

        db.commit()


# ============================================================
# PUBLIC
# ============================================================

@app.route("/")
def index():
    return page(
        "Главная",
        """
        <div class="hero">
            <div class="badge">PRIVATE VPN</div>

            <h1>☂️ ixxy VPN</h1>

            <p>
                Быстрый и простой доступ к VPN.
                Управляйте подпиской полностью через сайт.
            </p>

            <div class="space"></div>

            <div class="grid">
                <a class="btn" href="/register">
                    Создать аккаунт
                </a>

                <a class="btn secondary" href="/login">
                    Войти
                </a>
            </div>
        </div>

        <div class="card">
            <h2>Тарифы</h2>

            <div class="grid">
                <div>
                    <div class="price">129 ₽</div>
                    <p class="muted">1 месяц</p>
                </div>

                <div>
                    <div class="price">379 ₽</div>
                    <p class="muted">3 месяца</p>
                </div>

                <div>
                    <div class="price">659 ₽</div>
                    <p class="muted">6 месяцев</p>
                </div>

                <div>
                    <div class="price">1089 ₽</div>
                    <p class="muted">12 месяцев</p>
                </div>
            </div>
        </div>
        """,
    )


# ============================================================
# REGISTER
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    error = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if password != password2:
            error = "Пароли не совпадают"

        elif get_user_by_username(username):
            error = "Такой логин уже существует"

        else:
            try:
                user_id = create_user(
                    username,
                    password,
                )

                session["user_id"] = user_id

                sync_subscription(user_id)

                return redirect("/cabinet")

            except Exception as e:
                error = str(e)

    return page(
        "Регистрация",
        f"""
        <div class="card">
            <h1>Создание аккаунта</h1>

            <p class="muted">
                Ваш личный кабинет ixxy VPN.
            </p>

            {
                f'<p class="error">{error}</p>'
                if error else ""
            }

            <form method="post">
                <label>Логин</label>
                <input
                    name="username"
                    minlength="3"
                    required
                >

                <label>Пароль</label>
                <input
                    type="password"
                    name="password"
                    minlength="6"
                    required
                >

                <label>Повторите пароль</label>
                <input
                    type="password"
                    name="password2"
                    minlength="6"
                    required
                >

                <button class="btn">
                    Зарегистрироваться
                </button>
            </form>

            <div class="space"></div>

            <a href="/login" class="muted">
                Уже есть аккаунт?
            </a>
        </div>
        """,
    )


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        user = login_user(
            request.form.get("username", ""),
            request.form.get("password", ""),
        )

        if not user:
            error = "Неверный логин или пароль"
        else:
            session["user_id"] = user["id"]
            return redirect("/cabinet")

    return page(
        "Вход",
        f"""
        <div class="card">
            <h1>Вход</h1>

            {
                f'<p class="error">{error}</p>'
                if error else ""
            }

            <form method="post">
                <label>Логин</label>
                <input name="username" required>

                <label>Пароль</label>
                <input
                    type="password"
                    name="password"
                    required
                >

                <button class="btn">
                    Войти
                </button>
            </form>

            <div class="space"></div>

            <a href="/register" class="muted">
                Создать аккаунт
            </a>
        </div>
        """,
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ============================================================
# CABINET
# ============================================================

@app.route("/cabinet")
def cabinet():
    user = require_login()

    if not isinstance(user, dict):
        return user

    active = subscription_active(user["id"])

    until = user["subscription_until"]

    if until:
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)

        expiry = until.strftime("%d.%m.%Y %H:%M")

        seconds = (
            until - datetime.now(timezone.utc)
        ).total_seconds()

        days = max(0, int(seconds // 86400))
    else:
        expiry = "—"
        days = 0

    subscription_url = (
        f"{PUBLIC_URL}/sub/"
        f"{SUB_PREFIX}{user['id']}"
    )

    happ_url = (
        "https://happ.vpnbypass.click/?url="
        + quote(subscription_url, safe="")
    )

    incy_url = (
        "incy://add/"
        + quote(subscription_url, safe="")
    )

    status = (
        '<span class="success">● Активна</span>'
        if active
        else
        '<span class="error">● Не активна</span>'
    )

    return page(
        "Личный кабинет",
        f"""
        <div class="card">
            <h1>Личный кабинет</h1>

            <p>
                Добро пожаловать,
                <b>{user['username']}</b>
            </p>

            <div class="grid">
                <div class="card">
                    <p class="muted">Статус</p>
                    <h2>{status}</h2>
                </div>

                <div class="card">
                    <p class="muted">Осталось</p>
                    <h2>{days} дн.</h2>
                </div>

                <div class="card">
                    <p class="muted">До</p>
                    <h2>{expiry}</h2>
                </div>
            </div>

            <div class="space"></div>

            <h2>Подписка</h2>

            <input
                value="{subscription_url}"
                readonly
                onclick="this.select()"
            >

            <div class="grid">
                <a
                    class="btn"
                    href="{happ_url}"
                >
                    Добавить в Happ
                </a>

                <a
                    class="btn secondary"
                    href="{incy_url}"
                >
                    Добавить в INCY
                </a>
            </div>

            <div class="space"></div>

            <div class="grid">
                <a
                    class="btn"
                    href="/buy"
                >
                    Купить подписку
                </a>

                <a
                    class="btn secondary"
                    href="/promo"
                >
                    Промокод
                </a>

                <a
                    class="btn secondary"
                    href="/trial"
                >
                    Получить пробный период
                </a>
            </div>

            <div class="space"></div>

            <a
                class="btn secondary"
                href="/payments"
            >
                История платежей
            </a>

            <div class="space"></div>

            <a
                class="btn secondary"
                href="{SUPPORT}"
                target="_blank"
            >
                Поддержка
            </a>

            <div class="space"></div>

            {
                '<a class="btn secondary" href="/admin">Админ-панель</a>'
                if is_admin()
                else ""
            }

            <div class="space"></div>

            <a href="/logout" class="muted">
                Выйти
            </a>
        </div>
        """,
    )


# ============================================================
# BUY
# ============================================================

@app.route("/buy")
def buy():
    user = require_login()

    if not isinstance(user, dict):
        return user

    cards = ""

    for days, price in TARIFFS.items():
        cards += f"""
        <div class="card">
            <h2>{days} дней</h2>

            <div class="price">
                {price} ₽
            </div>

            <div class="space"></div>

            <a
                class="btn"
                href="/pay/{days}"
            >
                Оплатить
            </a>
        </div>
        """

    return page(
        "Тарифы",
        f"""
        <h1>Тарифы ixxy VPN</h1>

        <div class="grid">
            {cards}
        </div>
        """,
    )


@app.route("/pay/<int:days>")
def pay(days):
    user = require_login()

    if not isinstance(user, dict):
        return user

    if days not in TARIFFS:
        abort(404)

    price = TARIFFS[days]

    external_id = (
        f"ixxy-{user['id']}-"
        f"{days}-{secrets.token_hex(8)}"
    )

    create_payment(
        user["id"],
        external_id,
        price,
        days,
    )

    callback = f"{PUBLIC_URL}/cashera/webhook"
    success = f"{PUBLIC_URL}/payment/success"
    fail = f"{PUBLIC_URL}/payment/fail"

    try:
        data = cashera_create_payment(
            amount_rub=price,
            external_id=external_id,
            description=(
                f"ixxy VPN — {days} дней"
            ),
            callback_url=callback,
            success_url=success,
            fail_url=fail,
        )

        payment_url = (
            data.get("payment_url")
            or data.get("url")
            or data.get("pay_url")
        )

        if not payment_url:
            return page(
                "Ошибка",
                f"""
                <div class="card">
                    <h1>Ошибка оплаты</h1>
                    <p>
                        CasheRa не вернула ссылку
                        на оплату.
                    </p>
                    <pre>{data}</pre>
                </div>
                """,
            )

        return redirect(payment_url)

    except Exception as e:
        return page(
            "Ошибка оплаты",
            f"""
            <div class="card">
                <h1>Ошибка оплаты</h1>
                <p class="error">
                    {str(e)}
                </p>
                <a class="btn" href="/buy">
                    Назад
                </a>
            </div>
            """,
        )


@app.route("/payment/success")
def payment_success():
    return page(
        "Оплата",
        """
        <div class="card">
            <h1>Оплата отправлена ✅</h1>

            <p>
                После подтверждения платежа
                подписка автоматически активируется.
            </p>

            <a class="btn" href="/cabinet">
                Перейти в кабинет
            </a>
        </div>
        """,
    )


@app.route("/payment/fail")
def payment_fail():
    return page(
        "Оплата",
        """
        <div class="card">
            <h1>Оплата отменена</h1>

            <a class="btn" href="/buy">
                Вернуться к тарифам
            </a>
        </div>
        """,
    )


# ============================================================
# CASHERA WEBHOOK
# ============================================================

@app.route(
    "/cashera/webhook",
    methods=["POST"],
)
def cashera_webhook():

    if not check_webhook(request.headers):
        abort(403)

    data = request.get_json(
        silent=True
    ) or {}

    event = data.get("event")

    transaction = (
        data.get("transaction")
        or data.get("data")
        or data
    )

    status = str(
        transaction.get("status", "")
    ).lower()

    if event and event != "transaction.status_updated":
        return jsonify({"ok": True})

    if status != "paid":
        return jsonify({"ok": True})

    external_id = (
        transaction.get("external_id")
        or transaction.get("externalId")
    )

    if not external_id:
        return jsonify({"ok": True})

    payment = get_payment_by_external_id(
        external_id
    )

    if not payment:
        return jsonify({"ok": True})

    # Защита от повторной активации.
    if payment["status"] == "paid":
        return jsonify({"ok": True})

    amount = transaction.get("amount")

    if amount is not None:
        try:
            amount_rub = int(amount) / 100

            if int(amount_rub) != int(
                payment["amount"]
            ):
                return jsonify(
                    {"ok": False}
                ), 400

        except Exception:
            return jsonify(
                {"ok": False}
            ), 400

    result = mark_payment_paid(
        external_id,
        transaction.get("id"),
    )

    if result:
        user_id, days = result

        activate_subscription(
            user_id,
            days,
        )

        try:
            sync_subscription(user_id)
        except Exception:
            pass

    return jsonify({"ok": True})


# ============================================================
# TRIAL
# ============================================================

@app.route("/trial")
def trial():
    user = require_login()

    if not isinstance(user, dict):
        return user

    if use_trial(user["id"]):
        try:
            sync_subscription(user["id"])
        except Exception:
            pass

        message = (
            '<p class="success">'
            'Пробный период активирован на 1 день.'
            '</p>'
        )
    else:
        message = (
            '<p class="error">'
            'Пробный период уже использован.'
            '</p>'
        )

    return page(
        "Пробный период",
        f"""
        <div class="card">
            <h1>Пробный период</h1>

            {message}

            <a class="btn" href="/cabinet">
                В кабинет
            </a>
        </div>
        """,
    )


# ============================================================
# PROMO
# ============================================================

@app.route("/promo", methods=["GET", "POST"])
def promo():
    user = require_login()

    if not isinstance(user, dict):
        return user

    message = ""

    if request.method == "POST":
        code = request.form.get(
            "code",
            "",
        )

        days = use_promo(
            user["id"],
            code,
        )

        if days:
            try:
                sync_subscription(user["id"])
            except Exception:
                pass

            message = (
                f'<p class="success">'
                f'Промокод активирован: +{days} дней.'
                f'</p>'
            )
        else:
            message = (
                '<p class="error">'
                'Промокод недействителен.'
                '</p>'
            )

    return page(
        "Промокод",
        f"""
        <div class="card">
            <h1>Промокод</h1>

            {message}

            <form method="post">
                <input
                    name="code"
                    placeholder="Введите промокод"
                    required
                >

                <button class="btn">
                    Активировать
                </button>
            </form>
        </div>
        """,
    )


# ============================================================
# PAYMENTS
# ============================================================

@app.route("/payments")
def payments():
    user = require_login()

    if not isinstance(user, dict):
        return user

    rows = ""

    for p in get_payment_history(user["id"]):
        rows += f"""
        <tr>
            <td>{p['amount']} ₽</td>
            <td>{p['days']} дн.</td>
            <td>{p['status']}</td>
            <td>{p['created_at']}</td>
        </tr>
        """

    return page(
        "Платежи",
        f"""
        <div class="card">
            <h1>История платежей</h1>

            <table>
                <tr>
                    <th>Сумма</th>
                    <th>Срок</th>
                    <th>Статус</th>
                    <th>Дата</th>
                </tr>

                {rows or '''
                <tr>
                    <td colspan="4">
                        Платежей пока нет.
                    </td>
                </tr>
                '''}
            </table>
        </div>
        """,
    )


# ============================================================
# SUBSCRIPTION
# ============================================================

@app.route("/sub/<token>")
@app.route("/s/<token>")
def subscription(token):

    prefix = SUB_PREFIX

    if not token.startswith(prefix):
        abort(404)

    raw_id = token[len(prefix):]

    if not raw_id.isdigit():
        abort(404)

    user_id = int(raw_id)

    user = get_user(user_id)

    if not user:
        abort(404)

    if subscription_active(user_id):
        try:
            servers = github_file("servers.txt")
        except Exception:
            servers = ""

        until = user["subscription_until"]

        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)

        date = until.strftime("%d.%m.%Y")

        content = (
            "#profile-title: 𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️\n"
            "#profile-update-interval: 1\n"
            "#subscription-userinfo: "
            "upload=0; download=0; total=0\n"
            "#hide-settings: true\n"
            f"#announce: 🟢 Подписка активна "
            f"• до {date} • ☂️ ixxy VPN\n\n"
            f"{servers.strip()}\n"
        )

    else:
        content = (
            "#profile-title: 𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️\n"
            "#profile-update-interval: 1\n"
            "#subscription-userinfo: "
            "upload=0; download=0; total=0\n"
            "#hide-settings: true\n"
            "#announce: 🔴 Подписка не активна "
            "• Продлите подписку на сайте ixxy VPN\n"
        )

    return content, 200, {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-cache, no-store",
    }


# ============================================================
# ADMIN
# ============================================================

@app.route("/admin")
def admin():
    require_admin()

    s = stats()

    return page(
        "Админ-панель",
        f"""
        <h1>Админ-панель</h1>

        <div class="grid">
            <div class="card">
                <p class="muted">Пользователи</p>
                <div class="stat">{s['users']}</div>
            </div>

            <div class="card">
                <p class="muted">Активные</p>
                <div class="stat">{s['active']}</div>
            </div>

            <div class="card">
                <p class="muted">Платежи</p>
                <div class="stat">{s['payments']}</div>
            </div>

            <div class="card">
                <p class="muted">Доход</p>
                <div class="stat">{s['revenue']} ₽</div>
            </div>
        </div>

        <div class="space"></div>

        <div class="grid">
            <a class="btn" href="/admin/users">
                Пользователи
            </a>

            <a class="btn secondary" href="/admin/promos">
                Промокоды
            </a>

            <a class="btn secondary" href="/admin/sync">
                Синхронизация
            </a>
        </div>
        """,
    )


@app.route("/admin/users")
def admin_users():
    require_admin()

    q = request.args.get("q", "").strip()

    users = (
        search_users(q)
        if q
        else get_all_users()
    )

    rows = ""

    for u in users:
        active = subscription_active(u["id"])

        until = u["subscription_until"]

        if until:
            if until.tzinfo is None:
                until = until.replace(
                    tzinfo=timezone.utc
                )

            until_text = until.strftime(
                "%d.%m.%Y"
            )
        else:
            until_text = "—"

        rows += f"""
        <tr>
            <td>{u['id']}</td>
            <td>{u['username']}</td>
            <td>
                {
                    '<span class="success">Активна</span>'
                    if active
                    else
                    '<span class="error">Нет</span>'
                }
            </td>
            <td>{until_text}</td>
            <td>
                <a href="/admin/user/{u['id']}">
                    Открыть
                </a>
            </td>
        </tr>
        """

    return page(
        "Пользователи",
        f"""
        <div class="card">
            <h1>Пользователи</h1>

            <form>
                <input
                    name="q"
                    value="{q}"
                    placeholder="Поиск"
                >
            </form>

            <table>
                <tr>
                    <th>ID</th>
                    <th>Логин</th>
                    <th>Статус</th>
                    <th>До</th>
                    <th></th>
                </tr>

                {rows}
            </table>
        </div>
        """,
    )


@app.route(
    "/admin/user/<int:user_id>",
    methods=["GET", "POST"],
)
def admin_user(user_id):
    require_admin()

    user = get_user(user_id)

    if not user:
        abort(404)

    message = ""

    if request.method == "POST":

        action = request.form.get("action")

        if action == "add":
            days = int(
                request.form.get(
                    "days",
                    0,
                )
            )

            activate_subscription(
                user_id,
                days,
            )

            sync_subscription(user_id)

            message = (
                f"+{days} дней выдано"
            )

        elif action == "revoke":
            revoke_subscription(user_id)

            sync_subscription(user_id)

            message = "Подписка отключена"

        elif action == "block":
            set_blocked(user_id, True)
            message = "Пользователь заблокирован"

        elif action == "unblock":
            set_blocked(user_id, False)
            message = "Пользователь разблокирован"

    user = get_user(user_id)

    return page(
        "Пользователь",
        f"""
        <div class="card">
            <h1>
                Пользователь #{user['id']}
            </h1>

            <p>
                Логин:
                <b>{user['username']}</b>
            </p>

            <p>
                Статус:
                {
                    '<span class="success">Активен</span>'
                    if not user['blocked']
                    else
                    '<span class="error">Заблокирован</span>'
                }
            </p>

            <p>
                Подписка:
                {user['subscription_until'] or '—'}
            </p>

            {
                f'<p class="success">{message}</p>'
                if message else ""
            }

            <form method="post">
                <input
                    type="hidden"
                    name="action"
                    value="add"
                >

                <input
                    type="number"
                    name="days"
                    min="1"
                    placeholder="Количество дней"
                    required
                >

                <button class="btn">
                    Выдать дни
                </button>
            </form>

            <div class="space"></div>

            <form method="post">
                <input
                    type="hidden"
                    name="action"
                    value="revoke"
                >

                <button class="btn danger">
                    Отключить подписку
                </button>
            </form>

            <div class="space"></div>

            <form method="post">
                <input
                    type="hidden"
                    name="action"
                    value={
                        '"unblock"'
                        if user['blocked']
                        else '"block"'
                    }
                >

                <button class="btn secondary">
                    {
                        'Разблокировать'
                        if user['blocked']
                        else 'Заблокировать'
                    }
                </button>
            </form>
        </div>
        """,
    )


# ============================================================
# ADMIN PROMOS
# ============================================================

@app.route(
    "/admin/promos",
    methods=["GET", "POST"],
)
def admin_promos():
    require_admin()

    message = ""

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create":
            try:
                create_promo(
                    request.form["code"],
                    int(request.form["days"]),
                    int(request.form["max_uses"]),
                )

                message = "Промокод создан"

            except Exception as e:
                message = str(e)

        elif action == "delete":
            delete_promo(
                request.form["code"]
            )

            message = "Промокод отключён"

    rows = ""

    for p in get_promos():
        rows += f"""
        <tr>
            <td>{p['code']}</td>
            <td>{p['days']}</td>
            <td>{p['uses']}/{p['max_uses']}</td>
            <td>
                {'Да' if p['active'] else 'Нет'}
            </td>
            <td>
                <form method="post">
                    <input
                        type="hidden"
                        name="action"
                        value="delete"
                    >
                    <input
                        type="hidden"
                        name="code"
                        value="{p['code']}"
                    >
                    <button class="btn danger">
                        Отключить
                    </button>
                </form>
            </td>
        </tr>
        """

    return page(
        "Промокоды",
        f"""
        <div class="card">
            <h1>Создать промокод</h1>

            <p class="muted">{message}</p>

            <form method="post">
                <input
                    type="hidden"
                    name="action"
                    value="create"
                >

                <label>Код</label>
                <input
                    name="code"
                    placeholder="IXXY2026"
                    required
                >

                <label>Дни</label>
                <input
                    type="number"
                    name="days"
                    min="1"
                    required
                >

                <label>Количество использований</label>
                <input
                    type="number"
                    name="max_uses"
                    min="1"
                    value="1"
                    required
                >

                <button class="btn">
                    Создать
                </button>
            </form>
        </div>

        <div class="space"></div>

        <div class="card">
            <h2>Промокоды</h2>

            <table>
                <tr>
                    <th>Код</th>
                    <th>Дни</th>
                    <th>Использований</th>
                    <th>Активен</th>
                    <th></th>
                </tr>

                {rows}
            </table>
        </div>
        """,
    )


# ============================================================
# ADMIN SYNC
# ============================================================

@app.route("/admin/sync")
def admin_sync():
    require_admin()

    success = 0
    errors = 0

    for user in get_all_users():
        try:
            sync_subscription(user["id"])
            success += 1
        except Exception:
            errors += 1

    return page(
        "Синхронизация",
        f"""
        <div class="card">
            <h1>Синхронизация GitHub</h1>

            <p class="success">
                Обновлено: {success}
            </p>

            <p class="error">
                Ошибок: {errors}
            </p>

            <a class="btn" href="/admin">
                В админ-панель
            </a>
        </div>
        """,
    )


# ============================================================
# HEALTH
# ============================================================

@app.route("/health")
def health():
    return "OK", 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "10000",
            )
        ),
    )