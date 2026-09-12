import os
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
load_dotenv()
# ============================================================
# CONFIG
# ============================================================
DATABASE_URL = os.getenv("DATABASE_URL")
UTC = timezone.utc
# ============================================================
# DATABASE
# ============================================================
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL не установлен")
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        sslmode="require",
    )
# ============================================================
# TIME
# ============================================================
def now_utc():
    return datetime.now(UTC)
def parse_datetime(value):
    """
    Преобразует дату из PostgreSQL / строки в datetime UTC.
    Поддерживает:
    - datetime
    - ISO string
    - PostgreSQL timestamp string
    - даты с Z
    - даты без timezone
    """
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            # 2026-09-12T22:00:00Z
            value = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            # Дополнительные PostgreSQL-форматы
            formats = [
                "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d",
            ]
            for fmt in formats:
                try:
                    dt = datetime.strptime(value, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    return dt.astimezone(UTC)
                except ValueError:
                    continue
    return None
def format_date(value):
    dt = parse_datetime(value)
    if not dt:
        return "—"
    return dt.strftime("%d.%m.%Y")
# ============================================================
# USERNAME / LOGIN
# ============================================================
def normalize_username(username):
    if not username:
        return None
    username = str(username).strip()
    if username.startswith("@"):
        username = username[1:]
    return username.lower()
def is_telegram_id(value):
    if not value:
        return False
    value = str(value).strip()
    if value.startswith("-"):
        return value[1:].isdigit()
    return value.isdigit()
# ============================================================
# USERS
# ============================================================
def get_user(user_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
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
def get_user_by_username(username):
    username = normalize_username(username)
    if not username:
        return None
    conn = get_conn()
    try:
        with conn.cursor() as cur:
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
def get_user_by_login(login):
    """
    Поиск пользователя по:
    - Telegram ID
    - Telegram username
    """
    if not login:
        return None
    login = str(login).strip()
    if is_telegram_id(login):
        try:
            return get_user(int(login))
        except Exception:
            return None
    username = normalize_username(login)
    if not username:
        return None
    return get_user_by_username(username)
def create_site_user(login, first_name="Пользователь"):
    """
    Создаёт пользователя сайта.
    Если login — Telegram ID:
        user_id = Telegram ID
    Если login — username:
        PostgreSQL сам выдаёт user_id.
    Существующего пользователя повторно не создаёт.
    """
    if not login:
        raise ValueError("Не указан Telegram ID или username")
    login = str(login).strip()
    existing = get_user_by_login(login)
    if existing:
        return int(existing["user_id"])
    username = None
    telegram_id = None
    if is_telegram_id(login):
        telegram_id = int(login)
    else:
        username = normalize_username(login)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if telegram_id is not None:
                cur.execute(
                    """
                    INSERT INTO users (
                        user_id,
                        username,
                        first_name,
                        subscription,
                        subscription_until,
                        subscription_link,
                        uuid,
                        trial_used,
                        pending_days,
                        notify,
                        accepted_terms,
                        created_at,
                        subscription_content
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        FALSE,
                        NULL,
                        NULL,
                        NULL,
                        FALSE,
                        0,
                        TRUE,
                        FALSE,
                        NOW(),
                        NULL
                    )
                    ON CONFLICT (user_id)
                    DO NOTHING
                    RETURNING user_id
                    """,
                    (
                        telegram_id,
                        username,
                        first_name or "Пользователь",
                    ),
                )
                row = cur.fetchone()
                if row:
                    user_id = int(row["user_id"])
                else:
                    user_id = telegram_id
                # Синхронизируем sequence PostgreSQL,
                # если user_id был задан вручную.
                try:
                    cur.execute(
                        """
                        SELECT setval(
                            pg_get_serial_sequence('users', 'user_id'),
                            GREATEST(
                                COALESCE(
                                    (SELECT MAX(user_id) FROM users),
                                    1
                                ),
                                1
                            ),
                            true
                        )
                        """
                    )
                except Exception:
                    conn.rollback()
            else:
                cur.execute(
                    """
                    INSERT INTO users (
                        username,
                        first_name,
                        subscription,
                        subscription_until,
                        subscription_link,
                        uuid,
                        trial_used,
                        pending_days,
                        notify,
                        accepted_terms,
                        created_at,
                        subscription_content
                    )
                    VALUES (
                        %s,
                        %s,
                        FALSE,
                        NULL,
                        NULL,
                        NULL,
                        FALSE,
                        0,
                        TRUE,
                        FALSE,
                        NOW(),
                        NULL
                    )
                    RETURNING user_id
                    """,
                    (
                        username,
                        first_name or "Пользователь",
                    ),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError(
                        "Не удалось создать пользователя"
                    )
                user_id = int(row["user_id"])
        conn.commit()
        return user_id
    finally:
        conn.close()
# ============================================================
# SUBSCRIPTION
# ============================================================
def subscription_active(until):
    """
    Проверяет активна ли подписка.
    Важно:
    PostgreSQL может вернуть datetime,
    а некоторые существующие данные могут приходить строкой.
    """
    until = parse_datetime(until)
    if until is None:
        return False
    return until > now_utc()
def get_subscription_until(user_id):
    user = get_user(user_id)
    if not user:
        return None
    return parse_datetime(
        user.get("subscription_until")
    )
def save_subscription(
    user_id,
    subscription_until,
    subscription_link=None,
    subscription_content=None,
):
    """
    Сохраняет данные подписки.
    """
    subscription_until = parse_datetime(subscription_until)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if subscription_link is None and subscription_content is None:
                cur.execute(
                    """
                    UPDATE users
                    SET
                        subscription = %s,
                        subscription_until = %s
                    WHERE user_id = %s
                    """,
                    (
                        bool(
                            subscription_until
                            and subscription_until > now_utc()
                        ),
                        subscription_until,
                        int(user_id),
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE users
                    SET
                        subscription = %s,
                        subscription_until = %s,
                        subscription_link = %s,
                        subscription_content = %s
                    WHERE user_id = %s
                    """,
                    (
                        bool(
                            subscription_until
                            and subscription_until > now_utc()
                        ),
                        subscription_until,
                        subscription_link,
                        subscription_content,
                        int(user_id),
                    ),
                )
        conn.commit()
    finally:
        conn.close()
def extend_subscription(user_id, days):
    """
    Продлевает подписку пользователя.
    """
    days = int(days)
    if days <= 0:
        return False
    user = get_user(user_id)
    if not user:
        return False
    current = parse_datetime(
        user.get("subscription_until")
    )
    current_now = now_utc()
    if current and current > current_now:
        new_until = current + timedelta(days=days)
    else:
        new_until = current_now + timedelta(days=days)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET
                    subscription = TRUE,
                    subscription_until = %s
                WHERE user_id = %s
                """,
                (
                    new_until,
                    int(user_id),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return new_until
def expire_old_subscriptions():
    """
    Помечает просроченные подписки как неактивные.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET subscription = FALSE
                WHERE subscription = TRUE
                  AND subscription_until IS NOT NULL
                  AND subscription_until < NOW()
                """
            )
            count = cur.rowcount
        conn.commit()
        return count
    finally:
        conn.close()
# ============================================================
# TRIAL
# ============================================================
def use_trial(user_id, days=1):
    """
    Выдаёт пробный период один раз.
    """
    days = int(days)
    if days <= 0:
        return False
    user = get_user(user_id)
    if not user:
        return False
    if user.get("trial_used"):
        return False
    current = parse_datetime(
        user.get("subscription_until")
    )
    current_now = now_utc()
    if current and current > current_now:
        new_until = current + timedelta(days=days)
    else:
        new_until = current_now + timedelta(days=days)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET
                    subscription = TRUE,
                    subscription_until = %s,
                    trial_used = TRUE
                WHERE user_id = %s
                  AND COALESCE(trial_used, FALSE) = FALSE
                """,
                (
                    new_until,
                    int(user_id),
                ),
            )
            updated = cur.rowcount
        conn.commit()
        return updated > 0
    finally:
        conn.close()
# ============================================================
# PAYMENTS
# ============================================================
def create_payment(
    user_id,
    amount,
    days,
    external_id,
):
    """
    Создаёт платёж в существующей таблице payments.
    Поддерживает старую структуру таблицы.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO payments (
                    user_id,
                    amount,
                    days,
                    external_id,
                    status,
                    created_at
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    'pending',
                    NOW()
                )
                RETURNING *
                """,
                (
                    int(user_id),
                    amount,
                    int(days),
                    str(external_id),
                ),
            )
            row = cur.fetchone()
        conn.commit()
        return row
    finally:
        conn.close()
def get_payment_by_external_id(external_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
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
def complete_payment(external_id):
    """
    Помечает платёж как оплаченный.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE payments
                SET status = 'paid'
                WHERE external_id = %s
                """,
                (str(external_id),),
            )
        conn.commit()
    finally:
        conn.close()
def process_paid_payment(external_id):
    """
    Идемпотентная обработка оплаченного платежа.
    Возвращает:
        True  — подписка была выдана
        False — платёж уже обработан / не найден
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM payments
                WHERE external_id = %s
                FOR UPDATE
                """,
                (str(external_id),),
            )
            payment = cur.fetchone()
            if not payment:
                conn.rollback()
                return False
            if str(payment.get("status", "")).lower() == "paid":
                conn.rollback()
                return False
            user_id = int(payment["user_id"])
            days = int(payment["days"])
            user = None
            cur.execute(
                """
                SELECT *
                FROM users
                WHERE user_id = %s
                FOR UPDATE
                """,
                (user_id,),
            )
            user = cur.fetchone()
            if not user:
                conn.rollback()
                return False
            current = parse_datetime(
                user.get("subscription_until")
            )
            current_now = now_utc()
            if current and current > current_now:
                new_until = current + timedelta(days=days)
            else:
                new_until = current_now + timedelta(days=days)
            cur.execute(
                """
                UPDATE users
                SET
                    subscription = TRUE,
                    subscription_until = %s
                WHERE user_id = %s
                """,
                (
                    new_until,
                    user_id,
                ),
            )
            cur.execute(
                """
                UPDATE payments
                SET
                    status = 'paid'
                WHERE external_id = %s
                """,
                (str(external_id),),
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
# ============================================================
# PROMOCODES
# ============================================================
def use_promocode(user_id, code):
    """
    Использует промокод один раз для конкретного пользователя.
    Ожидаемая таблица promocodes:
        code
        days
        max_uses
        uses
        active
    Ожидаемая таблица promocode_uses:
        user_id
        code
        created_at
    """
    if not code:
        return False
    code = str(code).strip().upper()
    if not code:
        return False
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM promocodes
                WHERE UPPER(code) = %s
                  AND COALESCE(active, TRUE) = TRUE
                FOR UPDATE
                """,
                (code,),
            )
            promo = cur.fetchone()
            if not promo:
                conn.rollback()
                return False
            cur.execute(
                """
                SELECT 1
                FROM promocode_uses
                WHERE user_id = %s
                  AND UPPER(code) = %s
                LIMIT 1
                """,
                (
                    int(user_id),
                    code,
                ),
            )
            already_used = cur.fetchone()
            if already_used:
                conn.rollback()
                return False
            max_uses = promo.get("max_uses")
            uses = int(promo.get("uses") or 0)
            if max_uses is not None:
                if uses >= int(max_uses):
                    conn.rollback()
                    return False
            days = int(promo.get("days") or 0)
            if days <= 0:
                conn.rollback()
                return False
            user = get_user(user_id)
            current = None
            if user:
                current = parse_datetime(
                    user.get("subscription_until")
                )
            current_now = now_utc()
            if current and current > current_now:
                new_until = current + timedelta(days=days)
            else:
                new_until = current_now + timedelta(days=days)
            cur.execute(
                """
                UPDATE users
                SET
                    subscription = TRUE,
                    subscription_until = %s
                WHERE user_id = %s
                """,
                (
                    new_until,
                    int(user_id),
                ),
            )
            cur.execute(
                """
                INSERT INTO promocode_uses (
                    user_id,
                    code,
                    created_at
                )
                VALUES (
                    %s,
                    %s,
                    NOW()
                )
                """,
                (
                    int(user_id),
                    code,
                ),
            )
            cur.execute(
                """
                UPDATE promocodes
                SET uses = COALESCE(uses, 0) + 1
                WHERE UPPER(code) = %s
                """,
                (code,),
            )
        conn.commit()
        return days
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
# ============================================================
# DATABASE INIT
# ============================================================
def init_db():
    """
    Проверяет существующую структуру БД.
    Новую базу не создаёт.
    Добавляет только совместимые поля/индексы,
    если их нет.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # ------------------------------------------------
            # USERS
            # ------------------------------------------------
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS username TEXT
                """
            )
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS first_name TEXT
                """
            )
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS subscription BOOLEAN DEFAULT FALSE
                """
            )
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS subscription_until TIMESTAMPTZ
                """
            )
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS subscription_link TEXT
                """
            )
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS uuid TEXT
                """
            )
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS trial_used BOOLEAN DEFAULT FALSE
                """
            )
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS pending_days INTEGER DEFAULT 0
                """
            )
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS notify BOOLEAN DEFAULT TRUE
                """
            )
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS accepted_terms BOOLEAN DEFAULT FALSE
                """
            )
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()
                """
            )
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS subscription_content TEXT
                """
            )
            # Старые поля сайта оставляем для совместимости.
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS email TEXT
                """
            )
            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS password_hash TEXT
                """
            )
            # ------------------------------------------------
            # PAYMENTS
            # ------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT,
                    amount NUMERIC,
                    days INTEGER,
                    external_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            # ------------------------------------------------
            # PROMOCODES
            # ------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS promocodes (
                    id BIGSERIAL PRIMARY KEY,
                    code TEXT UNIQUE NOT NULL,
                    days INTEGER NOT NULL,
                    max_uses INTEGER,
                    uses INTEGER DEFAULT 0,
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            # ------------------------------------------------
            # PROMOCODE USES
            # ------------------------------------------------
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS promocode_uses (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    code TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            # ------------------------------------------------
            # INDEXES
            # ------------------------------------------------
            try:
                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    users_username_unique_idx
                    ON users (LOWER(username))
                    WHERE username IS NOT NULL
                    """
                )
            except Exception:
                # Если в старой БД уже есть дубликаты username,
                # индекс не должен ломать запуск сайта.
                conn.rollback()
            try:
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    payments_external_id_idx
                    ON payments (external_id)
                    """
                )
            except Exception:
                conn.rollback()
            try:
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                    promocode_uses_user_code_idx
                    ON promocode_uses (user_id, code)
                    """
                )
            except Exception:
                conn.rollback()
        conn.commit()
    finally:
        conn.close()
# ============================================================
# AUTO INIT
# ============================================================
try:
    init_db()
except Exception as e:
    print(
        "Database init warning:",
        repr(e),
    )