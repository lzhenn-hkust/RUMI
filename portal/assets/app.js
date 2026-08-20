const state = {
  user: null,
  constants: null,
  uploads: [],
  adminLoaded: false,
  // Resumable-upload UI state: the file+offset the "Resume upload" hint is
  // currently offering, the in-progress chunked transfer (if any), and a
  // transfer that was deliberately paused and can be continued in place.
  resumableUpload: null,
  activeUpload: null,
  pausedUpload: null,
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
  const query = options.query
    ? `&${new URLSearchParams(options.query).toString()}`
    : "";
  const response = await fetch(`api.cgi?action=${encodeURIComponent(action)}${query}`, init);
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
    renderIdentityViews();
    loadUploads();
  }
}

function participationProfileMarkup(profiles, compact = false) {
  if (!profiles.length) {
    return '<p class="muted">No participation profile is registered for this account yet. Please contact an administrator.</p>';
  }
  return profiles.map((profile) => `
    <article class="participation-profile${compact ? " compact" : ""}">
      <div class="participation-profile-head">
        <strong>${escapeHtml(profile.group_name)}</strong>
        <span class="pill">Registered POC profile</span>
      </div>
      <dl class="identity-fields">
        <dt>Model</dt><dd>${escapeHtml(profile.model)}</dd>
        <dt>Driving source</dt><dd>${escapeHtml(profile.forcing_sources || "—")}</dd>
        <dt>Case studies</dt><dd>${escapeHtml(profile.case_studies || "—")}</dd>
        <dt>Participants</dt><dd>${escapeHtml(profile.participants || "—")}</dd>
        <dt>Timeline</dt><dd>${escapeHtml(profile.timeline || "—")}</dd>
      </dl>
    </article>
  `).join("");
}

// Identity and participation metadata come from the authenticated account and
// the admin-curated registry. They are displayed for transparency, not sent
// back as editable form fields on every upload.
function renderIdentityViews() {
  if (!state.user) return;
  const profiles = state.user.participation_profiles || [];
  const identity = `
    <dt>Name</dt><dd>${escapeHtml(state.user.name || "—")}</dd>
    <dt>Email</dt><dd>${escapeHtml(state.user.email || "—")}</dd>
    <dt>Institution</dt><dd>${escapeHtml(state.user.institution || "—")}</dd>
    <dt>POC surname</dt><dd>${escapeHtml(state.user.poc_surname || "—")}</dd>
    <dt>Participants</dt><dd>${escapeHtml(state.user.participants || "—")}</dd>
  `;
  const accountIdentity = $("#accountIdentityFields");
  if (accountIdentity) accountIdentity.innerHTML = identity;
  const accountProfiles = $("#accountParticipationProfiles");
  if (accountProfiles) accountProfiles.innerHTML = participationProfileMarkup(profiles);

  const uploadIdentity = {
    uploadIdentityName: state.user.name,
    uploadIdentityEmail: state.user.email,
    uploadIdentityInstitution: state.user.institution,
  };
  Object.entries(uploadIdentity).forEach(([id, value]) => {
    const field = $(`#${id}`);
    if (field) field.textContent = value || "—";
  });
  const uploadProfiles = $("#uploadParticipationProfiles");
  if (uploadProfiles) uploadProfiles.innerHTML = participationProfileMarkup(profiles, true);
}

function renderVarList(selector, names) {
  const el = $(selector);
  if (!el) return;
  el.replaceChildren(...(names || []).map((name) => {
    const li = document.createElement("li");
    li.textContent = name;
    return li;
  }));
}

function fillConstants() {
  if (!state.constants) return;
  renderVarList("#coreVarList", state.constants.core_2d_vars);
  renderVarList("#radiationVarList", state.constants.recommended_radiation_vars);
  $("#radiationVarNote").textContent =
    "Recommended: missing one of these is accepted, not rejected — your submission receipt lists what was not found.";
  const levels = (state.constants.recommended_3d_levels_hpa || []).join(", ");
  const alternatives = (state.constants.recommended_3d_alternatives || [])
    .map((group) => group.join(" or "));
  renderVarList("#mandatory3dVarList", [
    ...state.constants.recommended_3d_level_vars,
    ...alternatives,
  ]);
  $("#mandatory3dVarNote").textContent = levels
    ? `Recommended at ${levels} hPa. Missing one is accepted, not rejected — your submission receipt lists what was not found.`
    : "";
  $("#format3dFields").textContent = levels
    ? `${levels} hPa; recommended: ${state.constants.recommended_3d_level_vars.join(", ")}, plus ${alternatives.join(" or ")}`
    : "—";
  const events = Object.entries(state.constants.events).map(([code, item]) => {
    const div = document.createElement("div");
    div.className = "event-item";
    div.innerHTML = `<strong>${escapeHtml(code)}</strong><span>${escapeHtml(item.name)}</span><span>${escapeHtml(item.start.slice(0, 10))} to ${escapeHtml(item.end.slice(0, 10))}</span>`;
    return div;
  });
  $("#eventList").replaceChildren(...events);
  $("#rulesVersion").textContent = state.constants.rules_version || "—";
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

function uploaderForUpload(upload) {
  if (upload.uploader?.name || upload.uploader?.email) return upload.uploader;
  return {
    name: state.user?.name || "Current user",
    email: state.user?.email || "",
  };
}

function groupUploads(uploads, keyFunction) {
  const groups = new Map();
  uploads.forEach((upload) => {
    const key = keyFunction(upload);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(upload);
  });
  return groups;
}

function submissionRows(uploads) {
  return uploads.map((upload) => {
    const validation = validationText(upload.validation);
    const fileInfo = `${escapeHtml(upload.file_name)}<br><span class="muted">${escapeHtml(bytes(upload.file_size))}</span>`;
    const actions = upload.status === "deleted"
      ? ""
      : `<button class="danger-text" type="button" data-upload-action="delete" data-upload-id="${escapeHtml(upload.upload_id)}">Delete</button>`;
    return `<tr>
      <td data-label="File">${fileInfo}</td>
      <td data-label="Event">${escapeHtml(upload.event)}</td>
      <td data-label="Model">${escapeHtml(upload.model)}</td>
      <td data-label="Status">${statusPill(upload.status)}</td>
      <td data-label="Validation">${validationDetails(upload.validation) || escapeHtml(validation)}</td>
      <td data-label="Updated">${escapeHtml(upload.updated_at || upload.created_at)}</td>
      <td data-label="Actions"><div class="row-actions">${actions}</div></td>
    </tr>`;
  }).join("");
}

function submissionTable(uploads) {
  return `<div class="table-wrap">
    <table class="submissions-table">
      <thead>
        <tr>
          <th>File</th>
          <th>Event</th>
          <th>Model</th>
          <th>Status</th>
          <th>Validation</th>
          <th>Updated</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>${submissionRows(uploads)}</tbody>
    </table>
  </div>`;
}

function submissionGroups(uploads) {
  const institutions = groupUploads(
    uploads,
    (upload) => upload.institution || "Unknown institution",
  );
  if (!institutions.size) return `<p class="submission-empty muted">No submissions yet.</p>`;

  return Array.from(institutions.entries()).map(([institution, institutionUploads]) => {
    const uploaders = groupUploads(institutionUploads, (upload) => {
      const uploader = uploaderForUpload(upload);
      return `${uploader.email || "unknown"}\u0000${uploader.name || "Unknown uploader"}`;
    });
    const uploaderSections = Array.from(uploaders.values()).map((uploaderUploads) => {
      const uploader = uploaderForUpload(uploaderUploads[0]);
      const identity = [uploader.name, uploader.email].filter(Boolean).join(" · ") || "Unknown uploader";
      const count = uploaderUploads.length;
      return `<details class="submission-group submission-uploader-group">
        <summary>
          <span class="submission-summary-copy">
            <span class="submission-summary-label">Uploader</span>
            <strong>${escapeHtml(identity)}</strong>
          </span>
          <span class="submission-count">${count} submission${count === 1 ? "" : "s"}</span>
        </summary>
        <div class="submission-group-body">${submissionTable(uploaderUploads)}</div>
      </details>`;
    }).join("");
    const count = institutionUploads.length;
    return `<details class="submission-group submission-institution-group">
      <summary>
        <span class="submission-summary-copy">
          <span class="submission-summary-label">Institution</span>
          <strong>${escapeHtml(institution)}</strong>
        </span>
        <span class="submission-count">${count} submission${count === 1 ? "" : "s"}</span>
      </summary>
      <div class="submission-group-body submission-uploader-groups">${uploaderSections}</div>
    </details>`;
  }).join("");
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
  $("#uploadsBody").innerHTML = submissionGroups(data.uploads);
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
    const participation = (user.participation_profiles || []).map((profile) =>
      `${escapeHtml(profile.group_name)} · ${escapeHtml(profile.model)}`
    ).join("<br>") || '<span class="muted">Not linked</span>';
    return `<tr>
      <td data-label="Name">${escapeHtml(user.name)}</td>
      <td data-label="Email">${escapeHtml(user.email)}</td>
      <td data-label="Institution">${escapeHtml(user.institution)}</td>
      <td data-label="Participation">${participation}</td>
      <td data-label="Role">${roleSelect}</td>
      <td data-label="Status">${statusPill(user.status)}</td>
      <td data-label="Actions"><div class="row-actions">${actions.join("")}</div></td>
    </tr>`;
  });
  $("#usersBody").innerHTML = rows.join("") || `<tr><td colspan="7" class="muted">No users.</td></tr>`;
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

function isArchiveFile(file) {
  return Boolean(file && /(?:\.zip|\.tar\.gz)$/i.test(file.name));
}

// Archive identity (institution/model/event/poc) is parsed
// entirely from the file name - the server is authoritative here too and
// overwrites anything the form would otherwise send, so both sides must
// agree on the pattern. Rather than keep a second hand-written regex in
// sync with the backend, build it from state.constants.archive_name_pattern
// (the exact string form of rumi_protocol.ARCHIVE_NAME_RE).
function parseArchiveName(name) {
  if (!state.constants || !state.constants.archive_name_pattern) return null;
  const pattern = new RegExp(state.constants.archive_name_pattern);
  const match = name.match(pattern);
  if (!match) return null;
  const [, institution, model, event, poc] = match;
  return {institution, model, event, poc};
}

const ARCHIVE_NAME_ERROR = "Archive name must be <INST>-<MODEL>-<EVENT>-<POC>.tar.gz or .zip, " +
  "for example HKUST-MPAS-HRAIN2025-SHI.tar.gz. " +
  "Fields must be uppercase letters and digits without hyphens, so a model such as WRF-ARW " +
  "is written WRFARW.";

const IDENTITY_FIELD_IDS = [
  "identityInstitution",
  "identityModel",
  "identityEvent",
  "identityContact",
];

function resetArchiveIdentityFields() {
  IDENTITY_FIELD_IDS.forEach((id) => {
    const el = $(`#${id}`);
    if (el) el.textContent = "—";
  });
}

function setUploadSubmitEnabled(enabled) {
  const button = $('button[type="submit"]', $("#uploadForm"));
  if (button) button.disabled = !enabled;
}

function showArchiveIdentityError(message) {
  resetArchiveIdentityFields();
  formMessage("#archiveIdentityError", message, "error");
  setUploadSubmitEnabled(false);
}

function renderArchiveIdentity(parsed) {
  formMessage("#archiveIdentityError");
  $("#identityInstitution").textContent = parsed.institution;
  $("#identityModel").textContent = parsed.model;
  $("#identityEvent").textContent = parsed.event;
  $("#identityContact").textContent = parsed.poc;
  setUploadSubmitEnabled(true);
}

function setUploadMode(file) {
  const archive = isArchiveFile(file);
  $("#archiveIdentity").classList.toggle("hidden", !archive);
  $("#fileSelection").textContent = file?.name || "No archive selected";
  $("#fileModeHint").textContent =
    "Upload a .zip or .tar.gz structured archive containing the required NetCDF files and Participant_Model_Documentation.pdf.";
  if (archive) {
    resetArchiveIdentityFields();
    formMessage("#archiveIdentityError");
    setUploadSubmitEnabled(false);
  } else {
    resetArchiveIdentityFields();
    if (file) {
      showArchiveIdentityError("Only .zip and .tar.gz structured archives are accepted.");
    } else {
      formMessage("#archiveIdentityError");
      setUploadSubmitEnabled(false);
    }
  }
}

function autoFillFromFile(file) {
  if (!isArchiveFile(file)) return;
  const parsed = parseArchiveName(file.name);
  if (!parsed) {
    showArchiveIdentityError(ARCHIVE_NAME_ERROR);
    return;
  }
  renderArchiveIdentity(parsed);
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
    const experiments = summary.experiments || {};
    const initFolders = Object.values(experiments)
      .reduce((total, inits) => total + Object.keys(inits).length, 0);
    const message = archive && Number.isFinite(checked)
      ? `${upload.file_name} passed structured archive validation: ${passed}/${checked} NetCDF files across ${initFolders} initialization directories.`
      : `${upload.file_name} passed validation and is now stored as the active submission.`;
    // Recommended variables never block a submission, but the uploader is
    // told what was not found so they can decide whether to resubmit.
    const notes = (upload.validation?.warnings || []).filter((item) =>
      item.includes("not found"),
    );
    showUploadMessage(
      notes.length ? "Submission accepted, with notes" : "Submission accepted",
      notes.length ? `${message} The submission is stored. Please note:` : message,
      "success",
      notes,
    );
    setProgress(upload.file_size, upload.file_size, "Accepted");
    return;
  }
  if (status === "queued") {
    showUploadMessage(
      "Upload received, validation queued",
      `${upload.file_name} was transferred. Validation of several hundred files takes a few minutes and runs on the server, so you may close this page and check Submissions later.`,
      "warning",
    );
    setProgress(0, 1, "Queued for validation");
    return;
  }
  if (status === "validating") {
    const done = upload.validation_done || 0;
    const total = upload.validation_total || 0;
    showUploadMessage(
      "Validating submission",
      total
        ? `Checking ${upload.file_name}: ${done} of ${total} NetCDF files.`
        : `Checking ${upload.file_name}.`,
      "warning",
    );
    setProgress(done, total || 1, total ? `Validating ${done}/${total}` : "Validating");
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

const VALIDATION_POLL_MS = 3000;
const VALIDATION_TIMEOUT_MS = 30 * 60 * 1000;
const VALIDATION_PENDING = ["queued", "validating"];

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function fetchUploadStatus(uploadId) {
  const data = await api("upload_status", null, {query: {upload_id: uploadId}});
  return data.upload;
}

async function awaitValidation(uploadId, onProgress) {
  // A per-event archive holds several hundred files, so the server validates it
  // in the background and we follow along. Transient failures are tolerated:
  // the work continues on the server whether or not this page is watching.
  const deadline = Date.now() + VALIDATION_TIMEOUT_MS;
  let consecutiveFailures = 0;
  let upload = null;
  while (Date.now() < deadline) {
    await sleep(VALIDATION_POLL_MS);
    try {
      upload = await fetchUploadStatus(uploadId);
      consecutiveFailures = 0;
    } catch (err) {
      consecutiveFailures += 1;
      if (consecutiveFailures >= 5) throw err;
      continue;
    }
    if (onProgress) onProgress(upload);
    if (!VALIDATION_PENDING.includes(upload.status)) return upload;
  }
  return upload;
}

// --- Resumable uploads -----------------------------------------------
//
// The server remembers a partially-received upload under its upload_id
// (see upload_start's 409 "resumable" response and upload_status). The
// browser side keeps a small breadcrumb in localStorage so that picking
// the same file again - after a closed tab, a crash, or a deliberate
// pause - offers to continue instead of starting over.

const UPLOAD_RECORD_PREFIX = "rumi.upload.v1.";
const UPLOAD_RECORD_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const BIG_FILE_WARNING_BYTES = 1 * 1024 * 1024 * 1024;
const CHUNK_RETRY_LIMIT = 3;
const CHUNK_RETRY_DELAYS_MS = [1000, 3000, 9000];
const MAX_OFFSET_CORRECTIONS = 5;

// Statuses upload_finish/awaitValidation can settle into where the upload
// is done - accepted or not - and there is nothing left to resume.
const TERMINAL_UPLOAD_STATUSES = new Set([
  "validated",
  "rejected",
  "duplicate",
  "server_error",
  "received_manual_review",
  "failed",
]);

function isTerminalUploadStatus(status) {
  return TERMINAL_UPLOAD_STATUSES.has(status);
}

// The key ties together the three attributes that, together, identify
// "the same file" across page loads: name, size, and last-modified time.
function uploadStorageKey(file) {
  return `${UPLOAD_RECORD_PREFIX}${file.name}.${file.size}.${file.lastModified}`;
}

function sameFileIdentity(a, b) {
  return Boolean(a && b && a.name === b.name && a.size === b.size && a.lastModified === b.lastModified);
}

function readUploadRecord(file, storage = window.localStorage) {
  try {
    const raw = storage.getItem(uploadStorageKey(file));
    if (!raw) return null;
    const record = JSON.parse(raw);
    if (!record || typeof record.uploadId !== "string") return null;
    return record;
  } catch (_) {
    return null;
  }
}

function writeUploadRecord(file, uploadId, storage = window.localStorage) {
  try {
    storage.setItem(uploadStorageKey(file), JSON.stringify({uploadId, createdAt: Date.now()}));
  } catch (_) {
    // Storage unavailable or full: resuming just won't be offered next time.
  }
}

function clearUploadRecord(file, storage = window.localStorage) {
  try {
    storage.removeItem(uploadStorageKey(file));
  } catch (_) {
    // Ignore: nothing to clean up.
  }
}

// Sweeps every rumi.upload.v1.* entry and drops ones older than the max
// age, so an abandoned upload doesn't linger in localStorage forever.
function pruneUploadRecords(now = Date.now(), storage = window.localStorage) {
  let removed = 0;
  try {
    const keys = [];
    for (let i = 0; i < storage.length; i += 1) {
      const key = storage.key(i);
      if (key && key.startsWith(UPLOAD_RECORD_PREFIX)) keys.push(key);
    }
    keys.forEach((key) => {
      let stale = true;
      try {
        const record = JSON.parse(storage.getItem(key) || "null");
        stale = !record || !Number.isFinite(record.createdAt) || now - record.createdAt > UPLOAD_RECORD_MAX_AGE_MS;
      } catch (_) {
        stale = true;
      }
      if (stale) {
        storage.removeItem(key);
        removed += 1;
      }
    });
  } catch (_) {
    // Storage unavailable: nothing to prune.
  }
  return removed;
}

// upload_chunk validates the offset strictly and answers a mismatch with
// 409 + {expected}. That is not a failure - it just means the client's
// idea of how much the server has is stale (e.g. a prior response was
// lost after the server had already written the bytes) - so the caller
// should adopt `expected` and keep going. Returns null when `err` is not
// that specific, recoverable shape.
function nextOffsetAfterConflict(err, currentOffset) {
  if (!err || err.status !== 409) return null;
  const expected = err.details && err.details.expected;
  if (typeof expected !== "number" || !Number.isFinite(expected)) return null;
  return expected;
}

function resumeProgressLabel(receivedBytes, fileSize) {
  const pct = fileSize ? Math.round((receivedBytes / fileSize) * 100) : 0;
  return `Resume upload — ${pct}% already transferred (${bytes(receivedBytes)} of ${bytes(fileSize)})`;
}

class UploadPausedError extends Error {
  constructor(offset) {
    super("Upload paused");
    this.name = "UploadPausedError";
    this.offset = offset;
  }
}

async function startUpload(file, replaceUploadId = "") {
  return api("upload_start", {
    file_name: file.name,
    file_size: file.size,
    replace_upload_id: replaceUploadId,
  });
}

async function uploadChunk(uploadId, file, offset, chunkSize, signal) {
  const chunk = file.slice(offset, offset + chunkSize);
  const response = await fetch(`api.cgi?action=upload_chunk&upload_id=${encodeURIComponent(uploadId)}&offset=${offset}`, {
    method: "POST",
    headers: {"Content-Type": "application/octet-stream", "X-RUMI-Portal": "1", "X-CSRF-Token": decodeURIComponent(cookieValue("rumi_csrf"))},
    credentials: "same-origin",
    body: chunk,
    signal,
  });
  const data = await response.json().catch(() => ({ok: false, error: "Invalid server response"}));
  if (!response.ok || data.ok === false) {
    const error = new Error(data.error || "Chunk upload failed");
    error.status = response.status;
    error.details = data.details || {};
    throw error;
  }
  return data.received_bytes;
}

// Wraps uploadChunk with retry/backoff (1s / 3s / 9s, up to 3 attempts)
// and offset self-healing: a 409 with a numeric `expected` re-slices the
// chunk from the corrected offset and tries again without counting
// against the retry budget. An aborted signal (the user hit Pause)
// propagates immediately instead of being retried.
async function uploadChunkWithRetry(uploadId, file, offset, chunkSize, options = {}) {
  const {signal, onRetry} = options;
  let currentOffset = offset;
  let attempt = 0;
  let corrections = 0;
  for (;;) {
    try {
      return await uploadChunk(uploadId, file, currentOffset, chunkSize, signal);
    } catch (err) {
      if (signal?.aborted || err.name === "AbortError") throw err;
      const corrected = nextOffsetAfterConflict(err, currentOffset);
      if (corrected !== null) {
        corrections += 1;
        if (corrections > MAX_OFFSET_CORRECTIONS) throw err;
        currentOffset = corrected;
        continue;
      }
      attempt += 1;
      if (attempt > CHUNK_RETRY_LIMIT) throw err;
      if (onRetry) onRetry(attempt, CHUNK_RETRY_LIMIT);
      await sleep(CHUNK_RETRY_DELAYS_MS[attempt - 1] ?? CHUNK_RETRY_DELAYS_MS.at(-1));
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    }
  }
}

function resumeHintElement() {
  return $("#resumeHint");
}

function hideResumeHint() {
  const el = resumeHintElement();
  state.resumableUpload = null;
  if (!el) return;
  el.classList.add("hidden");
  el.innerHTML = "";
}

function showResumeHint(file, uploadId, receivedBytes, fileSize) {
  const el = resumeHintElement();
  if (!el) return;
  state.resumableUpload = {file, uploadId, receivedBytes, fileSize};
  el.innerHTML = "";
  const text = document.createElement("span");
  text.textContent = resumeProgressLabel(receivedBytes, fileSize);
  const button = document.createElement("button");
  button.type = "button";
  button.id = "resumeUploadBtn";
  button.className = "ghost";
  button.textContent = "Resume upload";
  el.append(text, button);
  el.classList.remove("hidden");
}

// Bumped on every call so a slow upload_status response for a file the
// user has since replaced with a different selection can't clobber the
// hint for the file that is actually selected now.
let resumeCheckToken = 0;

// Looks up whether the given file has a matching, still-live partial
// upload on the server and, if so, shows the "Resume upload" hint.
// Any lookup failure (404, network) or a server status that has moved
// past "receiving" quietly drops the stale local record instead of
// bothering the user with it.
async function checkResumableUpload(file) {
  const token = (resumeCheckToken += 1);
  hideResumeHint();
  if (!file) return;
  const record = readUploadRecord(file);
  if (!record) return;
  let upload;
  try {
    upload = await fetchUploadStatus(record.uploadId);
  } catch (_) {
    clearUploadRecord(file);
    return;
  }
  if (token !== resumeCheckToken) return;
  if (!upload || upload.status !== "receiving") {
    clearUploadRecord(file);
    return;
  }
  showResumeHint(file, record.uploadId, upload.received_bytes, upload.file_size);
}

function pauseButtonElement() {
  return $("#pauseUploadBtn");
}

function ensurePauseButton() {
  let button = pauseButtonElement();
  if (button) return button;
  button = document.createElement("button");
  button.type = "button";
  button.id = "pauseUploadBtn";
  button.className = "ghost pause-btn";
  button.addEventListener("click", onPauseResumeClick);
  $("#progressWrap").append(button);
  return button;
}

function setPauseButtonMode(mode) {
  const button = ensurePauseButton();
  button.textContent = mode === "resume" ? "Resume upload" : "Pause";
  button.dataset.mode = mode;
}

function removePauseButton() {
  const button = pauseButtonElement();
  if (button) button.remove();
}

function pauseActiveUpload() {
  if (!state.activeUpload) return;
  state.activeUpload.controller.abort();
}

async function resumeActiveUpload() {
  const paused = state.pausedUpload;
  if (!paused) return;
  state.pausedUpload = null;
  await withUploadButtonDisabled(() =>
    performUpload(paused.file, paused.uploadId, paused.chunkSize, paused.offset));
}

function onPauseResumeClick() {
  const button = pauseButtonElement();
  if (!button) return;
  if (button.dataset.mode === "resume") {
    resumeActiveUpload();
  } else {
    pauseActiveUpload();
  }
}

async function withUploadButtonDisabled(fn) {
  const button = $('button[type="submit"]', $("#uploadForm"));
  button.disabled = true;
  try {
    return await fn();
  } finally {
    button.disabled = false;
  }
}

// Drives the chunk-by-chunk transfer for one upload_id starting at
// startOffset, then hands off to upload_finish + validation polling.
// Throws UploadPausedError (not a real failure) if the user pauses.
async function runChunkedUpload(file, uploadId, chunkSize, startOffset) {
  const controller = new AbortController();
  state.activeUpload = {file, uploadId, chunkSize, controller};
  setPauseButtonMode("pause");
  let offset = startOffset;
  try {
    while (offset < file.size) {
      setProgress(offset, file.size, "Uploading");
      try {
        offset = await uploadChunkWithRetry(uploadId, file, offset, chunkSize, {
          signal: controller.signal,
          onRetry: (attempt, limit) => setProgress(offset, file.size, `Retrying (${attempt}/${limit})…`),
        });
      } catch (err) {
        if (controller.signal.aborted) throw new UploadPausedError(offset);
        throw err;
      }
    }
  } finally {
    state.activeUpload = null;
  }
  removePauseButton();
  setProgress(file.size, file.size, "Validating");
  let outcome = (await api("upload_finish", {upload_id: uploadId})).upload;
  if (VALIDATION_PENDING.includes(outcome.status)) {
    showUploadOutcome(outcome);
    outcome = await awaitValidation(uploadId, (upload) => {
      showUploadOutcome(upload);
    });
  }
  return outcome;
}

// Common tail shared by a fresh upload_start, a hint-triggered resume,
// and an in-place pause -> resume: run the transfer, then reconcile
// localStorage and the UI with however it turned out.
async function performUpload(file, uploadId, chunkSize, startOffset) {
  hideResumeHint();
  let transferComplete = false;
  try {
    let outcome;
    try {
      outcome = await runChunkedUpload(file, uploadId, chunkSize, startOffset);
      transferComplete = true;
    } catch (err) {
      if (err instanceof UploadPausedError) {
        state.pausedUpload = {file, uploadId, chunkSize, offset: err.offset};
        setPauseButtonMode("resume");
        showUploadMessage(
          "Upload paused",
          `${file.name} is paused at ${bytes(err.offset)} of ${bytes(file.size)}. ` +
          "Click Resume upload to continue now, or come back later, reselect the file, " +
          "and Resume from there.",
          "warning",
        );
        setProgress(err.offset, file.size, "Paused");
        return;
      }
      throw err;
    }
    showUploadOutcome(outcome);
    if (isTerminalUploadStatus(outcome.status)) clearUploadRecord(file);
    const accepted = ["validated", "received_manual_review"].includes(outcome.status);
    toast(
      outcome.status === "validated"
        ? "Submission accepted"
        : outcome.status === "received_manual_review"
          ? "Upload received for manual review"
          : "Submission was not accepted",
      accepted ? "ok" : "error",
    );
    await loadUploads();
    activateTab("submissionsTab");
  } catch (err) {
    removePauseButton();
    let reconciled = null;
    try {
      const uploads = await loadUploads();
      reconciled = uploads.find((item) => item.upload_id === uploadId);
    } catch (_) {
      // Keep the original upload error as the most useful message.
    }
    if (reconciled && !["receiving", "validating"].includes(reconciled.status)) {
      showUploadOutcome(reconciled);
      if (isTerminalUploadStatus(reconciled.status)) clearUploadRecord(file);
      activateTab("submissionsTab");
    } else {
      showUploadMessage(
        transferComplete ? "Acceptance not confirmed" : "Upload interrupted",
        transferComplete
          ? `${err.message} The file transfer completed, but the submission was not confirmed as accepted. Check Submissions before retrying.`
          : `${err.message} The submission was not accepted. Progress up to this point is saved — ` +
            `reselect ${file.name} to resume.`,
        transferComplete ? "warning" : "error",
      );
      setProgress(
        transferComplete ? file.size : startOffset,
        file.size,
        transferComplete ? "Status unknown" : "Interrupted",
      );
    }
    toast(err.message, "error");
  }
}

async function resumeUploadFromRecord() {
  const pending = state.resumableUpload;
  if (!pending) return;
  hideResumeHint();
  $("#uploadResult").className = "upload-result hidden";
  const chunkSize = (state.constants && state.constants.chunk_size) || (8 * 1024 * 1024);
  await withUploadButtonDisabled(() =>
    performUpload(pending.file, pending.uploadId, chunkSize, pending.receivedBytes));
}

async function submitUpload(event) {
  event.preventDefault();
  const file = $("#fileInput").files[0];
  if (!file) {
    toast("Select a file first", "error");
    return;
  }
  hideResumeHint();
  $("#uploadResult").className = "upload-result hidden";
  setProgress(0, file.size, "Preparing");
  await withUploadButtonDisabled(async () => {
    try {
      let uploadId;
      let chunkSize = (state.constants && state.constants.chunk_size) || (8 * 1024 * 1024);
      let startOffset = 0;
      try {
        const start = await startUpload(file);
        uploadId = start.upload_id;
        chunkSize = start.chunk_size || chunkSize;
      } catch (err) {
        if (err.details?.code === "resumable") {
          // Not a competing submission - the very same file is already
          // partway uploaded (e.g. from another tab, or localStorage was
          // cleared). Continue it rather than treating this as an error.
          const existing = err.details.existing;
          uploadId = existing.upload_id;
          startOffset = existing.received_bytes || 0;
        } else if (err.details?.code === "duplicate_filename") {
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
          const start = await startUpload(file, existing.upload_id);
          uploadId = start.upload_id;
          chunkSize = start.chunk_size || chunkSize;
        } else {
          throw err;
        }
      }
      writeUploadRecord(file, uploadId);
      if (startOffset === 0 && file.size > BIG_FILE_WARNING_BYTES) {
        showUploadMessage(
          "Large transfer",
          `${bytes(file.size)} to send. This upload can be paused and resumed at any point, ` +
          "so it's fine to interrupt it and come back later.",
          "warning",
        );
      }
      await performUpload(file, uploadId, chunkSize, startOffset);
    } catch (err) {
      showUploadMessage(
        "Upload interrupted",
        `${err.message} The submission was not accepted.`,
        "error",
      );
      setProgress(0, file.size, "Interrupted");
      toast(err.message, "error");
    }
  });
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
  $("#uploadForm").addEventListener("reset", () => {
    // The native reset clears field values *after* this listener runs, so
    // defer to let it finish before re-deriving mode/identity/resume state
    // from the now-empty file input.
    window.setTimeout(() => onFileSelected(null), 0);
  });
  const onFileSelected = (file) => {
    // A pause/resume in progress for a *different* file is stale the
    // moment the user picks something else - drop it rather than let the
    // button silently keep pointing at the old file.
    if (state.pausedUpload && !sameFileIdentity(state.pausedUpload.file, file)) {
      state.pausedUpload = null;
      removePauseButton();
    }
    setUploadMode(file);
    if (file) autoFillFromFile(file);
    checkResumableUpload(file);
  };
  $("#fileInput").addEventListener("change", (event) => {
    onFileSelected(event.currentTarget.files[0]);
  });
  $("#resumeHint").addEventListener("click", (event) => {
    if (event.target.id !== "resumeUploadBtn") return;
    resumeUploadFromRecord();
  });
  const dropzone = $(".dropzone");
  const fileInput = $("#fileInput");
  dropzone.addEventListener("click", (event) => {
    if (event.target === fileInput || event.target.closest("label[for='fileInput']")) return;
    fileInput.click();
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
    onFileSelected(files[0]);
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
  pruneUploadRecords();
  bindEvents();
  try {
    await loadMe();
  } catch (err) {
    toast(err.message, "error");
  }
});

// Exposed only for the Node-based verification script under scratchpad/ -
// this branch never runs in the browser (there is no `module` global
// there), so it has no effect on the portal itself.
// Inert in the browser: a plain <script> has no `module`. This exists so
// tests/js/resumable_upload_test.js can drive the real upload logic against a
// scripted fetch, which is the only way this file gets executed under test.
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    state,
    bytes,
    api,
    fetchUploadStatus,
    isTerminalUploadStatus,
    uploadStorageKey,
    sameFileIdentity,
    readUploadRecord,
    writeUploadRecord,
    clearUploadRecord,
    pruneUploadRecords,
    nextOffsetAfterConflict,
    resumeProgressLabel,
    UploadPausedError,
    startUpload,
    uploadChunk,
    uploadChunkWithRetry,
    checkResumableUpload,
    showResumeHint,
    hideResumeHint,
    resumeUploadFromRecord,
    runChunkedUpload,
    performUpload,
    submitUpload,
    loadUploads,
    activateTab,
    pauseButtonElement,
    ensurePauseButton,
    setPauseButtonMode,
    pauseActiveUpload,
    resumeActiveUpload,
  };
}
