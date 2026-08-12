"use strict";

/* ---------- IndexedDB ---------- */
const DB_NAME = "voiceNotesDB";
const STORE = "recordings";

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function dbAdd(record) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).add(record);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function dbPut(record) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(record);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function dbDelete(id) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function dbClear() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).clear();
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function dbAll() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).getAll();
    req.onsuccess = () => resolve(req.result.sort((a, b) => b.createdAt - a.createdAt));
    req.onerror = () => reject(req.error);
  });
}

/* ---------- Passcode lock ---------- */
async function sha256Hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function getPinHash() { return localStorage.getItem("vn_pin_hash") || ""; }
function isUnlockedThisSession() { return sessionStorage.getItem("vn_unlocked") === "1"; }

/* ---------- Views ---------- */
const views = {
  lock: document.getElementById("view-lock"),
  record: document.getElementById("view-record"),
  history: document.getElementById("view-history"),
  settings: document.getElementById("view-settings"),
};
const tabbar = document.querySelector("nav.tabbar");

function showView(name) {
  Object.entries(views).forEach(([k, el]) => el.classList.toggle("active", k === name));
  tabbar.style.display = name === "lock" ? "none" : "flex";
  tabbar.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  if (name === "history") renderHistory();
  if (name === "settings") loadSettingsUI();
}

tabbar.querySelectorAll("button").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

/* ---------- Lock screen ---------- */
const lockInput = document.getElementById("lockInput");
const lockError = document.getElementById("lockError");

async function tryUnlock() {
  const hash = await sha256Hex(lockInput.value);
  if (hash === getPinHash()) {
    sessionStorage.setItem("vn_unlocked", "1");
    lockInput.value = "";
    lockError.textContent = "";
    afterUnlock();
  } else {
    lockError.textContent = "Incorrect passcode";
    lockInput.value = "";
  }
}
lockInput.addEventListener("input", () => {
  if (lockInput.value.length >= 4) tryUnlock();
});

function afterUnlock() {
  const params = new URLSearchParams(location.search);
  if (params.get("record") === "1") {
    showView("record");
    startRecording();
  } else {
    showView("record");
  }
}

/* ---------- Recording ---------- */
let mediaRecorder = null;
let chunks = [];
let startTime = 0;
let timerInterval = null;
let stream = null;

const recBtn = document.getElementById("recBtn");
const timerEl = document.getElementById("timer");
const recStatus = document.getElementById("recStatus");
const savedMsg = document.getElementById("savedMsg");

function pickMimeType() {
  const candidates = ["audio/mp4", "audio/mp4;codecs=mp4a.40.2", "audio/webm;codecs=opus", "audio/webm"];
  for (const c of candidates) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(c)) return c;
  }
  return "";
}

function formatTime(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

async function startRecording() {
  if (mediaRecorder && mediaRecorder.state === "recording") return;
  savedMsg.textContent = "";
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    recStatus.textContent = "Microphone permission denied";
    return;
  }
  const mimeType = pickMimeType();
  chunks = [];
  mediaRecorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
  mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  mediaRecorder.onstop = onRecordingStop;
  mediaRecorder.start();
  startTime = Date.now();
  timerInterval = setInterval(() => { timerEl.textContent = formatTime(Date.now() - startTime); }, 250);
  recBtn.classList.add("recording");
  recStatus.textContent = "Recording… tap to stop";
}

function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state !== "recording") return;
  mediaRecorder.stop();
  clearInterval(timerInterval);
  if (stream) stream.getTracks().forEach((t) => t.stop());
  recBtn.classList.remove("recording");
  recStatus.textContent = "Tap to start recording";
}

async function onRecordingStop() {
  const duration = Date.now() - startTime;
  const type = mediaRecorder.mimeType || "audio/webm";
  const blob = new Blob(chunks, { type });
  chunks = [];
  timerEl.textContent = "00:00";
  if (blob.size < 1000) { savedMsg.textContent = ""; return; }
  const record = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    createdAt: Date.now(),
    duration,
    mimeType: type,
    blob,
    transcript: "",
    transcriptStatus: "none", // none | pending | done | error
  };
  await dbAdd(record);
  savedMsg.textContent = "Saved";
  setTimeout(() => { savedMsg.textContent = ""; }, 2500);
}

recBtn.addEventListener("click", () => {
  if (mediaRecorder && mediaRecorder.state === "recording") stopRecording();
  else startRecording();
});

/* ---------- History ---------- */
const historyList = document.getElementById("historyList");

function fmtDate(ts) {
  const d = new Date(ts);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function extFor(mimeType) {
  if (mimeType.includes("mp4")) return "m4a";
  if (mimeType.includes("webm")) return "webm";
  return "audio";
}

async function shareOrDownload(blob, filename) {
  const file = new File([blob], filename, { type: blob.type });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try { await navigator.share({ files: [file] }); return; } catch (e) { /* fall through */ }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

async function renderHistory() {
  const items = await dbAll();
  if (items.length === 0) {
    historyList.innerHTML = `<div id="emptyHistory">No recordings yet</div>`;
    return;
  }
  historyList.innerHTML = "";
  for (const item of items) {
    const el = document.createElement("div");
    el.className = "rec-item";
    const url = URL.createObjectURL(item.blob);
    el.innerHTML = `
      <div class="row1">
        <div class="title">${fmtDate(item.createdAt)}</div>
        <div class="meta">${formatTime(item.duration)}</div>
      </div>
      <audio controls src="${url}"></audio>
      <div class="actions">
        <button class="btn-sm" data-act="transcribe">${
          item.transcriptStatus === "done" ? "Re-transcribe" : item.transcriptStatus === "pending" ? "Transcribing…" : "Transcribe"
        }</button>
        <button class="btn-sm" data-act="export">Export audio</button>
        ${item.transcript ? '<button class="btn-sm" data-act="exportTranscript">Export transcript</button>' : ""}
        <button class="btn-sm danger" data-act="delete">Delete</button>
      </div>
      ${item.transcript ? `<div class="transcript-box">${item.transcript}</div>` : ""}
      ${item.transcriptStatus === "error" ? `<div class="transcript-box" style="color:var(--danger)">Transcription failed. Check your API key in Settings.</div>` : ""}
    `;
    el.querySelector('[data-act="delete"]').addEventListener("click", async () => {
      await dbDelete(item.id);
      renderHistory();
    });
    el.querySelector('[data-act="export"]').addEventListener("click", () => {
      shareOrDownload(item.blob, `recording-${item.createdAt}.${extFor(item.mimeType)}`);
    });
    const transcriptBtn = el.querySelector('[data-act="transcribe"]');
    transcriptBtn.addEventListener("click", () => transcribeRecording(item.id));
    const exportTranscriptBtn = el.querySelector('[data-act="exportTranscript"]');
    if (exportTranscriptBtn) {
      exportTranscriptBtn.addEventListener("click", () => {
        const tblob = new Blob([item.transcript], { type: "text/plain" });
        shareOrDownload(tblob, `transcript-${item.createdAt}.txt`);
      });
    }
    historyList.appendChild(el);
  }
}

/* ---------- Transcription ---------- */
async function transcribeRecording(id) {
  const apiKey = localStorage.getItem("vn_openai_key") || "";
  if (!apiKey) {
    alert("Add your OpenAI API key in Settings first.");
    showView("settings");
    return;
  }
  const db = await openDB();
  const item = await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).get(id);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  if (!item) return;
  item.transcriptStatus = "pending";
  await dbPut(item);
  renderHistory();

  try {
    const form = new FormData();
    form.append("file", item.blob, `audio.${extFor(item.mimeType)}`);
    form.append("model", "whisper-1");
    const res = await fetch("https://api.openai.com/v1/audio/transcriptions", {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}` },
      body: form,
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    item.transcript = data.text || "";
    item.transcriptStatus = "done";
  } catch (err) {
    console.error(err);
    item.transcriptStatus = "error";
  }
  await dbPut(item);
  renderHistory();
}

/* ---------- Settings ---------- */
const apiKeyInput = document.getElementById("apiKeyInput");
const pinInput = document.getElementById("pinInput");

function loadSettingsUI() {
  apiKeyInput.value = localStorage.getItem("vn_openai_key") || "";
  pinInput.value = "";
}

document.getElementById("saveKeyBtn").addEventListener("click", () => {
  const val = apiKeyInput.value.trim();
  if (val) localStorage.setItem("vn_openai_key", val);
  else localStorage.removeItem("vn_openai_key");
  apiKeyInput.blur();
});

document.getElementById("savePinBtn").addEventListener("click", async () => {
  const val = pinInput.value.trim();
  if (!val) {
    localStorage.removeItem("vn_pin_hash");
  } else if (val.length < 4) {
    alert("Passcode must be at least 4 digits");
    return;
  } else {
    localStorage.setItem("vn_pin_hash", await sha256Hex(val));
  }
  pinInput.value = "";
  pinInput.blur();
});

document.getElementById("clearAllBtn").addEventListener("click", async () => {
  if (confirm("Delete all recordings and transcripts? This cannot be undone.")) {
    await dbClear();
    renderHistory();
  }
});

/* ---------- Boot ---------- */
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  });
}

(function boot() {
  if (getPinHash() && !isUnlockedThisSession()) {
    showView("lock");
    setTimeout(() => lockInput.focus(), 100);
  } else {
    afterUnlock();
  }
})();
