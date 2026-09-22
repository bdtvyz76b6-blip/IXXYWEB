import os
import logging
from datetime import datetime, timezone, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
# =========================================================
# ENV
# =========================================================
load_dotenv()
logger = logging.getLogger(__name__)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "",
).strip()
MAX_PROMO_DAYS = int(
    os.getenv(
        "MAX_PROMO_DAYS",
        "999999999999",
    )
)
UTC = timezone.utc
# =========================================================
# IXXY
# =========================================================
SUBSCRIPTION_BASE_URL = os.getenv(
    "SUBSCRIPTION_BASE_URL",
    "https://ixxyweb-1.onrender.com/sub/2ix847xy",
).strip().rstrip("/")
# =========================================================
# DATABASE
# =========================================================
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL не задан"
        )
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        connect_timeout=15,
    )
# =========================================================
# INIT DATABASE
# =========================================================
def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            # USERS
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    subscription TIMESTAMPTZ,
                    subscription_until TIMESTAMPTZ,
                    subscription_link TEXT,
                    uuid TEXT,
                    trial_used BOOLEAN DEFAULT FALSE,
                    pending_days INTEGER DEFAULT 0,
                    notify BOOLEAN DEFAULT TRUE,
                    accepted_terms BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    subscription_content TEXT
                )
                """
            )
            # PAYMENTS
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT,
                    amount INTEGER,
                    days INTEGER,
                    external_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    paid_at TIMESTAMPTZ
                )
                """
            )
            # PROCESSED WEBHOOKS
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS
                web_processed_payments (
                    external_id TEXT PRIMARY KEY,
                    processed_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            # PAYMENT INDEX
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_payments_external_id
                ON payments(external_id)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_payments_user_id
                ON payments(user_id)
                """
            )
            conn.commit()
# =========================================================
# USER COLUMNS
# =========================================================
def get_user_columns():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'users'
                ORDER BY ordinal_position
                """
            )
            return [
                row[0]
                for row in cur.fetchall()
            ]
# =========================================================
# USERS
# =========================================================
def create_user(
    user_id,
    username=None,
    first_name=None,
):
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                INSERT INTO users (
                    user_id,
                    username,
                    first_name,
                    subscription_link
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s
                )
                ON CONFLICT (user_id)
                DO UPDATE SET
                    username = COALESCE(
                        EXCLUDED.username,
                        users.username
                    ),
                    first_name = COALESCE(
                        EXCLUDED.first_name,
                        users.first_name
                    )
                RETURNING *
                """,
                (
                    int(user_id),
                    username,
                    first_name,
                    get_subscription_link_value(
                        user_id
                    ),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return (
                dict(row)
                if row
                else None
            )
def register_user(
    user_id,
    username=None,
    first_name=None,
):
    return create_user(
        user_id,
        username,
        first_name,
    )
def get_user(user_id):
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM users
                WHERE user_id = %s
                """,
                (int(user_id),),
            )
            row = cur.fetchone()
            return (
                dict(row)
                if row
                else None
            )
def get_user_dict(user_id):
    return get_user(user_id)
def get_user_by_login(login):
    login = (
        str(login)
        .strip()
        .lstrip("@")
    )
    # Сначала пробуем Telegram ID.
    try:
        user_id = int(login)
        user = get_user(user_id)
        if user:
            return user
    except (
        ValueError,
        TypeError,
    ):
        pass
    # Затем username.
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM users
                WHERE LOWER(
                    COALESCE(username, '')
                ) = LOWER(%s)
                LIMIT 1
                """,
                (login,),
            )
            row = cur.fetchone()
            return (
                dict(row)
                if row
                else None
            )
def get_all_users():
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM users
                ORDER BY created_at DESC
                """
            )
            return [
                dict(row)
                for row in cur.fetchall()
            ]
def count_users():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM users
                """
            )
            return int(
                cur.fetchone()[0]
            )
# =========================================================
# DATETIME
# =========================================================
def _to_datetime(value):
    if not value:
        return None
    if isinstance(
        value,
        datetime,
    ):
        result = value
    elif isinstance(
        value,
        str,
    ):
        try:
            result = datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00",
                )
            )
        except Exception:
            return None
    else:
        return None
    if result.tzinfo is None:
        result = result.replace(
            tzinfo=UTC
        )
    return result.astimezone(UTC)
def now_utc():
    return datetime.now(UTC)
def format_date(value):
    value = _to_datetime(value)
    if not value:
        return "—"
    return value.strftime(
        "%d.%m.%Y"
    )
# =========================================================
# SUBSCRIPTION
# =========================================================
def subscription_active(value):
    value = _to_datetime(value)
    if not value:
        return False
    return value >= datetime.now(
        UTC
    )
def days_left(value):
    value = _to_datetime(value)
    if not value:
        return 0
    seconds = (
        value
        - datetime.now(UTC)
    ).total_seconds()
    if seconds <= 0:
        return 0
    return int(
        (seconds + 86399)
        // 86400
    )
# =========================================================
# SUBSCRIPTION LINK
# =========================================================
def get_subscription_link_value(
    user_id
):
    return (
        f"{SUBSCRIPTION_BASE_URL}"
        f"{int(user_id)}"
    )
def get_subscription_link(user_id):
    user = get_user_dict(
        user_id
    )
    if not user:
        return None
    link = user.get(
        "subscription_link"
    )
    if link:
        return link
    return get_subscription_link_value(
        user_id
    )
def save_subscription_link(
    user_id,
    link=None,
):
    canonical_link = (
        link
        or get_subscription_link_value(
            user_id
        )
    )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET subscription_link = %s
                WHERE user_id = %s
                """,
                (
                    canonical_link,
                    int(user_id),
                ),
            )
            conn.commit()
    return canonical_link
# =========================================================
# SUBSCRIPTION CONTENT
# =========================================================
def get_subscription_content(
    user_id
):
    user = get_user_dict(
        user_id
    )
    if not user:
        return None
    return user.get(
        "subscription_content"
    )
def save_subscription_content(
    user_id,
    content,
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET subscription_content = %s
                WHERE user_id = %s
                """,
                (
                    content,
                    int(user_id),
                ),
            )
            conn.commit()
def update_subscription_data(
    user_id,
    subscription_link=None,
    subscription_content=None,
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET
                    subscription_link =
                        COALESCE(
                            %s,
                            subscription_link
                        ),
                    subscription_content =
                        COALESCE(
                            %s,
                            subscription_content
                        )
                WHERE user_id = %s
                """,
                (
                    subscription_link,
                    subscription_content,
                    int(user_id),
                ),
            )
            conn.commit()
# =========================================================
# EXTEND SUBSCRIPTION
# =========================================================
def extend_subscription(
    user_id,
    days,
):
    days = int(days)
    if days <= 0:
        return None
    now = datetime.now(UTC)
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT subscription_until
                FROM users
                WHERE user_id = %s
                FOR UPDATE
                """,
                (int(user_id),),
            )
            row = cur.fetchone()
            # Если пользователя нет —
            # создаём его.
            if not row:
                new_until = (
                    now
                    + timedelta(days=days)
                )
                cur.execute(
                    """
                    INSERT INTO users (
                        user_id,
                        subscription,
                        subscription_until,
                        subscription_link
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    RETURNING *
                    """,
                    (
                        int(user_id),
                        new_until,
                        new_until,
                        get_subscription_link_value(
                            user_id
                        ),
                    ),
                )
            else:
                current = _to_datetime(
                    row["subscription_until"]
                )
                if current and current > now:
                    base = current
                else:
                    base = now
                new_until = (
                    base
                    + timedelta(days=days)
                )
                cur.execute(
                    """
                    UPDATE users
                    SET
                        subscription = %s,
                        subscription_until = %s,
                        subscription_link = %s
                    WHERE user_id = %s
                    RETURNING *
                    """,
                    (
                        new_until,
                        new_until,
                        get_subscription_link_value(
                            user_id
                        ),
                        int(user_id),
                    ),
                )
            result = cur.fetchone()
            conn.commit()
            return (
                dict(result)
                if result
                else None
            )
# =========================================================
# DISABLE SUBSCRIPTION
# =========================================================
def disable_subscription(
    user_id
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET
                    subscription = NULL,
                    subscription_until = NULL,
                    subscription_content = NULL
                WHERE user_id = %s
                """,
                (int(user_id),),
            )
            conn.commit()
def deactivate_subscription(
    user_id
):
    return disable_subscription(
        user_id
    )
def revoke_subscription(
    user_id
):
    return disable_subscription(
        user_id
    )
# =========================================================
# EXPIRED
# =========================================================
def expire_old_subscriptions():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET subscription = NULL
                WHERE subscription_until IS NOT NULL
                  AND subscription_until <= NOW()
                """
            )
            changed = cur.rowcount
            conn.commit()
            return changed
def check_expired_subscriptions():
    return expire_old_subscriptions()
# =========================================================
# TRIAL
# =========================================================
def use_trial(
    user_id,
    days=3,
):
    user = get_user_dict(
        user_id
    )
    if not user:
        return False
    if user.get("trial_used"):
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET trial_used = TRUE
                WHERE user_id = %s
                """,
                (int(user_id),),
            )
            conn.commit()
    extend_subscription(
        user_id,
        min(
            int(days),
            MAX_PROMO_DAYS,
        ),
    )
    return True
def activate_trial(
    user_id,
    days=3,
):
    return use_trial(
        user_id,
        days,
    )
def check_trial(
    user_id
):
    user = get_user_dict(
        user_id
    )
    if not user:
        return False
    return bool(
        user.get(
            "trial_used"
        )
    )
def trial_used(
    user_id
):
    return check_trial(
        user_id
    )
def mark_trial_used(
    user_id
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET trial_used = TRUE
                WHERE user_id = %s
                """,
                (int(user_id),),
            )
            conn.commit()
# =========================================================
# PROMOCODES
# =========================================================
def use_promo(*args, **kwargs):
    return False
def create_promocode(
    code,
    days,
    max_uses=0,
):
    code = (
        str(code)
        .strip()
        .upper()
    )
    days = int(days)
    max_uses = int(max_uses)
    if (
        not code
        or days <= 0
        or days > MAX_PROMO_DAYS
        or max_uses < 0
    ):
        return False
    # Таблица создаётся отдельно,
    # если её ещё нет.
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS promocodes (
                    code TEXT PRIMARY KEY,
                    days BIGINT NOT NULL,
                    max_uses BIGINT DEFAULT 0,
                    uses BIGINT DEFAULT 0,
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS promocode_uses (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    code TEXT NOT NULL,
                    used_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_id, code)
                )
                """
            )
            cur.execute(
                """
                INSERT INTO promocodes (
                    code,
                    days,
                    max_uses,
                    uses,
                    active
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    0,
                    TRUE
                )
                ON CONFLICT (code)
                DO UPDATE SET
                    days = EXCLUDED.days,
                    max_uses = EXCLUDED.max_uses,
                    active = TRUE
                """,
                (
                    code,
                    days,
                    max_uses,
                ),
            )
            conn.commit()
            return True
def get_promocode(code):
    code = (
        str(code)
        .strip()
        .upper()
    )
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM promocodes
                WHERE code = %s
                """,
                (code,),
            )
            row = cur.fetchone()
            return (
                dict(row)
                if row
                else None
            )
def get_all_promocodes():
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM promocodes
                ORDER BY created_at DESC
                """
            )
            return [
                dict(row)
                for row in cur.fetchall()
            ]
def deactivate_promocode(
    code
):
    code = (
        str(code)
        .strip()
        .upper()
    )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE promocodes
                SET active = FALSE
                WHERE code = %s
                """,
                (code,),
            )
            changed = (
                cur.rowcount > 0
            )
            conn.commit()
            return changed
# =========================================================
# PAYMENTS
# =========================================================
def create_payment(
    user_id,
    amount,
    days,
    external_id,
    payment_id=None,
    status="pending",
    provider="cashera",
):
    external_id = str(
        external_id
    )
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            # Не создаём дубликат.
            cur.execute(
                """
                SELECT *
                FROM payments
                WHERE external_id = %s
                LIMIT 1
                """,
                (external_id,),
            )
            existing = cur.fetchone()
            if existing:
                return dict(existing)
            cur.execute(
                """
                INSERT INTO payments (
                    user_id,
                    amount,
                    days,
                    external_id,
                    status
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                RETURNING *
                """,
                (
                    int(user_id),
                    int(amount),
                    int(days),
                    external_id,
                    status,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return (
                dict(row)
                if row
                else None
            )
def get_payment_by_external_id(
    external_id
):
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM payments
                WHERE external_id = %s
                LIMIT 1
                """,
                (str(external_id),),
            )
            row = cur.fetchone()
            return (
                dict(row)
                if row
                else None
            )
def get_payment(
    external_id
):
    return get_payment_by_external_id(
        external_id
    )
def mark_payment_paid(
    external_id
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE payments
                SET
                    status = 'paid',
                    paid_at = NOW()
                WHERE external_id = %s
                """,
                (str(external_id),),
            )
            conn.commit()
def payment_processed(
    external_id
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM web_processed_payments
                WHERE external_id = %s
                """,
                (str(external_id),),
            )
            return (
                cur.fetchone()
                is not None
            )
def mark_payment_processed(
    external_id
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO web_processed_payments (
                    external_id
                )
                VALUES (%s)
                ON CONFLICT DO NOTHING
                """,
                (str(external_id),),
            )
            conn.commit()
def get_all_payments():
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM payments
                ORDER BY created_at DESC
                """
            )
            return [
                dict(row)
                for row in cur.fetchall()
            ]
def get_payments():
    return get_all_payments()
def get_user_payments(
    user_id
):
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM payments
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (int(user_id),),
            )
            return [
                dict(row)
                for row in cur.fetchall()
            ]
def get_payment_by_payment_id(
    payment_id
):
    return get_payment_by_external_id(
        payment_id
    )
def update_payment_status(
    payment_id,
    status,
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE payments
                SET
                    status = %s,
                    paid_at = CASE
                        WHEN %s = 'paid'
                        THEN COALESCE(
                            paid_at,
                            NOW()
                        )
                        ELSE paid_at
                    END
                WHERE external_id = %s
                """,
                (
                    status,
                    status,
                    str(payment_id),
                ),
            )
            conn.commit()
# =========================================================
# NOTIFICATIONS
# =========================================================
def get_notification_setting(
    user_id
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT notify
                FROM users
                WHERE user_id = %s
                """,
                (int(user_id),),
            )
            row = cur.fetchone()
            if not row:
                return True
            return bool(
                row[0]
            )
def set_notification(
    user_id,
    enabled,
):
    create_user(user_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET notify = %s
                WHERE user_id = %s
                """,
                (
                    bool(enabled),
                    int(user_id),
                ),
            )
            conn.commit()
# =========================================================
# TERMS
# =========================================================
def get_accepted_terms(
    user_id
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT accepted_terms
                FROM users
                WHERE user_id = %s
                """,
                (int(user_id),),
            )
            row = cur.fetchone()
            if not row:
                return False
            return bool(
                row[0]
            )
def has_accepted_terms(
    user_id
):
    return get_accepted_terms(
        user_id
    )
def set_accepted_terms(
    user_id,
    accepted=True,
):
    create_user(user_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET accepted_terms = %s
                WHERE user_id = %s
                """,
                (
                    bool(accepted),
                    int(user_id),
                ),
            )
            conn.commit()
def accept_terms(
    user_id
):
    return set_accepted_terms(
        user_id,
        True,
    )
# =========================================================
# PENDING DAYS
# =========================================================
def get_pending_days(
    user_id
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pending_days
                FROM users
                WHERE user_id = %s
                """,
                (int(user_id),),
            )
            row = cur.fetchone()
            if not row:
                return 0
            return int(
                row[0] or 0
            )
def set_pending_days(
    user_id,
    days,
):
    create_user(user_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET pending_days = %s
                WHERE user_id = %s
                """,
                (
                    int(days),
                    int(user_id),
                ),
            )
            conn.commit()
def add_pending_days(
    user_id,
    days,
):
    create_user(user_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET
                    pending_days =
                        COALESCE(
                            pending_days,
                            0
                        ) + %s
                WHERE user_id = %s
                """,
                (
                    int(days),
                    int(user_id),
                ),
            )
            conn.commit()
# =========================================================
# STATISTICS
# =========================================================
def get_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM users
                """
            )
            users = int(
                cur.fetchone()[0]
            )
            cur.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE subscription_until > NOW()
                """
            )
            active = int(
                cur.fetchone()[0]
            )
            cur.execute(
                """
                SELECT COUNT(*)
                FROM payments
                WHERE status = 'paid'
                """
            )
            paid = int(
                cur.fetchone()[0]
            )
            cur.execute(
                """
                SELECT COALESCE(
                    SUM(amount),
                    0
                )
                FROM payments
                WHERE status = 'paid'
                """
            )
            revenue = int(
                cur.fetchone()[0] or 0
            )
            return {
                "users": users,
                "active": active,
                "paid_payments": paid,
                "revenue": revenue,
            }
# =========================================================
# MIGRATION OF SUBSCRIPTION LINKS
# =========================================================
def migrate_subscription_links():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET subscription_link =
                    %s || user_id::text
                WHERE user_id IS NOT NULL
                """,
                (
                    SUBSCRIPTION_BASE_URL,
                ),
            )
            changed = cur.rowcount
            conn.commit()
            logger.info(
                "Исправлено ссылок IXXY: %s",
                changed,
            )
            return changed
# =========================================================
# DATABASE INIT
# =========================================================
try:
    init_db()
except Exception as e:
    logger.warning(
        "⚠️ Database init warning: %s",
        e,
    )

Теперь база сайта создаёт именно такую структуру:

users → пользователи и подписки
payments → оплаты
web_processed_payments → защита от повторного webhook

И важный момент: subscription и subscription_until здесь оба являются датами окончания подписки, как в твоём исходном варианте. Я не стал превращать subscription в BOOLEAN.

Бот для этой базы не нужен. api.py может сам создавать пользователей, читать их и продлевать подписку через PostgreSQL.