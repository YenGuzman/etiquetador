const params = new URLSearchParams(window.location.search);
if (params.get("expirado")) {
  document.getElementById("errorText").textContent = "Tu sesión expiró. Inicia sesión de nuevo.";
}

// Si ya hay sesión activa, saltar directo a la app. Usamos meSilent (no
// redirige por sí sola en 401) para evitar un bucle infinito de recargas
// cuando NO hay sesión — antes, un 401 aquí redirigía de vuelta a esta misma
// página de login, que volvía a preguntar, y volvía a redirigir...
Api.meSilent().then(() => { window.location.href = "/app.html"; }).catch(() => {});

async function doLogin() {
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value;
  const errorText = document.getElementById("errorText");
  errorText.textContent = "";
  if (!username || !password) {
    errorText.textContent = "Ingresa usuario y contraseña.";
    return;
  }
  try {
    await Api.login(username, password);
    window.location.href = "/app.html";
  } catch (e) {
    errorText.textContent = "Usuario o contraseña incorrectos.";
  }
}

document.getElementById("loginBtn").addEventListener("click", doLogin);
document.getElementById("password").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doLogin();
});
