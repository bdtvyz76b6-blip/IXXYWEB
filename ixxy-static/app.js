const SUBSCRIPTION_BASE =
  "https://ixxyweb-1.onrender.com/sub/2ix847xy";

function openCabinet() {
  const input = document.getElementById("userInput");
  const error = document.getElementById("error");

  const value = input.value.trim();

  if (!value) {
    error.textContent = "Введите Telegram ID или username";
    return;
  }

  localStorage.setItem("ixxy_user", value);

  window.location.href =
    "cabinet.html?id=" + encodeURIComponent(value);
}


function loadCabinet() {
  const params = new URLSearchParams(location.search);

  const user =
    params.get("id") ||
    localStorage.getItem("ixxy_user");

  if (!user) {
    window.location.href = "index.html";
    return;
  }

  const cleanUser = user.replace("@", "");

  document.getElementById("username").textContent =
    "@" + cleanUser;

  document.getElementById("username2").textContent =
    "@" + cleanUser;

  document.getElementById("telegramId").textContent =
    "Telegram ID: " + cleanUser;

  document.getElementById("telegramId2").textContent =
    cleanUser;

  /*
    ВРЕМЕННЫЕ ДАННЫЕ ДЛЯ ДИЗАЙНА.

    Здесь позже подключим реальные данные
    из твоей базы/API.
  */

  const days = 30;

  document.getElementById("days").textContent =
    days;

  document.getElementById("until").textContent =
    "Действует до —";

  document.getElementById("subscriptionLink").href =
    SUBSCRIPTION_BASE + cleanUser;
}


function buySubscription() {
  alert(
    "Здесь подключим оплату и выбор тарифа."
  );
}


function findUser() {
  const user =
    document.getElementById("adminUser").value.trim();

  if (!user) {
    return;
  }

  document.getElementById("userResult").innerHTML = `
    <div class="card" style="margin-top:15px">
      <h2>Пользователь найден</h2>
      <div class="info-row">
        <span>ID</span>
        <strong>${user}</strong>
      </div>
      <div class="info-row">
        <span>Статус</span>
        <strong>Активна</strong>
      </div>
    </div>
  `;
}