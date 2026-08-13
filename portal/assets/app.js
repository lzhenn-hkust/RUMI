const state = {
  user: null,
  constants: null,
  uploads: [],
  adminLoaded: false,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
}

function toast(message, type = "ok") {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("error", type === "error");
  el.classList.remove("hidden");
  window.clearTimeout(toast._timer);
  toast._timer = window.setTimeout(() => el.classList.add("hidden"), 4200);
}

function formMessage(id, message = "", type = "ok") {
  const el = $(id);
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("error", type === "error");
  el.classList.toggle("hidden", !message);
}

function cookieValue(name) {
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`))
    ?.split("=")
    .slice(1)
    .join("=") || "";
}

async function api(action, payload = null, options = {}) {
  const init = {
    method: payload === null && !options.method ? "GET" : (options.method || "POST"),
    headers: {"X-RUMI-Portal": "1"},
    credentials: "same-origin",
  };
  const csrf = decodeURIComponent(cookieValue("rumi_csrf"));
  if (csrf) init.headers["X-CSRF-Token"] = csrf;
  if (payload !== null) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(payload);
  }
  const response = await fetch(`api.cgi?action=${encodeURIComponent(action)}`, init);
  const data = await response.json().catch(() => ({ok: false, error: "Invalid server response"}));
  if (!response.ok || data.ok === false) {
    const error = new Error(data.error || `Request failed with ${response.status}`);
    error.status = response.status;
    error.details = data.details || {};
    throw error;
  }
  return data;
}

function formDataObject(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function bytes(n) {
  if (!Number.isFinite(n)) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function setView() {
  const signedIn = Boolean(state.user);
  $("#authView").classList.toggle("hidden", signedIn);
  $("#appView").classList.toggle("hidden", !signedIn);
  $("#logoutBtn").classList.toggle("hidden", !signedIn);
  if (!signedIn) $("#uploadResult").classList.add("hidden");
  $("#sessionLabel").textContent = signedIn
    ? `${state.user.name} · ${state.user.institution}`
    : "Not signed in";
  $$(".admin-only").forEach((el) => el.classList.toggle("hidden", !signedIn || state.user.role !== "admin"));
  if (signedIn) {
    fillConstants();
    loadUploads();
  }
}

function fillConstants() {
  if (!state.constants) return;
  const experimentList = $("#experimentOptions");
  const eventSelect = $('[name="event"]', $("#uploadForm"));
  if (!experimentList.children.length) {
    state.constants.experiments.forEach((item) => {
      const option = document.createElement("option");
      option.value = item;
      experimentList.append(option);
    });
  }
  if (!eventSelect.options.length) {
    Object.entries(state.constants.events).forEach(([code, item]) => {
      const option = document.createElement("option");
      option.value = code;
      option.textContent = `${code} · ${item.category}`;
      eventSelect.append(option);
    });
  }
  $("#coreVarList").replaceChildren(...state.constants.core_2d_vars.map((name) => {
    const li = document.createElement("li");
    li.textContent = name;
    return li;
  }));
  const events = Object.entries(state.constants.events).map(([code, item]) => {
    const div = document.createElement("div");
    div.className = "event-item";
    div.innerHTML = `<strong>${escapeHtml(code)}</strong><span>${escapeHtml(item.name)}</span><span>${escapeHtml(item.start.slice(0, 10))} to ${escapeHtml(item.end.slice(0, 10))}</span>`;
    return div;
  });
  $("#eventList").replaceChildren(...events);
}

function activateTab(tabId) {
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === tabId));
  $$(".tab-panel").forEach((panel) => panel.classList.toggle("hidden", panel.id !== tabId));
  if (tabId === "adminTab" && !state.adminLoaded) loadAdmin();
  if (tabId === "submissionsTab") loadUploads();
}

function validationText(validation) {
  if (!validation) return "";
  const errors = validation.errors || [];
  const warnings = validation.warnings || [];
  if (!errors.length && !warnings.length) return "Clean";
  const parts = [];
  if (errors.length) parts.push(`${errors.length} error${errors.length === 1 ? "" : "s"}`);
  if (warnings.length) parts.push(`${warnings.length} warning${warnings.length === 1 ? "" : "s"}`);
  return parts.join(", ");
}

function validationDetails(validation) {
  if (!validation) return "";
  const errors = validation.errors || [];
  const warnings = validation.warnings || [];
  const summary = validation.summary || {};
  if (!errors.length && !warnings.length && !Object.keys(summary).length) return "";
  const lines = [];
  if (errors.length) lines.push(`<strong>Errors</strong><ul>${errors.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`);
  if (warnings.length) lines.push(`<strong>Warnings</strong><ul>${warnings.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`);
  if (Object.keys(summary).length) lines.push(`<strong>Summary</strong><pre>${escapeHtml(JSON.stringify(summary, null, 2))}</pre>`);
  return `<details class="validation-details"><summary>${escapeHtml(validationText(validation)) || "Details"}</summary>${lines.join("")}</details>`;
}

function statusPill(status) {
  const safeStatus = String(status || "").replace(/[^a-z0-9_-]/gi, "");
  return `<span class="status ${escapeHtml(safeStatus)}">${escapeHtml(String(status || "").replace(/_/g, " "))}</span>`;
}

async function loadMe() {
  const data = await api("me");
  state.user = data.user;
  state.constants = data.constants;
  setView();
}

async function loadUploads() {
  if (!state.user) return;
  const data = await api("uploads");
  state.uploads = data.uploads;
  const isAdmin = state.user.role === "admin";
  const rows = data.uploads.map((upload) => {
    const validation = validationText(upload.validation);
    const fileInfo = `${escapeHtml(upload.file_name)}<br><span class="muted">${escapeHtml(bytes(upload.file_size))}</span>`;
    const uploader = upload.uploader || {};
    const uploaderCell = isAdmin
      ? `<td data-label="Uploader">
          <div class="uploader-identity">
            <strong>${escapeHtml(uploader.name || "Unknown user")}</strong>
            <span class="uploader-email">${escapeHtml(uploader.email || "")}</span>
            <span class="muted">${escapeHtml(uploader.institution || "")}</span>
          </div>
        </td>`
      : "";
    const actions = upload.status === "deleted"
      ? ""
      : `<button class="danger-text" type="button" data-upload-action="delete" data-upload-id="${escapeHtml(upload.upload_id)}">Delete</button>`;
    return `<tr>
      <td data-label="File">${fileInfo}</td>
      ${uploaderCell}
      <td data-label="Event">${escapeHtml(upload.event)}</td>
      <td data-label="Model">${escapeHtml(upload.model)}</td>
      <td data-label="Status">${statusPill(upload.status)}</td>
      <td data-label="Validation">${validationDetails(upload.validation) || escapeHtml(validation)}</td>
      <td data-label="Updated">${escapeHtml(upload.updated_at || upload.created_at)}</td>
      <td data-label="Actions"><div class="row-actions">${actions}</div></td>
    </tr>`;
  });
  const columns = isAdmin ? 8 : 7;
  $("#uploadsBody").innerHTML = rows.join("") || `<tr><td colspan="${columns}" class="muted">No submissions yet.</td></tr>`;
  return data.uploads;
}

async function loadAdmin() {
  if (!state.user || state.user.role !== "admin") return;
  const data = await api("admin_users");
  state.adminLoaded = true;
  renderUsers(data.users);
  $("#whitelistCount").textContent = `${data.whitelist.length} whitelisted emails`;
}

async function deleteUpload(uploadId) {
  const upload = state.uploads.find((item) => item.upload_id === uploadId);
  if (!upload) return false;
  const uploader = upload.uploader?.email ? ` uploaded by ${upload.uploader.email}` : "";
  const confirmed = window.confirm(
    `Delete ${upload.file_name}${uploader}? The stored file will be removed, but its audit record will remain.`,
  );
  if (!confirmed) return false;
  await api("upload_delete", {upload_id: uploadId});
  await loadUploads();
  toast("Submission deleted");
  return true;
}

function renderUsers(users) {
  const rows = users.map((user) => {
    const actions = [];
    if (user.status !== "approved") actions.push(`<button data-action="approve" data-id="${user.id}">Approve</button>`);
    if (user.status !== "disabled") actions.push(`<button data-action="disable" data-id="${user.id}">Disable</button>`);
    if (user.status !== "deleted") actions.push(`<button data-action="delete" data-id="${user.id}">Delete</button>`);
    const roleSelect = `<select data-role="${user.id}">
      <option value="modeler"${user.role === "modeler" ? " selected" : ""}>modeler</option>
      <option value="admin"${user.role === "admin" ? " selected" : ""}>admin</option>
    </select>`;
    return `<tr>
      <td data-label="Name">${escapeHtml(user.name)}</td>
      <td data-label="Email">${escapeHtml(user.email)}</td>
      <td data-label="Institution">${escapeHtml(user.institution)}</td>
      <td data-label="Role">${roleSelect}</td>
      <td data-label="Status">${statusPill(user.status)}</td>
      <td data-label="Actions"><div class="row-actions">${actions.join("")}</div></td>
    </tr>`;
  });
  $("#usersBody").innerHTML = rows.join("") || `<tr><td colspan="6" class="muted">No users.</td></tr>`;
}

async function submitLogin(event) {
  event.preventDefault();
  const form = event.currentTarget;
  formMessage("#loginMessage");
  try {
    const data = await api("login", formDataObject(form));
    state.user = data.user;
    state.constants = data.constants || state.constants;
    form.reset();
    toast("Signed in");
    setView();
  } catch (err) {
    formMessage("#loginMessage", err.message, "error");
    toast(err.message, "error");
  }
}

async function submitRegister(event) {
  event.preventDefault();
  const form = event.currentTarget;
  formMessage("#registerMessage");
  try {
    const data = await api("register", formDataObject(form));
    state.user = data.user;
    state.constants = data.constants || state.constants;
    form.reset();
    formMessage("#registerMessage", data.message || "Registration complete");
    toast(data.message || "Registration complete");
    setView();
  } catch (err) {
    formMessage("#registerMessage", err.message, "error");
    toast(err.message, "error");
  }
}

async function logout() {
  const button = $("#logoutBtn");
  button.disabled = true;
  try {
    await api("logout", {});
    state.user = null;
    state.uploads = [];
    state.adminLoaded = false;
    activateTab("uploadTab");
    setView();
    toast("Signed out");
  } catch (err) {
    toast(err.message || "Could not sign out", "error");
  } finally {
    button.disabled = false;
  }
}

function parseFileName(name) {
  if (!state.constants) return null;
  const events = Object.keys(state.constants.events).join("|");
  const pattern = new RegExp(`^RUMI-([A-Za-z0-9._]+(?:-[A-Za-z0-9._]+)*)-(AN|FC)-([A-Za-z0-9._]+)-(${events})-(\\d{14})(?:_([A-Za-z0-9._-]+))?(?:_v([0-9]{2,}))?\\.nc$`);
  const match = name.match(pattern);
  if (!match) return null;
  return {
    experiment: `RUMI-${match[1]}-${match[2]}`,
    model: match[3],
    event: match[4],
    stamp: match[5],
    member: match[6] || "",
    version: match[7] ? `v${match[7]}` : "",
  };
}

function isArchiveFile(file) {
  return Boolean(file && /(?:\.zip|\.tar\.gz|\.tgz)$/i.test(file.name));
}

function parseArchiveName(name) {
  if (!state.constants) return null;
  const events = Object.keys(state.constants.events).join("|");
  const pattern = new RegExp(`^RUMI-([A-Za-z0-9._]+(?:-[A-Za-z0-9._]+)*)-(AN|FC)-([A-Za-z0-9._]+)-(${events})(?:_v([0-9]{2,}))?(?:\\.zip|\\.tar\\.gz|\\.tgz)$`);
  const match = name.match(pattern);
  if (!match) return null;
  return {
    experiment: `RUMI-${match[1]}-${match[2]}`,
    model: match[3],
    event: match[4],
    member: "",
    version: match[5] ? `v${match[5]}` : "",
  };
}

function setUploadMode(file) {
  const archive = isArchiveFile(file);
  const form = $("#uploadForm");
  $$(".single-file-time", form).forEach((label) => {
    label.classList.toggle("hidden", archive);
    const input = $("input", label);
    input.disabled = archive;
    input.required = !archive && input.dataset.requiredSingle === "true";
  });
  $("#fileModeHint").textContent = archive
    ? "Structured archive: place each RUMI-named NetCDF under a lead_NNNh directory."
    : ".nc for a single snapshot, or .zip/.tar.gz for a structured archive.";
}

function autoFillFromFile(file) {
  const parsed = isArchiveFile(file)
    ? parseArchiveName(file.name)
    : parseFileName(file.name);
  if (!parsed) return;
  const form = $("#uploadForm");
  form.elements.experiment.value = parsed.experiment;
  form.elements.model.value = parsed.model;
  form.elements.event.value = parsed.event;
  form.elements.member.value = parsed.member;
  form.elements.version.value = parsed.version;
  const experimentParts = parsed.experiment.split("-");
  const mode = experimentParts.at(-1);
  if (mode === "AN" || mode === "FC") {
    form.elements.forcing_mode.value = mode === "AN" ? "analysis" : "forecast";
    form.elements.forcing_source.value = experimentParts.slice(1, -1).join("-");
  }
}

function setProgress(done, total, label) {
  const wrap = $("#progressWrap");
  wrap.classList.remove("hidden");
  const pct = total ? Math.round((done / total) * 100) : 0;
  $("#progressLabel").textContent = label;
  $("#progressPct").textContent = `${pct}%`;
  $("#progressBar").style.width = `${Math.min(100, pct)}%`;
}

function showUploadMessage(title, message, type = "warning", errors = []) {
  const result = $("#uploadResult");
  const details = errors.length
    ? `<ul>${errors.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : "";
  result.className = `upload-result ${type}`;
  result.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span>${details}`;
}

function showUploadOutcome(upload) {
  const errors = upload.validation?.errors || [];
  const summary = upload.validation?.summary || {};
  const status = upload.status;
  if (status === "validated") {
    const archive = ["zip", "tar"].includes(upload.file_kind);
    const checked = summary.checked_netcdf_files ?? summary.validated_netcdf_files;
    const passed = summary.passed_netcdf_files ?? checked;
    const leadFolders = Object.keys(summary.lead_time_folders || {}).length;
    const message = archive && Number.isFinite(checked)
      ? `${upload.file_name} passed structured archive validation: ${passed}/${checked} NetCDF files across ${leadFolders} lead-time folders.`
      : `${upload.file_name} passed validation and is now stored as the active submission.`;
    showUploadMessage(
      "Submission accepted",
      message,
      "success",
    );
    setProgress(upload.file_size, upload.file_size, "Accepted");
    return;
  }
  if (status === "received_manual_review") {
    showUploadMessage(
      "Upload received",
      `${upload.file_name} was stored and is awaiting manual archive review.`,
      "warning",
    );
    setProgress(upload.file_size, upload.file_size, "Manual review");
    return;
  }
  if (status === "rejected") {
    showUploadMessage(
      "Submission rejected",
      "The file was transferred to staging but was not accepted. Correct the issues below and upload it again.",
      "error",
      errors,
    );
    setProgress(upload.file_size, upload.file_size, "Rejected");
    return;
  }
  if (status === "duplicate") {
    showUploadMessage(
      "Duplicate not accepted",
      "Identical file content has already been accepted. No second submission was created.",
      "error",
      errors,
    );
    setProgress(upload.file_size, upload.file_size, "Duplicate");
    return;
  }
  if (status === "server_error" || status === "failed") {
    showUploadMessage(
      "Submission not accepted",
      "The file reached the server, but processing could not be completed. The reference below can be used by the administrator.",
      "error",
      errors,
    );
    setProgress(upload.file_size, upload.file_size, "Server error");
    return;
  }
  showUploadMessage(
    "Upload status pending",
    `The file was transferred, but its current status is ${status}. Refresh Submissions before uploading it again.`,
    "warning",
  );
}

async function startUpload(metadata, file, replaceUploadId = "") {
  return api("upload_start", {
    ...metadata,
    file_name: file.name,
    file_size: file.size,
    replace_upload_id: replaceUploadId,
  });
}

async function uploadChunk(uploadId, file, offset, chunkSize) {
  const chunk = file.slice(offset, offset + chunkSize);
  const response = await fetch(`api.cgi?action=upload_chunk&upload_id=${encodeURIComponent(uploadId)}&offset=${offset}`, {
    method: "POST",
    headers: {"Content-Type": "application/octet-stream", "X-RUMI-Portal": "1", "X-CSRF-Token": decodeURIComponent(cookieValue("rumi_csrf"))},
    credentials: "same-origin",
    body: chunk,
  });
  const data = await response.json().catch(() => ({ok: false, error: "Invalid server response"}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || "Chunk upload failed");
  }
  return data.received_bytes;
}

async function submitUpload(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const file = $("#fileInput").files[0];
  if (!file) {
    toast("Select a file first", "error");
    return;
  }
  const button = $('button[type="submit"]', form);
  button.disabled = true;
  $("#uploadResult").className = "upload-result hidden";
  setProgress(0, file.size, "Preparing");
  let uploadId = "";
  let transferComplete = false;
  try {
    const metadata = formDataObject(form);
    delete metadata.file;
    let start;
    try {
      start = await startUpload(metadata, file);
    } catch (err) {
      if (err.details?.code !== "duplicate_filename") throw err;
      const existing = err.details.existing;
      const confirmed = window.confirm(
        `${existing.file_name} already exists with status ${existing.status}. ` +
        "Replace it only if this new file passes validation?",
      );
      if (!confirmed) {
        showUploadMessage(
          "Upload cancelled",
          "The existing submission was kept unchanged.",
          "warning",
        );
        setProgress(0, file.size, "Cancelled");
        return;
      }
      start = await startUpload(metadata, file, existing.upload_id);
    }
    uploadId = start.upload_id;
    const chunkSize = start.chunk_size || (8 * 1024 * 1024);
    let offset = 0;
    while (offset < file.size) {
      setProgress(offset, file.size, "Uploading");
      offset = await uploadChunk(start.upload_id, file, offset, chunkSize);
    }
    transferComplete = true;
    setProgress(file.size, file.size, "Validating");
    const finished = await api("upload_finish", {upload_id: start.upload_id});
    showUploadOutcome(finished.upload);
    const accepted = ["validated", "received_manual_review"].includes(finished.upload.status);
    toast(
      finished.upload.status === "validated"
        ? "Submission accepted"
        : finished.upload.status === "received_manual_review"
          ? "Upload received for manual review"
          : "Submission was not accepted",
      accepted ? "ok" : "error",
    );
    await loadUploads();
    activateTab("submissionsTab");
  } catch (err) {
    let reconciled = null;
    if (uploadId) {
      try {
        const uploads = await loadUploads();
        reconciled = uploads.find((item) => item.upload_id === uploadId);
      } catch (_) {
        // Keep the original upload error as the most useful message.
      }
    }
    if (reconciled && !["receiving", "validating"].includes(reconciled.status)) {
      showUploadOutcome(reconciled);
      activateTab("submissionsTab");
    } else {
      showUploadMessage(
        transferComplete ? "Acceptance not confirmed" : "Upload interrupted",
        transferComplete
          ? `${err.message} The file transfer completed, but the submission was not confirmed as accepted. Check Submissions before retrying.`
          : `${err.message} The submission was not accepted.`,
        transferComplete ? "warning" : "error",
      );
      setProgress(
        transferComplete ? file.size : 0,
        file.size,
        transferComplete ? "Status unknown" : "Interrupted",
      );
    }
    toast(err.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function createUser(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const data = await api("admin_create_user", formDataObject(form));
    form.reset();
    state.adminLoaded = false;
    await loadAdmin();
    toast(data.temporary_password ? `Temporary password: ${data.temporary_password}` : "User added");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function updateUser(id, status = null, role = null) {
  const payload = {id};
  if (status) payload.status = status;
  if (role) payload.role = role;
  await api("admin_update_user", payload);
  state.adminLoaded = false;
  await loadAdmin();
}

async function deleteUser(id) {
  await api("admin_delete_user", {id});
  state.adminLoaded = false;
  await loadAdmin();
}

async function addWhitelist(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("admin_whitelist_add", formDataObject(form));
    form.reset();
    state.adminLoaded = false;
    await loadAdmin();
    toast("Whitelist updated");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function changePassword(event) {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    await api("change_password", formDataObject(form));
    form.reset();
    toast("Password changed");
  } catch (err) {
    toast(err.message, "error");
  }
}

function bindEvents() {
  $("#loginForm").addEventListener("submit", submitLogin);
  $("#registerForm").addEventListener("submit", submitRegister);
  $("#logoutBtn").addEventListener("click", logout);
  $$(".tab").forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));
  $("#uploadForm").addEventListener("submit", submitUpload);
  $("#fileInput").addEventListener("change", (event) => {
    const file = event.currentTarget.files[0];
    setUploadMode(file);
    if (file) autoFillFromFile(file);
  });
  const dropzone = $(".dropzone");
  const fileInput = $("#fileInput");
  dropzone.addEventListener("click", (event) => {
    if (event.target !== fileInput) fileInput.click();
  });
  ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragging");
  }));
  dropzone.addEventListener("drop", (event) => {
    const files = event.dataTransfer.files;
    if (!files.length) return;
    fileInput.files = files;
    setUploadMode(files[0]);
    autoFillFromFile(files[0]);
  });
  $("#refreshUploadsBtn").addEventListener("click", loadUploads);
  $("#uploadsBody").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-upload-action]");
    if (!button || button.dataset.uploadAction !== "delete") return;
    button.disabled = true;
    try {
      const deleted = await deleteUpload(button.dataset.uploadId);
      if (!deleted) button.disabled = false;
    } catch (err) {
      button.disabled = false;
      toast(err.message, "error");
    }
  });
  $("#refreshAdminBtn").addEventListener("click", () => {
    state.adminLoaded = false;
    loadAdmin();
  });
  $("#createUserForm").addEventListener("submit", createUser);
  $("#whitelistForm").addEventListener("submit", addWhitelist);
  $("#passwordForm").addEventListener("submit", changePassword);
  $("#usersBody").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    try {
      const id = Number(button.dataset.id);
      if (button.dataset.action === "disable" && !window.confirm("Disable this user account?")) return;
      if (button.dataset.action === "delete" && !window.confirm("Delete this user account? This cannot be undone in the portal.")) return;
      if (button.dataset.action === "approve") await updateUser(id, "approved");
      if (button.dataset.action === "disable") await updateUser(id, "disabled");
      if (button.dataset.action === "delete") await deleteUser(id);
      toast("User updated");
    } catch (err) {
      toast(err.message, "error");
    }
  });
  $("#usersBody").addEventListener("change", async (event) => {
    const select = event.target.closest("select[data-role]");
    if (!select) return;
    try {
      if (select.value === "admin" && !window.confirm("Grant administrator access to this user?")) {
        await loadAdmin();
        return;
      }
      await updateUser(Number(select.dataset.role), null, select.value);
      toast("Role updated");
    } catch (err) {
      toast(err.message, "error");
    }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  try {
    await loadMe();
  } catch (err) {
    toast(err.message, "error");
  }
});
