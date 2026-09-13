import os
import html
import hmac
import hashlib
import secrets
import json
import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import (
Flask,
request,
redirect,
session,
Response,
abort,
)

from dotenv import load_dotenv

from cashera_api import (
create_payment,
verify_webhook,
CasheraError,
)

load_dotenv()

============================================================

CONFIG

============================================================

app = Flask(name)

BOT_TOKEN = os.getenv(“BOT_TOKEN”, “”).strip()
TELEGRAM_BOT_USERNAME = os.getenv(
“TELEGRAM_BOT_USERNAME”,
“”
).strip().lstrip(”@”)

DATABASE_URL = os.getenv(“DATABASE_URL”, “”).strip()

PUBLIC_SITE_URL = os.getenv(
“PUBLIC_SITE_URL”,
“https://ixxyweb.onrender.com”,
).rstrip(”/”)

SUBSCRIPTION_PREFIX = os.getenv(
“SUBSCRIPTION_PREFIX”,
“2ix847xy”,
).strip()

GITHUB_TOKEN = os.getenv(“GITHUB_TOKEN”, “”).strip()
GITHUB_OWNER = os.getenv(
“GITHUB_OWNER”,
“bdtvyz76b6-blip”,
).strip()

GITHUB_REPO = os.getenv(
“GITHUB_REPO”,
“vpn-sub”,
).strip()

GITHUB_BRANCH = os.getenv(
“GITHUB_BRANCH”,
“main”,
).strip()

TELEGRAM_URL = os.getenv(
“TELEGRAM_URL”,
“https://t.me/rusrodyyya”,
).strip()

ADMIN_IDS = set()

for value in os.getenv(“ADMIN_IDS”, “”).split(”,”):
value = value.strip()
if value.isdigit():
ADMIN_IDS.add(int(value))

TARIFFS = {
30: 129,
90: 379,
180: 659,
365: 1089,
}

PROFILE_TITLE = “𝗦𝗨𝗕 - 𝗜𝗫𝗫𝗬 ☂️”

============================================================

FLASK SECURITY

============================================================

SECRET_KEY = os.getenv(“WEB_SECRET_KEY”, “”).strip()

if not SECRET_KEY:
if BOT_TOKEN:
SECRET_KEY = hashlib.sha256(
(“ixxy-web:” + BOT_TOKEN).encode()
).hexdigest()
else:
SECRET_KEY = secrets.token_hex(32)

app.secret_key = SECRET_KEY

app.config[“SESSION_COOKIE_HTTPONLY”] = True
app.config[“SESSION_COOKIE_SECURE”] = True
app.config[“SESSION_COOKIE_SAMESITE”] = “Lax”

NO_CACHE_HEADERS = {
“Cache-Control”: “no-store, no-cache, must-revalidate, max-age=0”,
“Pragma”: “no-cache”,
“Expires”: “0”,
}

============================================================

DATABASE

============================================================

def db():
if not DATABASE_URL:
raise RuntimeError(“DATABASE_URL не задан”)

return psycopg2.connect(
    DATABASE_URL,
    cursor_factory=RealDictCursor,
    connect_timeout=10,
)

def ensure_web_table():
“””
Создаём только техническую таблицу сайта.
Таблицу users бота НЕ меняем.
“””

conn = db()
try:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS web_processed_payments (
            external_id TEXT PRIMARY KEY,
            user_id BIGINT NOT NULL,
            days INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            processed_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    conn.commit()
finally:
    conn.close()

============================================================

USERS

============================================================

def get_user(user_id):
conn = db()

try:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM users
        WHERE user_id = %s
        LIMIT 1
        """,
        (int(user_id),),
    )
    return cur.fetchone()
finally:
    conn.close()

def get_user_columns():
conn = db()

try:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'users'
        """
    )
    return {
        row["column_name"]
        for row in cur.fetchall()
    }
finally:
    conn.close()

def subscription_until_value(user):
return user.get(“subscription_until”) if user else None

def parse_datetime(value):
if not value:
return None

if isinstance(value, datetime):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
text = str(value).strip()
try:
    return datetime.fromisoformat(
        text.replace("Z", "+00:00")
    )
except Exception:
    return None

def is_active(user):
if not user:
return False

until = parse_datetime(
    subscription_until_value(user)
)
if not until:
    return False
return until > datetime.now(timezone.utc)

def days_left(user):
if not user:
return 0

until = parse_datetime(
    subscription_until_value(user)
)
if not until:
    return 0
seconds = (
    until - datetime.now(timezone.utc)
).total_seconds()
if seconds <= 0:
    return 0
return max(1, int(seconds / 86400))

def format_date(value):
dt = parse_datetime(value)

if not dt:
    return "—"
return dt.strftime("%d.%m.%Y")

============================================================

SUBSCRIPTION

============================================================

def subscription_url(user_id):
token = f”{SUBSCRIPTION_PREFIX}{int(user_id)}”

return (
    f"{PUBLIC_SITE_URL}/sub/"
    f"{quote(token, safe='')}"
)

def github_user_path(user_id):
return f”users/{int(user_id)}.txt”

def github_headers():
headers = {
“Accept”: “application/vnd.github+json”,
“X-GitHub-Api-Version”: “2022-11-28”,
}

if GITHUB_TOKEN:
    headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
return headers

def github_get_file(path):
url = (
f”https://api.github.com/repos/”
f”{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}”
)

response = requests.get(
    url,
    headers=github_headers(),
    params={"ref": GITHUB_BRANCH},
    timeout=20,
)
if response.status_code == 404:
    return None
response.raise_for_status()
return response.json()

def github_write_file(path, content, message):
if not GITHUB_TOKEN:
return False

existing = github_get_file(path)
payload = {
    "message": message,
    "content": base64.b64encode(
        content.encode("utf-8")
    ).decode("ascii"),
    "branch": GITHUB_BRANCH,
}
if existing and existing.get("sha"):
    payload["sha"] = existing["sha"]
url = (
    f"https://api.github.com/repos/"
    f"{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
)
response = requests.put(
    url,
    headers=github_headers(),
    json=payload,
    timeout=30,
)
response.raise_for_status()
return True

def read_github_text(path):
item = github_get_file(path)

if not item:
    return ""
encoded = item.get("content", "")
if not encoded:
    return ""
try:
    return base64.b64decode(
        encoded.replace("\n", "")
    ).decode("utf-8")
except Exception:
    return ""

def active_subscription_content(user_id, until):
servers = read_github_text(“servers.txt”).strip()

date_text = format_date(until)
header = (
    f"#profile-title: {PROFILE_TITLE}\n"
    f"#profile-update-interval: 1\n"
    f"#subscription-userinfo: "
    f"upload=0; download=0; total=0\n"
    f"#hide-settings: true\n"
    f"#announce: "
    f"🟢 Подписка активна • до {date_text} "
    f"• ☂️ ixxy VPN\n\n"
)
return header + servers

def inactive_subscription_content():
return (
f”#profile-title: {PROFILE_TITLE}\n”
f”#profile-update-interval: 1\n”
f”#subscription-userinfo: “
f”upload=0; download=0; total=0\n”
f”#hide-settings: true\n”
f”#announce: “
f”🔴 Подписка не активна • “
f”Продлите подписку на сайте ixxy VPN\n”
)

def save_subscription_everywhere(user_id):
user = get_user(user_id)

if not user:
    return False
until = subscription_until_value(user)
if is_active(user):
    content = active_subscription_content(
        user_id,
        until,
    )
else:
    content = inactive_subscription_content()
link = subscription_url(user_id)
columns = get_user_columns()
conn = db()
try:
    cur = conn.cursor()
    updates = []
    values = []
    if "subscription_link" in columns:
        updates.append("subscription_link = %s")
        values.append(link)
    if "subscription_content" in columns:
        updates.append("subscription_content = %s")
        values.append(content)
    if "subscription" in columns:
        updates.append("subscription = %s")
        values.append(
            "active" if is_active(user) else "inactive"
        )
    if updates:
        values.append(int(user_id))
        cur.execute(
            f"""
            UPDATE users
            SET {", ".join(updates)}
            WHERE user_id = %s
            """,
            values,
        )
    conn.commit()
finally:
    conn.close()
try:
    github_write_file(
        github_user_path(user_id),
        content,
        f"ixxy: update subscription {user_id}",
    )
except Exception as e:
    print(
        "GitHub sync error:",
        repr(e),
    )
return True

============================================================

TELEGRAM LOGIN

============================================================

def verify_telegram_login(data):
if not BOT_TOKEN:
return False, “BOT_TOKEN не задан”

received_hash = str(
    data.get("hash", "")
).strip()
if not received_hash:
    return False, "Нет Telegram hash"
auth_date = str(
    data.get("auth_date", "")
).strip()
if not auth_date.isdigit():
    return False, "Неверный auth_date"
try:
    auth_timestamp = int(auth_date)
except Exception:
    return False, "Неверный auth_date"
now = int(
    datetime.now(timezone.utc).timestamp()
)
if abs(now - auth_timestamp) > 86400:
    return False, "Данные Telegram устарели"
check_items = []
for key in sorted(data.keys()):
    if key == "hash":
        continue
    value = data[key]
    if value is None:
        continue
    check_items.append(
        f"{key}={value}"
    )
data_check_string = "\n".join(check_items)
secret_key = hashlib.sha256(
    BOT_TOKEN.encode("utf-8")
).digest()
calculated_hash = hmac.new(
    secret_key,
    data_check_string.encode("utf-8"),
    hashlib.sha256,
).hexdigest()
if not hmac.compare_digest(
    calculated_hash,
    received_hash,
):
    return False, "Неверная подпись Telegram"
return True, ""

@app.route(”/auth/telegram”, methods=[“POST”])
def telegram_auth():
data = request.get_json(silent=True) or {}

ok, error = verify_telegram_login(data)
if not ok:
    return {
        "ok": False,
        "error": error,
    }, 403
telegram_id = data.get("id")
if not str(telegram_id).isdigit():
    return {
        "ok": False,
        "error": "Неверный Telegram ID",
    }, 400
telegram_id = int(telegram_id)
user = get_user(telegram_id)
if not user:
    return {
        "ok": False,
        "error": (
            "Пользователь не найден в базе ixxy. "
            "Сначала оформите подписку."
        ),
    }, 404
if "blocked" in user and user["blocked"]:
    return {
        "ok": False,
        "error": "Ваш аккаунт заблокирован.",
    }, 403
session.clear()
session["telegram_id"] = telegram_id
session["telegram_username"] = (
    data.get("username") or ""
)
return {
    "ok": True,
    "redirect": "/cabinet",
}

============================================================

AUTH HELPERS

============================================================

def current_user():
telegram_id = session.get(“telegram_id”)

if not telegram_id:
    return None
try:
    return get_user(int(telegram_id))
except Exception:
    return None

def require_user():
user = current_user()

if not user:
    return redirect("/login")
return user

def is_admin():
telegram_id = session.get(“telegram_id”)

if not telegram_id:
    return False
return int(telegram_id) in ADMIN_IDS

============================================================

HTML

============================================================

def page(title, body):
return f”””
<!doctype html>

<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,
      initial-scale=1,
      maximum-scale=1">
<meta name="theme-color" content="#07040d">
<title>{html.escape(title)}</title>
<style>
:root {{
    --bg:#07040d;
    --card:rgba(25,18,38,.72);
    --line:rgba(190,130,255,.18);
    --purple:#9b5cff;
    --purple2:#c08cff;
    --text:#fff;
    --muted:#9c94a8;
}}
* {{
    box-sizing:border-box;
    -webkit-tap-highlight-color:transparent;
}}
html,body {{
    margin:0;
    min-height:100%;
    background:
        radial-gradient(
            circle at 50% -10%,
            rgba(155,92,255,.30),
            transparent 38%
        ),
        linear-gradient(
            180deg,
            #0d0716,
            #07040d 70%
        );
    color:var(--text);
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "SF Pro Display",
        Inter,
        Arial,
        sans-serif;
}}
body {{
    min-height:100vh;
}}
.wrap {{
    width:min(100% - 28px, 650px);
    margin:auto;
    padding:24px 0 40px;
}}
.header {{
    display:flex;
    justify-content:space-between;
    align-items:center;
    margin-bottom:24px;
}}
.brand {{
    display:flex;
    align-items:center;
    gap:11px;
    font-weight:900;
    font-size:20px;
}}
.logo {{
    width:44px;
    height:44px;
    display:grid;
    place-items:center;
    border-radius:15px;
    background:
        linear-gradient(
            145deg,
            #a65cff,
            #5e27a7
        );
    box-shadow:
        0 10px 35px
        rgba(155,92,255,.28);
    font-size:21px;
    font-weight:1000;
}}
.card {{
    margin-top:14px;
    padding:21px;
    border:1px solid var(--line);
    border-radius:25px;
    background:var(--card);
    backdrop-filter:blur(25px);
    box-shadow:
        0 20px 70px
        rgba(0,0,0,.30);
}}
.hero {{
    text-align:center;
    padding:30px 10px 20px;
}}
.hero h1 {{
    margin:0 0 10px;
    font-size:42px;
    line-height:1.03;
    letter-spacing:-2px;
}}
.hero p {{
    margin:0;
    color:var(--muted);
    line-height:1.5;
}}
.label {{
    color:#8f849d;
    font-size:11px;
    text-transform:uppercase;
    letter-spacing:1px;
    font-weight:800;
}}
.status {{
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:10px;
}}
.badge {{
    padding:8px 12px;
    border-radius:999px;
    background:rgba(155,92,255,.14);
    border:1px solid rgba(155,92,255,.20);
    font-size:12px;
    font-weight:800;
}}
.badge.off {{
    background:rgba(255,255,255,.06);
    border-color:rgba(255,255,255,.08);
}}
.big {{
    margin:18px 0;
    font-size:34px;
    font-weight:950;
    letter-spacing:-1.5px;
}}
.grid {{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:10px;
}}
.stat {{
    padding:15px;
    border-radius:17px;
    background:rgba(255,255,255,.045);
    border:1px solid rgba(255,255,255,.06);
}}
.stat small {{
    display:block;
    color:#847b90;
    margin-bottom:7px;
    font-size:10px;
    text-transform:uppercase;
    letter-spacing:.8px;
}}
.stat b {{
    font-size:16px;
}}
.btn {{
    width:100%;
    min-height:53px;
    border:0;
    border-radius:17px;
    display:flex;
    align-items:center;
    justify-content:center;
    text-decoration:none;
    cursor:pointer;
    font-weight:900;
    font-size:14px;
    background:
        linear-gradient(
            135deg,
            #b56aff,
            #7735ca
        );
    color:white;
    box-shadow:
        0 14px 35px
        rgba(125,53,202,.28);
}}
.btn.secondary {{
    margin-top:9px;
    background:rgba(255,255,255,.055);
    border:1px solid rgba(255,255,255,.09);
    box-shadow:none;
}}
.btn.white {{
    background:#fff;
    color:#08050d;
    box-shadow:none;
}}
.actions {{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:9px;
    margin-top:9px;
}}
.url {{
    display:flex;
    gap:7px;
    padding:6px;
    border-radius:16px;
    background:#08050d;
    border:1px solid rgba(255,255,255,.08);
}}
.url input {{
    min-width:0;
    flex:1;
    border:0;
    outline:0;
    background:transparent;
    color:#938a9d;
    padding:10px;
    font-size:11px;
}}
.copy {{
    border:0;
    border-radius:11px;
    padding:0 13px;
    background:#fff;
    color:#000;
    font-weight:900;
    cursor:pointer;
}}
.price {{
    display:flex;
    justify-content:space-between;
    align-items:center;
    padding:16px;
    margin-top:9px;
    border-radius:17px;
    background:rgba(255,255,255,.045);
    border:1px solid rgba(255,255,255,.07);
}}
.price b {{
    font-size:18px;
}}
.price span {{
    color:#aaa0b4;
    font-size:12px;
}}
.footer {{
    text-align:center;
    color:#62596b;
    font-size:10px;
    padding:25px 0 5px;
}}
.error {{
    margin-top:12px;
    padding:13px;
    border-radius:15px;
    background:rgba(255,60,90,.08);
    border:1px solid rgba(255,60,90,.15);
    color:#ffb7c2;
    font-size:12px;
    line-height:1.45;
}}
.ok {{
    margin-top:12px;
    padding:13px;
    border-radius:15px;
    background:rgba(100,255,180,.07);
    border:1px solid rgba(100,255,180,.12);
    color:#baffd9;
    font-size:12px;
}}
@media(max-width:430px) {{
    .hero h1 {{
        font-size:36px;
    }}
}}
</style>
</head>
<body>
<div class="wrap">
<header class="header">
    <div class="brand">
        <div class="logo">☂</div>
        <span>ixxy VPN</span>
    </div>
</header>

{body}

<footer class="footer">
    ixxy VPN · Быстро. Приватно. Без лишнего.
</footer>
</div>
</body>
</html>
"""

============================================================

HOME

============================================================

@app.route(”/”)
def index():
user = current_user()

if user:
    return redirect("/cabinet")
body = f"""
<section class="hero">
    <div class="label">PRIVATE VPN</div>
    <h1>☂️ ixxy VPN</h1>
    <p>
        Личный кабинет, подписка и подключение
        в одном месте.
    </p>
</section>
<div class="card">
    <div class="label">Личный кабинет</div>
<h2 style="margin:10px 0 8px">
    Войдите через Telegram
</h2>
<p style="color:#9c94a8;line-height:1.5">
    Если у вас уже есть аккаунт и подписка
    ixxy VPN, сайт автоматически найдёт
    ваш профиль.
</p>
<div style="margin-top:20px;text-align:center">
    <script async
        src="https://telegram.org/js/telegram-widget.js?22"
        data-telegram-login="{html.escape(TELEGRAM_BOT_USERNAME)}"
        data-size="large"
        data-userpic="false"
        data-request-access="write"
        data-onauth="onTelegramAuth(user)">
    </script>
</div>
</div>
<div class="card">
    <div class="label">Тарифы</div>
<div class="price">
    <span>1 месяц</span>
    <b>129 ₽</b>
</div>
<div class="price">
    <span>3 месяца</span>
    <b>379 ₽</b>
</div>
<div class="price">
    <span>6 месяцев</span>
    <b>659 ₽</b>
</div>
<div class="price">
    <span>12 месяцев</span>
    <b>1089 ₽</b>
</div>
</div>
<script>
function onTelegramAuth(user) {{
    fetch("/auth/telegram", {{
        method:"POST",
        headers:{{
            "Content-Type":"application/json"
        }},
        body:JSON.stringify(user)
    }})
    .then(r => r.json())
    .then(data => {{
        if (data.ok) {{
            location.href = data.redirect;
        }} else {{
            alert(data.error || "Ошибка авторизации");
        }}
    }})
    .catch(() => {{
        alert("Ошибка соединения с сайтом");
    }});
}}
</script>

“””

return page("ixxy VPN", body)

============================================================

LOGIN

============================================================

@app.route(”/login”)
def login():
return redirect(”/”)

============================================================

CABINET

============================================================

@app.route(”/cabinet”)
def cabinet():
user = current_user()

if not user:
    return redirect("/login")
user_id = int(user["user_id"])
first_name = (
    user.get("first_name")
    or user.get("username")
    or "Пользователь"
)
active = is_active(user)
until = user.get("subscription_until")
days = days_left(user)
tariff = (
    user.get("subscription")
    or "ixxy VPN"
)
sub_url = subscription_url(user_id)
status = "Активна" if active else "Неактивна"
body = f"""
<section class="hero">
    <div class="label">Личный кабинет</div>
<h1>
    Привет, {html.escape(str(first_name))}
</h1>
<p>
    Ваша подписка ixxy VPN
</p>
</section>
<div class="card">
<div class="status">
    <div class="label">
        Состояние подписки
    </div>
    <div class="badge {' ' if active else 'off'}">
        {'🟢' if active else '🔴'} {status}
    </div>
</div>
<div class="big">
    {days if active else 0} дн.
</div>
<div class="grid">
    <div class="stat">
        <small>Тариф</small>
        <b>{html.escape(str(tariff))}</b>
    </div>
    <div class="stat">
        <small>Действует до</small>
        <b>{format_date(until)}</b>
    </div>
</div>
</div>
<div class="card">
<div class="label">
    Подключение
</div>
<h2 style="margin:9px 0">
    Ваша подписка
</h2>
<p style="color:#9c94a8;line-height:1.5">
    Серверы, UUID, Reality и другие
    технические параметры здесь не отображаются.
</p>
<div class="url">
    <input
        id="sub"
        readonly
        value="{html.escape(sub_url, quote=True)}"
    >
    <button
        class="copy"
        onclick="copySub()">
        COPY
    </button>
</div>
<a
    class="btn"
    style="margin-top:10px"
    href="https://happ.vpnbypass.click/?url={quote(sub_url, safe='')}"
>
    Подключить через Happ
</a>
<div class="actions">
    <a
        class="btn secondary"
        href="incy://add/{quote(sub_url, safe='')}"
    >
        INCY
    </a>
    <button
        class="btn secondary"
        onclick="copySub()"
    >
        Скопировать
    </button>
</div>
</div>
<div class="card">
<div class="label">
    Продление
</div>
<h2 style="margin:9px 0">
    Выберите тариф
</h2>
<a class="price"
   style="text-decoration:none;color:white"
   href="/buy/30">
    <span>1 месяц</span>
    <b>129 ₽</b>
</a>
<a class="price"
   style="text-decoration:none;color:white"
   href="/buy/90">
    <span>3 месяца</span>
    <b>379 ₽</b>
</a>
<a class="price"
   style="text-decoration:none;color:white"
   href="/buy/180">
    <span>6 месяцев</span>
    <b>659 ₽</b>
</a>
<a class="price"
   style="text-decoration:none;color:white"
   href="/buy/365">
    <span>12 месяцев</span>
    <b>1089 ₽</b>
</a>
</div>
<div class="card">
<div class="label">
    Поддержка
</div>
<p style="color:#9c94a8;line-height:1.5">
    Если возникла проблема с подключением,
    напишите в поддержку.
</p>
<a
    class="btn white"
    href="{html.escape(TELEGRAM_URL, quote=True)}"
>
    Открыть поддержку
</a>
</div>
<script>
function copySub() {{
    const input = document.getElementById("sub");
    navigator.clipboard.writeText(input.value)
        .then(() => alert("Ссылка скопирована"));
}}
</script>

“””

return page(
    "Личный кабинет — ixxy VPN",
    body,
)

============================================================

BUY

============================================================

@app.route(”/buy/int:days”)
def buy(days):
user = current_user()

if not user:
    return redirect("/login")
if days not in TARIFFS:
    abort(404)
amount = TARIFFS[days]
user_id = int(user["user_id"])
external_id = (
    f"ixxy-{user_id}-"
    f"{days}-"
    f"{secrets.token_hex(8)}"
)
callback_url = (
    f"{PUBLIC_SITE_URL}/cashera/webhook"
)
success_url = (
    f"{PUBLIC_SITE_URL}/cabinet"
)
fail_url = (
    f"{PUBLIC_SITE_URL}/cabinet"
)
try:
    payment = create_payment(
        amount_rub=amount,
        external_id=external_id,
        description=(
            f"ixxy VPN — {days} дней"
        ),
        callback_url=callback_url,
        success_url=success_url,
        fail_url=fail_url,
        user_id=user_id,
        days=days,
    )
except CasheraError as e:
    error = html.escape(
        str(e)
    )
    body = f"""
<div class="hero">
    <div class="label">CasheRa</div>
    <h1>Ошибка оплаты</h1>
    <p>
        CasheRa вернула ошибку
        HTTP {e.status_code}.
    </p>
</div>
<div class="card">
    <div class="error">
        {error}
    </div>
<a
    class="btn secondary"
    href="/cabinet"
>
    Вернуться в кабинет
</a>
</div>
"""
    return page(
        "Ошибка оплаты",
        body,
    ), 422
except Exception as e:
    body = f"""
<div class="hero">
    <h1>Ошибка</h1>
    <p>Не удалось создать платеж.</p>
</div>
<div class="card">
    <div class="error">
        {html.escape(str(e))}
    </div>
<a
    class="btn secondary"
    href="/cabinet"
>
    Вернуться
</a>
</div>
"""
    return page(
        "Ошибка",
        body,
    ), 500
# --------------------------------------------------------
# SAVE PAYMENT IN EXISTING BOT PAYMENTS TABLE
# --------------------------------------------------------
try:
    save_payment(
        user_id,
        amount,
        days,
        external_id,
    )
except Exception as e:
    print(
        "Payment DB save error:",
        repr(e),
    )
# --------------------------------------------------------
# EXTRACT PAYMENT URL
# --------------------------------------------------------
payment_url = extract_payment_url(
    payment
)
if not payment_url:
    body = f"""
<div class="hero">
    <h1>Платёж создан</h1>
    <p>
        Но CasheRa не вернула ссылку
        на оплату.
    </p>
</div>
<div class="card">
    <div class="error">
        Ответ CasheRa:<br><br>
        {html.escape(
            json.dumps(
                payment,
                ensure_ascii=False,
                indent=2,
            )
        )}
    </div>
<a
    class="btn secondary"
    href="/cabinet"
>
    Вернуться
</a>
</div>
"""
    return page(
        "Платёж",
        body,
    )
return redirect(payment_url)

def extract_payment_url(data):
if not isinstance(data, dict):
return None

possible = [
    data.get("payment_url"),
    data.get("checkout_url"),
    data.get("url"),
]
payment = data.get("payment")
if isinstance(payment, dict):
    possible.extend([
        payment.get("payment_url"),
        payment.get("checkout_url"),
        payment.get("url"),
    ])
for value in possible:
    if isinstance(value, str) and value.startswith("http"):
        return value
return None

============================================================

PAYMENT DATABASE

============================================================

def save_payment(
user_id,
amount,
days,
external_id,
):
conn = db()

try:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'payments'
        """
    )
    columns = {
        row["column_name"]
        for row in cur.fetchall()
    }
    fields = []
    values = []
    placeholders = []
    mapping = [
        ("user_id", user_id),
        ("amount", amount),
        ("days", days),
        ("external_id", external_id),
    ]
    for column, value in mapping:
        if column in columns:
            fields.append(column)
            values.append(value)
            placeholders.append("%s")
    if "status" in columns:
        fields.append("status")
        values.append("pending")
        placeholders.append("%s")
    if not fields:
        conn.commit()
        return
    cur.execute(
        f"""
        INSERT INTO payments
        ({", ".join(fields)})
        VALUES ({", ".join(placeholders)})
        """,
        values,
    )
    conn.commit()
finally:
    conn.close()

============================================================

WEBHOOK

============================================================

@app.route(
“/cashera/webhook”,
methods=[“POST”]
)
def cashera_webhook():

if not verify_webhook(request.headers):
    return {
        "ok": False,
        "error": "invalid signature",
    }, 401
data = request.get_json(
    silent=True
) or {}
print(
    "CasheRa webhook:",
    json.dumps(
        data,
        ensure_ascii=False,
    ),
)
event = data.get("event")
if event != "transaction.status_updated":
    return {
        "ok": True,
        "ignored": True,
    }
transaction = (
    data.get("transaction")
    or data.get("data")
    or {}
)
if not isinstance(transaction, dict):
    transaction = {}
status = str(
    transaction.get("status")
    or data.get("status")
    or ""
).lower()
if status != "paid":
    return {
        "ok": True,
        "status": status,
    }
external_id = (
    transaction.get("external_id")
    or data.get("external_id")
)
if not external_id:
    return {
        "ok": False,
        "error": "external_id missing",
    }, 400
payment = get_local_payment(
    external_id
)
if not payment:
    return {
        "ok": False,
        "error": "payment not found",
    }, 404
user_id = int(
    payment["user_id"]
)
days = int(
    payment["days"]
)
# --------------------------------------------------------
# ANTI DOUBLE PAYMENT
# --------------------------------------------------------
if is_payment_processed(
    external_id
):
    return {
        "ok": True,
        "already_processed": True,
    }
# --------------------------------------------------------
# EXTEND USER
# --------------------------------------------------------
extend_user(
    user_id,
    days,
)
# --------------------------------------------------------
# MARK PAYMENT
# --------------------------------------------------------
mark_payment_paid(
    external_id
)
mark_payment_processed(
    external_id,
    user_id,
    days,
    int(payment.get("amount") or 0),
)
# --------------------------------------------------------
# UPDATE SUBSCRIPTION
# --------------------------------------------------------
save_subscription_everywhere(
    user_id
)
return {
    "ok": True,
    "processed": True,
    "user_id": user_id,
    "days": days,
}

def get_local_payment(external_id):
conn = db()

try:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM payments
        WHERE external_id = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (external_id,),
    )
    return cur.fetchone()
finally:
    conn.close()

def is_payment_processed(external_id):
conn = db()

try:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1
        FROM web_processed_payments
        WHERE external_id = %s
        LIMIT 1
        """,
        (external_id,),
    )
    return cur.fetchone() is not None
finally:
    conn.close()

def mark_payment_processed(
external_id,
user_id,
days,
amount,
):
conn = db()

try:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO web_processed_payments
        (
            external_id,
            user_id,
            days,
            amount
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (external_id)
        DO NOTHING
        """,
        (
            external_id,
            user_id,
            days,
            amount,
        ),
    )
    conn.commit()
finally:
    conn.close()

def mark_payment_paid(external_id):
conn = db()

try:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE payments
        SET status = 'paid',
            paid_at = NOW()
        WHERE external_id = %s
        """,
        (external_id,),
    )
    conn.commit()
finally:
    conn.close()

============================================================

EXTEND USER

============================================================

def extend_user(user_id, days):
conn = db()

try:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT subscription_until
        FROM users
        WHERE user_id = %s
        FOR UPDATE
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(
            "Пользователь не найден"
        )
    old_until = parse_datetime(
        row["subscription_until"]
    )
    now = datetime.now(
        timezone.utc
    )
    if old_until and old_until > now:
        base = old_until
    else:
        base = now
    new_until = (
        base + timedelta(days=days)
    )
    columns = get_user_columns()
    updates = [
        "subscription_until = %s"
    ]
    values = [
        new_until
    ]
    if "subscription" in columns:
        updates.append(
            "subscription = %s"
        )
        values.append(
            f"{days} days"
        )
    if "subscription_link" in columns:
        updates.append(
            "subscription_link = %s"
        )
        values.append(
            subscription_url(user_id)
        )
    values.append(user_id)
    cur.execute(
        f"""
        UPDATE users
        SET {", ".join(updates)}
        WHERE user_id = %s
        """,
        values,
    )
    conn.commit()
finally:
    conn.close()

============================================================

ADMIN

============================================================

@app.route(”/admin”)
def admin():
if not is_admin():
return redirect(”/cabinet”)

conn = db()
try:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS count FROM users"
    )
    users_count = cur.fetchone()["count"]
    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM users
        WHERE subscription_until > NOW()
        """
    )
    active_count = cur.fetchone()["count"]
    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM payments
        WHERE status = 'paid'
        """
    )
    paid_count = cur.fetchone()["count"]
finally:
    conn.close()
body = f"""
<div class="hero">
    <div class="label">Администратор</div>
    <h1>ixxy VPN</h1>
    <p>Панель управления сайтом</p>
</div>
<div class="card">
<div class="grid">
    <div class="stat">
        <small>Пользователи</small>
        <b>{users_count}</b>
    </div>
    <div class="stat">
        <small>Активные</small>
        <b>{active_count}</b>
    </div>
    <div class="stat">
        <small>Оплаты</small>
        <b>{paid_count}</b>
    </div>
    <div class="stat">
        <small>Сервис</small>
        <b>ONLINE</b>
    </div>
</div>
</div>
<div class="card">
<div class="label">Пользователь</div>
<form method="get" action="/admin/user">
    <input
        name="id"
        inputmode="numeric"
        placeholder="Telegram ID"
        style="
            width:100%;
            padding:15px;
            margin-top:10px;
            border-radius:15px;
            border:1px solid rgba(255,255,255,.1);
            background:#0b0711;
            color:white;
        "
    >
    <button
        class="btn"
        style="margin-top:9px"
    >
        Найти
    </button>
</form>
</div>
"""
return page(
    "Админка — ixxy VPN",
    body,
)

@app.route(”/admin/user”)
def admin_user():
if not is_admin():
return redirect(”/cabinet”)

raw_id = request.args.get("id", "")
if not raw_id.isdigit():
    return redirect("/admin")
user_id = int(raw_id)
user = get_user(user_id)
if not user:
    return page(
        "Пользователь",
        """
        <div class="hero">
            <h1>Не найден</h1>
            <p>Пользователь отсутствует в базе.</p>
        </div>
        """,
    )
first_name = (
    user.get("first_name")
    or user.get("username")
    or str(user_id)
)
body = f"""
<div class="hero">
    <div class="label">Пользователь</div>
    <h1>{html.escape(str(first_name))}</h1>
    <p>ID: {user_id}</p>
</div>
<div class="card">
<div class="grid">
    <div class="stat">
        <small>Статус</small>
        <b>
            {'Активна' if is_active(user)
             else 'Неактивна'}
        </b>
    </div>
    <div class="stat">
        <small>До</small>
        <b>
            {format_date(
                user.get("subscription_until")
            )}
        </b>
    </div>
</div>
</div>
<div class="card">
<div class="label">Выдать дни</div>
<div class="actions">
    <a
        class="btn"
        href="/admin/grant/{user_id}/30"
    >
        +30
    </a>
    <a
        class="btn"
        href="/admin/grant/{user_id}/90"
    >
        +90
    </a>
</div>
<div class="actions">
    <a
        class="btn secondary"
        href="/admin/grant/{user_id}/180"
    >
        +180
    </a>
    <a
        class="btn secondary"
        href="/admin/grant/{user_id}/365"
    >
        +365
    </a>
</div>
</div>
<div class="card">
<a
    class="btn secondary"
    href="/admin/sync/{user_id}"
>
    Синхронизировать подписку
</a>
</div>
"""
return page(
    "Пользователь — ixxy VPN",
    body,
)

@app.route(
“/admin/grant/int:user_id/int:days”
)
def admin_grant(user_id, days):
if not is_admin():
return redirect(”/cabinet”)

if days <= 0 or days > 9999:
    abort(400)
extend_user(
    user_id,
    days,
)
save_subscription_everywhere(
    user_id
)
return redirect(
    f"/admin/user?id={user_id}"
)

@app.route(
“/admin/sync/int:user_id”
)
def admin_sync(user_id):
if not is_admin():
return redirect(”/cabinet”)

save_subscription_everywhere(
    user_id
)
return redirect(
    f"/admin/user?id={user_id}"
)

============================================================

SUBSCRIPTION URL

============================================================

def parse_subscription_token(token):
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
return int(raw)

@app.route(”/s/”)
def subscription_page(token):
user_id = parse_subscription_token(
token
)

if user_id is None:
    abort(404)
user = get_user(user_id)
if not user:
    abort(404)
first_name = (
    user.get("first_name")
    or user.get("username")
    or "Пользователь"
)
body = f"""
<div class="hero">
    <div class="label">ixxy VPN</div>
    <h1>
        {html.escape(str(first_name))}
    </h1>
    <p>
        Персональная подписка
    </p>
</div>
<div class="card">
<div class="status">
    <div class="label">
        Состояние
    </div>
    <div class="badge">
        {'🟢 Активна' if is_active(user)
         else '🔴 Неактивна'}
    </div>
</div>
<div class="big">
    {days_left(user) if is_active(user)
     else 0} дн.
</div>
<div class="grid">
    <div class="stat">
        <small>Действует до</small>
        <b>
            {format_date(
                user.get("subscription_until")
            )}
        </b>
    </div>
    <div class="stat">
        <small>ID</small>
        <b>{user_id}</b>
    </div>
</div>
</div>
"""
return page(
    "Подписка — ixxy VPN",
    body,
)

@app.route(”/sub/”)
def subscription(token):
user_id = parse_subscription_token(
token
)

if user_id is None:
    abort(404)
user = get_user(user_id)
if not user:
    abort(404)
content = user.get(
    "subscription_content"
)
if not content:
    if is_active(user):
        content = active_subscription_content(
            user_id,
            user.get("subscription_until"),
        )
    else:
        content = inactive_subscription_content()
response = Response(
    content,
    mimetype="text/plain; charset=utf-8",
)
response.headers.update(
    NO_CACHE_HEADERS
)
return response

============================================================

HEALTH

============================================================

@app.route(”/health”)
def health():
return {
“service”: “ixxy VPN”,
“status”: “ok”,
}

============================================================

LOGOUT

============================================================

@app.route(”/logout”)
def logout():
session.clear()
return redirect(”/”)

============================================================

ERROR

============================================================

@app.errorhandler(404)
def not_found(error):
return Response(
“Not Found”,
status=404,
mimetype=“text/plain”,
)

============================================================

START

============================================================

try:
ensure_web_table()
except Exception as e:
print(
“Database initialization warning:”,
repr(e),
)

if name == “main”:
port = int(
os.getenv(“PORT”, “10000”)
)

app.run(
    host="0.0.0.0",
    port=port,
    debug=False,
)