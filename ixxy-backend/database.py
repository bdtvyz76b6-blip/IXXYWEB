import os
import logging

from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    ""
).strip()

MAX_PROMO_DAYS = int(
    os.getenv(
        "MAX_PROMO_DAYS",
        "999999999999"
    )
)

UTC = timezone.utc


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL не задан"
        )

    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require"
    )


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:

            cur.execute("""
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
            """)

            cur.execute("""
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
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS
                web_processed_payments (
                    external_id TEXT PRIMARY KEY,
                    processed_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_payments_external_id
                ON payments(external_id)
            """)

            conn.commit()


def get_user_columns():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'users'
                ORDER BY ordinal_position
            """)

            return [
                row[0]
                for row in cur.fetchall()
            ]


def create_user(
    user_id,
    username=None,
    first_name=None
):
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute("""
                INSERT INTO users (
                    user_id,
                    username,
                    first_name
                )
                VALUES (%s, %s, %s)
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
            """, (
                int(user_id),
                username,
                first_name
            ))

            return dict(cur.fetchone())


def register_user(
    user_id,
    username=None,
    first_name=None
):
    return create_user(
        user_id,
        username,
        first_name
    )


def get_user(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT *
                FROM users
                WHERE user_id = %s
            """, (int(user_id),))

            return cur.fetchone()


def get_user_dict(user_id):
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute("""
                SELECT *
                FROM users
                WHERE user_id = %s
            """, (int(user_id),))

            row = cur.fetchone()

            return dict(row) if row else None


def get_user_by_login(login):
    login = str(login).strip().lstrip("@")

    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute("""
                SELECT *
                FROM users
                WHERE LOWER(username) = LOWER(%s)
                LIMIT 1
            """, (login,))

            row = cur.fetchone()

            return dict(row) if row else None


def get_all_users():
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute("""
                SELECT *
                FROM users
                ORDER BY created_at DESC
            """)

            return [
                dict(row)
                for row in cur.fetchall()
            ]


def count_users():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM users
            """)

            return cur.fetchone()[0]


def subscription_active(value):
    if not value:
        return False

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except Exception:
            return False

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )

    return value > datetime.now(timezone.utc)


def days_left(value):
    if not value:
        return 0

    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except Exception:
            return 0

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc
        )

    seconds = (
        value -
        datetime.now(timezone.utc)
    ).total_seconds()

    if seconds <= 0:
        return 0

    return int(
        (seconds + 86399) // 86400
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

    return user.get(
        "subscription_content"
    )


def update_subscription_data(
    user_id,
    subscription_link=None,
    subscription_content=None
):
    with get_conn() as conn:
        with conn.cursor() as cur:

            cur.execute("""
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
            """, (
                subscription_link,
                subscription_content,
                int(user_id)
            ))

            conn.commit()


def save_subscription_link(
    user_id,
    link
):
    update_subscription_data(
        user_id,
        subscription_link=link
    )


def save_subscription_content(
    user_id,
    content
):
    update_subscription_data(
        user_id,
        subscription_content=content
    )


def extend_subscription(
    user_id,
    days
):
    now = datetime.now(timezone.utc)

    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute("""
                SELECT subscription_until
                FROM users
                WHERE user_id = %s
            """, (int(user_id),))

            row = cur.fetchone()

            if not row:
                return None

            current = row["subscription_until"]

            if (
                current and
                current.tzinfo is None
            ):
                current = current.replace(
                    tzinfo=timezone.utc
                )

            if current and current > now:
                base = current
            else:
                base = now

            from datetime import timedelta

            new_until = (
                base +
                timedelta(days=int(days))
            )

            cur.execute("""
                UPDATE users
                SET
                    subscription_until = %s,
                    subscription = %s
                WHERE user_id = %s
                RETURNING *
            """, (
                new_until,
                new_until,
                int(user_id)
            ))

            result = cur.fetchone()

            conn.commit()

            return dict(result)


def disable_subscription(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET
                    subscription = NULL,
                    subscription_until = NULL
                WHERE user_id = %s
            """, (int(user_id),))

            conn.commit()


def deactivate_subscription(user_id):
    disable_subscription(user_id)


def use_trial(user_id, days=3):
    user = get_user_dict(user_id)

    if not user:
        return False

    if user.get("trial_used"):
        return False

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET trial_used = TRUE
                WHERE user_id = %s
            """, (int(user_id),))

            conn.commit()

    extend_subscription(
        user_id,
        min(int(days), MAX_PROMO_DAYS)
    )

    return True


def use_promo(*args, **kwargs):
    return False


def create_payment(
    user_id,
    amount,
    days,
    external_id
):
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute("""
                INSERT INTO payments (
                    user_id,
                    amount,
                    days,
                    external_id,
                    status
                )
                VALUES (
                    %s, %s, %s, %s, 'pending'
                )
                RETURNING *
            """, (
                int(user_id),
                int(amount),
                int(days),
                str(external_id)
            ))

            row = cur.fetchone()

            conn.commit()

            return dict(row)


def get_payment_by_external_id(
    external_id
):
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute("""
                SELECT *
                FROM payments
                WHERE external_id = %s
                LIMIT 1
            """, (str(external_id),))

            row = cur.fetchone()

            return dict(row) if row else None


def mark_payment_paid(
    external_id
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE payments
                SET
                    status = 'paid',
                    paid_at = NOW()
                WHERE external_id = %s
            """, (str(external_id),))

            conn.commit()


def payment_processed(
    external_id
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1
                FROM web_processed_payments
                WHERE external_id = %s
            """, (str(external_id),))

            return cur.fetchone() is not None


def mark_payment_processed(
    external_id
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO web_processed_payments (
                    external_id
                )
                VALUES (%s)
                ON CONFLICT DO NOTHING
            """, (str(external_id),))

            conn.commit()


def get_all_payments():
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute("""
                SELECT *
                FROM payments
                ORDER BY created_at DESC
            """)

            return [
                dict(row)
                for row in cur.fetchall()
            ]


def get_payments():
    return get_all_payments()


def get_user_payments(user_id):
    with get_conn() as conn:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute("""
                SELECT *
                FROM payments
                WHERE user_id = %s
                ORDER BY created_at DESC
            """, (int(user_id),))

            return [
                dict(row)
                for row in cur.fetchall()
            ]


def expire_old_subscriptions():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET subscription = NULL
                WHERE subscription_until IS NOT NULL
                  AND subscription_until <= NOW()
            """)

            conn.commit()


def get_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT COUNT(*)
                FROM users
            """)
            users = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*)
                FROM users
                WHERE subscription_until > NOW()
            """)
            active = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*)
                FROM payments
                WHERE status = 'paid'
            """)
            paid = cur.fetchone()[0]

            return {
                "users": users,
                "active": active,
                "paid_payments": paid,
            }


try:
    init_db()
except Exception as e:
    print(
        "⚠️ Database init warning:",
        e
    )