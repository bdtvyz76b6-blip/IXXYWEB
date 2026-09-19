const API_URL = "https://ТВОЙ-API-ДОМЕН";

const SUPPORT_URL =
    "https://t.me/orelvpntopbot";


function getToken() {
    return localStorage.getItem(
        "ixxy_token"
    );
}


function logout() {
    localStorage.removeItem(
        "ixxy_token"
    );

    window.location.href =
        "index.html";
}


async function api(path, options = {}) {

    const token = getToken();

    if (!token) {
        window.location.href =
            "index.html";

        throw new Error(
            "Не авторизован"
        );
    }

    const headers = {
        "Content-Type": "application/json",
        ...(options.headers || {})
    };

    headers.Authorization =
        `Bearer ${token}`;

    const response = await fetch(
        API_URL + path,
        {
            ...options,
            headers
        }
    );

    let data;

    try {
        data = await response.json();
    } catch {
        data = {
            ok: false,
            error: "Ошибка сервера"
        };
    }

    if (
        response.status === 401 ||
        response.status === 403
    ) {
        localStorage.removeItem(
            "ixxy_token"
        );

        window.location.href =
            "index.html";

        throw new Error(
            "Сессия закончилась"
        );
    }

    if (!response.ok) {
        throw new Error(
            data.error ||
            "Ошибка запроса"
        );
    }

    return data;
}


function formatDate(value) {

    if (!value) {
        return "—";
    }

    const date =
        new Date(value);

    if (Number.isNaN(
        date.getTime()
    )) {
        return value;
    }

    return date.toLocaleDateString(
        "ru-RU",
        {
            day: "2-digit",
            month: "2-digit",
            year: "numeric"
        }
    );
}


async function loadCabinet() {

    try {

        const result =
            await api("/api/me");

        const user =
            result.user;


        const name =
            user.first_name ||
            user.username ||
            `ID ${user.user_id}`;


        document.getElementById(
            "hello"
        ).textContent =
            `Добро пожаловать, ${name}`;


        document.getElementById(
            "subscriptionUrl"
        ).value =
            user.subscription_link;


        document.getElementById(
            "happButton"
        ).href =
            user.happ_url;


        document.getElementById(
            "incyButton"
        ).href =
            user.incy_url;


        document.getElementById(
            "supportLink"
        ).href =
            SUPPORT_URL;


        document.getElementById(
            "days"
        ).textContent =
            user.active
                ? `${user.days_left} дн.`
                : "0 дн.";


        document.getElementById(
            "until"
        ).textContent =
            user.active
                ? formatDate(
                    user.subscription_until
                )
                : "Не активна";


        const status =
            document.getElementById(
                "status"
            );

        const block =
            document.getElementById(
                "statusBlock"
            );


        if (user.active) {

            status.textContent =
                "🟢 Активна";

            block.textContent =
                `🟢 Подписка активна • осталось ${user.days_left} дн.`;

            block.className =
                "status active";

        } else {

            status.textContent =
                "🔴 Не активна";

            block.textContent =
                "🔴 Подписка не активна";

            block.className =
                "status inactive";
        }

    } catch (error) {

        console.error(error);

        document.getElementById(
            "hello"
        ).textContent =
            "Не удалось загрузить кабинет";
    }
}


async function copySubscription() {

    const input =
        document.getElementById(
            "subscriptionUrl"
        );

    try {

        await navigator.clipboard.writeText(
            input.value
        );

        const button =
            document.querySelector(
                ".subscription-box .main-button"
            );

        const oldText =
            button.textContent;

        button.textContent =
            "✓ Скопировано";

        setTimeout(() => {
            button.textContent =
                oldText;
        }, 1500);

    } catch {

        input.select();

        document.execCommand(
            "copy"
        );
    }
}


async function buy(days) {

    const message =
        document.getElementById(
            "buyMessage"
        );

    message.textContent =
        "Создаём оплату...";

    message.className =
        "buy-loading";


    try {

        const result =
            await api(
                `/api/buy/${days}`,
                {
                    method: "POST"
                }
            );


        if (!result.payment_url) {
            throw new Error(
                "Ссылка на оплату не получена"
            );
        }


        window.location.href =
            result.payment_url;

    } catch (error) {

        message.textContent =
            error.message;

        message.className =
            "buy-error";
    }
}


loadCabinet();