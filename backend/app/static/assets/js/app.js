// app.js — lógica principal de la aplicación de etiquetado.

const CLOSE_SHAPE_THRESHOLD_PX = 10;
const ZOOM_STEP = 1.2;
const MIN_ZOOM = 0.05;
const MAX_ZOOM = 8;
const HEARTBEAT_INTERVAL_MS = 20000;
const LOCK_POLL_INTERVAL_MS = 2000;
const POINT_RADIUS = 5;
const VERTEX_RADIUS = 4;

const state = {
  me: null,
  labels: [],           // {id, name, color}
  images: [],           // resumen de /api/images
  currentIndex: -1,
  currentImageId: null,
  currentAnn: { points: [], regions: [] },
  imgEl: null,           // HTMLImageElement cargado
  scale: 1,
  mode: "point",
  currentLabel: "",
  currentLabelId: null,
  currentCategoryId: null,
  selectedAnnotationId: null,
  selectedLabelId: null,
  readOnly: false,
  heartbeatTimer: null,
  lockPollTimer: null,
  lockPollInFlight: false,
  undoStacks: {},        // imageId -> [{points, regions}, ...]
  polygonPoints: [],
  freehandActive: false,
  freehandPoints: [],
  freehandAwayFromStart: false,
};

const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const canvasArea = document.getElementById("canvasArea");
const canvasPlaceholder = document.getElementById("canvasPlaceholder");

// ---------------------------------------------------------------------
// Inicialización
// ---------------------------------------------------------------------

async function init() {
  try {
    state.me = await Api.me();
  } catch (e) {
    window.location.href = "/";
    return;
  }
  document.getElementById("userDropdownBtn").textContent = state.me.username;
  if (state.me.is_admin) {
    document.getElementById("adminLink").style.display = "block";
    document.getElementById("btnSave").style.display = "inline-block";
    document.getElementById("btnExport").style.display = "inline-block";
  } else {
    document.getElementById("menuConfigDrive").style.display = "none";
    document.getElementById("labelsDropdown").style.display = "none";
    document.getElementById("btnSave").style.display = "none";
    document.getElementById("btnExport").style.display = "none";
  }

  bindUI();
  await refreshLabels();
  await refreshImageList();
  startLockPolling();

  if (state.images.length > 0) {
    await loadImageAt(0);
  } else {
    setStatus('No hay imágenes todavía. Súbelas con el botón "🖼 Subir imagen".');
  }
}

window.addEventListener("beforeunload", () => {
  stopLockPolling();
  if (state.currentImageId && !state.readOnly) {
    navigator.sendBeacon(`/api/images/${state.currentImageId}/unlock`);
  }
});

// ---------------------------------------------------------------------
// Menús desplegables
// ---------------------------------------------------------------------

function setupDropdown(containerId, buttonId) {
  const container = document.getElementById(containerId);
  const button = document.getElementById(buttonId);
  button.addEventListener("click", (e) => {
    e.stopPropagation();
    const wasOpen = container.classList.contains("open");
    document.querySelectorAll(".dropdown.open").forEach((d) => d.classList.remove("open"));
    if (!wasOpen) container.classList.add("open");
  });
}

document.addEventListener("click", () => {
  document.querySelectorAll(".dropdown.open").forEach((d) => d.classList.remove("open"));
});

// ---------------------------------------------------------------------
// UI binding
// ---------------------------------------------------------------------

function bindUI() {
  setupDropdown("labelsDropdown", "labelsDropdownBtn");
  setupDropdown("driveDropdown", "driveDropdownBtn");
  setupDropdown("userDropdown", "userDropdownBtn");

  document.getElementById("btnUploadImages").addEventListener("click", () => {
    document.getElementById("fileInput").click();
  });
  document.getElementById("fileInput").addEventListener("change", onUploadFiles);

  document.getElementById("btnSave").addEventListener("click", saveCurrentAnnotations);
  document.getElementById("btnExport").addEventListener("click", exportDataset);

  document.getElementById("menuManageLabels").addEventListener("click", openLabelsModal);
  document.getElementById("btnCloseLabelsModal").addEventListener("click", closeLabelsModal);
  document.getElementById("btnAddLabel").addEventListener("click", addLabelFlow);
  document.getElementById("btnAddCategory").addEventListener("click", addCategoryFlow);

  document.getElementById("menuUploadDrive").addEventListener("click", uploadToDrive);
  document.getElementById("menuConfigDrive").addEventListener("click", () => {
    window.location.href = "/drive-settings.html";
  });

  document.getElementById("adminLink").addEventListener("click", () => {
    window.location.href = "/admin.html";
  });

  document.getElementById("logoutBtn").addEventListener("click", async () => {
    if (state.currentImageId && !state.readOnly) {
      try { await saveCurrentAnnotations(); } catch (e) {}
      try { await Api.unlockImage(state.currentImageId); } catch (e) {}
    }
    await Api.logout();
    window.location.href = "/";
  });

  document.getElementById("modeGroup").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-mode]");
    if (!btn) return;
    setMode(btn.dataset.mode);
  });


  document.getElementById("btnUndo").addEventListener("click", undo);
  document.getElementById("btnZoomOut").addEventListener("click", () => zoomBy(1 / ZOOM_STEP));
  document.getElementById("btnZoomIn").addEventListener("click", () => zoomBy(ZOOM_STEP));
  document.getElementById("btnFit").addEventListener("click", fitToWindow);
  document.getElementById("btnPrev").addEventListener("click", goPrevious);
  document.getElementById("btnNext").addEventListener("click", goNext);


  document.getElementById("btnCancelDriveUpload").addEventListener("click", async () => {
    await Api.cancelDriveUpload();
  });

  canvas.addEventListener("mousedown", onCanvasMouseDown);
  canvas.addEventListener("mousemove", onCanvasMouseMove);
  canvas.addEventListener("mouseup", onCanvasMouseUp);
  canvas.addEventListener("dblclick", onCanvasDoubleClick);
  canvas.addEventListener("wheel", onCanvasWheel, { passive: false });

  document.addEventListener("keydown", onKeyDown);
}

function onKeyDown(e) {
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "select" || tag === "textarea") return;

  const ctrlOrCmd = e.ctrlKey || e.metaKey;

  if (ctrlOrCmd && (e.key === "z" || e.key === "Z")) { e.preventDefault(); undo(); return; }
  if (ctrlOrCmd && (e.key === "s" || e.key === "S")) { e.preventDefault(); saveCurrentAnnotations(); return; }
  if (ctrlOrCmd) return; // cualquier otra combinación con Ctrl/Cmd no la interceptamos

  if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); goNext(); }
  else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); goPrevious(); }
  else if (e.key === "p" || e.key === "P") setMode("point");
  else if (e.key === "g" || e.key === "G") setMode("polygon");
  else if (e.key === "l" || e.key === "L") setMode("freehand");
  else if (e.key === "s" || e.key === "S") setMode("select");
  else if (e.key === "Escape") cancelTempDrawing();
  else if (e.key === "Enter") finishPolygon();
  else if (e.key === "Backspace" || e.key === "Delete") {
    const labelsModalOpen = document.getElementById("labelsModal").classList.contains("open");
    if (labelsModalOpen) {
      if (state.selectedLabelId) {
        e.preventDefault();
        const l = state.labels.find((x) => x.id === state.selectedLabelId);
        if (l) deleteLabelFlow(l);
      }
    } else if (state.selectedAnnotationId) {
      // Si hay una anotación seleccionada, Delete/Backspace elimina la
      // anotación antes que la imagen completa.
      e.preventDefault();
      deleteAnnotationById(state.selectedAnnotationId);
    } else if (state.currentIndex >= 0) {
      e.preventDefault();
      deleteImageAt(state.currentIndex);
    }
  }
}

function setMode(mode) {
  state.mode = mode;
  cancelTempDrawing();
  document.querySelectorAll("#modeGroup button").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === mode);
  });
  canvas.style.cursor = mode === "select" ? "pointer" : "crosshair";
}

// ---------------------------------------------------------------------
// Etiquetas
// ---------------------------------------------------------------------

async function refreshLabels() {
  state.labels = await Api.listLabels();

  const categorySelect = document.getElementById("categorySelect");
  const labelSelect = document.getElementById("labelSelect");
  const prevLabelId = state.currentLabelId;
  const prevCategoryId = state.currentCategoryId;

  const categories = state.labels.filter((l) => l.is_category);
  const subtagsOf = (catId) =>
    state.labels.filter((l) => !l.is_category && l.parent_id === catId);
  const uncategorized = state.labels.filter((l) => !l.is_category && !l.parent_id);

  // Primer nivel: maintags.
  categorySelect.innerHTML = "";
  const noCategoryOpt = document.createElement("option");
  noCategoryOpt.value = "";
  noCategoryOpt.textContent = "Sin categoría";
  categorySelect.appendChild(noCategoryOpt);

  for (const cat of categories) {
    const opt = document.createElement("option");
    opt.value = String(cat.id);
    opt.textContent = cat.name;
    categorySelect.appendChild(opt);
  }

  // Conserva la categoría anterior si todavía existe.
  if (prevCategoryId && categories.some((c) => c.id === prevCategoryId)) {
    categorySelect.value = String(prevCategoryId);
  } else if (prevLabelId) {
    const previousLabel = state.labels.find((l) => l.id === prevLabelId && !l.is_category);
    categorySelect.value = previousLabel?.parent_id ? String(previousLabel.parent_id) : "";
  }

  function populateSubtags(categoryId, preferredLabelId = null) {
    labelSelect.innerHTML = "";

    const subtags = categoryId
      ? subtagsOf(Number(categoryId))
      : uncategorized;

    for (const l of subtags) {
      const opt = document.createElement("option");
      // Usamos el ID para permitir subtags con el mismo nombre en categorías distintas.
      opt.value = String(l.id);
      opt.textContent = l.name;
      labelSelect.appendChild(opt);
    }

    labelSelect.disabled = subtags.length === 0;

    const selected = subtags.find((l) => l.id === preferredLabelId) || subtags[0];
    if (selected) {
      labelSelect.value = String(selected.id);
      state.currentLabelId = selected.id;
      state.currentLabel = selected.name;
      state.currentCategoryId = selected.parent_id || null;
    } else {
      state.currentLabelId = null;
      state.currentLabel = "";
      state.currentCategoryId = categoryId ? Number(categoryId) : null;
    }
  }

  populateSubtags(categorySelect.value, prevLabelId);

  categorySelect.onchange = () => {
    state.currentCategoryId = categorySelect.value ? Number(categorySelect.value) : null;
    populateSubtags(categorySelect.value);
  };

  labelSelect.onchange = () => {
    const selected = state.labels.find(
      (l) => !l.is_category && l.id === Number(labelSelect.value)
    );
    if (!selected) return;
    state.currentLabelId = selected.id;
    state.currentLabel = selected.name;
    state.currentCategoryId = selected.parent_id || null;
  };
}

function getLabelDefinition(name, id = null, categoryId = null) {
  return state.labels.find((l) =>
    !l.is_category &&
    ((id != null && l.id === id) ||
     (id == null && l.name === name && (categoryId == null || l.parent_id === categoryId)))
  );
}

function labelColor(name, id = null, categoryId = null) {
  const l = getLabelDefinition(name, id, categoryId);
  return l ? l.color : "#ff0000";
}

function labelDisplayText(item) {
  const label = item.label || "";
  const category = item.category || item.category_name;
  return category ? `${category}\n${label}` : label;
}

function openLabelsModal() {
  renderLabelsModal();
  document.getElementById("labelsModal").classList.add("open");
}
function closeLabelsModal() {
  state.selectedLabelId = null;
  document.getElementById("labelsModal").classList.remove("open");
}

async function deleteLabelFlow(l) {
  const warning = l.is_category
    ? `¿Eliminar la categoría "${l.name}"? Sus subtags NO se borran, quedarán "sin categoría".`
    : `¿Eliminar la etiqueta "${l.name}"? Las anotaciones que ya la usan no se borran, pero quedarán con un nombre que ya no existe en la lista.`;
  if (!confirm(warning)) return;
  try {
    await Api.deleteLabel(l.id);
    if (state.selectedLabelId === l.id) state.selectedLabelId = null;
    await refreshLabels();
    renderLabelsModal();
  } catch (e) {
    alert(e.message);
  }
}

function buildCategoryOptionsHtml(selectedId) {
  const categories = state.labels.filter((l) => l.is_category);
  let html = `<option value="">— sin categoría —</option>`;
  for (const c of categories) {
    const sel = c.id === selectedId ? "selected" : "";
    html += `<option value="${c.id}" ${sel}>${escapeHtml(c.name)}</option>`;
  }
  return html;
}

function makeLabelRow(l, { indent = false } = {}) {
  const row = document.createElement("div");
  row.className = "label-row" + (indent ? " indent" : "") + (l.id === state.selectedLabelId ? " selected" : "");
  if (indent) row.style.marginLeft = "20px";
  row.innerHTML = `
    <span class="color-dot" style="background:${l.color}"></span>
    <span class="name">${escapeHtml(l.name)}</span>
    ${!l.is_category ? `<select data-action="parent" style="font-size:12px;">${buildCategoryOptionsHtml(l.parent_id)}</select>` : ""}
    <span class="actions">
      <button data-action="rename">Renombrar</button>
      <button data-action="color">Color</button>
      <button data-action="delete" title="Eliminar" style="padding:1px 6px; font-size:12px;">🗑</button>
    </span>
  `;

  // Clic en la fila (fuera de los botones/select) la selecciona, para poder
  // borrarla luego con Backspace igual que con las imágenes.
  row.addEventListener("click", (e) => {
    if (e.target.closest("button, select")) return;
    state.selectedLabelId = state.selectedLabelId === l.id ? null : l.id;
    renderLabelsModal();
  });

  row.querySelector('[data-action="rename"]').addEventListener("click", async () => {
    const newName = prompt("Nuevo nombre:", l.name);
    if (!newName) return;
    try {
      await Api.renameLabel(l.id, newName);
      await refreshLabels();
      renderLabelsModal();
      redraw();
      renderAnnotationList();
    } catch (e) { alert(e.message); }
  });
  row.querySelector('[data-action="color"]').addEventListener("click", async () => {
    const input = document.createElement("input");
    input.type = "color";
    input.value = l.color;
    input.addEventListener("change", async () => {
      try {
        await Api.setLabelColor(l.id, input.value);
        await refreshLabels();
        renderLabelsModal();
        redraw();
      } catch (e) { alert(e.message); }
    });
    input.click();
  });
  row.querySelector('[data-action="delete"]').addEventListener("click", () => deleteLabelFlow(l));
  const parentSelect = row.querySelector('[data-action="parent"]');
  if (parentSelect) {
    parentSelect.addEventListener("change", async () => {
      const val = parentSelect.value ? parseInt(parentSelect.value, 10) : null;
      try {
        await Api.setLabelParent(l.id, val);
        await refreshLabels();
        renderLabelsModal();
      } catch (e) {
        alert(e.message);
        renderLabelsModal();
      }
    });
  }
  return row;
}

function renderLabelsModal() {
  const container = document.getElementById("labelsListContainer");
  container.innerHTML = "";

  const categories = state.labels.filter((l) => l.is_category);
  const subtagsOf = (catId) => state.labels.filter((l) => !l.is_category && l.parent_id === catId);
  const uncategorized = state.labels.filter((l) => !l.is_category && !l.parent_id);

  for (const cat of categories) {
    const catBlock = document.createElement("div");
    catBlock.style.marginBottom = "10px";
    catBlock.appendChild(makeLabelRow(cat));
    const addBtn = document.createElement("button");
    addBtn.textContent = `+ Agregar subtag en "${cat.name}"`;
    addBtn.style.marginLeft = "20px";
    addBtn.style.fontSize = "12px";
    addBtn.addEventListener("click", async () => {
      const name = prompt(`Nombre del nuevo subtag dentro de "${cat.name}":`);
      if (!name) return;
      try {
        await Api.createLabel(name, undefined, cat.id);
        await refreshLabels();
        renderLabelsModal();
      } catch (e) { alert(e.message); }
    });
    catBlock.appendChild(addBtn);
    for (const sub of subtagsOf(cat.id)) {
      catBlock.appendChild(makeLabelRow(sub, { indent: true }));
    }
    container.appendChild(catBlock);
  }

  if (uncategorized.length > 0) {
    const header = document.createElement("h3");
    header.textContent = "Sin categoría";
    container.appendChild(header);
    for (const l of uncategorized) {
      container.appendChild(makeLabelRow(l));
    }
  }
}

async function addCategoryFlow() {
  const name = prompt("Nombre de la nueva categoría general (ej. Benigno, Maligno, Sospechoso):");
  if (!name) return;
  try {
    await Api.createCategory(name);
    await refreshLabels();
    renderLabelsModal();
  } catch (e) {
    alert(e.message);
  }
}

async function addLabelFlow() {
  const name = prompt("Nombre de la nueva etiqueta (subtag) — puedes asignarle una categoría después con el desplegable de cada fila:");
  if (!name) return;
  try {
    await Api.createLabel(name);
    await refreshLabels();
    renderLabelsModal();
  } catch (e) {
    alert(e.message);
  }
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

// ---------------------------------------------------------------------
// Lista e imágenes
// ---------------------------------------------------------------------

async function refreshImageList() {
  state.images = await Api.listImages();
  renderImageList();
}

function startLockPolling() {
  stopLockPolling();
  pollImageLocks();
  state.lockPollTimer = setInterval(pollImageLocks, LOCK_POLL_INTERVAL_MS);
}

function stopLockPolling() {
  if (state.lockPollTimer) {
    clearInterval(state.lockPollTimer);
    state.lockPollTimer = null;
  }
}

async function pollImageLocks() {
  if (state.lockPollInFlight || !state.me) return;
  state.lockPollInFlight = true;
  try {
    const locks = await Api.listImageLocks();
    let listChanged = false;

    state.images.forEach((img) => {
      const lock = locks[String(img.id)];
      const newLockedBy = lock ? lock.locked_by : null;
      const newAge = lock ? lock.locked_seconds_ago : null;
      if (img.locked_by !== newLockedBy || img.locked_seconds_ago !== newAge) {
        img.locked_by = newLockedBy;
        img.locked_seconds_ago = newAge;
        listChanged = true;
      }
    });

    // Si la imagen abierta pasa a estar bloqueada por otra persona,
    // cambia inmediatamente a solo lectura para evitar editar contra un bloqueo ajeno.
    const current = state.currentImageId
      ? state.images.find((img) => img.id === state.currentImageId)
      : null;

    if (current) {
      const lockedByOther = current.locked_by && current.locked_by !== state.me.username;
      if (lockedByOther && !state.readOnly) {
        stopHeartbeat();
        state.readOnly = true;
        state.selectedAnnotationId = null;
        cancelTempDrawing();
        redraw();
        renderAnnotationList();
        updateStatus();
        listChanged = true;
      }
    }

    if (listChanged) renderImageList();
  } catch (e) {
    // El polling no debe interrumpir el trabajo si una consulta falla temporalmente.
    console.debug("No se pudo actualizar el estado de los bloqueos", e);
  } finally {
    state.lockPollInFlight = false;
  }
}

function renderImageList() {
  const box = document.getElementById("imageList");
  box.innerHTML = "";
  state.images.forEach((img, idx) => {
    const item = document.createElement("div");
    item.className = "list-item" + (idx === state.currentIndex ? " selected" : "");
    const lockedByOther = img.locked_by && img.locked_by !== state.me.username;
    item.innerHTML = `
      <span>${img.has_annotations ? '<span class="check">✔</span> ' : ""}${escapeHtml(img.original_filename)}</span>
      <span style="display:flex; align-items:center; gap:6px;">
        ${lockedByOther ? `<span class="lock-badge">🔒 ${escapeHtml(img.locked_by)}</span>` : ""}
        <button data-action="delete-image" title="Eliminar esta imagen" style="padding:1px 6px; font-size:12px;">🗑</button>
      </span>
    `;
    item.addEventListener("click", () => loadImageAt(idx));
    item.querySelector('[data-action="delete-image"]').addEventListener("click", (e) => {
      e.stopPropagation(); // no abrir la imagen al hacer clic en "eliminar"
      deleteImageAt(idx);
    });
    box.appendChild(item);
  });
}

async function deleteImageAt(idx) {
  const img = state.images[idx];
  if (!img) return;
  if (img.locked_by && img.locked_by !== state.me.username) {
    alert(`No se puede eliminar: ${img.locked_by} la está editando ahora mismo.`);
    return;
  }
  if (!confirm(`¿Eliminar "${img.original_filename}" de la aplicación?\n\nEsto NO borra nada de Google Drive, solo quita la imagen y sus anotaciones de aquí. Esta acción no se puede deshacer.`)) {
    return;
  }

  const wasCurrent = idx === state.currentIndex;

  try {
    if (wasCurrent) {
      stopHeartbeat();
      if (!state.readOnly) {
        try { await Api.unlockImage(img.id); } catch (e) {}
      }
    }
    await Api.deleteImage(img.id);
  } catch (e) {
    alert("No se pudo eliminar la imagen: " + e.message);
    return;
  }

  delete state.undoStacks[img.id];

  if (wasCurrent) {
    state.currentImageId = null;
    state.currentIndex = -1;
    state.currentAnn = { points: [], regions: [] };
    state.imgEl = null;
    state.selectedAnnotationId = null;
    cancelTempDrawing();
    canvas.style.display = "none";
    canvasPlaceholder.style.display = "block";
  }

  await refreshImageList();

  if (state.images.length === 0) {
    setStatus('No hay imágenes todavía. Súbelas con el botón "🖼 Subir imagen".');
    renderAnnotationList();
    return;
  }

  if (wasCurrent) {
    // Abrir la imagen que quedó en el mismo lugar de la lista, o la anterior
    // si la eliminada era la última.
    const nextIndex = Math.min(idx, state.images.length - 1);
    await loadImageAt(nextIndex);
  } else if (idx < state.currentIndex) {
    // Una imagen ANTES de la actual se eliminó: el índice de la actual se
    // corrió una posición hacia atrás, hay que actualizarlo sin recargarla.
    state.currentIndex -= 1;
    renderImageList();
  }
}

async function onUploadFiles(e) {
  const files = e.target.files;
  if (!files || files.length === 0) return;
  try {
    const result = await Api.uploadImages(files);
    if (result.errors && result.errors.length) {
      alert("Algunos archivos no se pudieron subir:\n" + result.errors.join("\n"));
    }
    await refreshImageList();
    if (state.currentIndex === -1 && state.images.length > 0) {
      await loadImageAt(0);
    }
  } catch (err) {
    alert("Error al subir imágenes: " + err.message);
  } finally {
    e.target.value = "";
  }
}

async function loadImageAt(index) {
  if (index < 0 || index >= state.images.length) return;

  // Guardar y liberar el bloqueo de la imagen anterior antes de cambiar.
  if (state.currentImageId && !state.readOnly) {
    try { await saveCurrentAnnotations(); } catch (e) {}
    try { await Api.unlockImage(state.currentImageId); } catch (e) {}
  }
  stopHeartbeat();

  state.currentIndex = index;
  const summary = state.images[index];
  state.currentImageId = summary.id;
  state.selectedAnnotationId = null;
  cancelTempDrawing();

  // Intentar bloquear la imagen para poder editarla.
  state.readOnly = false;
  try {
    await Api.lockImage(summary.id);
    startHeartbeat();
  } catch (e) {
    state.readOnly = true;
    setStatus(`⚠ Esta imagen está siendo editada por ${e.data && e.data.detail ? e.data.detail : "otra persona"} — modo solo lectura.`);
  }

  const ann = await Api.getAnnotations(summary.id);
  state.currentAnn = { points: ann.points || [], regions: ann.regions || [] };

  await loadImageElement(summary.id);
  fitToWindow();
  updateStatus();
  renderAnnotationList();
  renderImageList();
}

function loadImageElement(imageId) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      state.imgEl = img;
      canvasPlaceholder.style.display = "none";
      canvas.style.display = "block";
      resolve();
    };
    img.onerror = reject;
    img.src = Api.imageFileUrl(imageId) + `?t=${Date.now()}`;
  });
}

function startHeartbeat() {
  stopHeartbeat();
  state.heartbeatTimer = setInterval(async () => {
    try {
      await Api.heartbeatImage(state.currentImageId);
    } catch (e) {
      stopHeartbeat();
      state.readOnly = true;
      setStatus("⚠ Se perdió el bloqueo de edición de esta imagen (posiblemente por inactividad). Recarga para reintentar.");
    }
  }, HEARTBEAT_INTERVAL_MS);
}
function stopHeartbeat() {
  if (state.heartbeatTimer) {
    clearInterval(state.heartbeatTimer);
    state.heartbeatTimer = null;
  }
}

async function goNext() {
  if (state.currentIndex < state.images.length - 1) await loadImageAt(state.currentIndex + 1);
}
async function goPrevious() {
  if (state.currentIndex > 0) await loadImageAt(state.currentIndex - 1);
}

async function saveCurrentAnnotations() {
  if (!state.currentImageId || state.readOnly) return;
  try {
    await Api.saveAnnotations(state.currentImageId, state.currentAnn.points, state.currentAnn.regions);
    const img = state.images[state.currentIndex];
    if (img) img.has_annotations = state.currentAnn.points.length > 0 || state.currentAnn.regions.length > 0;
    renderImageList();
  } catch (e) {
    console.error("Error guardando anotaciones", e);
  }
}

function exportDataset() {
  window.open(Api.exportDatasetUrl(), "_blank");
}

// ---------------------------------------------------------------------
// Deshacer
// ---------------------------------------------------------------------

function pushUndo() {
  if (!state.currentImageId) return;
  const stack = state.undoStacks[state.currentImageId] || (state.undoStacks[state.currentImageId] = []);
  stack.push(JSON.parse(JSON.stringify(state.currentAnn)));
  if (stack.length > 100) stack.shift();
}

function undo() {
  if (!state.currentImageId) return;
  const stack = state.undoStacks[state.currentImageId];
  if (!stack || stack.length === 0) {
    flashStatus("No hay más cambios para deshacer en esta imagen.");
    return;
  }
  state.currentAnn = stack.pop();
  state.selectedAnnotationId = null;
  cancelTempDrawing();
  renderAnnotationList();
  redraw();
  updateStatus();
}

let statusFlashTimer = null;
function flashStatus(text) {
  const el = document.getElementById("statusLeft");
  el.textContent = text;
  clearTimeout(statusFlashTimer);
  statusFlashTimer = setTimeout(() => updateStatus(), 1800);
}

// ---------------------------------------------------------------------
// Zoom / ajuste
// ---------------------------------------------------------------------

function fitToWindow() {
  if (!state.imgEl) return;
  const cw = Math.max(canvasArea.clientWidth, 100);
  const ch = Math.max(canvasArea.clientHeight, 100);
  const scaleW = cw / state.imgEl.width;
  const scaleH = ch / state.imgEl.height;
  state.scale = Math.min(Math.min(scaleW, scaleH), 3.0);
  state.scale = Math.max(state.scale, MIN_ZOOM);
  redraw();
}

function zoomBy(factor) {
  if (!state.imgEl) return;
  let newScale = state.scale * factor;
  newScale = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, newScale));
  state.scale = newScale;
  redraw();
}

function onCanvasWheel(e) {
  if (!state.imgEl) return;
  e.preventDefault();
  zoomBy(e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP);
}

// ---------------------------------------------------------------------
// Dibujo
// ---------------------------------------------------------------------

function redraw() {
  if (!state.imgEl) return;
  const w = Math.max(1, Math.round(state.imgEl.width * state.scale));
  const h = Math.max(1, Math.round(state.imgEl.height * state.scale));
  canvas.width = w;
  canvas.height = h;
  ctx.clearRect(0, 0, w, h);
  ctx.drawImage(state.imgEl, 0, 0, w, h);
  document.getElementById("zoomPct").textContent = `${Math.round(state.scale * 100)}%`;
  drawAnnotations();
}

function drawAnnotations() {
  for (const p of state.currentAnn.points) {
    const cx = p.x * state.scale, cy = p.y * state.scale;
    const color = labelColor(p.label, p.label_id, p.category);
    const selected = p.id === state.selectedAnnotationId;
    ctx.beginPath();
    ctx.arc(cx, cy, POINT_RADIUS, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.lineWidth = selected ? 3 : 1;
    ctx.strokeStyle = selected ? "#ffffff" : color;
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.font = "bold 12px sans-serif";
    labelDisplayText(p).split("\n").forEach((line, i) => {
      ctx.fillText(line, cx + POINT_RADIUS + 3, cy - POINT_RADIUS - 3 + i * 14);
    });
  }

  for (const r of state.currentAnn.regions) {
    const color = labelColor(r.label, r.label_id, r.category);
    const selected = r.id === state.selectedAnnotationId;
    if (r.type === "rect") {
      const [[x1, y1], [x2, y2]] = r.coords;
      const rx = x1 * state.scale, ry = y1 * state.scale;
      const rw = (x2 - x1) * state.scale, rh = (y2 - y1) * state.scale;
      if (selected) {
        ctx.lineWidth = 6;
        ctx.strokeStyle = "#ffffff";
        ctx.strokeRect(rx, ry, rw, rh);
      }
      ctx.lineWidth = selected ? 3 : 2;
      ctx.strokeStyle = color;
      ctx.strokeRect(rx, ry, rw, rh);
      ctx.fillStyle = color;
      ctx.font = "bold 12px sans-serif";
      labelDisplayText(r).split("\n").forEach((line, i) => {
        ctx.fillText(line, Math.min(x1, x2) * state.scale + 3, Math.min(y1, y2) * state.scale + 12 + i * 14);
      });
    } else if (r.type === "polygon") {
      const buildPath = () => {
        ctx.beginPath();
        r.coords.forEach(([x, y], i) => {
          const cx = x * state.scale, cy = y * state.scale;
          if (i === 0) ctx.moveTo(cx, cy); else ctx.lineTo(cx, cy);
        });
        ctx.closePath();
      };
      if (selected) {
        buildPath();
        ctx.lineWidth = 6;
        ctx.strokeStyle = "#ffffff";
        ctx.stroke();
      }
      buildPath();
      ctx.lineWidth = selected ? 3 : 2;
      ctx.strokeStyle = color;
      ctx.stroke();
      ctx.fillStyle = color;
      ctx.font = "bold 12px sans-serif";
      const [x0, y0] = r.coords[0];
      labelDisplayText(r).split("\n").forEach((line, i) => {
        ctx.fillText(line, x0 * state.scale + 3, y0 * state.scale + 12 + i * 14);
      });
    }
  }

  // Vista previa de polígono en construcción
  if (state.polygonPoints.length > 0) {
    const color = labelColor(state.currentLabel, state.currentLabelId, state.currentCategoryId) || "#ffffff";
    const canClose = state.polygonPoints.length >= 3;
    ctx.beginPath();
    state.polygonPoints.forEach(([x, y], i) => {
      const cx = x * state.scale, cy = y * state.scale;
      if (i === 0) ctx.moveTo(cx, cy); else ctx.lineTo(cx, cy);
    });
    ctx.strokeStyle = color;
    ctx.setLineDash([4, 3]);
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.setLineDash([]);

    state.polygonPoints.forEach(([x, y], i) => {
      const isOrigin = i === 0;
      const radius = isOrigin && canClose ? VERTEX_RADIUS + 3 : VERTEX_RADIUS;
      ctx.beginPath();
      ctx.arc(x * state.scale, y * state.scale, radius, 0, Math.PI * 2);
      ctx.fillStyle = isOrigin && canClose ? "#2ecc71" : "#ffffff";
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = color;
      ctx.stroke();
    });
  }
}

function screenDistXY(ax, ay, bx, by) {
  return Math.hypot(ax - bx, ay - by) * state.scale;
}

function pointInRect(x, y, coords) {
  const [[x1, y1], [x2, y2]] = coords;
  const minX = Math.min(x1, x2), maxX = Math.max(x1, x2);
  const minY = Math.min(y1, y2), maxY = Math.max(y1, y2);
  return x >= minX && x <= maxX && y >= minY && y <= maxY;
}

function pointInPolygon(x, y, coords) {
  // Algoritmo estándar de ray-casting.
  let inside = false;
  for (let i = 0, j = coords.length - 1; i < coords.length; j = i++) {
    const [xi, yi] = coords[i];
    const [xj, yj] = coords[j];
    const intersect =
      yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function findAnnotationAt(x, y) {
  // Los puntos son objetivos pequeños y precisos: se revisan primero.
  // Se recorre en reversa para preferir el más reciente en caso de solape.
  const POINT_HIT_TOLERANCE_PX = POINT_RADIUS + 4;
  for (let i = state.currentAnn.points.length - 1; i >= 0; i--) {
    const p = state.currentAnn.points[i];
    if (screenDistXY(x, y, p.x, p.y) <= POINT_HIT_TOLERANCE_PX) {
      return p;
    }
  }
  for (let i = state.currentAnn.regions.length - 1; i >= 0; i--) {
    const r = state.currentAnn.regions[i];
    const hit = r.type === "rect" ? pointInRect(x, y, r.coords) : pointInPolygon(x, y, r.coords);
    if (hit) return r;
  }
  return null;
}

function selectAnnotation(idOrNull) {
  state.selectedAnnotationId = idOrNull;
  redraw();
  renderAnnotationList();
  const el = document.querySelector(`#annotationList .list-item.selected`);
  if (el) el.scrollIntoView({ block: "nearest" });
}

function toImageCoords(e) {
  const rect = canvas.getBoundingClientRect();
  const x = (e.clientX - rect.left) / state.scale;
  const y = (e.clientY - rect.top) / state.scale;
  return [x, y];
}

function requireLabel() {
  if (!state.currentLabel) {
    if (confirm("No hay una etiqueta activa seleccionada. ¿Quieres abrir el gestor de etiquetas para crear o elegir una?")) {
      openLabelsModal();
    }
    return false;
  }
  return true;
}

function onCanvasMouseDown(e) {
  if (!state.imgEl || state.readOnly) return;
  if (e.button !== 0) return;

  if (state.mode === "select") {
    const [x, y] = toImageCoords(e);
    const found = findAnnotationAt(x, y);
    selectAnnotation(found ? found.id : null);
    return;
  }

  if (!requireLabel()) return;
  const [x, y] = toImageCoords(e);

  if (state.mode === "point") {
    pushUndo();
    state.currentAnn.points.push({
      id: uuid(),
      x,
      y,
      label: state.currentLabel,
      label_id: state.currentLabelId,
      category: state.currentCategoryId
    });
    redraw();
    renderAnnotationList();
    updateStatus();
  } else if (state.mode === "polygon") {
    if (state.polygonPoints.length >= 3 && screenDistXY(x, y, state.polygonPoints[0][0], state.polygonPoints[0][1]) <= CLOSE_SHAPE_THRESHOLD_PX) {
      finishPolygon();
      return;
    }
    state.polygonPoints.push([x, y]);
    redraw();
  } else if (state.mode === "freehand") {
    state.freehandActive = true;
    state.freehandPoints = [[x, y]];
    state.freehandAwayFromStart = false;
  }
}

function onCanvasMouseMove(e) {
  if (!state.imgEl || state.readOnly) return;
  if (state.mode === "freehand" && state.freehandActive) {
    const [x, y] = toImageCoords(e);
    const [lastX, lastY] = state.freehandPoints[state.freehandPoints.length - 1];
    const distScreen = screenDistXY(x, y, lastX, lastY);
    if (distScreen >= 3) {
      state.freehandPoints.push([x, y]);
      redrawFreehandPreview();
    }
    const [ox, oy] = state.freehandPoints[0];
    const distToOrigin = screenDistXY(x, y, ox, oy);
    if (!state.freehandAwayFromStart) {
      if (distToOrigin > CLOSE_SHAPE_THRESHOLD_PX * 2) state.freehandAwayFromStart = true;
    } else if (distToOrigin <= CLOSE_SHAPE_THRESHOLD_PX && state.freehandPoints.length >= 4) {
      finishFreehand();
    }
  }
}

function onCanvasMouseUp(e) {
  if (!state.imgEl || state.readOnly) return;
  if (state.mode === "freehand" && state.freehandActive) {
    finishFreehand();
  }
}

function onCanvasDoubleClick(e) {
  if (state.mode === "polygon") finishPolygon();
}

function redrawFreehandPreview() {
  redraw();
  const color = labelColor(state.currentLabel, state.currentLabelId, state.currentCategoryId) || "#ffffff";
  ctx.beginPath();
  state.freehandPoints.forEach(([x, y], i) => {
    const cx = x * state.scale, cy = y * state.scale;
    if (i === 0) ctx.moveTo(cx, cy); else ctx.lineTo(cx, cy);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();
}

function finishPolygon() {
  if (state.mode !== "polygon" || state.polygonPoints.length < 3) {
    cancelTempDrawing();
    return;
  }
  if (!state.currentLabel) { cancelTempDrawing(); return; }
  pushUndo();
  state.currentAnn.regions.push({
    id: uuid(),
    type: "polygon",
    label: state.currentLabel,
    label_id: state.currentLabelId,
    category: state.currentCategoryId,
    coords: state.polygonPoints.map((p) => [...p])
  });
  cancelTempDrawing();
  redraw();
  renderAnnotationList();
  updateStatus();
}

function finishFreehand() {
  state.freehandActive = false;
  const points = state.freehandPoints;
  state.freehandPoints = [];
  if (points.length < 3) { redraw(); return; }
  if (!state.currentLabel) { redraw(); return; }
  pushUndo();
  state.currentAnn.regions.push({
    id: uuid(),
    type: "polygon",
    label: state.currentLabel,
    label_id: state.currentLabelId,
    category: state.currentCategoryId,
    coords: points.map((p) => [...p])
  });
  redraw();
  renderAnnotationList();
  updateStatus();
}

function cancelTempDrawing() {
  state.polygonPoints = [];
  state.freehandPoints = [];
  state.freehandActive = false;
  state.freehandAwayFromStart = false;
  redraw();
}

function uuid() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// ---------------------------------------------------------------------
// Panel de anotaciones
// ---------------------------------------------------------------------

function renderAnnotationList() {
  const box = document.getElementById("annotationList");
  box.innerHTML = "";

  const annotations = [
    ...state.currentAnn.points.map((p) => ({ ...p, _kind: "point" })),
    ...state.currentAnn.regions.map((r) => ({ ...r, _kind: "region" })),
  ];

  for (const annotation of annotations) {
    const item = document.createElement("div");
    item.className = "list-item annotation-item" +
      (annotation.id === state.selectedAnnotationId ? " selected" : "");

    const labelText = labelDisplayText(annotation).replace(/\n/g, " · ");
    const description = annotation._kind === "point"
      ? `● Punto — ${labelText} (${Math.round(annotation.x)}, ${Math.round(annotation.y)})`
      : `▭ ${annotation.type === "rect" ? "Rectángulo" : `Polígono (${annotation.coords.length} pts)`} — ${labelText}`;

    item.innerHTML = `
      <span class="annotation-name">${escapeHtml(description)}</span>
      <span class="annotation-actions">
        <button data-action="edit-annotation" class="icon-action" title="Cambiar etiqueta" aria-label="Cambiar etiqueta">✏️</button>
        <button data-action="delete-annotation" class="icon-action danger-icon" title="Eliminar etiqueta" aria-label="Eliminar etiqueta">🗑</button>
      </span>
    `;

    item.addEventListener("click", () => {
      state.selectedAnnotationId = annotation.id;
      redraw();
      renderAnnotationList();
    });

    item.querySelector('[data-action="edit-annotation"]').addEventListener("click", (e) => {
      e.stopPropagation();
      state.selectedAnnotationId = annotation.id;
      reassignAnnotationById(annotation.id);
    });

    item.querySelector('[data-action="delete-annotation"]').addEventListener("click", (e) => {
      e.stopPropagation();
      deleteAnnotationById(annotation.id);
    });

    box.appendChild(item);
  }
}

function deleteAnnotationById(id) {
  if (!id) return;
  const target =
    state.currentAnn.points.find((p) => p.id === id) ||
    state.currentAnn.regions.find((r) => r.id === id);
  if (!target) return;

  const labelText = labelDisplayText(target).replace(/\n/g, " · ");
  if (!confirm(`¿Eliminar la etiqueta "${labelText}" de esta anotación?`)) return;

  pushUndo();
  state.currentAnn.points = state.currentAnn.points.filter((p) => p.id !== id);
  state.currentAnn.regions = state.currentAnn.regions.filter((r) => r.id !== id);
  state.selectedAnnotationId = null;
  renderAnnotationList();
  redraw();
  updateStatus();
}

function deleteSelectedAnnotation() {
  if (!state.selectedAnnotationId) return;
  deleteAnnotationById(state.selectedAnnotationId);
}

function reassignAnnotationById(id) {
  if (!id) return;
  if (!requireLabel()) return;

  const target =
    state.currentAnn.points.find((p) => p.id === id) ||
    state.currentAnn.regions.find((r) => r.id === id);
  if (!target) return;

  pushUndo();
  target.label = state.currentLabel;
  target.label_id = state.currentLabelId;
  target.category = state.currentCategoryId;
  redraw();
  renderAnnotationList();
  updateStatus();
}

function reassignSelectedLabel() {
  if (!state.selectedAnnotationId) {
    alert("Primero selecciona una anotación (modo Seleccionar, o haciendo clic en la lista).");
    return;
  }
  reassignAnnotationById(state.selectedAnnotationId);
}

// ---------------------------------------------------------------------
// Estado / barra inferior
// ---------------------------------------------------------------------

function setStatus(text) {
  document.getElementById("statusLeft").textContent = text;
}

function updateStatus() {
  if (state.currentIndex < 0) {
    setStatus("Ningún proyecto abierto.");
    return;
  }
  const img = state.images[state.currentIndex];
  const total = state.images.length;
  const nPoints = state.currentAnn.points.length;
  const nRegions = state.currentAnn.regions.length;
  const readOnlyTxt = state.readOnly ? " · SOLO LECTURA" : "";
  setStatus(`Imagen ${state.currentIndex + 1} de ${total} | ${img.original_filename} | ${nPoints} puntos, ${nRegions} regiones${readOnlyTxt}`);
}

// ---------------------------------------------------------------------
// Google Drive
// ---------------------------------------------------------------------

let driveStatusPoll = null;

async function uploadToDrive() {
  try {
    await Api.startDriveUpload();
  } catch (e) {
    alert("No se pudo iniciar la subida a Drive: " + e.message);
    return;
  }
  document.getElementById("driveProgressModal").classList.add("open");
  pollDriveStatus();
}

function pollDriveStatus() {
  clearInterval(driveStatusPoll);
  driveStatusPoll = setInterval(async () => {
    let s;
    try {
      s = await Api.driveUploadStatus();
    } catch (e) {
      return;
    }
    const pct = s.total > 0 ? Math.round((s.done / s.total) * 100) : 0;
    document.getElementById("driveProgressFill").style.width = `${pct}%`;
    document.getElementById("driveProgressLabel").textContent =
      s.status === "running" ? `(${s.done}/${s.total}) ${s.current_name || ""}` : `Estado: ${s.status}`;

    if (s.status !== "running") {
      clearInterval(driveStatusPoll);
      document.getElementById("driveProgressModal").classList.remove("open");
      if (s.status === "completed") alert(`Subida completa: ${s.done}/${s.total} archivos.`);
      else if (s.status === "cancelled") alert(`Subida cancelada (${s.done}/${s.total} archivos subidos).`);
      else if (s.status === "error") alert("Error durante la subida: " + s.message);
    }
  }, 1000);
}

init();
