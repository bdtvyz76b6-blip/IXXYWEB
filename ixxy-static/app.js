/*
 * ВАЖНО:
 * После размещения API на VPS
 * поменяй только API_URL.
 */

const API_URL = "https://ТВОЙ-API-ДОМЕН";

const SUPPORT_URL = "https://t.me/orelvpntopbot";


document.getElementById(
    "supportLink"
).href = SUPPORT_URL;


function showMessage(text, error = true) {
    const box = document.getElementById("message");

    box.textContent = text;

    box.style.color = error
        ? "#ff8eaa"
        : "#8ff0b0";
}


function showLogin() {
    document.getElementById(
        "loginForm"
    ).classList.remove("hidden");

    document.getElementById(
        "registerForm"
    ).classList.add("hidden");

    document.getElementById(
        "loginTab"
    ).classList.add("active");

    document.getElementById(
        "registerTab"
    ).classList.remove("active");

    showMessage("");
}


function showRegister() {
    document.getElementById(
        "loginForm"
    ).classList.add("hidden");

    document.getElementById(
        "registerForm"
    ).classList.remove("hidden");

    document.getElementById(
        "loginTab"
    ).classList.remove("active");

    document.getElementById(
        "registerTab"
    ).classList.add("active");

    showMessage("");
}


async function api(path, options = {}) {

    const token =
        localStorage.getItem("ixxy_token");

    const headers = {
        "Content-Type": "application/json",
        ...(options.headers || {})
    };

    if (token) {
        headers.Authorization =
            `Bearer ${token}`;
    }

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

    if (!response.ok) {
        throw new Error(
            data.error ||
            "Ошибка запроса"
        );
    }

    return data;
}


async function login() {

    const loginValue =
        document.getElementById(
            "login"
        ).value.trim();

    if (!loginValue) {
        showMessage(
            "Введите Telegram ID или username"
        );
        return;
    }

    try {

        showMessage(
            "Выполняется вход...",
            false
        );

        const result =
            await api(
                "/api/auth/login",
                {
                    method: "POST",

                    body: JSON.stringify({
                        login: loginValue
                    })
                }
            );

        localStorage.setItem(
            "ixxy_token",
            result.token
        );

        window.location.href =
            "cabinet.html";

    } catch (error) {

        showMessage(
            error.message
        );
    }
}


async function register() {

    const telegramId =
        document.getElementById(
            "telegramId"
        ).value.trim();

    const username =
        document.getElementById(
            "username"
        ).value.trim();

    const firstName =
        document.getElementById(
            "firstName"
        ).value.trim();

    if (!telegramId) {
        showMessage(
            "Введите Telegram ID"
        );
        return;
    }

    try {

        showMessage(
            "Создание аккаунта...",
            false
        );

        const result =
            await api(
                "/api/auth/register",
                {
                    method: "POST",

                    body: JSON.stringify({
                        telegram_id:
                            telegramId,

                        username:
                            username,

                        first_name:
                            firstName
                    })
                }
            );

        localStorage.setItem(
            "ixxy_token",
            result.token
        );

        window.location.href =
            "cabinet.html";

    } catch (error) {

        showMessage(
            error.message
        );
    }
}