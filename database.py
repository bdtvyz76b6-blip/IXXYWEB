import os
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL не задан")

UTC = timezone.utc


def get_conn():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )


def init_db():
    conn = get_conn()

    try:
        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGSERIAL PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    subscription BOOLEAN DEFAULT FALSE,
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
            """)

            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS email TEXT
            """)

            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS password_hash TEXT
            """)

            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique_idx
                ON users (LOWER(email))
                WHERE email IS NOT NULL
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT,
                    payment_id TEXT UNIQUE NOT NULL,
                    external_id TEXT UNIQUE,
                    amount INTEGER NOT NULL DEFAULT 0,
                    days INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    provider TEXT DEFAULT 'cashera',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    paid_at TIMESTAMPTZ
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS promocodes (
                    code TEXT PRIMARY KEY,
                    days INTEGER NOT NULL,
                    max_uses INTEGER DEFAULT 0,
                    uses INTEGER DEFAULT 0,
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS promocode_uses (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    code TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(user_id, code)
                )
            """)

        conn.commit()

    finally:
        conn.close()


def get_user(user_id):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE user_id=%s",
                (int(user_id),)
            )
            return cur.fetchone()

    finally:
        conn.close()


def get_user_by_email(email):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM users
                WHERE LOWER(email)=LOWER(%s)
                LIMIT 1
                """,
                (email.strip(),)
            )

            return cur.fetchone()

    finally:
        conn.close()


def create_site_user(email, password_hash, first_name="Пользователь"):
    conn = get_conn()

    try:
        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO users (
                    username,
                    first_name,
                    email,
                    password_hash,
                    subscription,
                    trial_used,
                    notify,
                    accepted_terms
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    FALSE,
                    FALSE,
                    TRUE,
                    TRUE
                )
                RETURNING user_id
                """,
                (
                    email,
                    first_name,
                    email,
                    password_hash
                )
            )

            user_id = cur.fetchone()["user_id"]

        conn.commit()

        return int(user_id)

    finally:
        conn.close()


def save_subscription(user_id, link, content):
    conn = get_conn()

    try:
        with conn.cursor() as cur:

            cur.execute(
                """
                UPDATE users
                SET subscription_link=%s,
                    subscription_content=%s
                WHERE user_id=%s
                """,
                (
                    link,
                    content,
                    int(user_id)
                )
            )

        conn.commit()

    finally:
        conn.close()


def subscription_active(until):
    if not until:
        return False

    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)

    return until > datetime.now(UTC)


def activate_subscription(user_id, days):
    conn = get_conn()

    try:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT subscription_until
                FROM users
                WHERE user_id=%s
                FOR UPDATE
                """,
                (int(user_id),)
            )

            row = cur.fetchone()

            if not row:
                raise ValueError("Пользователь не найден")

            now = datetime.now(UTC)

            old_until = row["subscription_until"]

            if old_until and old_until.tzinfo is None:
                old_until = old_until.replace(tzinfo=UTC)

            if old_until and old_until > now:
                base = old_until
            else:
                base = now

            new_until = base + timedelta(days=int(days))

            cur.execute(
                """
                UPDATE users
                SET subscription=TRUE,
                    subscription_until=%s,
                    pending_days=0
                WHERE user_id=%s
                """,
                (
                    new_until,
                    int(user_id)
                )
            )

        conn.commit()

        return new_until

    finally:
        conn.close()


def use_trial(user_id, days=1):
    conn = get_conn()

    try:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT trial_used, subscription_until
                FROM users
                WHERE user_id=%s
                FOR UPDATE
                """,
                (int(user_id),)
            )

            row = cur.fetchone()

            if not row:
                return None

            if row["trial_used"]:
                return None

            now = datetime.now(UTC)

            old_until = row["subscription_until"]

            if old_until and old_until.tzinfo is None:
                old_until = old_until.replace(tzinfo=UTC)

            base = (
                old_until
                if old_until and old_until > now
                else now
            )

            new_until = base + timedelta(days=int(days))

            cur.execute(
                """
                UPDATE users
                SET trial_used=TRUE,
                    subscription=TRUE,
                    subscription_until=%s
                WHERE user_id=%s
                """,
                (
                    new_until,
                    int(user_id)
                )
            )

        conn.commit()

        return new_until

    finally:
        conn.close()


def create_payment(
    user_id,
    payment_id,
    external_id,
    amount,
    days
):
    conn = get_conn()

    try:
        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO payments (
                    user_id,
                    payment_id,
                    external_id,
                    amount,
                    days,
                    status,
                    provider
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'pending',
                    'cashera'
                )
                ON CONFLICT (payment_id)
                DO NOTHING
                """,
                (
                    int(user_id),
                    str(payment_id),
                    str(external_id),
                    int(amount),
                    int(days)
                )
            )

        conn.commit()

    finally:
        conn.close()


def get_payment(payment_id):
    conn = get_conn()

    try:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT *
                FROM payments
                WHERE payment_id=%s
                LIMIT 1
                """,
                (str(payment_id),)
            )

            return cur.fetchone()

    finally:
        conn.close()


def process_paid_payment(payment_id):
    """
    Повторный webhook не начислит подписку второй раз.
    """

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT *
                FROM payments
                WHERE payment_id=%s
                FOR UPDATE
                """,
                (str(payment_id),)
            )

            payment = cur.fetchone()

            if not payment:
                return None

            cur.execute(
                """
                SELECT subscription_until
                FROM users
                WHERE user_id=%s
                FOR UPDATE
                """,
                (payment["user_id"],)
            )

            user = cur.fetchone()

            if not user:
                raise ValueError(
                    "Пользователь платежа не найден"
                )

            if payment["status"] == "paid":

                conn.commit()

                return (
                    int(payment["user_id"]),
                    user["subscription_until"],
                    True
                )

            now = datetime.now(UTC)

            old_until = user["subscription_until"]

            if old_until and old_until.tzinfo is None:
                old_until = old_until.replace(tzinfo=UTC)

            if old_until and old_until > now:
                base = old_until
            else:
                base = now

            new_until = base + timedelta(
                days=int(payment["days"])
            )

            cur.execute(
                """
                UPDATE users
                SET subscription=TRUE,
                    subscription_until=%s,
                    pending_days=0
                WHERE user_id=%s
                """,
                (
                    new_until,
                    payment["user_id"]
                )
            )

            cur.execute(
                """
                UPDATE payments
                SET status='paid',
                    paid_at=NOW()
                WHERE payment_id=%s
                """,
                (str(payment_id),)
            )

        conn.commit()

        return (
            int(payment["user_id"]),
            new_until,
            False
        )

    except Exception:

        conn.rollback()

        raise

    finally:
        conn.close()


def use_promocode(user_id, code):

    code = code.strip().upper()

    conn = get_conn()

    try:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT *
                FROM promocodes
                WHERE code=%s
                FOR UPDATE
                """,
                (code,)
            )

            promo = cur.fetchone()

            if not promo or not promo["active"]:
                return None, "Промокод недействителен"

            if (
                promo["max_uses"]
                and promo["uses"] >= promo["max_uses"]
            ):
                return None, "Лимит промокода закончился"

            cur.execute(
                """
                SELECT 1
                FROM promocode_uses
                WHERE user_id=%s
                AND code=%s
                """,
                (
                    int(user_id),
                    code
                )
            )

            if cur.fetchone():
                return None, "Вы уже использовали этот промокод"

            cur.execute(
                """
                SELECT subscription_until
                FROM users
                WHERE user_id=%s
                FOR UPDATE
                """,
                (int(user_id),)
            )

            user = cur.fetchone()

            if not user:
                return None, "Пользователь не найден"

            now = datetime.now(UTC)

            old_until = user["subscription_until"]

            if old_until and old_until.tzinfo is None:
                old_until = old_until.replace(tzinfo=UTC)

            base = (
                old_until
                if old_until and old_until > now
                else now
            )

            new_until = base + timedelta(
                days=int(promo["days"])
            )

            cur.execute(
                """
                UPDATE users
                SET subscription=TRUE,
                    subscription_until=%s
                WHERE user_id=%s
                """,
                (
                    new_until,
                    int(user_id)
                )
            )

            cur.execute(
                """
                UPDATE promocodes
                SET uses=uses+1
                WHERE code=%s
                """,
                (code,)
            )

            cur.execute(
                """
                INSERT INTO promocode_uses(user_id, code)
                VALUES (%s,%s)
                """,
                (
                    int(user_id),
                    code
                )
            )

        conn.commit()

        return new_until, None

    except Exception:

        conn.rollback()

        raise

    finally:
        conn.close()


def get_all_users():
    conn = get_conn()

    try:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT *
                FROM users
                ORDER BY user_id
                """
            )

            return cur.fetchall()

    finally:
        conn.close()


init_db()