import os
import html
import logging
from datetime import datetime, timezone
from urllib.parse import quote
from flask import (
    Flask,
    request,
    redirect,
    render_template,
    abort,
    jsonify,
)
from dotenv import load_dotenv
load_dotenv()
from database import (
    get_user,
    get_subscription_content,
    create_payment,
    process_paid_payment,
    update_payment_status,
)
from cashera_api import create_cashera_payment
# ============================================================
# CONFIG
# ============================================================
APP_NAME = "☂️ ixxy VPN"
PUBLIC_SITE_URL = os.getenv(
    "PUBLIC_SITE_URL",
    "https://ixxyweb.onrender.com",
).rstrip("/")
SUBSCRIPTION_PREFIX = os.getenv(
    "SUBSCRIPTION_PREFIX",
    "2ix847xy",
)
SUPPORT_URL = os.getenv(
    "SUPPORT_URL",
    "https://t.me/rusrodyyya",
).strip()
GITHUB_RAW_BASE = (
    "https://raw.githubusercontent.com/"
    "bdtvyz76b6-blip/vpn-sub/main/users"
)
HAPP_BASE = "https://happ.vpnbypass.click/?url="
# ============================================================
# TARIFFS
# ============================================================
TARIFFS = {
    "30": {
        "days": 30,
        "amount": 129,
        "title": "1 месяц",
    },
    "90": {
        "days": 90,
        "amount": 379,
        "title": "3 месяца",
    },
    "180": {
        "days": 180,
        "amount": 659,
        "title": "6 месяцев",
    },
    "365": {
        "days": 365,
        "amount": 1089,
        "title": "12 месяцев",
    },
}
# ============================================================
# FLASK
# ============================================================
app = Flask(
    __name__,
    template_folder="templates",
)
app.config["JSON_AS_ASCII"] = False
logging.basicConfig(
    level=logging.INFO,
)
log = logging.getLogger("ixxy-web")
# ============================================================
# TIME
# ============================================================
def normalize_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    try:
        value = str(value).strip()
        if not value:
            return None
        value = value.replace(
            "Z",
            "+00:00",
        )
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            result = result.replace(
                tzinfo=timezone.utc
            )
        return result.astimezone(
            timezone.utc
        )
    except Exception:
        return None
def subscription_info(user):
    if not user:
        return {
            "active": False,
            "until": None,
            "until_text": "—",
            "days": 0,
        }
    until = normalize_datetime(
        user.get("subscription_until")
    )
    if not until:
        return {
            "active": False,
            "until": None,
            "until_text": "—",
            "days": 0,
        }
    now = datetime.now(timezone.utc)
    if until <= now:
        return {
            "active": False,
            "until": until,
            "until_text": until.strftime(
                "%d.%m.%Y"
            ),
            "days": 0,
        }
    seconds = (
        until - now
    ).total_seconds()
    days = int(
        seconds // 86400
    )
    return {
        "active": True,
        "until": until,
        "until_text": until.strftime(
            "%d.%m.%Y"
        ),
        "days": max(1, days),
    }
# ============================================================
# TOKEN
# ============================================================
def parse_token(token):
    if not token:
        return None
    token = str(token).strip()
    if not token.startswith(
        SUBSCRIPTION_PREFIX
    ):
        return None
    raw_id = token[
        len(SUBSCRIPTION_PREFIX):
    ]
    if not raw_id.isdigit():
        return None
    try:
        return int(raw_id)
    except Exception:
        return None
def make_token(user_id):
    return (
        f"{SUBSCRIPTION_PREFIX}"
        f"{int(user_id)}"
    )
def subscription_url(user_id):
    return (
        f"{PUBLIC_SITE_URL}/sub/"
        f"{make_token(user_id)}"
    )
def github_url(user_id):
    return (
        f"{GITHUB_RAW_BASE}/"
        f"{int(user_id)}.txt"
    )
def happ_url(user_id):
    url = subscription_url(user_id)
    return (
        HAPP_BASE +
        quote(
            url,
            safe=""
        )
    )
# ============================================================
# USER
# ============================================================
def get_user_from_token(token):
    user_id = parse_token(token)
    if not user_id:
        return None, None
    user = get_user(user_id)
    if not user:
        return None, user_id
    return user, user_id
# ============================================================
# HOME
# ============================================================
@app.route("/")
def home():
    return render_template(
        "index.html",
        app_name=APP_NAME,
        support_url=SUPPORT_URL,
        tariffs=TARIFFS,
        public_url=PUBLIC_SITE_URL,
        token=None,
        user=None,
        info=None,
        subscription_url=None,
        github_url=None,
        happ_url=None,
        message=None,
        error=None,
    )
# ============================================================
# CABINET
# ============================================================
@app.route(
    "/s/<token>",
    methods=["GET"],
)
def cabinet(token):
    user, user_id = get_user_from_token(
        token
    )
    if not user:
        abort(404)
    info = subscription_info(
        user
    )
    sub_url = subscription_url(
        user_id
    )
    gh_url = github_url(
        user_id
    )
    h_url = happ_url(
        user_id
    )
    return render_template(
        "index.html",
        app_name=APP_NAME,
        support_url=SUPPORT_URL,
        tariffs=TARIFFS,
        public_url=PUBLIC_SITE_URL,
        token=token,
        user=user,
        info=info,
        subscription_url=sub_url,
        github_url=gh_url,
        happ_url=h_url,
        message=None,
        error=None,
    )
# ============================================================
# SUBSCRIPTION
# ============================================================
@app.route(
    "/sub/<token>",
    methods=["GET"],
)
def subscription(token):
    user, user_id = get_user_from_token(
        token
    )
    if not user:
        abort(404)
    info = subscription_info(
        user
    )
    content = get_subscription_content(
        user_id
    )
    if not content:
        content = ""
    response = str(content)
    return response, 200, {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
# ============================================================
# GITHUB RAW REDIRECT
# ============================================================
@app.route(
    "/github/<token>",
    methods=["GET"],
)
def github_redirect(token):
    user, user_id = get_user_from_token(
        token
    )
    if not user:
        abort(404)
    return redirect(
        github_url(user_id)
    )
# ============================================================
# CREATE CASHeRA PAYMENT
# ============================================================
@app.route(
    "/pay/<token>/<tariff>",
    methods=["GET"],
)
def create_payment_route(
    token,
    tariff,
):
    user, user_id = get_user_from_token(
        token
    )
    if not user:
        abort(404)
    plan = TARIFFS.get(
        str(tariff)
    )
    if not plan:
        abort(404)
    amount = int(
        plan["amount"]
    )
    days = int(
        plan["days"]
    )
    try:
        result = create_cashera_payment(
            user_id=user_id,
            amount=amount,
            days=days,
        )
        if not isinstance(
            result,
            dict,
        ):
            raise RuntimeError(
                "CasheRa returned invalid response"
            )
        payment_uuid = (
            result.get("uuid")
            or result.get("id")
        )
        payment_url = (
            result.get("payment_url")
            or result.get("url")
        )
        if not payment_uuid:
            raise RuntimeError(
                "CasheRa did not return payment ID"
            )
        if not payment_url:
            raise RuntimeError(
                "CasheRa did not return payment URL"
            )
        # ----------------------------------------------------
        # Сохраняем платёж в PostgreSQL
        # ----------------------------------------------------
        try:
            create_payment(
                user_id=user_id,
                payment_id=str(
                    payment_uuid
                ),
                amount=amount * 100,
                days=days,
                provider="cashera",
            )
        except TypeError:
            # Совместимость со старой сигнатурой
            create_payment(
                user_id=user_id,
                payment_id=str(
                    payment_uuid
                ),
                amount=amount * 100,
                days=days,
            )
        log.info(
            "CasheRa payment created "
            "user=%s payment=%s days=%s amount=%s",
            user_id,
            payment_uuid,
            days,
            amount,
        )
        return redirect(
            payment_url
        )
    except Exception as e:
        log.exception(
            "Payment creation failed"
        )
        info = subscription_info(
            user
        )
        return render_template(
            "index.html",
            app_name=APP_NAME,
            support_url=SUPPORT_URL,
            tariffs=TARIFFS,
            public_url=PUBLIC_SITE_URL,
            token=token,
            user=user,
            info=info,
            subscription_url=subscription_url(
                user_id
            ),
            github_url=github_url(
                user_id
            ),
            happ_url=happ_url(
                user_id
            ),
            message=None,
            error=(
                "Не удалось создать платёж. "
                "Попробуйте ещё раз."
            ),
        ), 500
# ============================================================
# CASHeRA WEBHOOK
# ============================================================
@app.route(
    "/webhook/cashera",
    methods=["POST"],
)
def cashera_webhook():
    try:
        payload = request.get_json(
            silent=True
        ) or {}
        log.info(
            "CasheRa webhook: %s",
            payload,
        )
        event = (
            payload.get("event")
            or payload.get("type")
            or ""
        )
        transaction = (
            payload.get("transaction")
            or payload.get("data")
            or payload
        )
        status = str(
            transaction.get("status")
            or payload.get("status")
            or ""
        ).lower()
        if event:
            if event not in (
                "transaction.status_updated",
                "transaction_status_updated",
            ):
                return jsonify({
                    "ok": True,
                    "ignored": True,
                })
        if status not in (
            "paid",
            "success",
            "completed",
        ):
            return jsonify({
                "ok": True,
                "ignored": True,
            })
        payment_id = (
            transaction.get("uuid")
            or transaction.get("id")
            or payload.get("uuid")
            or payload.get("id")
        )
        if not payment_id:
            return jsonify({
                "ok": False,
                "error": "payment id missing",
            }), 400
        payment_id = str(
            payment_id
        )
        # ----------------------------------------------------
        # Идемпотентное зачисление
        # ----------------------------------------------------
        result = process_paid_payment(
            payment_id
        )
        log.info(
            "CasheRa payment processed "
            "%s: %s",
            payment_id,
            result,
        )
        return jsonify({
            "ok": True,
            "result": result,
        })
    except Exception as e:
        log.exception(
            "CasheRa webhook error"
        )
        return jsonify({
            "ok": False,
            "error": str(e),
        }), 500
# ============================================================
# HEALTH
# ============================================================
@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "ixxy-web",
        "version": "2026.09",
    })
# ============================================================
# 404
# ============================================================
@app.errorhandler(404)
def not_found(error):
    return render_template(
        "index.html",
        app_name=APP_NAME,
        support_url=SUPPORT_URL,
        tariffs=TARIFFS,
        public_url=PUBLIC_SITE_URL,
        token=None,
        user=None,
        info=None,
        subscription_url=None,
        github_url=None,
        happ_url=None,
        message=None,
        error="Страница не найдена.",
    ), 404
# ============================================================
# LOCAL
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
        debug=False,
    )