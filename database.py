import os
import secrets
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

UTC = timezone.utc


def conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан")

    return psycopg2.connect(DATABASE_URL)


def now():
    return datetime.now(UTC)


def init_db():
    with conn() as db:
        with db.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS site_users (
                    id BIGSERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    subscription_until TIMESTAMPTZ,
                    subscription_link TEXT,
                    subscription_content TEXT,
                    trial_used BOOLEAN DEFAULT FALSE,
                    blocked BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS site_payments (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    external_id TEXT UNIQUE NOT NULL,
                    cashera_id TEXT,
                    amount INTEGER NOT NULL,
                    days INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    paid_at TIMESTAMPTZ
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS site_promocodes (
                    id BIGSERIAL PRIMARY KEY,
                    code TEXT UNIQUE NOT NULL,
                    days INTEGER NOT NULL,
                    max_uses INTEGER DEFAULT 1,
                    uses INTEGER DEFAULT 0,
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS site_promo_uses (
                    id BIGSERIAL PRIMARY KEY,
                    promo_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(promo_id, user_id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS site_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

        db.commit()


def create_user(username, password):
    username = username.strip().lower()

    if len(username) < 3:
        raise ValueError("Логин минимум 3 символа")

    if len(password) < 6:
        raise ValueError("Пароль минимум 6 символов")

    with conn() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO site_users
                (username, password_hash)
                VALUES (%s, %s)
                RETURNING id
                """,
                (
                    username,
                    generate_password_hash(password),
                ),
            )

            user_id = cur.fetchone()[0]

        db.commit()

    return user_id


def get_user(user_id):
    with conn() as db:
        with db.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM site_users
                WHERE id = %s
                """,
                (user_id,),
            )

            return cur.fetchone()


def get_user_by_username(username):
    with conn() as db:
        with db.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM site_users
                WHERE username = %s
                """,
                (username.strip().lower(),),
            )

            return cur.fetchone()


def login_user(username, password):
    user = get_user_by_username(username)

    if not user:
        return None

    if user["blocked"]:
        return None

    if not check_password_hash(
        user["password_hash"],
        password,
    ):
        return None

    return user


def get_subscription_until(user_id):
    user = get_user(user_id)

    if not user:
        return None

    return user["subscription_until"]


def subscription_active(user_id):
    until = get_subscription_until(user_id)

    if not until:
        return False

    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)

    return until > now()


def activate_subscription(user_id, days):
    current = get_subscription_until(user_id)
    current_now = now()

    if current and current.tzinfo is None:
        current = current.replace(tzinfo=UTC)

    if current and current > current_now:
        start = current
    else:
        start = current_now

    until = start + timedelta(days=int(days))

    with conn() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE site_users
                SET subscription_until = %s
                WHERE id = %s
                """,
                (until, user_id),
            )

        db.commit()

    return until


def revoke_subscription(user_id):
    with conn() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE site_users
                SET subscription_until = %s
                WHERE id = %s
                """,
                (now(), user_id),
            )

        db.commit()


def use_trial(user_id):
    with conn() as db:
        with db.cursor() as cur:

            cur.execute(
                """
                SELECT trial_used
                FROM site_users
                WHERE id = %s
                FOR UPDATE
                """,
                (user_id,),
            )

            row = cur.fetchone()

            if not row:
                return False

            if row[0]:
                return False

            cur.execute(
                """
                UPDATE site_users
                SET trial_used = TRUE
                WHERE id = %s
                """,
                (user_id,),
            )

        db.commit()

    activate_subscription(user_id, 1)
    return True


def create_payment(
    user_id,
    external_id,
    amount,
    days,
):
    with conn() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO site_payments
                (user_id, external_id, amount, days)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    external_id,
                    amount,
                    days,
                ),
            )

            payment_id = cur.fetchone()[0]

        db.commit()

    return payment_id


def get_payment_by_external_id(external_id):
    with conn() as db:
        with db.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM site_payments
                WHERE external_id = %s
                """,
                (external_id,),
            )

            return cur.fetchone()


def mark_payment_paid(external_id, cashera_id=None):
    with conn() as db:
        with db.cursor() as cur:

            cur.execute(
                """
                UPDATE site_payments
                SET status = 'paid',
                    cashera_id = %s,
                    paid_at = NOW()
                WHERE external_id = %s
                  AND status != 'paid'
                RETURNING user_id, days
                """,
                (
                    cashera_id,
                    external_id,
                ),
            )

            row = cur.fetchone()

        db.commit()

    return row


def get_payment_history(user_id):
    with conn() as db:
        with db.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM site_payments
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (user_id,),
            )

            return cur.fetchall()


def use_promo(user_id, code):
    code = code.strip().upper()

    with conn() as db:
        with db.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT *
                FROM site_promocodes
                WHERE code = %s
                  AND active = TRUE
                FOR UPDATE
                """,
                (code,),
            )

            promo = cur.fetchone()

            if not promo:
                return None

            if promo["uses"] >= promo["max_uses"]:
                return None

            cur.execute(
                """
                SELECT id
                FROM site_promo_uses
                WHERE promo_id = %s
                  AND user_id = %s
                """,
                (
                    promo["id"],
                    user_id,
                ),
            )

            if cur.fetchone():
                return None

            cur.execute(
                """
                INSERT INTO site_promo_uses
                (promo_id, user_id)
                VALUES (%s, %s)
                """,
                (
                    promo["id"],
                    user_id,
                ),
            )

            cur.execute(
                """
                UPDATE site_promocodes
                SET uses = uses + 1
                WHERE id = %s
                """,
                (promo["id"],),
            )

        db.commit()

    activate_subscription(user_id, promo["days"])

    return promo["days"]


def create_promo(code, days, max_uses=1):
    code = code.strip().upper()

    with conn() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO site_promocodes
                (code, days, max_uses)
                VALUES (%s, %s, %s)
                """,
                (
                    code,
                    days,
                    max_uses,
                ),
            )

        db.commit()


def delete_promo(code):
    with conn() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE site_promocodes
                SET active = FALSE
                WHERE code = %s
                """,
                (code.upper(),),
            )

        db.commit()


def get_promos():
    with conn() as db:
        with db.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM site_promocodes
                ORDER BY created_at DESC
                """
            )

            return cur.fetchall()


def get_all_users():
    with conn() as db:
        with db.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM site_users
                ORDER BY id DESC
                """
            )

            return cur.fetchall()


def search_users(q):
    q = f"%{q.strip().lower()}%"

    with conn() as db:
        with db.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT *
                FROM site_users
                WHERE LOWER(username) LIKE %s
                   OR CAST(id AS TEXT) LIKE %s
                ORDER BY id DESC
                """,
                (q, q),
            )

            return cur.fetchall()


def set_blocked(user_id, blocked):
    with conn() as db:
        with db.cursor() as cur:
            cur.execute(
                """
                UPDATE site_users
                SET blocked = %s
                WHERE id = %s
                """,
                (
                    blocked,
                    user_id,
                ),
            )

        db.commit()


def stats():
    with conn() as db:
        with db.cursor() as cur:

            cur.execute("SELECT COUNT(*) FROM site_users")
            users = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM site_users
                WHERE subscription_until > NOW()
                """
            )
            active = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM site_payments
                WHERE status = 'paid'
                """
            )
            revenue = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM site_payments
                WHERE status = 'paid'
                """
            )
            payments = cur.fetchone()[0]

    return {
        "users": users,
        "active": active,
        "revenue": revenue,
        "payments": payments,
    }


init_db()