async function ensureAdmin() {
  try {
    const me = await Api.me();
    if (!me.is_admin) {
      alert("Solo un administrador puede configurar Google Drive.");
      window.location.href = "/app.html";
    }
  } catch (e) {
    window.location.href = "/";
  }
}

async function loadSettings() {
  const s = await Api.getDriveSettings();
  document.getElementById("folderLink").value = s.folder_link || "";
  document.getElementById("credStatus").textContent = s.has_credentials ? "cargadas ✔" : "no configuradas";
  document.getElementById("tokenStatus").textContent = s.has_token ? "autorizado ✔" : "pendiente de autorizar";
}

async function saveSettings() {
  const folderLink = document.getElementById("folderLink").value.trim();
  const fileInput = document.getElementById("credentialsFile");
  const statusEl = document.getElementById("saveStatus");
  statusEl.textContent = "";
  statusEl.className = "status-msg";

  let clientConfigJson = null;
  if (fileInput.files && fileInput.files.length > 0) {
    clientConfigJson = await fileInput.files[0].text();
  }

  try {
    await Api.setDriveSettings(folderLink, clientConfigJson);
    statusEl.textContent = "Configuración guardada.";
    statusEl.className = "status-msg ok";
    await loadSettings();
  } catch (e) {
    statusEl.textContent = e.message;
    statusEl.className = "status-msg err";
  }
}

function authorize() {
  window.location.href = "/api/drive/oauth/start";
}

async function testConnection() {
  const statusEl = document.getElementById("testStatus");
  statusEl.textContent = "Probando…";
  statusEl.className = "status-msg";
  try {
    const r = await Api.testDriveConnection();
    statusEl.textContent = `Conexión exitosa. Carpeta: "${r.folder_name}".`;
    statusEl.className = "status-msg ok";
  } catch (e) {
    statusEl.textContent = e.message;
    statusEl.className = "status-msg err";
  }
}

const params = new URLSearchParams(window.location.search);
if (params.get("drive_ok")) {
  window.addEventListener("DOMContentLoaded", () => {
    document.getElementById("tokenStatus").textContent = "autorizado ✔";
  });
}
if (params.get("drive_error")) {
  window.addEventListener("DOMContentLoaded", () => {
    alert("Error al autorizar con Google: " + params.get("drive_error"));
  });
}

document.getElementById("btnSaveSettings").addEventListener("click", saveSettings);
document.getElementById("btnAuthorize").addEventListener("click", authorize);
document.getElementById("btnTestConnection").addEventListener("click", testConnection);

ensureAdmin().then(loadSettings);
