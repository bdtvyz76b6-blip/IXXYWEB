import os
import html
import hmac
import hashlib
import secrets
import base64
from datetime import datetime, timezone

import requests
from flask import (
Flask,
request,
redirect,
session,
Response,
)

from dotenv import load_dotenv

from database import (
init_db,
get_user,
subscription_active,
days_left,
format_date,
extend_subscription,
update_subscription_data,
create_payment,
get_payment_by_external_id,
mark_payment_paid,
payment_processed,
mark_payment_processed,
get_stats,
)

from cashera_api import (
create_payment as cashera_create_payment,
verify_webhook,
CasheraError,
)

load_dotenv()

app = Flask(name)

============================================================

CONFIG

============================================================

BOT_TOKEN = os.getenv(
“BOT_TOKEN”,
“”,
).strip()

TELEGRAM_BOT_USERNAME = os.getenv(
“TELEGRAM_BOT_USERNAME”,
“”,
).strip().lstrip(”@”)

DATABASE_URL = os.getenv(
“DATABASE_URL”,
“”,
).strip()

PUBLIC_SITE_URL = os.getenv(
“PUBLIC_SITE_URL”,
“https://ixxyweb.onrender.com”,
).rstrip(”/”)

SUBSCRIPTION_PREFIX = os.getenv(
“SUBSCRIPTION_PREFIX”,
“2ix847xy”,
).strip()

GITHUB_TOKEN = os.getenv(
“GITHUB_TOKEN”,
“”,
).strip()

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

for value in os.getenv(
“ADMIN_IDS”,
“”,
).split(”,”):

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

SECRET

============================================================

SECRET = os.getenv(
“WEB_SECRET_KEY”,
“”,
).strip()

if not SECRET:

if BOT_TOKEN:
    SECRET = hashlib.sha256(
        (
            "ixxy-web:"
            + BOT_TOKEN
        ).encode()
    ).hexdigest()
else:
    SECRET = secrets.token_hex(32)

app.secret_key = SECRET

app.config[
“SESSION_COOKIE_HTTPONLY”
] = True

app.config[
“SESSION_COOKIE_SECURE”
] = True

app.config[
“SESSION_COOKIE_SAMESITE”
] = “Lax”

============================================================

GITHUB

============================================================

def github_headers():

result = {
    "Accept":
        "application/vnd.github+json",
    "X-GitHub-Api-Version":
        "2022-11-28",
}
if GITHUB_TOKEN:
    result["Authorization"] = (
        f"Bearer {GITHUB_TOKEN}"
    )
return result

def github_file(path):

url = (
    "https://api.github.com/repos/"
    f"{GITHUB_OWNER}/"
    f"{GITHUB_REPO}/contents/{path}"
)
response = requests.get(
    url,
    headers=github_headers(),
    params={
        "ref": GITHUB_BRANCH
    },
    timeout=20,
)
if response.status_code == 404:
    return None
response.raise_for_status()
return response.json()

def github_text(path):

item = github_file(path)
if not item:
    return ""
content = item.get(
    "content",
    "",
)
if not content:
    return ""
try:
    return base64.b64decode(
        content.replace("\n", "")
    ).decode("utf-8")
except Exception:
    return ""

def github_write(path, content):

if not GITHUB_TOKEN:
    return
old = github_file(path)
payload = {
    "message":
        f"ixxy subscription update",
    "content":
        base64.b64encode(
            content.encode("utf-8")
        ).decode("ascii"),
    "branch":
        GITHUB_BRANCH,
}
if old and old.get("sha"):
    payload["sha"] = old["sha"]
url = (
    "https://api.github.com/repos/"
    f"{GITHUB_OWNER}/"
    f"{GITHUB_REPO}/contents/{path}"
)
response = requests.put(
    url,
    headers=github_headers(),
    json=payload,
    timeout=30,
)
response.raise_for_status()

============================================================

SUBSCRIPTION

============================================================

def subscription_url(user_id):

return (
    f"{PUBLIC_SITE_URL}/sub/"
    f"{SUBSCRIPTION_PREFIX}"
    f"{int(user_id)}"
)

def active_content(
user_id,
until,
):

servers = github_text(
    "servers.txt"
).strip()
return (
    f"#profile-title: "
    f"{PROFILE_TITLE}\n"
    f"#profile-update-interval: 1\n"
    f"#subscription-userinfo: "
    f"upload=0; download=0; total=0\n"
    f"#hide-settings: true\n"
    f"#announce: "
    f"🟢 Подписка активна • "
    f"до {format_date(until)} "
    f"• ☂️ ixxy VPN\n\n"
    f"{servers}"
)

def inactive_content():

return (
    f"#profile-title: "
    f"{PROFILE_TITLE}\n"
    f"#profile-update-interval: 1\n"
    f"#subscription-userinfo: "
    f"upload=0; download=0; total=0\n"
    f"#hide-settings: true\n"
    f"#announce: "
    f"🔴 Подписка не активна • "
    f"Продлите подписку на сайте "
    f"ixxy VPN\n"
)

def sync_subscription(user_id):

user = get_user(user_id)
if not user:
    return False
active = subscription_active(user)
if active:
    content = active_content(
        user_id,
        user.get(
            "subscription_until"
        ),
    )
    status = "active"
else:
    content = inactive_content()
    status = "inactive"
link = subscription_url(
    user_id
)
update_subscription_data(
    user_id=user_id,
    subscription=status,
    subscription_until=user.get(
        "subscription_until"
    ),
    subscription_link=link,
    subscription_content=content,
)
try:
    github_write(
        f"users/{int(user_id)}.txt",
        content,
    )
except Exception as e:
    print(
        "GitHub sync error:",
        repr(e),
    )
return True

============================================================

TELEGRAM AUTH

============================================================

def verify_telegram(data):

if not BOT_TOKEN:
    return False, "BOT_TOKEN не задан"
received_hash = str(
    data.get("hash", "")
)
auth_date = str(
    data.get("auth_date", "")
)
if not received_hash:
    return False, "Telegram hash отсутствует"
if not auth_date.isdigit():
    return False, "Неверный auth_date"
now = int(
    datetime.now(
        timezone.utc
    ).timestamp()
)
if abs(
    now - int(auth_date)
) > 86400:
    return False, (
        "Данные Telegram устарели"
    )
values = []
for key in sorted(data):
    if key == "hash":
        continue
    value = data[key]
    if value is None:
        continue
    values.append(
        f"{key}={value}"
    )
check_string = "\n".join(
    values
)
secret_key = hashlib.sha256(
    BOT_TOKEN.encode("utf-8")
).digest()
calculated = hmac.new(
    secret_key,
    check_string.encode("utf-8"),
    hashlib.sha256,
).hexdigest()
if not hmac.compare_digest(
    calculated,
    received_hash,
):
    return False, (
        "Неверная подпись Telegram"
    )
return True, ""

@app.route(
“/auth/telegram”,
methods=[“POST”],
)
def telegram_auth():

data = (
    request.get_json(
        silent=True
    )
    or {}
)
ok, error = verify_telegram(
    data
)
if not ok:
    return {
        "ok": False,
        "error": error,
    }, 403
telegram_id = data.get("id")
if not str(
    telegram_id
).isdigit():
    return {
        "ok": False,
        "error":
            "Неверный Telegram ID",
    }, 400
telegram_id = int(
    telegram_id
)
user = get_user(
    telegram_id
)
if not user:
    return {
        "ok": False,
        "error":
            "Пользователь не найден "
            "в базе ixxy VPN.",
    }, 404
session.clear()
session["telegram_id"] = (
    telegram_id
)
return {
    "ok": True,
    "redirect": "/cabinet",
}

def current_user():

user_id = session.get(
    "telegram_id"
)
if not user_id:
    return None
return get_user(
    int(user_id)
)

def admin_access():

user_id = session.get(
    "telegram_id"
)
if not user_id:
    return False
return int(user_id) in ADMIN_IDS

============================================================

HTML

============================================================

def page(title, body):

return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport"
content="width=device-width,initial-scale=1">
<meta name="theme-color"
content="#08050e">
<title>{html.escape(title)}</title>
<style>
* {{
box-sizing:border-box;
}}
body {{
margin:0;
background:
radial-gradient(
circle at top,
#32145b 0,
#0c0713 38%,
#050309 100%
);
color:white;
font-family:
-apple-system,
BlinkMacSystemFont,
Arial,sans-serif;
min-height:100vh;
}}
.wrap {{
width:min(650px,calc(100% - 24px));
margin:auto;
padding:22px 0 40px;
}}
.header {{
font-size:21px;
font-weight:900;
margin-bottom:18px;
}}
.logo {{
display:inline-flex;
width:43px;
height:43px;
align-items:center;
justify-content:center;
border-radius:15px;
background:
linear-gradient(135deg,#bd76ff,#6426a7);
margin-right:9px;
}}
.card {{
background:rgba(22,14,33,.82);
border:1px solid
rgba(190,120,255,.16);
border-radius:24px;
padding:20px;
margin-top:12px;
box-shadow:
0 20px 60px
rgba(0,0,0,.35);
}}
.hero {{
text-align:center;
padding:28px 8px;
}}
.hero h1 {{
font-size:38px;
margin:8px 0;
}}
.muted {{
color:#a59bad;
line-height:1.5;
}}
.label {{
font-size:11px;
letter-spacing:1px;
text-transform:uppercase;
color:#94869e;
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
border-radius:100px;
background:
rgba(145,75,255,.15);
font-size:12px;
font-weight:800;
}}
.big {{
font-size:36px;
font-weight:950;
margin:18px 0;
}}
.grid {{
display:grid;
grid-template-columns:1fr 1fr;
gap:9px;
}}
.stat {{
padding:14px;
border-radius:16px;
background:
rgba(255,255,255,.045);
}}
.stat small {{
display:block;
color:#81778b;
font-size:10px;
margin-bottom:6px;
}}
.btn {{
display:flex;
align-items:center;
justify-content:center;
width:100%;
min-height:52px;
border:0;
border-radius:16px;
margin-top:9px;
background:
linear-gradient(135deg,#bd70ff,#7031c0);
color:white;
text-decoration:none;
font-weight:900;
cursor:pointer;
}}
.secondary {{
background:
rgba(255,255,255,.055);
border:1px solid
rgba(255,255,255,.08);
}}
.price {{
display:flex;
justify-content:space-between;
align-items:center;
padding:16px;
margin-top:9px;
border-radius:16px;
background:
rgba(255,255,255,.045);
color:white;
text-decoration:none;
}}
.url {{
display:flex;
margin-top:12px;
background:#08050d;
border-radius:15px;
padding:5px;
}}
.url input {{
flex:1;
min-width:0;
background:transparent;
border:0;
outline:0;
color:#918799;
padding:10px;
font-size:11px;
}}
.copy {{
border:0;
border-radius:11px;
padding:0 13px;
font-weight:900;
}}
.error {{
padding:14px;
border-radius:15px;
background:
rgba(255,50,80,.08);
border:1px solid
rgba(255,50,80,.15);
color:#ffb8c3;
font-size:12px;
line-height:1.5;
}}
.footer {{
text-align:center;
color:#62596a;
font-size:10px;
margin-top:25px;
}}
</style>
</head>
<body>
<div class="wrap">
<div class="header">
<span class="logo">☂</span>
ixxy VPN
</div>

{body}

<div class="footer">
ixxy VPN
</div>
</div>
</body>
</html>"""

============================================================

HOME

============================================================

@app.route(”/”)
def index():

if current_user():
    return redirect(
        "/cabinet"
    )
body = f"""
<div class="hero">
<div class="label">
PRIVATE VPN
</div>
<h1>☂️ ixxy VPN</h1>
<p class="muted">
Личный кабинет и подписка
в одном месте.
</p>
</div>
<div class="card">
<div class="label">
Авторизация
</div>
<h2>
Войти через Telegram
</h2>
<p class="muted">
Войдите через Telegram.
Сайт найдёт ваш существующий
профиль ixxy VPN по Telegram ID.
</p>
<div style="text-align:center;margin-top:20px">
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
<div class="label">
Тарифы
</div>
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
if(data.ok) {{
location.href=data.redirect;
}} else {{
alert(data.error ||
"Ошибка авторизации");
}}
}})
.catch(() => {{
alert("Ошибка соединения");
}});
}}
</script>

“””

return page(
    "ixxy VPN",
    body,
)

============================================================

CABINET

============================================================

@app.route(”/cabinet”)
def cabinet():

user = current_user()
if not user:
    return redirect("/")
user_id = int(
    user["user_id"]
)
active = subscription_active(
    user
)
days = days_left(user)
until = user.get(
    "subscription_until"
)
link = subscription_url(
    user_id
)
name = (
    user.get("first_name")
    or user.get("username")
    or "Пользователь"
)
body = f"""
<div class="hero">
<div class="label">
Личный кабинет
</div>
<h1>
Привет, {html.escape(str(name))}
</h1>
<p class="muted">
☂️ ixxy VPN
</p>
</div>
<div class="card">
<div class="status">
<div class="label">
Подписка
</div>
<div class="badge">
{'🟢 Активна' if active
else '🔴 Неактивна'}
</div>
</div>
<div class="big">
{days if active else 0} дн.
</div>
<div class="grid">
<div class="stat">
<small>До</small>
<b>
{format_date(until)}
</b>
</div>
<div class="stat">
<small>Telegram ID</small>
<b>
{user_id}
</b>
</div>
</div>
</div>
<div class="card">
<div class="label">
Подключение
</div>
<h2>
Ваша подписка
</h2>
<p class="muted">
Технические параметры серверов
здесь не отображаются.
</p>
<div class="url">

COPY
</div>

Подключить через Happ
Открыть в INCY
</div>
<div class="card">
<div class="label">
Продление
</div>

1 месяц
129 ₽
3 месяца
379 ₽
6 месяцев
659 ₽
12 месяцев
1089 ₽
</div>
<div class="card">

Поддержка
Выйти
</div>
<script>
function copySub() {{
navigator.clipboard.writeText(
document.getElementById("sub").value
).then(() => {{
alert("Ссылка скопирована");
}});
}}
</script>

“””

return page(
    "Кабинет — ixxy VPN",
    body,
)

============================================================

BUY

============================================================

@app.route(”/buy/int:days”)
def buy(days):

user = current_user()
if not user:
    return redirect("/")
if days not in TARIFFS:
    return Response(
        "Tariff not found",
        status=404,
    )
user_id = int(
    user["user_id"]
)
amount = TARIFFS[days]
external_id = (
    f"ixxy-{user_id}-"
    f"{days}-"
    f"{secrets.token_hex(8)}"
)
try:
    payment = cashera_create_payment(
        amount_rub=amount,
        external_id=external_id,
        description=(
            f"ixxy VPN — {days} дней"
        ),
        callback_url=(
            f"{PUBLIC_SITE_URL}"
            "/cashera/webhook"
        ),
        success_url=(
            f"{PUBLIC_SITE_URL}"
            "/cabinet"
        ),
        fail_url=(
            f"{PUBLIC_SITE_URL}"
            "/cabinet"
        ),
        user_id=user_id,
        days=days,
    )
    create_payment(
        user_id=user_id,
        amount=amount,
        days=days,
        external_id=external_id,
    )
    url = extract_payment_url(
        payment
    )
    if not url:
        raise RuntimeError(
            "CasheRa не вернула "
            "ссылку на оплату"
        )
    return redirect(url)
except CasheraError as e:
    body = f"""
<div class="hero">
<h1>Ошибка оплаты</h1>
<p class="muted">
CasheRa вернула HTTP
{e.status_code}
</p>
</div>
<div class="card">
<div class="error">
{html.escape(str(e))}
</div>

Вернуться в кабинет
</div>
"""
    return page(
        "Ошибка CasheRa",
        body,
    ), 422
except Exception as e:
    body = f"""
<div class="hero">
<h1>Ошибка</h1>
</div>
<div class="card">
<div class="error">
{html.escape(str(e))}
</div>

Вернуться
</div>
"""
    return page(
        "Ошибка",
        body,
    ), 500

def extract_payment_url(data):

if not isinstance(
    data,
    dict,
):
    return None
keys = [
    "payment_url",
    "checkout_url",
    "url",
]
for key in keys:
    value = data.get(key)
    if (
        isinstance(value, str)
        and value.startswith("http")
    ):
        return value
for key in (
    "payment",
    "transaction",
    "data",
):
    nested = data.get(key)
    if isinstance(
        nested,
        dict,
    ):
        result = (
            extract_payment_url(
                nested
            )
        )
        if result:
            return result
return None

============================================================

CASHERA WEBHOOK

============================================================

@app.route(
“/cashera/webhook”,
methods=[“POST”],
)
def cashera_webhook():

if not verify_webhook(
    request.headers
):
    return {
        "ok": False,
        "error": "invalid signature",
    }, 401
data = (
    request.get_json(
        silent=True
    )
    or {}
)
print(
    "CasheRa webhook:",
    data,
)
event = data.get(
    "event"
)
if event != (
    "transaction.status_updated"
):
    return {
        "ok": True,
        "ignored": True,
    }
transaction = (
    data.get("transaction")
    or data.get("data")
    or data
)
status = str(
    transaction.get("status")
    or ""
).lower()
if status != "paid":
    return {
        "ok": True,
        "status": status,
    }
external_id = (
    transaction.get(
        "external_id"
    )
)
if not external_id:
    return {
        "ok": False,
        "error":
            "external_id missing",
    }, 400
if payment_processed(
    external_id
):
    return {
        "ok": True,
        "already_processed": True,
    }
payment = (
    get_payment_by_external_id(
        external_id
    )
)
if not payment:
    return {
        "ok": False,
        "error":
            "payment not found",
    }, 404
user_id = int(
    payment["user_id"]
)
days = int(
    payment["days"]
)
amount = int(
    payment.get("amount")
    or 0
)
extend_subscription(
    user_id,
    days,
)
mark_payment_paid(
    external_id
)
mark_payment_processed(
    external_id,
    user_id,
    days,
    amount,
)
sync_subscription(
    user_id
)
return {
    "ok": True,
    "processed": True,
    "user_id": user_id,
    "days": days,
}

============================================================

SUBSCRIPTION

============================================================

def parse_token(token):

prefix = SUBSCRIPTION_PREFIX
if not token.startswith(prefix):
    return None
raw = token[
    len(prefix):
]
if not raw.isdigit():
    return None
return int(raw)

@app.route(”/sub/”)
def subscription(token):

user_id = parse_token(
    token
)
if user_id is None:
    return Response(
        "Not Found",
        status=404,
    )
user = get_user(
    user_id
)
if not user:
    return Response(
        "Not Found",
        status=404,
    )
content = user.get(
    "subscription_content"
)
if not content:
    if subscription_active(
        user
    ):
        content = active_content(
            user_id,
            user.get(
                "subscription_until"
            ),
        )
    else:
        content = inactive_content()
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
return response

============================================================

ADMIN

============================================================

@app.route(”/admin”)
def admin():

if not admin_access():
    return redirect("/cabinet")
stats = get_stats()
body = f"""
<div class="hero">
<div class="label">ADMIN</div>
<h1>☂️ ixxy</h1>
<p class="muted">
Управление сайтом
</p>
</div>
<div class="card">
<div class="grid">
<div class="stat">
<small>Пользователи</small>
<b>{stats["users"]}</b>
</div>
<div class="stat">
<small>Активные</small>
<b>{stats["active"]}</b>
</div>
<div class="stat">
<small>Оплаты</small>
<b>{stats["paid"]}</b>
</div>
</div>
</div>
<div class="card">
<form action="/admin/user"
method="get">
<button class="btn">
Найти пользователя
</button>
</form>
</div>
"""
return page(
    "Админка",
    body,
)

@app.route(”/admin/user”)
def admin_user():

if not admin_access():
    return redirect("/cabinet")
raw_id = request.args.get(
    "id",
    "",
)
if not raw_id.isdigit():
    return redirect("/admin")
user_id = int(raw_id)
user = get_user(
    user_id
)
if not user:
    return page(
        "Пользователь",
        """
<div class="hero">
<h1>Не найден</h1>
<p class="muted">
Пользователь отсутствует в БД.
</p>
</div>
""",
        )
body = f"""
<div class="hero">
<div class="label">
Пользователь
</div>
<h1>
{html.escape(
str(
user.get("first_name")
or user.get("username")
or user_id
)
)}
</h1>
<p class="muted">
ID: {user_id}
</p>
</div>
<div class="card">
<div class="grid">
<div class="stat">
<small>Статус</small>
<b>
{"🟢 Активна"
if subscription_active(user)
else "🔴 Неактивна"}
</b>
</div>
<div class="stat">
<small>До</small>
<b>
{format_date(
user.get(
"subscription_until"
)
)}
</b>
</div>
</div>
</div>
<div class="card">
<div class="label">
Выдать дни
</div>

+30 дней
+90 дней
+180 дней
+365 дней
</div>
"""
return page(
    "Пользователь",
    body,
)

@app.route(
“/admin/grant/int:user_id/int:days”
)
def admin_grant(
user_id,
days,
):

if not admin_access():
    return redirect("/cabinet")
if days <= 0:
    return redirect("/admin")
extend_subscription(
    user_id,
    days,
)
sync_subscription(
    user_id
)
return redirect(
    f"/admin/user?id={user_id}"
)

============================================================

LOGOUT / HEALTH

============================================================

@app.route(”/logout”)
def logout():

session.clear()
return redirect("/")

@app.route(”/health”)
def health():

return {
    "service": "ixxy VPN",
    "status": "ok",
}

============================================================

STARTUP

============================================================

try:
init_db()
except Exception as e:
print(
“Database init warning:”,
repr(e),
)

if name == “main”:

port = int(
    os.getenv(
        "PORT",
        "10000",
    )
)
app.run(
    host="0.0.0.0",
    port=port,
    debug=False,
)