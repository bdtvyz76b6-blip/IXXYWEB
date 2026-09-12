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
    Преобразует:
    - datetime
    - ISO string
    - PostgreSQL timestamp
    - дату с Z
    - дату без timezone

    в timezone-aware datetime UTC.
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

        value = value.replace("Z", "+00:00")

        try:
            dt = datetime.fromisoformat(value)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)

            return dt.astimezone(UTC)

        except ValueError:
            pass

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
    Telegram ID или username.
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


def create_user(
    user_id,
    username=None,
    first_name=None,
):
    """
    Создаёт Telegram-пользователя,
    если его ещё нет.
    """

    user_id = int(user_id)

    existing = get_user(user_id)

    if existing:
        return existing

    username = normalize_username(username)

    conn = get_conn()

    try:
        with conn.cursor() as cur:
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
                DO UPDATE SET
                    username = COALESCE(EXCLUDED.username, users.username),
                    first_name = COALESCE(EXCLUDED.first_name, users.first_name)
                RETURNING *
                """,
                (
                    user_id,
                    username,
                    first_name or "Пользователь",
                ),
            )

            row = cur.fetchone()

        conn.commit()

        return row

    finally:
        conn.close()


def create_site_user(
    login,
    first_name="Пользователь",
):
    """
    Создание пользователя через сайт.

    Если login = Telegram ID,
    используется этот ID.

    Если login = username,
    PostgreSQL создаёт ID.
    """

    if not login:
        raise ValueError(
            "Не указан Telegram ID или username"
        )

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
    until = parse_datetime(until)

    if until is None:
        return False

    return until > now_utc()


def check_user_subscription(user_id):
    """
    Проверяет подписку и возвращает bool.
    """

    user = get_user(user_id)

    if not user:
        return False

    until = parse_datetime(
        user.get("subscription_until")
    )

    active = (
        bool(user.get("subscription"))
        and until is not None
        and until > now_utc()
    )

    return active


def is_subscription_active(user_id):
    return check_user_subscription(user_id)


def get_subscription_until(user_id):
    user = get_user(user_id)

    if not user:
        return None

    return parse_datetime(
        user.get("subscription_until")
    )


def get_subscription_content(user_id):
    """
    Возвращает сохранённое содержимое подписки.
    """

    user = get_user(user_id)

    if not user:
        return None

    return user.get("subscription_content")


def get_subscription_link(user_id):
    """
    Возвращает сохранённую ссылку подписки.
    """

    user = get_user(user_id)

    if not user:
        return None

    return user.get("subscription_link")


def save_subscription(
    user_id,
    subscription_until,
    subscription_link=None,
    subscription_content=None,
):
    """
    Сохраняет состояние подписки.
    """

    subscription_until = parse_datetime(
        subscription_until
    )

    active = bool(
        subscription_until
        and subscription_until > now_utc()
    )

    conn = get_conn()

    try:
        with conn.cursor() as cur:

            if (
                subscription_link is None
                and subscription_content is None
            ):

                cur.execute(
                    """
                    UPDATE users
                    SET
                        subscription = %s,
                        subscription_until = %s
                    WHERE user_id = %s
                    """,
                    (
                        active,
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
                        active,
                        subscription_until,
                        subscription_link,
                        subscription_content,
                        int(user_id),
                    ),
                )

        conn.commit()

    finally:
        conn.close()


def save_subscription_link(
    user_id,
    subscription_link,
):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET subscription_link = %s
                WHERE user_id = %s
                """,
                (
                    subscription_link,
                    int(user_id),
                ),
            )

        conn.commit()

    finally:
        conn.close()


def save_subscription_content(
    user_id,
    subscription_content,
):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET subscription_content = %s
                WHERE user_id = %s
                """,
                (
                    subscription_content,
                    int(user_id),
                ),
            )

        conn.commit()

    finally:
        conn.close()


def extend_subscription(user_id, days):
    """
    Продлевает подписку.
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


def activate_subscription(
    user_id,
    days,
):
    return extend_subscription(
        user_id,
        days,
    )


def deactivate_subscription(user_id):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET subscription = FALSE
                WHERE user_id = %s
                """,
                (int(user_id),),
            )

        conn.commit()

    finally:
        conn.close()


def expire_old_subscriptions():
    """
    Помечает просроченные подписки неактивными.
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
                  AND subscription_until <= NOW()
                """
            )

            count = cur.rowcount

        conn.commit()

        return count

    finally:
        conn.close()


def check_expired_subscriptions():
    return expire_old_subscriptions()


def get_expired_users():
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM users
                WHERE subscription = TRUE
                  AND subscription_until IS NOT NULL
                  AND subscription_until <= NOW()
                ORDER BY user_id
                """
            )

            return cur.fetchall()

    finally:
        conn.close()


def disable_subscription(user_id):
    deactivate_subscription(user_id)


# ============================================================
# TRIAL
# ============================================================

def check_trial(user_id):
    user = get_user(user_id)

    if not user:
        return False

    return not bool(
        user.get("trial_used")
    )


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


def activate_trial(user_id, days=1):
    return use_trial(
        user_id,
        days,
    )


# ============================================================
# TERMS
# ============================================================

def has_accepted_terms(user_id):
    user = get_user(user_id)

    if not user:
        return False

    return bool(
        user.get("accepted_terms")
    )


def accept_terms(user_id):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET accepted_terms = TRUE
                WHERE user_id = %s
                """,
                (int(user_id),),
            )

        conn.commit()

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
    Создаёт платёж.

    external_id = ID платежа CasheRa.
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


def add_payment(
    user_id,
    amount,
    days,
    external_id=None,
):
    """
    Совместимость со старым кодом.
    """

    if external_id is None:
        external_id = (
            f"local_{user_id}_"
            f"{int(datetime.now().timestamp())}"
        )

    return create_payment(
        user_id=user_id,
        amount=amount,
        days=days,
        external_id=external_id,
    )


def save_payment_id(
    user_id,
    payment_id,
):
    """
    Совместимость со старым кодом.

    Если платёж уже существует — ничего не ломает.
    Если не существует — создаёт запись.
    """

    payment = get_payment_by_external_id(
        payment_id
    )

    if payment:
        return payment

    return None


def get_payment_by_external_id(external_id):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
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


def get_payment_by_payment_id(payment_id):
    """
    Совместимость с bot.py.
    """

    return get_payment_by_external_id(
        payment_id
    )


def get_payment(payment_id):
    return get_payment_by_external_id(
        payment_id
    )


def update_payment_status(
    payment_id,
    status,
):
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE payments
                SET status = %s
                WHERE external_id = %s
                """,
                (
                    str(status),
                    str(payment_id),
                ),
            )

        conn.commit()

    finally:
        conn.close()


def complete_payment(external_id):
    update_payment_status(
        external_id,
        "paid",
    )


def process_paid_payment(external_id):
    """
    Идемпотентно:
    1. находит платёж;
    2. проверяет, не обработан ли он;
    3. продлевает пользователя;
    4. ставит paid.

    Возвращает True, если подписка была выдана.
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

            if str(
                payment.get("status", "")
            ).lower() == "paid":

                conn.rollback()
                return False

            user_id = int(
                payment["user_id"]
            )

            days = int(
                payment["days"]
            )

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
                user.get(
                    "subscription_until"
                )
            )

            current_now = now_utc()

            if current and current > current_now:
                new_until = (
                    current
                    + timedelta(days=days)
                )
            else:
                new_until = (
                    current_now
                    + timedelta(days=days)
                )

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
                    status = 'paid',
                    paid_at = NOW()
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

def use_promocode(
    user_id,
    code,
):
    """
    Использует промокод один раз
    для конкретного пользователя.
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

            if cur.fetchone():
                conn.rollback()
                return False

            max_uses = promo.get(
                "max_uses"
            )

            uses = int(
                promo.get("uses") or 0
            )

            if (
                max_uses is not None
                and uses >= int(max_uses)
            ):
                conn.rollback()
                return False

            days = int(
                promo.get("days") or 0
            )

            if days <= 0:
                conn.rollback()
                return False

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
                conn.rollback()
                return False

            current = parse_datetime(
                user.get(
                    "subscription_until"
                )
            )

            current_now = now_utc()

            if current and current > current_now:
                new_until = (
                    current
                    + timedelta(days=days)
                )
            else:
                new_until = (
                    current_now
                    + timedelta(days=days)
                )

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
# USERS LIST / SEARCH
# ============================================================

def get_all_users():
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM users
                ORDER BY user_id DESC
                """
            )

            return cur.fetchall()

    finally:
        conn.close()


def count_users():
    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS count
                FROM users
                """
            )

            row = cur.fetchone()

            return int(
                row["count"]
            )

    finally:
        conn.close()


def search_users(query):
    query = str(query).strip()

    if not query:
        return []

    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM users
                WHERE
                    CAST(user_id AS TEXT) ILIKE %s
                    OR COALESCE(username, '') ILIKE %s
                    OR COALESCE(first_name, '') ILIKE %s
                ORDER BY user_id DESC
                LIMIT 50
                """,
                (
                    f"%{query}%",
                    f"%{query}%",
                    f"%{query}%",
                ),
            )

            return cur.fetchall()

    finally:
        conn.close()


# ============================================================
# NOTIFICATIONS
# ============================================================

def get_notify(user_id):
    user = get_user(user_id)

    if not user:
        return True

    return bool(
        user.get("notify", True)
    )


def set_notify(
    user_id,
    enabled,
):
    conn = get_conn()

    try:
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

    finally:
        conn.close()


# ============================================================
# PENDING DAYS
# ============================================================

def get_pending_days(user_id):
    user = get_user(user_id)

    if not user:
        return 0

    return int(
        user.get("pending_days") or 0
    )


def set_pending_days(
    user_id,
    days,
):
    conn = get_conn()

    try:
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

    finally:
        conn.close()


# ============================================================
# UPDATE USER
# ============================================================

def update_user(
    user_id,
    **fields,
):
    allowed = {
        "username",
        "first_name",
        "subscription",
        "subscription_until",
        "subscription_link",
        "uuid",
        "trial_used",
        "pending_days",
        "notify",
        "accepted_terms",
        "subscription_content",
    }

    fields = {
        key: value
        for key, value in fields.items()
        if key in allowed
    }

    if not fields:
        return False

    if "username" in fields:
        fields["username"] = normalize_username(
            fields["username"]
        )

    if "subscription_until" in fields:
        fields["subscription_until"] = (
            parse_datetime(
                fields["subscription_until"]
            )
        )

    set_parts = []
    values = []

    for key, value in fields.items():
        set_parts.append(
            f"{key} = %s"
        )
        values.append(value)

    values.append(int(user_id))

    conn = get_conn()

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE users
                SET {", ".join(set_parts)}
                WHERE user_id = %s
                """,
                values,
            )

        conn.commit()

        return True

    finally:
        conn.close()


# ============================================================
# STATS
# ============================================================

def get_stats():
    conn = get_conn()

    try:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT COUNT(*) AS total
                FROM users
                """
            )

            total = int(
                cur.fetchone()["total"]
            )

            cur.execute(
                """
                SELECT COUNT(*) AS active
                FROM users
                WHERE subscription = TRUE
                  AND subscription_until > NOW()
                """
            )

            active = int(
                cur.fetchone()["active"]
            )

            cur.execute(
                """
                SELECT COUNT(*) AS expired
                FROM users
                WHERE subscription_until IS NOT NULL
                  AND subscription_until <= NOW()
                """
            )

            expired = int(
                cur.fetchone()["expired"]
            )

            cur.execute(
                """
                SELECT COUNT(*) AS paid
                FROM payments
                WHERE status = 'paid'
                """
            )

            paid = int(
                cur.fetchone()["paid"]
            )

        return {
            "total": total,
            "active": active,
            "expired": expired,
            "paid": paid,
        }

    finally:
        conn.close()


# ============================================================
# DELETE USER
# ============================================================

def delete_user(user_id):
    conn = get_conn()

    try:
        with conn.cursor() as cur:

            cur.execute(
                """
                DELETE FROM promocode_uses
                WHERE user_id = %s
                """,
                (int(user_id),),
            )

            cur.execute(
                """
                DELETE FROM payments
                WHERE user_id = %s
                """,
                (int(user_id),),
            )

            cur.execute(
                """
                DELETE FROM users
                WHERE user_id = %s
                """,
                (int(user_id),),
            )

            deleted = cur.rowcount

        conn.commit()

        return deleted > 0

    finally:
        conn.close()


# ============================================================
# DATABASE INIT
# ============================================================

def init_db():
    """
    Проверяет существующую БД.
    Новую структуру пользователей не удаляет.
    """

    conn = get_conn()

    try:
        with conn.cursor() as cur:

            # =================================================
            # USERS
            # =================================================

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
                ADD COLUMN IF NOT EXISTS subscription BOOLEAN
                DEFAULT FALSE
                """
            )

            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS subscription_until
                TIMESTAMPTZ
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
                ADD COLUMN IF NOT EXISTS trial_used BOOLEAN
                DEFAULT FALSE
                """
            )

            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS pending_days INTEGER
                DEFAULT 0
                """
            )

            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS notify BOOLEAN
                DEFAULT TRUE
                """
            )

            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS accepted_terms BOOLEAN
                DEFAULT FALSE
                """
            )

            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS created_at
                TIMESTAMPTZ DEFAULT NOW()
                """
            )

            cur.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS
                subscription_content TEXT
                """
            )

            # Старые поля оставляем
            # для совместимости.

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

            # =================================================
            # PAYMENTS
            # =================================================

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS payments (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT,
                    amount NUMERIC,
                    days INTEGER,
                    external_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    paid_at TIMESTAMPTZ
                )
                """
            )

            # Если старая таблица payments
            # не имеет paid_at.

            cur.execute(
                """
                ALTER TABLE payments
                ADD COLUMN IF NOT EXISTS paid_at
                TIMESTAMPTZ
                """
            )

            cur.execute(
                """
                ALTER TABLE payments
                ADD COLUMN IF NOT EXISTS external_id TEXT
                """
            )

            # =================================================
            # PROMOCODES
            # =================================================

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

            # =================================================
            # PROMOCODE USES
            # =================================================

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

            # =================================================
            # INDEXES
            # =================================================

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
                    ON promocode_uses (
                        user_id,
                        code
                    )
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