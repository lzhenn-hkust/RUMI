"use strict";
// Verification-only harness for the browser-side resumable-upload logic
// added to portal/assets/app.js. Run via tests/test_browser_upload.py, or
// directly with: node tests/js/resumable_upload_test.js
//
// Strategy: build a minimal fake DOM (Element tree with querySelector/
// querySelectorAll/classList/append, matching the tiny subset of DOM API
// app.js actually uses), a fake localStorage, and a fake fetch that plays
// the role of api.cgi for the specific sequence under test. Then require
// app.js as CommonJS (it exports its internals via `module.exports` only
// when `module` exists, which is never true in a real browser) and drive
// the real, unmodified functions.

const assert = require("assert");
const path = require("path");

// ---------------------------------------------------------------------
// Minimal fake DOM
// ---------------------------------------------------------------------
class FakeElement {
  constructor(tag) {
    this.tagName = (tag || "div").toUpperCase();
    this.children = [];
    this.parent = null;
    this._classes = new Set();
    this.dataset = {};
    this.style = {};
    this.attrs = {};
    this.id = "";
    this._text = "";
    this._html = "";
    this.listeners = {};
    this.disabled = false;
    this.value = "";
    const self = this;
    this.classList = {
      add(...names) { names.forEach((n) => self._classes.add(n)); },
      remove(...names) { names.forEach((n) => self._classes.delete(n)); },
      toggle(name, force) {
        const has = self._classes.has(name);
        const want = force === undefined ? !has : Boolean(force);
        if (want) self._classes.add(name); else self._classes.delete(name);
        return want;
      },
      contains(name) { return self._classes.has(name); },
    };
  }
  get className() { return Array.from(this._classes).join(" "); }
  set className(value) { this._classes = new Set(String(value).split(/\s+/).filter(Boolean)); }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  append(...nodes) { nodes.forEach((n) => { n.parent = this; this.children.push(n); }); }
  remove() {
    if (this.parent) {
      this.parent.children = this.parent.children.filter((c) => c !== this);
      this.parent = null;
    }
  }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = String(v); this.children = []; }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  querySelector(sel) { return queryFirst(this, sel); }
  querySelectorAll(sel) { return queryAll(this, sel); }
}

function elMatches(el, sel) {
  if (sel.startsWith("#")) return el.id === sel.slice(1);
  if (sel.startsWith(".")) return el._classes.has(sel.slice(1));
  const attrMatch = sel.match(/^([a-zA-Z0-9]+)\[(\w+)="([^"]*)"\]$/);
  if (attrMatch) {
    const [, tag, attr, val] = attrMatch;
    return el.tagName.toLowerCase() === tag.toLowerCase() && el.attrs[attr] === val;
  }
  return el.tagName.toLowerCase() === sel.toLowerCase();
}

function queryFirst(root, sel) {
  for (const child of root.children) {
    if (elMatches(child, sel)) return child;
    const found = queryFirst(child, sel);
    if (found) return found;
  }
  return null;
}

function queryAll(root, sel) {
  const out = [];
  (function walk(node) {
    node.children.forEach((child) => {
      if (elMatches(child, sel)) out.push(child);
      walk(child);
    });
  })(root);
  return out;
}

function makeDocument() {
  const doc = new FakeElement("#document");
  doc.cookie = "rumi_csrf=test-csrf";
  doc.createElement = (tag) => new FakeElement(tag);
  doc.addEventListener = () => {};
  return doc;
}

function makeLocalStorage() {
  const store = new Map();
  return {
    getItem(key) { return store.has(key) ? store.get(key) : null; },
    setItem(key, value) { store.set(key, String(value)); },
    removeItem(key) { store.delete(key); },
    clear() { store.clear(); },
    key(index) { return Array.from(store.keys())[index] ?? null; },
    get length() { return store.size; },
    _dump() { return Object.fromEntries(store); },
  };
}

// ---------------------------------------------------------------------
// Wire up the fake document with the elements app.js actually touches
// during the code paths under test.
// ---------------------------------------------------------------------
const document_ = makeDocument();
const fakeLocalStorage = makeLocalStorage();

function el(tag, id) {
  const e = new FakeElement(tag);
  if (id) e.id = id;
  return e;
}

const resumeHint = el("div", "resumeHint");
resumeHint.classList.add("hidden");
const uploadForm = el("form", "uploadForm");
const submitBtn = el("button");
submitBtn.attrs.type = "submit";
uploadForm.append(submitBtn);
const progressWrap = el("div", "progressWrap");
const progressLabel = el("span", "progressLabel");
const progressPct = el("span", "progressPct");
const progressBar = el("span", "progressBar");
progressWrap.append(progressLabel, progressPct, progressBar);
const uploadResult = el("div", "uploadResult");
const uploadsBody = el("div", "uploadsBody");
const toastEl = el("div", "toast");
toastEl.classList.add("hidden");
const fileInput = el("input", "fileInput");
fileInput.files = [];

document_.append(resumeHint, uploadForm, progressWrap, uploadResult, uploadsBody, toastEl, fileInput);

global.document = document_;
global.window = {
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (id) => clearTimeout(id),
  confirm: () => true,
  localStorage: fakeLocalStorage,
};
global.fetch = async () => { throw new Error("fetch not stubbed for this call"); };

const appPath = path.resolve(__dirname, "..", "..", "portal", "assets", "app.js");
const app = require(appPath);

// ---------------------------------------------------------------------
// Part 1: pure-function unit checks (no DOM/network involved)
// ---------------------------------------------------------------------
function testPureFunctions() {
  console.log("\n=== Pure function checks ===");

  const file = {name: "RUMI-TEST-AN-WRF-EVT1-20200101000000.nc", size: 123456, lastModified: 1700000000000};
  const key = app.uploadStorageKey(file);
  assert.strictEqual(key, `rumi.upload.v1.${file.name}.123456.1700000000000`);
  console.log("uploadStorageKey ->", key, "OK");

  assert.strictEqual(app.sameFileIdentity(file, {...file}), true);
  assert.strictEqual(app.sameFileIdentity(file, {...file, size: 1}), false);
  console.log("sameFileIdentity OK");

  // nextOffsetAfterConflict: only a 409 with a numeric details.expected counts.
  assert.strictEqual(app.nextOffsetAfterConflict(null, 0), null);
  assert.strictEqual(app.nextOffsetAfterConflict({status: 500, details: {expected: 10}}, 0), null);
  assert.strictEqual(app.nextOffsetAfterConflict({status: 409, details: {}}, 0), null);
  assert.strictEqual(app.nextOffsetAfterConflict({status: 409, details: {expected: "10"}}, 0), null);
  assert.strictEqual(app.nextOffsetAfterConflict({status: 409, details: {expected: 8388608}}, 4194304), 8388608);
  console.log("nextOffsetAfterConflict OK");

  assert.strictEqual(app.isTerminalUploadStatus("validated"), true);
  assert.strictEqual(app.isTerminalUploadStatus("rejected"), true);
  assert.strictEqual(app.isTerminalUploadStatus("duplicate"), true);
  assert.strictEqual(app.isTerminalUploadStatus("server_error"), true);
  assert.strictEqual(app.isTerminalUploadStatus("received_manual_review"), true);
  assert.strictEqual(app.isTerminalUploadStatus("receiving"), false);
  assert.strictEqual(app.isTerminalUploadStatus("validating"), false);
  assert.strictEqual(app.isTerminalUploadStatus("queued"), false);
  console.log("isTerminalUploadStatus OK");

  assert.strictEqual(app.resumeProgressLabel(3_000_000_000, 7_000_000_000), "Resume upload — 43% already transferred (2.8 GB of 6.5 GB)");
  console.log("resumeProgressLabel ->", app.resumeProgressLabel(3_000_000_000, 7_000_000_000), "OK");

  // write/read/clear round trip against the fake localStorage directly.
  const storage = makeLocalStorage();
  assert.strictEqual(app.readUploadRecord(file, storage), null);
  app.writeUploadRecord(file, "up-xyz", storage);
  const record = app.readUploadRecord(file, storage);
  assert.strictEqual(record.uploadId, "up-xyz");
  assert.strictEqual(typeof record.createdAt, "number");
  app.clearUploadRecord(file, storage);
  assert.strictEqual(app.readUploadRecord(file, storage), null);
  console.log("readUploadRecord/writeUploadRecord/clearUploadRecord round trip OK");

  // pruneUploadRecords: keeps fresh entries, drops entries older than 7 days,
  // drops corrupt entries, and ignores unrelated keys.
  const pruneStorage = makeLocalStorage();
  const now = Date.now();
  pruneStorage.setItem("rumi.upload.v1.fresh.1.1", JSON.stringify({uploadId: "a", createdAt: now - 1000}));
  pruneStorage.setItem("rumi.upload.v1.stale.1.1", JSON.stringify({uploadId: "b", createdAt: now - 8 * 24 * 60 * 60 * 1000}));
  pruneStorage.setItem("rumi.upload.v1.corrupt.1.1", "{not json");
  pruneStorage.setItem("unrelated.key", "keep me");
  const removed = app.pruneUploadRecords(now, pruneStorage);
  assert.strictEqual(removed, 2);
  assert.notStrictEqual(pruneStorage.getItem("rumi.upload.v1.fresh.1.1"), null);
  assert.strictEqual(pruneStorage.getItem("rumi.upload.v1.stale.1.1"), null);
  assert.strictEqual(pruneStorage.getItem("rumi.upload.v1.corrupt.1.1"), null);
  assert.strictEqual(pruneStorage.getItem("unrelated.key"), "keep me");
  console.log("pruneUploadRecords OK (removed", removed, "of 3 rumi.* entries, left unrelated key alone)");
}

// ---------------------------------------------------------------------
// Part 2: end-to-end resumable-upload flow through the real DOM-driving
// functions (checkResumableUpload -> resumeUploadFromRecord ->
// performUpload -> runChunkedUpload -> uploadChunkWithRetry), backed by
// a scripted fake fetch.
//
// This proves, by actually executing the code (not by inspection):
//   1. Selecting a file with a matching localStorage record triggers an
//      upload_status lookup.
//   2. When the server reports received_bytes = N, the transfer resumes
//      from N, not from 0.
//   3. An upload_chunk 409 with `expected` is treated as a self-heal, not
//      a failure: the offset is corrected and the transfer proceeds.
//   4. Reaching a terminal status (here: validated) removes the
//      localStorage record.
// ---------------------------------------------------------------------
async function testEndToEndResumeFlow() {
  console.log("\n=== End-to-end resumable upload flow ===");

  const TEST_FILE = {
    name: "RUMI-TEST-AN-WRF-EVT1-20200101000000.nc",
    size: 7_000_000_000,
    lastModified: 1_700_000_000_000,
    slice(start, end) {
      const clampedEnd = Math.min(end, this.size);
      return {byteLength: Math.max(0, clampedEnd - start)};
    },
  };

  // Fresh fake localStorage + a pre-seeded record simulating "the user
  // started this upload earlier, then the tab was closed/crashed".
  const storage = makeLocalStorage();
  app.writeUploadRecord(TEST_FILE, "up1", storage);
  global.window.localStorage = storage;

  app.state.constants = {chunk_size: 2_000_000_000};

  const fetchCalls = [];
  let chunkAttempt = 0;
  let offsetConflictInjected = false;

  global.fetch = async (url, init = {}) => {
    fetchCalls.push({url, method: init.method, bodyLen: init.body && typeof init.body.byteLength === "number" ? init.body.byteLength : null});
    const [, qs] = url.split("?");
    const params = new URLSearchParams(qs || "");
    const action = params.get("action");
    const respond = (status, body) => ({ok: status >= 200 && status < 300, status, json: async () => body});

    if (action === "upload_status") {
      assert.strictEqual(params.get("upload_id"), "up1");
      return respond(200, {
        ok: true,
        upload: {status: "receiving", received_bytes: 3_000_000_000, file_size: 7_000_000_000, file_name: TEST_FILE.name},
      });
    }
    if (action === "upload_chunk") {
      chunkAttempt += 1;
      const offset = Number(params.get("offset"));
      const chunkLen = init.body.byteLength;
      // Simulate a "server already has more than the client thinks"
      // conflict on the very first chunk write attempt: the server
      // secretly already has 3.5e9 bytes (as if an earlier response was
      // lost after the write succeeded).
      if (offset === 3_000_000_000 && !offsetConflictInjected) {
        offsetConflictInjected = true;
        return respond(409, {
          ok: false,
          error: "Chunk offset does not match server state.",
          details: {expected: 3_500_000_000},
        });
      }
      const received = offset + chunkLen;
      return respond(200, {ok: true, received_bytes: received, file_size: TEST_FILE.size});
    }
    if (action === "upload_finish") {
      return respond(200, {
        ok: true,
        upload: {
          upload_id: "up1", file_name: TEST_FILE.name, file_size: TEST_FILE.size,
          file_kind: "netcdf", status: "validated", validation: {errors: [], warnings: [], summary: {}},
        },
      });
    }
    if (action === "uploads") {
      return respond(200, {ok: true, uploads: []});
    }
    throw new Error("Unhandled mock fetch action: " + action);
  };

  // --- Point 1: selecting the file hits localStorage and calls upload_status ---
  await app.checkResumableUpload(TEST_FILE);
  const statusCalls = fetchCalls.filter((c) => c.url.includes("action=upload_status"));
  assert.strictEqual(statusCalls.length, 1, "expected exactly one upload_status call after selecting the file");
  assert.strictEqual(resumeHint.classList.contains("hidden"), false, "resume hint should be visible");
  assert.ok(app.state.resumableUpload, "state.resumableUpload should be populated");
  assert.strictEqual(app.state.resumableUpload.receivedBytes, 3_000_000_000);
  console.log("[1] File selection -> localStorage hit -> upload_status called:", statusCalls.length, "call(s). PASS");

  // --- Point 2 & 3: resuming starts at N (not 0), and a 409+expected mid-transfer is self-healed ---
  await app.resumeUploadFromRecord();

  const chunkCalls = fetchCalls.filter((c) => c.url.includes("action=upload_chunk"));
  const firstChunkOffset = Number(new URLSearchParams(chunkCalls[0].url.split("?")[1]).get("offset"));
  assert.strictEqual(firstChunkOffset, 3_000_000_000, "first chunk request must start at the server's received_bytes, not 0");
  console.log("[2] First upload_chunk offset =", firstChunkOffset, "(server-reported received_bytes). PASS");

  const offsets = chunkCalls.map((c) => Number(new URLSearchParams(c.url.split("?")[1]).get("offset")));
  assert.deepStrictEqual(offsets, [3_000_000_000, 3_500_000_000, 5_500_000_000],
    "expected: initial offset, 409-corrected retry at `expected`, then the next chunk from there");
  console.log("[3] Chunk offsets across retry:", offsets, "-> 409+expected was corrected and retried, not thrown as a failure. PASS");

  // --- Point 4: terminal status (validated) clears the localStorage record ---
  const stillThere = storage.getItem(app.uploadStorageKey(TEST_FILE));
  assert.strictEqual(stillThere, null, "localStorage record should be removed once the upload reaches a terminal status");
  console.log("[4] localStorage record after terminal status 'validated':", stillThere, "(removed). PASS");

  assert.ok(uploadResult.innerHTML.includes("accepted") || uploadResult.className.includes("success"),
    "upload result panel should reflect acceptance");
  console.log("Final #uploadResult class:", uploadResult.className);

  console.log("\nAll fetch calls in order:");
  fetchCalls.forEach((c, i) => console.log(`  ${i + 1}. ${c.method || "GET"} ${c.url}`));
}

// ---------------------------------------------------------------------
// Part 3: a 404/network failure on upload_status silently drops the
// stale localStorage record instead of showing the resume hint.
// ---------------------------------------------------------------------
async function testResumeStatusLookupFailureClearsRecord() {
  console.log("\n=== upload_status failure clears stale record silently ===");
  const file = {name: "RUMI-GONE.nc", size: 1000, lastModified: 42};
  const storage = makeLocalStorage();
  app.writeUploadRecord(file, "up-missing", storage);
  global.window.localStorage = storage;

  global.fetch = async (url) => {
    if (url.includes("action=upload_status")) {
      return {ok: false, status: 404, json: async () => ({ok: false, error: "Upload not found."})};
    }
    throw new Error("unexpected fetch: " + url);
  };

  await app.checkResumableUpload(file);
  assert.strictEqual(resumeHint.classList.contains("hidden"), true, "hint must stay hidden on lookup failure");
  assert.strictEqual(storage.getItem(app.uploadStorageKey(file)), null, "stale record must be cleared");
  console.log("404 on upload_status -> hint hidden, record cleared. PASS");
}

// ---------------------------------------------------------------------
// Part 4: a completed server-side upload (status no longer "receiving")
// also clears the local record and does not show the hint.
// ---------------------------------------------------------------------
async function testResumeHintHiddenWhenNoLongerReceiving() {
  console.log("\n=== Non-'receiving' server status clears the hint/record ===");
  const file = {name: "RUMI-DONE.nc", size: 2000, lastModified: 99};
  const storage = makeLocalStorage();
  app.writeUploadRecord(file, "up-done", storage);
  global.window.localStorage = storage;

  global.fetch = async (url) => {
    if (url.includes("action=upload_status")) {
      return {ok: true, status: 200, json: async () => ({ok: true, upload: {status: "validating", received_bytes: 2000, file_size: 2000}})};
    }
    throw new Error("unexpected fetch: " + url);
  };

  await app.checkResumableUpload(file);
  assert.strictEqual(resumeHint.classList.contains("hidden"), true);
  assert.strictEqual(storage.getItem(app.uploadStorageKey(file)), null);
  console.log("status='validating' -> hint hidden, record cleared. PASS");
}

// ---------------------------------------------------------------------
// Part 5: Pause mid-transfer (item D). Uses a real AbortController; the
// mock fetch races a delayed "success" response against the abort
// signal, exactly like a real in-flight fetch would.
// ---------------------------------------------------------------------
function makeAbortError() {
  return new DOMException("The operation was aborted.", "AbortError");
}

function fetchThatRespectsAbort(init, responder, delayMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => resolve(responder()), delayMs);
    if (init.signal) {
      if (init.signal.aborted) {
        clearTimeout(timer);
        reject(makeAbortError());
        return;
      }
      init.signal.addEventListener("abort", () => {
        clearTimeout(timer);
        reject(makeAbortError());
      });
    }
  });
}

async function testPauseThenResumeInPlace() {
  console.log("\n=== Pause mid-transfer, then Resume in place ===");
  const FILE = {
    name: "RUMI-PAUSE-AN-WRF-EVT1-20200101000000.nc",
    size: 300,
    lastModified: 5,
    slice(start, end) { return {byteLength: Math.max(0, Math.min(end, this.size) - start)}; },
  };
  const storage = makeLocalStorage();
  global.window.localStorage = storage;

  let chunkCallLog = [];
  global.fetch = async (url, init = {}) => {
    const [, qs] = url.split("?");
    const params = new URLSearchParams(qs || "");
    const action = params.get("action");
    const respond = (status, body) => ({ok: status >= 200 && status < 300, status, json: async () => body});
    if (action === "upload_chunk") {
      const offset = Number(params.get("offset"));
      chunkCallLog.push(offset);
      // First chunk write is deliberately slow so the test can pause
      // while it is in flight, mirroring a real network round trip.
      const delay = offset === 0 ? 30 : 0;
      return fetchThatRespectsAbort(init, () => respond(200, {ok: true, received_bytes: offset + init.body.byteLength, file_size: FILE.size}), delay);
    }
    if (action === "upload_finish") {
      return respond(200, {ok: true, upload: {upload_id: "up-pause", file_name: FILE.name, file_size: FILE.size, file_kind: "netcdf", status: "validated", validation: {errors: [], warnings: [], summary: {}}}});
    }
    if (action === "uploads") return respond(200, {ok: true, uploads: []});
    throw new Error("unexpected action " + action);
  };

  app.writeUploadRecord(FILE, "up-pause", storage);
  const runPromise = app.performUpload(FILE, "up-pause", 100, 0);

  // Give the first chunk request time to start, then pause mid-flight.
  await new Promise((resolve) => setTimeout(resolve, 5));
  const pauseBtn = app.pauseButtonElement();
  assert.ok(pauseBtn, "pause button should exist while a transfer is active");
  assert.strictEqual(pauseBtn.dataset.mode, "pause");
  app.pauseActiveUpload();
  await runPromise;

  assert.ok(app.state.pausedUpload, "state.pausedUpload should be set after pausing");
  assert.strictEqual(app.state.pausedUpload.offset, 0, "paused before the first chunk completed, so offset stays at 0");
  assert.strictEqual(pauseBtn.dataset.mode, "resume", "button flips to Resume upload in place");
  assert.notStrictEqual(storage.getItem(app.uploadStorageKey(FILE)), null, "pausing must NOT delete the localStorage record");
  console.log("Pause mid-flight -> paused at offset", app.state.pausedUpload.offset, "record kept, button now shows 'Resume upload'. PASS");

  // Resume in place: should replay from offset 0 (nothing had actually
  // landed) through to completion.
  await app.resumeActiveUpload();
  assert.strictEqual(storage.getItem(app.uploadStorageKey(FILE)), null, "terminal status after resuming should clear the record");
  assert.strictEqual(app.pauseButtonElement(), null, "pause/resume button should be removed once the upload finishes");
  console.log("Resume in place -> completed, record cleared, pause button removed. Chunk offsets seen:", chunkCallLog, "PASS");
}

// ---------------------------------------------------------------------
// Part 6: generic transient failures (not the 409/expected case) are
// retried with backoff, up to 3 attempts, before succeeding (item C).
// ---------------------------------------------------------------------
async function testGenericRetrySucceedsWithinBudget() {
  console.log("\n=== Generic chunk failure retried with backoff, then succeeds ===");
  const FILE = {
    name: "RUMI-RETRY-AN-WRF-EVT1-20200101000000.nc",
    size: 50,
    lastModified: 7,
    slice(start, end) { return {byteLength: Math.max(0, Math.min(end, this.size) - start)}; },
  };

  // Speed up the 1s/3s/9s backoff for the test; app.js calls the bare
  // `sleep()` helper, which resolves via window.setTimeout.
  const realSetTimeout = global.window.setTimeout;
  global.window.setTimeout = (fn) => { fn(); return 0; };

  let attempts = 0;
  const retryLog = [];
  global.fetch = async (url, init = {}) => {
    attempts += 1;
    const [, qs] = url.split("?");
    const params = new URLSearchParams(qs || "");
    if (params.get("action") !== "upload_chunk") throw new Error("unexpected action");
    if (attempts < 3) {
      // Simulate a transient server hiccup unrelated to offset tracking.
      return {ok: false, status: 500, json: async () => ({ok: false, error: "Temporary server error"})};
    }
    const offset = Number(params.get("offset"));
    return {ok: true, status: 200, json: async () => ({ok: true, received_bytes: offset + init.body.byteLength, file_size: FILE.size})};
  };

  const received = await app.uploadChunkWithRetry("up-retry", FILE, 0, 50, {
    onRetry: (attempt, limit) => retryLog.push([attempt, limit]),
  });

  global.window.setTimeout = realSetTimeout;

  assert.strictEqual(attempts, 3, "should fail twice then succeed on the 3rd attempt");
  assert.deepStrictEqual(retryLog, [[1, 3], [2, 3]], "onRetry should fire before attempts 2 and 3, reporting (attempt/limit)");
  assert.strictEqual(received, 50, "final received_bytes should reflect the successful attempt");
  console.log("3 attempts total (2 failures + 1 success), onRetry log:", retryLog, "PASS");
}

(async () => {
  try {
    testPureFunctions();
    await testEndToEndResumeFlow();
    await testResumeStatusLookupFailureClearsRecord();
    await testResumeHintHiddenWhenNoLongerReceiving();
    await testPauseThenResumeInPlace();
    await testGenericRetrySucceedsWithinBudget();
    console.log("\nALL CHECKS PASSED");
    process.exit(0);
  } catch (err) {
    console.error("\nFAILED:", err);
    process.exit(1);
  }
})();
