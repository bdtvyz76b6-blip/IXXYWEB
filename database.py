import os
from datetime import datetime, timezone, timedelta

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(“DATABASE_URL”, “”).strip()

def get_conn():
if not DATABASE_URL:
raise RuntimeError(“DATABASE_URL не задан”)

return psycopg2.connect(
    DATABASE_URL,
    cursor_factory=RealDictCursor,
    connect_timeout=10,
)

def init_db():
“””
Существующую таблицу users бота НЕ создаём и НЕ изменяем.

Создаём только техническую таблицу сайта,
необходимую для защиты от повторной обработки платежа.
"""
conn = get_conn()
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

def get_user(user_id):
conn = get_conn()

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
conn = get_conn()

try:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'users'
        """
    )
    return {
        row["column_name"]
        for row in cur.fetchall()
    }
finally:
    conn.close()

def parse_datetime(value):
if value is None:
return None

if isinstance(value, datetime):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
try:
    return datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
except Exception:
    return None

def subscription_active(user):
if not user:
return False

until = parse_datetime(
    user.get("subscription_until")
)
if not until:
    return False
return until > datetime.now(timezone.utc)

def days_left(user):
if not user:
return 0

until = parse_datetime(
    user.get("subscription_until")
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

def get_subscription_link(user_id):
user = get_user(user_id)

if not user:
    return None
return user.get("subscription_link")

def get_subscription_content(user_id):
user = get_user(user_id)

if not user:
    return None
return user.get("subscription_content")

def update_subscription_data(
user_id,
subscription,
subscription_until,
subscription_link,
subscription_content,
):
columns = get_user_columns()

fields = []
values = []
if "subscription" in columns:
    fields.append("subscription = %s")
    values.append(subscription)
if "subscription_until" in columns:
    fields.append("subscription_until = %s")
    values.append(subscription_until)
if "subscription_link" in columns:
    fields.append("subscription_link = %s")
    values.append(subscription_link)
if "subscription_content" in columns:
    fields.append("subscription_content = %s")
    values.append(subscription_content)
if not fields:
    return False
conn = get_conn()
try:
    cur = conn.cursor()
    values.append(int(user_id))
    cur.execute(
        f"""
        UPDATE users
        SET {", ".join(fields)}
        WHERE user_id = %s
        """,
        values,
    )
    conn.commit()
    return cur.rowcount > 0
finally:
    conn.close()

def extend_subscription(user_id, days):
conn = get_conn()

try:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT subscription_until
        FROM users
        WHERE user_id = %s
        FOR UPDATE
        """,
        (int(user_id),),
    )
    user = cur.fetchone()
    if not user:
        raise RuntimeError(
            "Пользователь не найден"
        )
    old_until = parse_datetime(
        user.get("subscription_until")
    )
    now = datetime.now(timezone.utc)
    if old_until and old_until > now:
        base = old_until
    else:
        base = now
    new_until = (
        base + timedelta(days=int(days))
    )
    columns = get_user_columns()
    fields = [
        "subscription_until = %s"
    ]
    values = [new_until]
    if "subscription" in columns:
        fields.append(
            "subscription = %s"
        )
        values.append("active")
    cur.execute(
        f"""
        UPDATE users
        SET {", ".join(fields)}
        WHERE user_id = %s
        """,
        values + [int(user_id)],
    )
    conn.commit()
    return new_until
finally:
    conn.close()

def create_payment(
user_id,
amount,
days,
external_id,
):
conn = get_conn()

try:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'payments'
        """
    )
    columns = {
        row["column_name"]
        for row in cur.fetchall()
    }
    fields = []
    values = []
    mapping = {
        "user_id": int(user_id),
        "amount": int(amount),
        "days": int(days),
        "external_id": str(external_id),
        "status": "pending",
    }
    for column, value in mapping.items():
        if column in columns:
            fields.append(column)
            values.append(value)
    if not fields:
        raise RuntimeError(
            "В таблице payments нет подходящих полей"
        )
    placeholders = [
        "%s" for _ in fields
    ]
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

def get_payment_by_external_id(external_id):
conn = get_conn()

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
        (str(external_id),),
    )
    return cur.fetchone()
finally:
    conn.close()

def mark_payment_paid(external_id):
conn = get_conn()

try:
    cur = conn.cursor()
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
    cur = conn.cursor()
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
user_id,
days,
amount,
):
conn = get_conn()

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
            str(external_id),
            int(user_id),
            int(days),
            int(amount),
        ),
    )
    conn.commit()
finally:
    conn.close()

def get_stats():
conn = get_conn()

try:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS count FROM users"
    )
    users = cur.fetchone()["count"]
    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM users
        WHERE subscription_until > NOW()
        """
    )
    active = cur.fetchone()["count"]
    try:
        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM payments
            WHERE status = 'paid'
            """
        )
        paid = cur.fetchone()["count"]
    except Exception:
        paid = 0
    return {
        "users": users,
        "active": active,
        "paid": paid,
    }
finally:
    conn.close()