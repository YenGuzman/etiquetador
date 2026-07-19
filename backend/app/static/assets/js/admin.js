let meUser = null;

async function ensureAdmin() {
  try {
    meUser = await Api.me();
    if (!meUser.is_admin) {
      alert("Solo un administrador puede acceder a esta página.");
      window.location.href = "/app.html";
    }
  } catch (e) {
    window.location.href = "/";
  }
}

async function loadUsers() {
  const users = await Api.listUsers();
  const box = document.getElementById("usersList");
  box.innerHTML = "";
  for (const u of users) {
    const row = document.createElement("div");
    row.className = "user-row";
    row.innerHTML = `
      <span class="name">${escapeHtml(u.username)} ${u.is_admin ? "(admin)" : ""}</span>
      <button data-id="${u.id}" class="danger">Eliminar</button>
    `;
    row.querySelector("button").addEventListener("click", async () => {
      if (!confirm(`¿Eliminar al usuario "${u.username}"?`)) return;
      try {
        await Api.deleteUser(u.id);
        await loadUsers();
      } catch (e) {
        alert(e.message);
      }
    });
    box.appendChild(row);
  }
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

async function createUser() {
  const username = document.getElementById("newUsername").value.trim();
  const password = document.getElementById("newPassword").value;
  const isAdmin = document.getElementById("newIsAdmin").checked;
  const statusEl = document.getElementById("createStatus");
  statusEl.textContent = "";
  try {
    await Api.createUser(username, password, isAdmin);
    statusEl.textContent = "Usuario creado.";
    statusEl.className = "status-msg ok";
    document.getElementById("newUsername").value = "";
    document.getElementById("newPassword").value = "";
    document.getElementById("newIsAdmin").checked = false;
    await loadUsers();
  } catch (e) {
    statusEl.textContent = e.message;
    statusEl.className = "status-msg err";
  }
}

document.getElementById("btnCreateUser").addEventListener("click", createUser);

ensureAdmin().then(loadUsers);
