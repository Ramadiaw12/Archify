/**
 * app.js — DocSummarizer
 * Gère : Auth (login/register/Google/logout) · Résumé · Historique
 */

"use strict";

/* ══════════════════════════════════════════════════════════════
   1. ÉTAT GLOBAL
══════════════════════════════════════════════════════════════ */

const state = {
  file:       null,
  processing: false,
  result:     null,
  activeTab:  "summary",
  options: {
    style:      "concis",
    lang:       "fr",
    detail:     3,
    keypoints:  true,
    stats:      true,
    quotes:     false,
    entities:   false,
    conclusion: true,
  },
  // Auth
  user:          null,    // {id, email, full_name, avatar_url, ...}
  access_token:  null,
  refresh_token: null,
};

/* ══════════════════════════════════════════════════════════════
   2. DOM
══════════════════════════════════════════════════════════════ */

const $ = id => document.getElementById(id);

const dropzone      = $("dropzone");
const fileInput     = $("file-input");
const filePreview   = $("file-preview");
const fileCard      = $("file-card");
const selStyle      = $("sel-style");
const selLang       = $("sel-lang");
const rangeDetail   = $("range-detail");
const rangeVal      = $("range-val");
const togglesCt     = $("toggles");
const progressArea  = $("progress-area");
const progressFill  = $("progress-fill");
const progressMsg   = $("progress-msg");
const alertArea     = $("alert-area");
const btnGo         = $("btn-go");
const emptyState    = $("empty-state");
const resultPanel   = $("result-panel");
const resultBadges  = $("result-badges");
const tabBody       = $("tab-body");
const btnCopy       = $("btn-copy");
const headerAuth    = $("header-auth");
const historySection= $("history-section");
const historyList   = $("history-list");
// Modal
const modalOverlay  = $("modal-overlay");
const modalClose    = $("modal-close");
const panelLogin    = $("panel-login");
const panelRegister = $("panel-register");
const loginEmail    = $("login-email");
const loginPassword = $("login-password");
const loginError    = $("login-error");
const btnLogin      = $("btn-login");
const regName       = $("reg-name");
const regEmail      = $("reg-email");
const regPassword   = $("reg-password");
const registerError = $("register-error");
const btnRegister   = $("btn-register");
// Dropdown profil
const profileDropdown = $("profile-dropdown");
const profileAvatar   = $("profile-avatar");
const profileName     = $("profile-name");
const profileEmail    = $("profile-email");

/* ══════════════════════════════════════════════════════════════
   3. AUTH — TOKENS (localStorage)
══════════════════════════════════════════════════════════════ */

function saveTokens(access, refresh) {
  state.access_token  = access;
  state.refresh_token = refresh;
  localStorage.setItem("access_token",  access);
  localStorage.setItem("refresh_token", refresh);
}

function loadTokens() {
  state.access_token  = localStorage.getItem("access_token");
  state.refresh_token = localStorage.getItem("refresh_token");
}

function clearTokens() {
  state.access_token  = null;
  state.refresh_token = null;
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
}

function authHeaders() {
  return state.access_token
    ? { "Authorization": `Bearer ${state.access_token}` }
    : {};
}

/* ══════════════════════════════════════════════════════════════
   4. AUTH — API CALLS
══════════════════════════════════════════════════════════════ */

async function apiLogin(email, password) {
  const res = await fetch("/auth/login", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ email, password }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Connexion échouée");
  return data;
}

async function apiRegister(email, password, full_name) {
  const res = await fetch("/auth/register", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ email, password, full_name }),
  });
  const data = await res.json();
  if (!res.ok) {
    const msg = typeof data.detail === "object"
      ? data.detail.errors?.join(" ") || data.detail.message
      : data.detail;
    throw new Error(msg || "Inscription échouée");
  }
  return data;
}

async function apiMe() {
  const res = await fetch("/auth/me", { headers: authHeaders() });
  if (!res.ok) return null;
  return res.json();
}

async function apiLogout() {
  if (!state.refresh_token) return;
  await fetch("/auth/logout", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ refresh_token: state.refresh_token }),
  });
}

async function apiRefresh() {
  if (!state.refresh_token) return false;
  const res = await fetch("/auth/refresh", {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify({ refresh_token: state.refresh_token }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  saveTokens(data.access_token, data.refresh_token);
  return true;
}

async function apiSummaries(page = 1) {
  const res = await fetch(`/api/summaries?page=${page}&per_page=5`, {
    headers: authHeaders(),
  });
  if (!res.ok) return null;
  return res.json();
}

/* ══════════════════════════════════════════════════════════════
   5. AUTH — ÉTAT UI
══════════════════════════════════════════════════════════════ */

async function initAuth() {
  // Récupérer les tokens depuis l'URL (retour Google OAuth)
  const params = new URLSearchParams(window.location.search);
  const urlAccess  = params.get("access_token");
  const urlRefresh = params.get("refresh_token");
  const authError  = params.get("auth_error");

  if (authError) {
    showAlert(`Connexion Google échouée : ${authError}`);
    window.history.replaceState({}, "", "/");
  }

  if (urlAccess && urlRefresh) {
    saveTokens(urlAccess, urlRefresh);
    // Nettoyer l'URL sans recharger la page
    window.history.replaceState({}, "", "/");
  }

  loadTokens();
  if (!state.access_token) {
    renderHeaderGuest();
    return;
  }
  const user = await apiMe();
  if (user) {
    state.user = user;
    renderHeaderUser(user);
    loadHistory();
  } else {
    // Token expiré → essayer refresh
    const ok = await apiRefresh();
    if (ok) {
      const user2 = await apiMe();
      if (user2) {
        state.user = user2;
        renderHeaderUser(user2);
        loadHistory();
        return;
      }
    }
    clearTokens();
    renderHeaderGuest();
  }
}

function renderHeaderGuest() {
  headerAuth.innerHTML = `
    <button class="btn-auth-outline" id="btn-open-login" type="button">Connexion</button>
    <button class="btn-auth-solid"   id="btn-open-register" type="button">S'inscrire</button>
  `;
  $("btn-open-login").addEventListener("click", () => openModal("login"));
  $("btn-open-register").addEventListener("click", () => openModal("register"));
  historySection.hidden = true;
}

function renderHeaderUser(user) {
  const initials = user.full_name
    ? user.full_name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase()
    : user.email[0].toUpperCase();

  headerAuth.innerHTML = `
    <button class="btn-profile" id="btn-profile" type="button" aria-label="Mon profil">
      ${user.avatar_url
        ? `<img src="${esc(user.avatar_url)}" alt="Avatar" class="avatar-img" />`
        : `<div class="avatar-initials">${esc(initials)}</div>`
      }
      <span class="profile-display-name">${esc(user.full_name || user.email)}</span>
      <span class="chevron">▾</span>
    </button>
  `;

  $("btn-profile").addEventListener("click", toggleProfileDropdown);

  // Remplir le dropdown
  profileName.textContent  = user.full_name || "";
  profileEmail.textContent = user.email;
  profileAvatar.innerHTML  = user.avatar_url
    ? `<img src="${esc(user.avatar_url)}" alt="Avatar" class="avatar-img" />`
    : `<div class="avatar-initials">${esc(initials)}</div>`;
}

function toggleProfileDropdown() {
  const btn  = $("btn-profile");
  const rect = btn.getBoundingClientRect();
  profileDropdown.style.top   = (rect.bottom + 8) + "px";
  profileDropdown.style.right = (window.innerWidth - rect.right) + "px";
  profileDropdown.hidden      = !profileDropdown.hidden;
}

// Fermer le dropdown en cliquant ailleurs
document.addEventListener("click", e => {
  if (!profileDropdown.hidden &&
      !profileDropdown.contains(e.target) &&
      !e.target.closest("#btn-profile")) {
    profileDropdown.hidden = true;
  }
});

// Boutons dropdown
$("btn-history").addEventListener("click", () => {
  profileDropdown.hidden = true;
  historySection.scrollIntoView({ behavior: "smooth" });
});

$("btn-logout").addEventListener("click", async () => {
  profileDropdown.hidden = true;
  await apiLogout();
  clearTokens();
  state.user = null;
  renderHeaderGuest();
  historySection.hidden = true;
  historyList.innerHTML = "";
});

/* ══════════════════════════════════════════════════════════════
   6. MODAL AUTH
══════════════════════════════════════════════════════════════ */

function openModal(tab = "login") {
  switchModalTab(tab);
  modalOverlay.hidden = false;
  document.body.style.overflow = "hidden";
  if (tab === "login") loginEmail.focus();
  else regName.focus();
}

function closeModal() {
  modalOverlay.hidden = true;
  document.body.style.overflow = "";
  loginError.hidden    = true;
  registerError.hidden = true;
}

function switchModalTab(tab) {
  document.querySelectorAll(".modal-tab").forEach(t => {
    t.classList.toggle("active", t.dataset.modalTab === tab);
  });
  panelLogin.hidden    = tab !== "login";
  panelRegister.hidden = tab !== "register";
}

modalClose.addEventListener("click", closeModal);
modalOverlay.addEventListener("click", e => { if (e.target === modalOverlay) closeModal(); });

document.querySelectorAll(".modal-tab").forEach(tab => {
  tab.addEventListener("click", () => switchModalTab(tab.dataset.modalTab));
});

// Connexion
btnLogin.addEventListener("click", async () => {
  const email    = loginEmail.value.trim();
  const password = loginPassword.value;
  if (!email || !password) return showFormError(loginError, "Remplissez tous les champs.");

  btnLogin.disabled     = true;
  btnLogin.textContent  = "Connexion…";
  loginError.hidden     = true;

  try {
    const data = await apiLogin(email, password);
    saveTokens(data.access_token, data.refresh_token);
    const user = await apiMe();
    if (user) {
      state.user = user;
      renderHeaderUser(user);
      loadHistory();
    }
    closeModal();
  } catch (err) {
    showFormError(loginError, err.message);
  } finally {
    btnLogin.disabled    = false;
    btnLogin.textContent = "Se connecter";
  }
});

// Inscription
btnRegister.addEventListener("click", async () => {
  const name     = regName.value.trim();
  const email    = regEmail.value.trim();
  const password = regPassword.value;
  if (!name || !email || !password) return showFormError(registerError, "Remplissez tous les champs.");

  btnRegister.disabled    = true;
  btnRegister.textContent = "Création…";
  registerError.hidden    = true;

  try {
    const data = await apiRegister(email, password, name);
    saveTokens(data.access_token, data.refresh_token);
    const user = await apiMe();
    if (user) {
      state.user = user;
      renderHeaderUser(user);
      loadHistory();
    }
    closeModal();
  } catch (err) {
    showFormError(registerError, err.message);
  } finally {
    btnRegister.disabled    = false;
    btnRegister.textContent = "Créer mon compte";
  }
});

// Enter dans les inputs
loginPassword.addEventListener("keydown", e => { if (e.key === "Enter") btnLogin.click(); });
regPassword.addEventListener("keydown",   e => { if (e.key === "Enter") btnRegister.click(); });

/* ══════════════════════════════════════════════════════════════
   7. HISTORIQUE
══════════════════════════════════════════════════════════════ */

async function loadHistory() {
  historySection.hidden = false;
  historyList.innerHTML = `<p style="color:var(--text-muted);font-size:13px;">Chargement…</p>`;

  const data = await apiSummaries(1);
  if (!data || !data.items.length) {
    historyList.innerHTML = `<p style="color:var(--text-muted);font-size:13px;">Aucun résumé sauvegardé.</p>`;
    return;
  }

  historyList.innerHTML = data.items.map(s => `
    <div class="history-item">
      <div class="history-item-head">
        <span class="history-badge">${esc(s.file_type)}</span>
        <span class="history-date">${new Date(s.created_at).toLocaleDateString("fr-FR")}</span>
      </div>
      <div class="history-filename">${esc(s.filename)}</div>
      <div class="history-preview">${esc(s.summary)}</div>
    </div>
  `).join("");
}

/* ══════════════════════════════════════════════════════════════
   8. UPLOAD FICHIER
══════════════════════════════════════════════════════════════ */

const ALLOWED = [".pdf",".doc",".docx",".txt",".md",".rtf"];

dropzone.addEventListener("dragover", e => { e.preventDefault(); dropzone.classList.add("drag-over"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag-over"));
dropzone.addEventListener("drop", e => {
  e.preventDefault();
  dropzone.classList.remove("drag-over");
  if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", e => { if (e.target.files.length) setFile(e.target.files[0]); });
dropzone.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } });

function setFile(file) {
  const ext = "." + file.name.split(".").pop().toLowerCase();
  if (!ALLOWED.includes(ext)) return showAlert(`Format non supporté : ${ext}`);
  if (file.size > 20 * 1024 * 1024) return showAlert("Fichier trop volumineux (max 20 Mo).");
  clearAlert();
  state.file = file;
  renderFileCard(file);
  updateBtn();
}

function renderFileCard(file) {
  const icons = { PDF:"📄", DOC:"📝", DOCX:"📝", TXT:"📋", MD:"📋", RTF:"📋" };
  const ext   = file.name.split(".").pop().toUpperCase();
  fileCard.innerHTML = `
    <span class="fc-icon">${icons[ext] || "📁"}</span>
    <span class="fc-name" title="${esc(file.name)}">${esc(file.name)}</span>
    <span class="fc-size">${fmtSize(file.size)}</span>
    <button class="fc-remove" type="button" aria-label="Retirer">✕</button>
  `;
  fileCard.querySelector(".fc-remove").addEventListener("click", () => {
    state.file = null;
    fileInput.value = "";
    filePreview.hidden = true;
    updateBtn();
  });
  filePreview.hidden = false;
}

/* ══════════════════════════════════════════════════════════════
   9. OPTIONS
══════════════════════════════════════════════════════════════ */

selStyle.addEventListener("change", () => { state.options.style = selStyle.value; });
selLang.addEventListener("change",  () => { state.options.lang  = selLang.value; });

rangeDetail.addEventListener("input", () => {
  state.options.detail  = parseInt(rangeDetail.value, 10);
  rangeVal.textContent  = `${rangeDetail.value} / 5`;
});

togglesCt.addEventListener("click", e => {
  const btn = e.target.closest(".toggle");
  if (!btn) return;
  btn.classList.toggle("on");
  state.options[btn.dataset.key] = btn.classList.contains("on");
});

/* ══════════════════════════════════════════════════════════════
   10. PIPELINE ANIMATION
══════════════════════════════════════════════════════════════ */

function resetPipeline() { for (let i = 0; i < 6; i++) setPipe(i, null); }

function setPipe(i, s) {
  const el = $(`pipe-${i}`);
  if (!el) return;
  el.classList.remove("active", "done");
  if (s) el.classList.add(s);
}

async function animatePipeline() {
  const steps = [
    { label: "Extraction du texte…",       ms: 700  },
    { label: "Chunking RAG…",              ms: 800  },
    { label: "Génération embeddings…",     ms: 900  },
    { label: "Classification Groq…",       ms: 600  },
    { label: "Routage LangGraph…",         ms: 500  },
    { label: "Génération du résumé…",      ms: 1400 },
  ];
  for (let i = 0; i < steps.length; i++) {
    setPipe(i, "active");
    setProgress(Math.round((i / steps.length) * 88), steps[i].label);
    await sleep(steps[i].ms);
    setPipe(i, "done");
  }
}

/* ══════════════════════════════════════════════════════════════
   11. ANALYSE PRINCIPALE
══════════════════════════════════════════════════════════════ */

btnGo.addEventListener("click", run);

async function run() {
  if (state.processing || !state.file) return;

  state.processing = true;
  clearAlert();
  resetPipeline();
  hideResult();

  btnGo.disabled   = true;
  btnGo.innerHTML  = `<span class="spinner"></span>Traitement en cours…`;
  progressArea.hidden = false;
  setProgress(0, "Initialisation…");

  const anim = animatePipeline();

  try {
    const form = new FormData();
    form.append("file",               state.file);
    form.append("style",              state.options.style);
    form.append("lang",               state.options.lang);
    form.append("detail_level",       String(state.options.detail));
    form.append("include_keypoints",  String(state.options.keypoints));
    form.append("include_stats",      String(state.options.stats));
    form.append("include_quotes",     String(state.options.quotes));
    form.append("include_entities",   String(state.options.entities));
    form.append("include_conclusion", String(state.options.conclusion));

    const headers = authHeaders();   // Ajoute le Bearer token si connecté

    const res = await fetch("/api/summarize", { method: "POST", headers, body: form });

    await anim;

    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: `Erreur HTTP ${res.status}` }));
      throw new Error(body.detail || `Erreur ${res.status}`);
    }

    const data  = await res.json();
    state.result = data;

    setProgress(100, "Résumé généré ✓");
    await sleep(300);

    progressArea.hidden = true;
    renderResult(data);

    // Rafraîchir l'historique si connecté
    if (state.user) loadHistory();

  } catch (err) {
    await anim.catch(() => {});
    resetPipeline();
    progressArea.hidden = true;
    showAlert(err.message);
  } finally {
    state.processing   = false;
    btnGo.disabled     = !state.file;
    btnGo.innerHTML    = "✦ &nbsp;Analyser et générer le résumé";
  }
}

/* ══════════════════════════════════════════════════════════════
   12. RÉSULTATS
══════════════════════════════════════════════════════════════ */

function renderResult(data) {
  const sentClass = { positif: "res-badge-pos", négatif: "res-badge-neg", negatif: "res-badge-neg" }[data.sentiment] || "res-badge-neu";
  const cxClass   = { simple: "res-badge-cx-s", intermédiaire: "res-badge-cx-i", complexe: "res-badge-cx-c" }[data.complexity] || "res-badge-cx-i";

  resultBadges.innerHTML = `
    <span class="res-badge res-badge-type">${esc(data.document_type || "Document")}</span>
    <span class="res-badge ${sentClass}">${esc(data.sentiment || "neutre")}</span>
    <span class="res-badge ${cxClass}">${esc(data.complexity || "intermédiaire")}</span>
    ${data.summary_id ? `<span class="res-badge res-badge-saved">💾 Sauvegardé</span>` : ""}
  `;

  state.activeTab = "summary";
  syncTabs();
  renderTab("summary", data);

  emptyState.hidden  = true;
  resultPanel.hidden = false;
  resultPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function syncTabs() {
  document.querySelectorAll(".tab").forEach(t => {
    t.classList.toggle("active", t.dataset.tab === state.activeTab);
  });
}

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    state.activeTab = tab.dataset.tab;
    syncTabs();
    renderTab(tab.dataset.tab, state.result);
  });
});

function renderTab(tab, data) {
  if (!data) return;
  switch (tab) {
    case "summary":
      tabBody.innerHTML = `<p class="summary-text">${esc(data.summary || "")}</p>`;
      break;
    case "keypoints": {
      const kps = data.key_points || [];
      tabBody.innerHTML = kps.length
        ? `<ul class="kp-list">${kps.map(kp => `<li class="kp-item"><div class="kp-dot"></div><span class="kp-text">${esc(kp)}</span></li>`).join("")}</ul>`
        : `<p style="color:var(--text-muted);font-size:13px;">Aucun point clé extrait.</p>`;
      break;
    }
    case "stats": {
      const s = data.stats || {};
      tabBody.innerHTML = `
        <div class="stats-grid">
          <div class="stat-box"><span class="stat-val">${fmt(s.word_count_original)}</span><div class="stat-lbl">Mots (doc)</div></div>
          <div class="stat-box"><span class="stat-val">${fmt(s.word_count_summary)}</span><div class="stat-lbl">Mots (résumé)</div></div>
          <div class="stat-box"><span class="stat-val">${s.compression_ratio != null ? s.compression_ratio.toFixed(0)+"%" : "N/A"}</span><div class="stat-lbl">Compression</div></div>
          <div class="stat-box"><span class="stat-val">${s.page_count ?? 1}</span><div class="stat-lbl">Page(s)</div></div>
          <div class="stat-box"><span class="stat-val">${(data.key_points||[]).length}</span><div class="stat-lbl">Points clés</div></div>
          <div class="stat-box"><span class="stat-val">${s.read_time_min ?? 1} min</span><div class="stat-lbl">Lecture</div></div>
        </div>
        ${(data.main_topics||[]).length ? `
          <div style="margin-top:1rem;">
            <p style="font-size:10px;font-family:var(--f-mono);text-transform:uppercase;letter-spacing:.5px;color:var(--text-muted);margin-bottom:8px;">Sujets</p>
            <div class="topics-row">${data.main_topics.map(t=>`<span class="topic-chip">${esc(t)}</span>`).join("")}</div>
          </div>` : ""}
      `;
      break;
    }
    case "pipeline": {
      const p = data.pipeline || {};
      const rows = [
        ["Modèle", p.model || "Groq"],
        ["Fournisseur", p.provider || "Groq"],
        ["Route détectée", p.route || "-"],
        ["Langue sortie", p.language || "-"],
        ["Chunks RAG", data.stats?.chunk_count ?? "-"],
        ["Résumé sauvegardé", data.summary_id ? "✅ Oui" : "Non (non connecté)"],
      ];
      tabBody.innerHTML = `<div class="pipe-rows">${rows.map(([l,v])=>`
        <div class="pipe-row">
          <span class="pipe-row-lbl">${esc(l)}</span>
          <span class="pipe-row-val">${esc(String(v))}</span>
        </div>`).join("")}</div>`;
      break;
    }
  }
}

function hideResult() {
  resultPanel.hidden = true;
  emptyState.hidden  = false;
}

btnCopy.addEventListener("click", () => {
  if (!state.result?.summary) return;
  navigator.clipboard.writeText(state.result.summary).then(() => {
    btnCopy.textContent = "✅ Copié !";
    setTimeout(() => { btnCopy.innerHTML = "📋 Copier"; }, 2000);
  });
});

/* ══════════════════════════════════════════════════════════════
   13. UTILITAIRES
══════════════════════════════════════════════════════════════ */

function updateBtn() {
  btnGo.disabled = !state.file || state.processing;
}

function setProgress(pct, msg) {
  progressFill.style.width = `${Math.min(100, pct)}%`;
  progressMsg.textContent  = msg;
}

function showAlert(msg) {
  alertArea.innerHTML = `<div class="alert alert-error">⚠️ &nbsp;${esc(msg)}</div>`;
}

function clearAlert() { alertArea.innerHTML = ""; }

function showFormError(el, msg) {
  el.textContent = msg;
  el.hidden = false;
}

function fmtSize(b) {
  if (b < 1024) return `${b} o`;
  if (b < 1048576) return `${Math.round(b/1024)} Ko`;
  return `${(b/1048576).toFixed(1)} Mo`;
}

function fmt(n) { return n != null ? Number(n).toLocaleString("fr-FR") : "—"; }

function esc(s) {
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

/* ══════════════════════════════════════════════════════════════
   14. INIT
══════════════════════════════════════════════════════════════ */

initAuth();