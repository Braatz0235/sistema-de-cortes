"use strict";

const API = "/api";

const STATUS_LABELS = {
  queued: "Na fila...",
  extracting_audio: "Extraindo áudio...",
  transcribing: "Transcrevendo a fala...",
  analyzing: "Identificando os melhores momentos...",
  ready: "Pronto!",
  failed: "Falhou",
};

const EXPORT_STATUS_LABELS = {
  queued: "na fila",
  processing: "gerando...",
  done: "pronto",
  failed: "erro",
};

let platforms = [];
let currentVideoId = null;
let statusPollTimer = null;
const exportPollTimers = new Map();

const el = (id) => document.getElementById(id);

function showOnly(sectionId) {
  ["upload-section", "status-section", "error-section", "clips-section"].forEach((id) => {
    el(id).classList.toggle("hidden", id !== sectionId);
  });
}

function fmtTime(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = `Erro ${res.status}`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch (_) { /* ignore */ }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

async function loadPlatforms() {
  platforms = await fetchJSON(`${API}/platforms`);
}

/* ---------------- Upload ---------------- */

function initUpload() {
  const dropzone = el("dropzone");
  const input = el("file-input");

  dropzone.addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    if (input.files && input.files[0]) uploadFile(input.files[0]);
  });

  ["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("drag-over");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("drag-over");
    })
  );
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });

  el("retry-button").addEventListener("click", resetToUpload);
  el("new-video-button").addEventListener("click", resetToUpload);
}

function resetToUpload() {
  stopStatusPoll();
  exportPollTimers.forEach((timer) => clearInterval(timer));
  exportPollTimers.clear();
  currentVideoId = null;
  el("file-input").value = "";
  el("upload-progress").classList.add("hidden");
  el("upload-progress-fill").style.width = "0%";
  showOnly("upload-section");
}

function uploadFile(file) {
  const progressRow = el("upload-progress");
  const fill = el("upload-progress-fill");
  const label = el("upload-progress-label");
  progressRow.classList.remove("hidden");
  fill.style.width = "0%";
  label.textContent = "Enviando...";

  const formData = new FormData();
  formData.append("file", file);

  const xhr = new XMLHttpRequest();
  xhr.open("POST", `${API}/videos`);
  xhr.upload.addEventListener("progress", (e) => {
    if (e.lengthComputable) {
      const pct = Math.round((e.loaded / e.total) * 100);
      fill.style.width = `${pct}%`;
      label.textContent = pct < 100 ? `Enviando... ${pct}%` : "Processando envio...";
    }
  });
  xhr.onload = () => {
    if (xhr.status === 201) {
      const data = JSON.parse(xhr.responseText);
      currentVideoId = data.id;
      showOnly("status-section");
      startStatusPoll(currentVideoId);
    } else {
      let message = `Erro ${xhr.status} ao enviar o vídeo.`;
      try {
        const body = JSON.parse(xhr.responseText);
        if (body.detail) message = body.detail;
      } catch (_) { /* ignore */ }
      showError(message);
    }
  };
  xhr.onerror = () => showError("Falha de rede ao enviar o vídeo.");
  xhr.send(formData);
}

function showError(message) {
  stopStatusPoll();
  el("error-message").textContent = message;
  showOnly("error-section");
}

/* ---------------- Status polling ---------------- */

function startStatusPoll(videoId) {
  stopStatusPoll();
  pollStatusOnce(videoId);
  statusPollTimer = setInterval(() => pollStatusOnce(videoId), 2500);
}

function stopStatusPoll() {
  if (statusPollTimer) {
    clearInterval(statusPollTimer);
    statusPollTimer = null;
  }
}

async function pollStatusOnce(videoId) {
  let job;
  try {
    job = await fetchJSON(`${API}/videos/${videoId}`);
  } catch (err) {
    showError(err.message);
    return;
  }

  if (job.status === "ready") {
    stopStatusPoll();
    renderClips(job);
    showOnly("clips-section");
    return;
  }
  if (job.status === "failed") {
    showError(job.error || "Não foi possível processar o vídeo.");
    return;
  }

  el("status-label").textContent = STATUS_LABELS[job.status] || job.status;
}

/* ---------------- Clips ---------------- */

function platformChip(clipId, platform) {
  const label = document.createElement("label");
  label.className = "platform-chip";
  label.innerHTML = `
    <input type="checkbox" value="${platform.id}" />
    <span>${platform.icon} ${platform.label}</span>
    <span class="platform-note">${platform.note}</span>
  `;
  const checkbox = label.querySelector("input");
  checkbox.addEventListener("change", () => {
    label.classList.toggle("selected", checkbox.checked);
  });
  return label;
}

function renderClips(job) {
  const list = el("clips-list");
  list.innerHTML = "";

  if (!job.clips || job.clips.length === 0) {
    list.innerHTML = `<p class="hint">Nenhum corte relevante foi encontrado neste vídeo.</p>`;
    return;
  }

  job.clips.forEach((clip) => list.appendChild(renderClipCard(job, clip)));
}

function renderClipCard(job, clip) {
  const card = document.createElement("div");
  card.className = "clip-card";
  card.dataset.clipId = clip.id;

  const hashtags = (clip.hashtags || [])
    .map((h) => `<span class="hashtag">${h}</span>`)
    .join("");

  card.innerHTML = `
    <div class="clip-top">
      <div>
        <p class="clip-title">${clip.title}</p>
        <p class="clip-meta">${fmtTime(clip.start)} – ${fmtTime(clip.end)} · ${clip.duration}s</p>
      </div>
      <div class="clip-score">
        <span class="score-badge">🔥 ${Math.round(clip.score)}</span>
      </div>
    </div>
    <p class="clip-summary">${clip.summary || ""}</p>
    <div class="hashtags">${hashtags}</div>
    <div class="clip-actions">
      <button class="preview-btn" type="button">▶ Prévia do corte</button>
    </div>
    <div class="platform-grid"></div>
    <div class="clip-footer">
      <label class="captions-toggle">
        <input type="checkbox" class="captions-checkbox" checked />
        Legendas queimadas no vídeo
      </label>
      <button class="btn generate-btn" type="button">Gerar cortes selecionados</button>
    </div>
    <div class="exports-list"></div>
  `;

  const grid = card.querySelector(".platform-grid");
  platforms.forEach((p) => grid.appendChild(platformChip(clip.id, p)));

  card.querySelector(".preview-btn").addEventListener("click", () => openPreview(job, clip));
  card.querySelector(".generate-btn").addEventListener("click", () => generateExports(job, clip, card));

  return card;
}

/* ---------------- Preview ---------------- */

function openPreview(job, clip) {
  const modal = el("preview-modal");
  const video = el("preview-video");
  el("preview-caption").textContent = clip.title;

  const onLoaded = () => {
    video.currentTime = clip.start;
    video.play().catch(() => {});
    video.removeEventListener("loadedmetadata", onLoaded);
  };
  video.addEventListener("loadedmetadata", onLoaded);

  const onTimeUpdate = () => {
    if (video.currentTime >= clip.end) {
      video.pause();
    }
  };
  video.removeEventListener("timeupdate", video._cutHandler || (() => {}));
  video._cutHandler = onTimeUpdate;
  video.addEventListener("timeupdate", onTimeUpdate);

  video.src = `${API}/videos/${job.id}/source`;
  modal.classList.remove("hidden");
}

function closePreview() {
  const modal = el("preview-modal");
  const video = el("preview-video");
  video.pause();
  video.removeAttribute("src");
  video.load();
  modal.classList.add("hidden");
}

function initPreviewModal() {
  el("preview-close").addEventListener("click", closePreview);
  el("preview-backdrop").addEventListener("click", closePreview);
}

/* ---------------- Exports ---------------- */

async function generateExports(job, clip, card) {
  const selected = Array.from(card.querySelectorAll(".platform-grid input:checked")).map((i) => i.value);
  if (selected.length === 0) {
    alert("Selecione ao menos uma plataforma/formato para gerar o corte.");
    return;
  }
  const captions = card.querySelector(".captions-checkbox").checked;
  const exportsList = card.querySelector(".exports-list");
  const generateBtn = card.querySelector(".generate-btn");
  generateBtn.disabled = true;

  try {
    await Promise.all(
      selected.map(async (platformId) => {
        const platform = platforms.find((p) => p.id === platformId);
        try {
          const exp = await fetchJSON(`${API}/videos/${job.id}/clips/${clip.id}/exports`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ platform: platformId, captions }),
          });
          const row = renderExportRow(exportsList, platform, exp);
          pollExport(job.id, exp.id, row);
        } catch (err) {
          const row = renderExportRow(exportsList, platform, { status: "failed", error: err.message });
        }
      })
    );
  } finally {
    generateBtn.disabled = false;
  }
}

function renderExportRow(container, platform, exp) {
  let row = container.querySelector(`[data-export-id="${exp.id}"]`);
  if (!row) {
    row = document.createElement("div");
    row.className = "export-row";
    if (exp.id) row.dataset.exportId = exp.id;
    container.prepend(row);
  }
  const label = platform ? `${platform.icon} ${platform.label}` : "Corte";
  const status = exp.status || "queued";
  const statusText = EXPORT_STATUS_LABELS[status] || status;

  let extra = "";
  if (status === "done") {
    extra = `<a class="download-link" href="${API}/videos/${currentVideoId}/exports/${exp.id}/download">⬇ Baixar</a>`;
  } else if (status === "failed") {
    extra = `<span class="hint" title="${exp.error || ""}">falhou</span>`;
  }

  row.innerHTML = `
    <span>${label}</span>
    <span class="export-status ${status}">${statusText}</span>
    ${extra}
  `;
  return row;
}

function pollExport(videoId, exportId, row) {
  const existing = exportPollTimers.get(exportId);
  if (existing) clearInterval(existing);

  const timer = setInterval(async () => {
    let exp;
    try {
      exp = await fetchJSON(`${API}/videos/${videoId}/exports/${exportId}`);
    } catch (err) {
      clearInterval(timer);
      exportPollTimers.delete(exportId);
      return;
    }
    const platform = platforms.find((p) => p.id === exp.platform);
    renderExportRow(row.parentElement, platform, exp);
    if (exp.status === "done" || exp.status === "failed") {
      clearInterval(timer);
      exportPollTimers.delete(exportId);
    }
  }, 2000);
  exportPollTimers.set(exportId, timer);
}

/* ---------------- Init ---------------- */

async function init() {
  initUpload();
  initPreviewModal();
  try {
    await loadPlatforms();
  } catch (err) {
    console.error("Falha ao carregar plataformas", err);
  }
}

init();
