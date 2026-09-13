import os
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import RealDictCursor


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не задан")

    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
    )


def init_db():
    conn = get_conn()

    try:
        with conn.cursor() as cur:
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
                """
            )

            return {
                row[0]
                for row in cur.fetchall()
            }

    finally:
        conn.close()


def get_user(user_id):
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
                LIMIT 1
                """,
                (int(user_id),),
            )

            row = cur.fetchone()

            if not row:
                return None

            return tuple(row.values())

    finally:
        conn.close()


def get_user_by_login(login):
    """
    Поиск пользователя по Telegram ID или username.

    Можно вводить:
        123456789
        @username
        username
    """

    if login is None:
        return None

    login = str(login).strip()

    if not login:
        return None

    conn = get_conn()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            if login.isdigit():
                cur.execute(
                    """
                    SELECT *
                    FROM users
                    WHERE user_id = %s
                    LIMIT 1
                    """,
                    (int(login),),
                )

            else:
                username = login.lstrip("@").strip()

                cur.execute(
                    """
                    SELECT *
                    FROM users
                    WHERE LOWER(username) = LOWER(%s)
                    LIMIT 1
                    """,
                    (username,),
                )

            return cur.fetchone()

    finally:
        conn.close()


def register_user(login):
    """
    Регистрация пользователя на сайте.

    Регистрация не использует Telegram API
    и не требует работающего бота.

    Если пользователь уже есть в users,
    возвращается существующий пользователь.

    Если введён Telegram ID:
        создаётся пользователь с этим ID.

    Если введён username:
        создать пользователя без Telegram ID
        невозможно, поэтому возвращается ошибка.
    """

    if login is None:
        raise ValueError("Введите Telegram ID или username")

    login = str(login).strip()

    if not login:
        raise ValueError("Введите Telegram ID или username")

    existing = get_user_by_login(login)

    if existing:
        return existing

    if not login.isdigit():
        raise ValueError(
            "Для первой регистрации нужен Telegram ID"
        )

    user_id = int(login)

    columns = get_user_columns()

    insert_columns = []
    insert_values = []

    if "user_id" not in columns:
        raise RuntimeError(
            "В таблице users нет user_id"
        )

    insert_columns.append("user_id")
    insert_values.append(user_id)

    if "username" in columns:
        insert_columns.append("username")
        insert_values.append(None)

    if "first_name" in columns:
        insert_columns.append("first_name")
        insert_values.append(None)

    if "subscription" in columns:
        insert_columns.append("subscription")
        insert_values.append("inactive")

    if "subscription_until" in columns:
        insert_columns.append("subscription_until")
        insert_values.append(None)

    if "trial_used" in columns:
        insert_columns.append("trial_used")
        insert_values.append(False)

    if "pending_days" in columns:
        insert_columns.append("pending_days")
        insert_values.append(0)

    if "notify" in columns:
        insert_columns.append("notify")
        insert_values.append(True)

    if "accepted_terms" in columns:
        insert_columns.append("accepted_terms")
        insert_values.append(True)

    if "created_at" in columns:
        insert_columns.append("created_at")
        insert_values.append(datetime.now(timezone.utc))

    placeholders = ", ".join(
        ["%s"] * len(insert_values)
    )

    column_sql = ", ".join(
        f'"{column}"'
        for column in insert_columns
    )

    conn = get_conn()

    try:
        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                f"""
                INSERT INTO users
                    ({column_sql})
                VALUES
                    ({placeholders})
                ON CONFLICT (user_id)
                DO NOTHING
                RETURNING *
                """,
                tuple(insert_values),
            )

            row = cur.fetchone()

            if not row:
                cur.execute(
                    """
                    SELECT *
                    FROM users
                    WHERE user_id = %s
                    LIMIT 1
                    """,
                    (user_id,),
                )

                row = cur.fetchone()

        conn.commit()

        return row

    except Exception:
        conn.rollback()
        raise

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
                LIMIT 1
                """,
                (int(user_id),),
            )

            return cur.fetchone()

    finally:
        conn.close()


def get_value(user_id, column):
    allowed = get_user_columns()

    if column not in allowed:
        return None

    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT "{column}"
                FROM users
                WHERE user_id = %s
                LIMIT 1
                """,
                (int(user_id),),
            )

            row = cur.fetchone()

            if not row:
                return None

            return row[0]

    finally:
        conn.close()


def parse_datetime(value):
    if not value:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt


def subscription_active(value):
    dt = parse_datetime(value)

    if not dt:
        return False

    return dt > datetime.now(timezone.utc)


def days_left(value):
    dt = parse_datetime(value)

    if not dt:
        return 0

    seconds = (
        dt - datetime.now(timezone.utc)
    ).total_seconds()

    if seconds <= 0:
        return 0

    return max(
        1,
        int(seconds / 86400),
    )


def format_date(value):
    dt = parse_datetime(value)

    if not dt:
        return "—"

    return dt.strftime("%d.%m.%Y")


def get_subscription_link(user_id):
    columns = get_user_columns()

    if "subscription_link" not in columns:
        return None

    return get_value(
        user_id,
        "subscription_link",
    )


def get_subscription_content(user_id):
    columns = get_user_columns()

    if "subscription_content" not in columns:
        return None

    return get_value(
        user_id,
        "subscription_content",
    )


def update_subscription_data(
    user_id,
    subscription_until,
    content=None,
    subscription_link=None,
):
    columns = get_user_columns()

    updates = []
    values = []

    if "subscription" in columns:
        updates.append(
            '"subscription" = %s'
        )

        values.append(
            "active"
            if subscription_until
            and subscription_active(
                subscription_until
            )
            else "inactive"
        )

    if "subscription_until" in columns:
        updates.append(
            '"subscription_until" = %s'
        )
        values.append(
            subscription_until
        )

    if (
        content is not None
        and "subscription_content" in columns
    ):
        updates.append(
            '"subscription_content" = %s'
        )
        values.append(content)

    if (
        subscription_link is not None
        and "subscription_link" in columns
    ):
        updates.append(
            '"subscription_link" = %s'
        )
        values.append(subscription_link)

    if not updates:
        return False

    values.append(int(user_id))

    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE users
                SET {", ".join(updates)}
                WHERE user_id = %s
                """,
                tuple(values),
            )

        conn.commit()

    finally:
        conn.close()

    return True


def extend_subscription(
    user_id,
    days,
):
    columns = get_user_columns()

    if "subscription_until" not in columns:
        raise RuntimeError(
            "В таблице users нет subscription_until"
        )

    conn = get_conn()

    try:
        with conn.cursor() as cur:
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

            if not row:
                raise RuntimeError(
                    "Пользователь не найден"
                )

            current = parse_datetime(
                row[0]
            )

            now = datetime.now(
                timezone.utc
            )

            if current and current > now:
                base = current
            else:
                base = now

            new_until = (
                base
                + timedelta(days=int(days))
            )

            updates = [
                '"subscription_until" = %s'
            ]

            values = [new_until]

            if "subscription" in columns:
                updates.append(
                    '"subscription" = %s'
                )
                values.append("active")

            if "pending_days" in columns:
                updates.append(
                    '"pending_days" = %s'
                )
                values.append(0)

            values.append(int(user_id))

            cur.execute(
                f"""
                UPDATE users
                SET {", ".join(updates)}
                WHERE user_id = %s
                """,
                tuple(values),
            )

        conn.commit()

        return new_until

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def create_payment(
    user_id,
    amount,
    days,
    external_id,
    status="pending",
):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
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
                    (%s, %s, %s, %s, %s, NOW())
                """,
                (
                    int(user_id),
                    int(amount),
                    int(days),
                    str(external_id),
                    str(status),
                ),
            )

        conn.commit()

    finally:
        conn.close()


def get_payment_by_external_id(
    external_id,
):
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
                LIMIT 1
                """,
                (str(external_id),),
            )

            return cur.fetchone()

    finally:
        conn.close()


def mark_payment_paid(
    external_id,
):
    conn = get_conn()

    try:
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

    finally:
        conn.close()


def payment_processed(
    external_id,
):
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


def mark_payment_processed(
    external_id,
):
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

            total_users = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE subscription_until IS NOT NULL
                  AND subscription_until > NOW()
                """
            )

            active_users = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE subscription_until IS NOT NULL
                  AND subscription_until <= NOW()
                """
            )

            expired_users = cur.fetchone()[0]

            return {
                "users": total_users,
                "active": active_users,
                "expired": expired_users,
            }

    finally:
        conn.close()


# ============================================================
# INIT
# ============================================================

try:
    init_db()
except Exception as e:
    print(
        f"[database] init warning: {e}"
    )