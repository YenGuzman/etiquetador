// api.js — capa delgada sobre fetch() para hablar con el backend.
// Todas las peticiones incluyen credenciales (cookie de sesión).

const Api = (() => {
  async function request(method, url, body, isForm = false, opts2 = {}) {
    const { redirectOn401 = true } = opts2;
    const opts = {
      method,
      credentials: "include",
    };
    if (body !== undefined) {
      if (isForm) {
        opts.body = body; // FormData
      } else {
        opts.headers = { "Content-Type": "application/json" };
        opts.body = JSON.stringify(body);
      }
    }
    const resp = await fetch(url, opts);
    if (resp.status === 401) {
      if (redirectOn401) {
        window.location.href = "/?expirado=1";
      }
      throw new Error("No autenticado");
    }
    let data = null;
    const contentType = resp.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      data = await resp.json();
    }
    if (!resp.ok) {
      const message = (data && (data.detail || data.message)) || `Error ${resp.status}`;
      const err = new Error(typeof message === "string" ? message : JSON.stringify(message));
      err.status = resp.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  return {
    login: (username, password) => request("POST", "/api/auth/login", { username, password }),
    logout: () => request("POST", "/api/auth/logout"),
    me: () => request("GET", "/api/auth/me"),
    // Variante "silenciosa": no redirige a /login si da 401 (para usarla
    // justamente EN la página de login al preguntar "¿ya hay sesión?" —
    // redirigir ahí mismo provocaba un bucle infinito de recargas).
    meSilent: () => request("GET", "/api/auth/me", undefined, false, { redirectOn401: false }),

    listUsers: () => request("GET", "/api/users"),
    createUser: (username, password, is_admin) => request("POST", "/api/users", { username, password, is_admin }),
    deleteUser: (id) => request("DELETE", `/api/users/${id}`),

    listLabels: () => request("GET", "/api/labels"),
    createLabel: (name, color, parent_id) => request("POST", "/api/labels", { name, color, parent_id }),
    createCategory: (name, color) => request("POST", "/api/labels/categories", { name, color }),
    setLabelParent: (id, parent_id) => request("PATCH", `/api/labels/${id}/parent`, { parent_id }),
    renameLabel: (id, new_name) => request("PATCH", `/api/labels/${id}/rename`, { new_name }),
    setLabelColor: (id, color) => request("PATCH", `/api/labels/${id}/color`, { color }),
    deleteLabel: (id) => request("DELETE", `/api/labels/${id}`),

    listImages: () => request("GET", "/api/images"),
    uploadImages: (fileList) => {
      const fd = new FormData();
      for (const f of fileList) fd.append("files", f);
      return request("POST", "/api/images/upload", fd, true);
    },
    imageFileUrl: (id) => `/api/images/${id}/file`,
    getAnnotations: (id) => request("GET", `/api/images/${id}/annotations`),
    saveAnnotations: (id, points, regions) => request("PUT", `/api/images/${id}/annotations`, { points, regions }),
    lockImage: (id) => request("POST", `/api/images/${id}/lock`),
    heartbeatImage: (id) => request("POST", `/api/images/${id}/heartbeat`),
    unlockImage: (id) => request("POST", `/api/images/${id}/unlock`),
    deleteImage: (id) => request("DELETE", `/api/images/${id}`),
    exportDatasetUrl: () => "/api/images/export",

    getDriveSettings: () => request("GET", "/api/drive/settings"),
    setDriveSettings: (folder_link, client_config_json) =>
      request("POST", "/api/drive/settings", { folder_link, client_config_json }),
    testDriveConnection: () => request("POST", "/api/drive/test"),
    startDriveUpload: () => request("POST", "/api/drive/upload"),
    driveUploadStatus: () => request("GET", "/api/drive/upload/status"),
    cancelDriveUpload: () => request("POST", "/api/drive/upload/cancel"),
  };
})();

