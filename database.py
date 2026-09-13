# database.py

import os
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

from dotenv import load_dotenv

load_dotenv()


# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

UTC = timezone.utc


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан")

    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
    )


# ============================================================
# TIME
# ============================================================

def now_utc():
    return datetime.now(UTC)


def parse_datetime(value):
    if not value:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    try:
        value = str(value).strip()

        if value.endswith("Z"):
            value = value[:-1] + "+00:00"

        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)

        return dt.astimezone(UTC)

    except Exception:
        return None


def format_date(value):
    dt = parse_datetime(value)

    if not dt:
        return "—"

    return dt.strftime("%d.%m.%Y")


# ============================================================
# DATABASE INIT / MIGRATIONS
# ============================================================

def init_db():
    conn = get_conn()

    try:
        with conn.cursor() as cur:

            # ------------------------------------------------
            # PAYMENTS
            # ------------------------------------------------

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

            # Старые таблицы могли быть созданы без этих колонок.
            # Поэтому добавляем их автоматически.

            cur.execute(
                """
                ALTER TABLE payments
                ADD COLUMN IF NOT EXISTS user_id BIGINT
                """
            )

            cur.execute(
                """
                ALTER TABLE payments
                ADD COLUMN IF NOT EXISTS amount INTEGER
                """
            )

            cur.execute(
                """
                ALTER TABLE payments
                ADD COLUMN IF NOT EXISTS days INTEGER
                """
            )

            cur.execute(
                """
                ALTER TABLE payments
                ADD COLUMN IF NOT EXISTS external_id TEXT
                """
            )

            cur.execute(
                """
                ALTER TABLE payments
                ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'
                """
            )

            cur.execute(
                """
                ALTER TABLE payments
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()
                """
            )

            cur.execute(
                """
                ALTER TABLE payments
                ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ
                """
            )

            # ------------------------------------------------
            # USERS
            # ------------------------------------------------

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

            # ------------------------------------------------
            # WEB PROCESSED PAYMENTS
            # ------------------------------------------------

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS web_processed_payments (
                    external_id TEXT PRIMARY KEY,
                    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

        conn.commit()

    finally:
        conn.close()


# ============================================================
# USERS — COLUMNS
# ============================================================

def get_user_columns():
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'users'
                ORDER BY ordinal_position
                """
            )

            return [row[0] for row in cur.fetchall()]

    finally:
        conn.close()


# ============================================================
# USERS
# ============================================================

def create_user(
    user_id,
    username=None,
    first_name=None,
):
    user_id = int(user_id)

    columns = get_user_columns()

    data = {
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "created_at": now_utc(),
        "trial_used": False,
        "pending_days": 0,
        "notify": True,
        "accepted_terms": False,
    }

    available = {
        key: value
        for key, value in data.items()
        if key in columns
    }

    conn = get_conn()

    try:
        with conn.cursor() as cur:

            cur.execute(
                "SELECT 1 FROM users WHERE user_id = %s",
                (user_id,),
            )

            if cur.fetchone():
                return

            column_names = list(available.keys())

            placeholders = ", ".join(
                ["%s"] * len(column_names)
            )

            query = f"""
                INSERT INTO users
                ({", ".join(column_names)})
                VALUES ({placeholders})
            """

            cur.execute(
                query,
                [
                    available[column]
                    for column in column_names
                ],
            )

        conn.commit()

    finally:
        conn.close()


def register_user(
    user_id,
    username=None,
    first_name=None,
):
    create_user(
        user_id=user_id,
        username=username,
        first_name=first_name,
    )


def get_user(user_id):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM users
                WHERE user_id = %s
                """,
                (int(user_id),),
            )

            row = cur.fetchone()

            if not row:
                return None

            return tuple(row)

    finally:
        conn.close()


def get_user_dict(user_id):
    conn = get_conn()

    try:
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

            if not row:
                return None

            return dict(row)

    finally:
        conn.close()


def get_user_by_login(login):
    if not login:
        return None

    login = str(login).strip()

    if login.startswith("@"):
        login = login[1:]

    conn = get_conn()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT *
                FROM users
                WHERE LOWER(username) = LOWER(%s)
                LIMIT 1
                """,
                (login,),
            )

            row = cur.fetchone()

            if not row:
                return None

            return dict(row)

    finally:
        conn.close()


# ============================================================
# SUBSCRIPTION
# ============================================================

def subscription_active(value):
    dt = parse_datetime(value)

    if not dt:
        return False

    return dt > now_utc()


def days_left(value):
    dt = parse_datetime(value)

    if not dt:
        return 0

    delta = dt - now_utc()

    if delta.total_seconds() <= 0:
        return 0

    return delta.days + (
        1 if delta.seconds > 0 else 0
    )


def get_subscription_link(user_id):
    user = get_user_dict(user_id)

    if not user:
        return None

    return user.get("subscription_link")


def get_subscription_content(user_id):
    user = get_user_dict(user_id)

    if not user:
        return None

    return user.get("subscription_content")


def update_subscription_data(
    user_id,
    subscription_link=None,
    subscription_content=None,
):
    fields = []
    values = []

    if subscription_link is not None:
        fields.append("subscription_link = %s")
        values.append(subscription_link)

    if subscription_content is not None:
        fields.append("subscription_content = %s")
        values.append(subscription_content)

    if not fields:
        return

    values.append(int(user_id))

    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE users
                SET {", ".join(fields)}
                WHERE user_id = %s
                """,
                values,
            )

        conn.commit()

    finally:
        conn.close()


def extend_subscription(
    user_id,
    days,
):
    user_id = int(user_id)
    days = int(days)

    conn = get_conn()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT subscription_until
                FROM users
                WHERE user_id = %s
                """,
                (user_id,),
            )

            user = cur.fetchone()

            if not user:
                create_user(user_id)

                cur.execute(
                    """
                    SELECT subscription_until
                    FROM users
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )

                user = cur.fetchone()

            current = parse_datetime(
                user["subscription_until"]
            )

            current_time = now_utc()

            if current and current > current_time:
                new_until = current + timedelta(
                    days=days
                )
            else:
                new_until = current_time + timedelta(
                    days=days
                )

            cur.execute(
                """
                UPDATE users
                SET subscription_until = %s,
                    subscription = %s
                WHERE user_id = %s
                """,
                (
                    new_until,
                    new_until,
                    user_id,
                ),
            )

        conn.commit()

        return new_until

    finally:
        conn.close()


def use_trial(user_id):
    user_id = int(user_id)

    conn = get_conn()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT trial_used
                FROM users
                WHERE user_id = %s
                """,
                (user_id,),
            )

            user = cur.fetchone()

            if not user:
                return False

            if user.get("trial_used"):
                return False

            cur.execute(
                """
                UPDATE users
                SET trial_used = TRUE
                WHERE user_id = %s
                """,
                (user_id,),
            )

        conn.commit()

        return True

    finally:
        conn.close()


def use_promo(user_id, code):
    """
    Базовая совместимость с существующим ботом.
    Если промокоды обрабатываются отдельно,
    эта функция просто возвращает False.
    """

    return False


# ============================================================
# PAYMENTS
# ============================================================

def create_payment(
    user_id,
    amount,
    days,
    external_id,
    status="pending",
):
    user_id = int(user_id)
    amount = int(amount)
    days = int(days)
    external_id = str(external_id)
    status = str(status)

    conn = get_conn()

    try:
        with conn.cursor() as cur:

            # Проверяем, что таблица существует
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = 'payments'
                )
                """
            )

            exists = cur.fetchone()[0]

            if not exists:
                raise RuntimeError(
                    "Таблица payments не найдена"
                )

            cur.execute(
                """
                INSERT INTO payments
                (
                    user_id,
                    amount,
                    days,
                    external_id,
                    status,
                    created_at
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    NOW()
                )
                """,
                (
                    user_id,
                    amount,
                    days,
                    external_id,
                    status,
                ),
            )

        conn.commit()

    finally:
        conn.close()


def get_payment_by_external_id(external_id):
    conn = get_conn()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT *
                FROM payments
                WHERE external_id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (str(external_id),),
            )

            row = cur.fetchone()

            if not row:
                return None

            return dict(row)

    finally:
        conn.close()


def mark_payment_paid(external_id):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE payments
                SET status = 'paid',
                    paid_at = NOW()
                WHERE external_id = %s
                """,
                (str(external_id),),
            )

        conn.commit()

    finally:
        conn.close()


def payment_processed(external_id):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM web_processed_payments
                WHERE external_id = %s
                LIMIT 1
                """,
                (str(external_id),),
            )

            return cur.fetchone() is not None

    finally:
        conn.close()


def mark_payment_processed(external_id):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO web_processed_payments
                    (external_id)
                VALUES
                    (%s)
                ON CONFLICT (external_id)
                DO NOTHING
                """,
                (str(external_id),),
            )

        conn.commit()

    finally:
        conn.close()


# ============================================================
# EXPIRE SUBSCRIPTIONS
# ============================================================

def expire_old_subscriptions():
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET subscription = NULL
                WHERE subscription_until IS NOT NULL
                  AND subscription_until <= NOW()
                """
            )

        conn.commit()

    finally:
        conn.close()


# ============================================================
# STATISTICS
# ============================================================

def get_stats():
    conn = get_conn()

    try:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT COUNT(*)
                FROM users
                """
            )

            total = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE subscription_until > NOW()
                """
            )

            active = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE subscription_until IS NOT NULL
                  AND subscription_until <= NOW()
                """
            )

            expired = cur.fetchone()[0]

            return {
                "total": total,
                "active": active,
                "expired": expired,
            }

    finally:
        conn.close()


# ============================================================
# AUTO INIT
# ============================================================

try:
    init_db()
    print("[database] PostgreSQL database initialized")

except Exception as e:
    print(
        f"[database] init warning: {e}"
    )