const API_BASE =
window.IXXY_API_URL ||
“https://ixxyweb-1.onrender.com”;

const TOKEN_KEY = “ixxy_token”;
const USER_KEY = “ixxy_user”;

function getToken() {
return localStorage.getItem(TOKEN_KEY);
}

function setToken(token) {
localStorage.setItem(TOKEN_KEY, token);
}

function authHeaders() {
const token = getToken();

return {
“Content-Type”: “application/json”,
…(token
? { Authorization: “Bearer “ + token }
: {})
};
}

async function apiRequest(url, options = {}) {
const response = await fetch(API_BASE + url, {
…options,
headers: {
…authHeaders(),
…(options.headers || {})
}
});

let data = {};

try {
data = await response.json();
} catch {
data = {};
}

if (!response.ok) {
throw new Error(
data.error ||
data.message ||
“Ошибка сервера”
);
}

return data;
}

/* =========================
ВХОД
========================= */

async function openCabinet() {
const input = document.getElementById(“userInput”);
const error = document.getElementById(“error”);

const value = input.value.trim();

error.textContent = “”;

if (!value) {
error.textContent =
“Введите Telegram ID или username”;
return;
}

try {
const data = await apiRequest(
“/api/auth/login”,
{
method: “POST”,
body: JSON.stringify({
login: value.replace(/^@/, “”)
})
}
);

if (!data.token) {
  throw new Error(
    "Сервер не вернул токен авторизации"
  );
}
setToken(data.token);
localStorage.setItem(
  USER_KEY,
  value.replace(/^@/, "")
);
window.location.href = "cabinet.html";

} catch (errorObject) {
error.textContent =
errorObject.message ||
“Пользователь не найден”;
}
}

/* =========================
КАБИНЕТ
========================= */

async function loadCabinet() {
const token = getToken();

if (!token) {
window.location.href = “index.html”;
return;
}

try {
const [me, subscription] =
await Promise.all([
apiRequest(”/api/me”),
apiRequest(”/api/subscription”)
]);

const user =
  me.user ||
  me;
const sub =
  subscription.subscription ||
  subscription;
const userId =
  user.user_id ??
  user.id ??
  "";
const username =
  user.username ||
  "";
const firstName =
  user.first_name ||
  "";
const daysLeft = Number(
  sub.days_left ??
  subscription.days_left ??
  0
);
const active =
  sub.active ??
  subscription.active ??
  false;
const until =
  sub.subscription_until ??
  sub.until ??
  subscription.subscription_until ??
  null;
const subscriptionLink =
  sub.subscription_link ??
  subscription.subscription_link ??
  "";
const displayName =
  username
    ? "@" + username.replace(/^@/, "")
    : firstName ||
      String(userId);
const usernameElement =
  document.getElementById("username");
const username2Element =
  document.getElementById("username2");
const telegramIdElement =
  document.getElementById("telegramId");
const telegramId2Element =
  document.getElementById("telegramId2");
const daysElement =
  document.getElementById("days");
const untilElement =
  document.getElementById("until");
const linkElement =
  document.getElementById(
    "subscriptionLink"
  );
if (usernameElement) {
  usernameElement.textContent =
    displayName;
}
if (username2Element) {
  username2Element.textContent =
    displayName;
}
if (telegramIdElement) {
  telegramIdElement.textContent =
    "Telegram ID: " + userId;
}
if (telegramId2Element) {
  telegramId2Element.textContent =
    userId;
}
if (daysElement) {
  daysElement.textContent =
    daysLeft;
}
if (untilElement) {
  untilElement.textContent =
    active && until
      ? "Действует до — " +
        formatDate(until)
      : "Подписка неактивна";
}
if (linkElement) {
  if (subscriptionLink) {
    linkElement.href =
      subscriptionLink;
    linkElement.style.display = "";
  } else {
    linkElement.removeAttribute("href");
  }
}
updateSubscriptionStatus(active);
await loadTariffs();

} catch (errorObject) {
console.error(errorObject);

if (
  errorObject.message
    .toLowerCase()
    .includes("token")
) {
  localStorage.removeItem(TOKEN_KEY);
  window.location.href = "index.html";
  return;
}
const errorElement =
  document.getElementById("error");
if (errorElement) {
  errorElement.textContent =
    errorObject.message ||
    "Не удалось загрузить данные";
}

}
}

/* =========================
СТАТУС
========================= */

function updateSubscriptionStatus(active) {
const elements = [
document.getElementById(“status”),
document.getElementById(“subscriptionStatus”)
].filter(Boolean);

elements.forEach((element) => {
element.textContent =
active
? “Активна”
: “Неактивна”;
});
}

/* =========================
ДАТА
========================= */

function formatDate(value) {
if (!value) {
return “—”;
}

const date = new Date(value);

if (Number.isNaN(date.getTime())) {
return String(value);
}

return date.toLocaleDateString(
“ru-RU”,
{
day: “2-digit”,
month: “2-digit”,
year: “numeric”
}
);
}

/* =========================
ТАРИФЫ
========================= */

async function loadTariffs() {
try {
const data =
await apiRequest(”/api/tariffs”);

const tariffs =
  data.tariffs ||
  data ||
  [];
const container =
  document.getElementById("tariffs");
if (!container) {
  return;
}
container.innerHTML = "";
if (!Array.isArray(tariffs)) {
  return;
}
tariffs.forEach((tariff) => {
  const days =
    Number(
      tariff.days ??
      tariff.duration ??
      0
    );
  const amount =
    Number(
      tariff.amount ??
      tariff.price ??
      0
    );
  if (!days || !amount) {
    return;
  }
  const button =
    document.createElement("button");
  button.className =
    "tariff-button";
  button.textContent =
    `${days} дней — ${amount} ₽`;
  button.onclick = () =>
    buySubscription(days);
  container.appendChild(button);
});

} catch (errorObject) {
console.error(
“Не удалось загрузить тарифы:”,
errorObject
);
}
}

/* =========================
ОПЛАТА
========================= */

async function buySubscription(days) {
if (!days) {
const tariffs = [
30,
90,
180,
365
];

const value =
  prompt(
    "Введите срок подписки в днях:\n\n30 / 90 / 180 / 365"
  );
days = Number(value);
if (!tariffs.includes(days)) {
  alert("Выберите доступный тариф.");
  return;
}

}

try {
const data =
await apiRequest(
“/api/payment/create”,
{
method: “POST”,
body: JSON.stringify({
days
})
}
);

const paymentUrl =
  data.payment_url ||
  data.url;
if (!paymentUrl) {
  throw new Error(
    "Ссылка на оплату не получена"
  );
}
window.location.href =
  paymentUrl;

} catch (errorObject) {
alert(
errorObject.message ||
“Не удалось создать оплату”
);
}
}

/* =========================
ОБНОВЛЕНИЕ КАБИНЕТА
========================= */

async function refreshCabinet() {
await loadCabinet();
}

/* =========================
ВЫХОД
========================= */

function logout() {
localStorage.removeItem(TOKEN_KEY);
localStorage.removeItem(USER_KEY);

window.location.href =
“index.html”;
}

/* =========================
АДМИН
========================= */

async function findUser() {
const input =
document.getElementById(
“adminUser”
);

const result =
document.getElementById(
“userResult”
);

const value =
input?.value.trim();

if (!value || !result) {
return;
}

result.innerHTML =
<div class="card" style="margin-top:15px"> Загрузка... </div>;

try {
/*
Сейчас обычный API не позволяет
публично получать данные любого
пользователя.

  Поэтому здесь НЕ показываем
  выдуманные данные.
  Для полноценной админки нужен
  защищённый /api/admin/* endpoint
  на сервере.
*/
throw new Error(
  "Админский API ещё не подключён"
);

} catch (errorObject) {
result.innerHTML =
<div class="card" style="margin-top:15px"> <h2>Ошибка</h2> <div class="info-row"> <span>Статус</span> <strong>${escapeHtml( errorObject.message )}</strong> </div> </div>;
}
}

/* =========================
БЕЗОПАСНЫЙ HTML
========================= */

function escapeHtml(value) {
return String(value)
.replace(/&/g, “&”)
.replace(/</g, “<”)
.replace(/>/g, “>”)
.replace(/”/g, “"”)
.replace(/’/g, “'”);
}

/* =========================
АВТОЗАПУСК
========================= */

document.addEventListener(
“DOMContentLoaded”,
() => {
if (
location.pathname.endsWith(
“cabinet.html”
)
) {
loadCabinet();
}

if (
  location.pathname.endsWith(
    "index.html"
  ) ||
  location.pathname === "/"
) {
  const token = getToken();
  if (token) {
    // Токен уже есть — пользователь
    // может сразу открыть кабинет.
  }
}

}
);