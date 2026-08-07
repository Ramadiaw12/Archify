"use strict";

document.addEventListener("DOMContentLoaded", function() {

/**
 * app.js — DocSummarizer
 * Gère : Auth (login/register/Google/logout) · Résumé · Historique
 */


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
const resultPlaceholder    = $("empty-state");
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

async function apiSummaryById(id) {
  const res = await fetch("/api/summaries/" + id, { headers: authHeaders() });
  if (!res.ok) return null;
  return res.json();
}

async function loadHistory() {
  if (!historySection || !historyList) return;
  historySection.hidden = false;
  historyList.innerHTML = "<p style='color:var(--text-muted);font-size:13px;'>Chargement...</p>";

  const data = await apiSummaries(1);
  if (!data || !data.items || !data.items.length) {
    historyList.innerHTML = "<p style='color:var(--text-muted);font-size:13px;text-align:center;padding:1rem 0;'>Aucun r\u00e9sum\u00e9 sauvegard\u00e9.<br/>Analysez votre premier document !</p>";
    return;
  }

  var html = "";
  data.items.forEach(function(s) {
    html += "<div class='history-item' data-id='" + esc(s.id) + "'>";
    html += "<div class='history-item-head'>";
    html += "<span class='history-badge'>" + esc(s.file_type) + "</span>";
    html += "<span class='history-date'>" + new Date(s.created_at).toLocaleDateString("fr-FR") + "</span>";
    html += "</div>";
    html += "<div class='history-filename'>\ud83d\udcc4 " + esc(s.filename) + "</div>";
    html += "<div class='history-preview'>" + esc(s.summary) + "</div>";
    html += "<div class='history-cta'>Voir le r\u00e9sum\u00e9 complet \u2192</div>";
    html += "</div>";
  });
  historyList.innerHTML = html;

  historyList.querySelectorAll(".history-item").forEach(function(item) {
    item.addEventListener("click", async function() {
      var id = item.dataset.id;
      if (!id) return;
      historyList.querySelectorAll(".history-item").forEach(function(el) {
        el.classList.remove("history-item--active");
      });
      item.classList.add("history-item--active");
      try {
        var res = await apiSummaryById(id);
        if (!res) throw new Error("Introuvable");
        state.result = res;
        state.activeTab = "summary";
        renderResult(res);
        var col = document.querySelector(".result-column");
        if (col) col.scrollIntoView({ behavior: "smooth", block: "start" });
        showToast("R\u00e9sum\u00e9 charg\u00e9 : " + res.filename, "success", 2500);
      } catch(e) {
        showToast("Impossible de charger ce r\u00e9sum\u00e9", "error", 3000);
      }
    });
  });
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
    clearInterval(_progressInterval);
    setTopProgress(100);
    renderResult(data);
    updateGuide(4);
    showToast("Résumé généré avec succès !", "success", 4000);
    if (data.summary_id) {
      setTimeout(function() { showToast("Résumé sauvegardé dans votre historique 💾", "info", 3000); }, 1200);
    }

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

  if (resultPlaceholder) resultPlaceholder.hidden = true;
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
  if (resultPlaceholder) resultPlaceholder.hidden = false;
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

/* ══════════════════════════════════════════════════════════════
   UX GUIDE — TOASTS — PROGRESS BAR
══════════════════════════════════════════════════════════════ */

function initToasts() {
  if (!document.getElementById("toast-container")) {
    var tc = document.createElement("div");
    tc.className = "toast-container";
    tc.id = "toast-container";
    document.body.appendChild(tc);
  }
}

function showToast(msg, type, duration) {
  type = type || "info";
  duration = duration || 3500;
  var icons = { success: "✅", error: "❌", info: "ℹ️" };
  var tc = document.getElementById("toast-container");
  if (!tc) return;
  var toast = document.createElement("div");
  toast.className = "toast toast-" + type;
  toast.innerHTML =
    '<span class="toast-icon">' + (icons[type] || "ℹ️") + "</span>" +
    '<span class="toast-msg">' + String(msg).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;") + "</span>" +
    '<button class="toast-close" type="button">✕</button>';
  tc.appendChild(toast);
  function remove() {
    toast.classList.add("removing");
    setTimeout(function() { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 300);
  }
  toast.querySelector(".toast-close").addEventListener("click", remove);
  setTimeout(remove, duration);
}

function initTopProgress() {
  if (!document.getElementById("top-progress")) {
    var bar = document.createElement("div");
    bar.className = "top-progress";
    bar.id = "top-progress";
    bar.style.width = "0%";
    document.body.prepend(bar);
  }
}

function setTopProgress(pct) {
  var bar = document.getElementById("top-progress");
  if (!bar) return;
  bar.style.width = pct + "%";
  if (pct >= 100) {
    setTimeout(function() { bar.style.width = "0%"; }, 600);
  }
}

function initGuide() {
  var container = document.querySelector(".container.main-layout");
  var parent = container ? container.parentNode : null;
  if (!parent || document.getElementById("guide-bar")) return;

  var guide = document.createElement("div");
  guide.className = "guide-bar";
  guide.id = "guide-bar";
  guide.innerHTML =
    '<div class="guide-step active" id="gs-1"><div class="guide-step-circle">1</div><div class="guide-step-label">Document</div></div>' +
    '<div class="guide-line" id="gl-1"></div>' +
    '<div class="guide-step" id="gs-2"><div class="guide-step-circle">2</div><div class="guide-step-label">Options</div></div>' +
    '<div class="guide-line" id="gl-2"></div>' +
    '<div class="guide-step" id="gs-3"><div class="guide-step-circle">3</div><div class="guide-step-label">Analyse</div></div>' +
    '<div class="guide-line" id="gl-3"></div>' +
    '<div class="guide-step" id="gs-4"><div class="guide-step-circle">4</div><div class="guide-step-label">Résultat</div></div>';

  var main = document.querySelector(".main-layout");
  if (main) main.parentNode.insertBefore(guide, main);

  // Hint bubble
  var dropzone = document.getElementById("dropzone");
  if (dropzone) {
    var hint = document.createElement("div");
    hint.className = "hint-bubble";
    hint.id = "hint-bubble";
    hint.innerHTML = '<span class="hint-dot"></span>Commencez ici — glissez ou cliquez pour charger votre fichier';
    dropzone.parentNode.insertBefore(hint, dropzone);
  }
}

function updateGuide(step) {
  for (var i = 1; i <= 4; i++) {
    var gs = document.getElementById("gs-" + i);
    var gl = document.getElementById("gl-" + i);
    if (!gs) continue;
    gs.classList.remove("active", "done");
    if (i < step) gs.classList.add("done");
    else if (i === step) gs.classList.add("active");
    if (gl) gl.classList.toggle("done", i < step);
  }
}

/* ── INIT ─────────────────────────────────────────────────── */
initToasts();
initTopProgress();
initGuide();
initAuth();

// Hook: fichier chargé
var _origFileInput = document.getElementById("file-input");
if (_origFileInput) {
  _origFileInput.addEventListener("change", function() {
    setTimeout(function() {
      if (state.file) {
        updateGuide(2);
        var hint = document.getElementById("hint-bubble");
        if (hint) hint.remove();
        showToast("Fichier chargé : " + state.file.name, "success", 3000);
      }
    }, 100);
  });
}

/* ═══════════════════════════════════════════════════════════
   PAGE DOCUMENTS & CHAT
   ═══════════════════════════════════════════════════════════ */

var currentDocId  = null;
var currentChatId = null;

/* ── Navigation ─────────────────────────────────────────── */
function showPage(page) {
  var summarizePage = document.getElementById("page-summarize") || document.querySelector(".hero");
  var docsPage      = document.getElementById("page-documents");
  var mainLayout    = document.querySelector(".main-layout");
  var footer        = document.querySelector(".footer");

  document.querySelectorAll(".nav-tab").forEach(function(t) {
    t.classList.toggle("active", t.dataset.page === page);
  });

  if (page === "documents") {
    if (summarizePage) summarizePage.style.display = "none";
    if (mainLayout)    mainLayout.style.display    = "none";
    if (footer)        footer.style.display        = "none";
    if (docsPage)      docsPage.hidden              = false;
    loadDocumentsList();
  } else {
    if (summarizePage) summarizePage.style.display = "";
    if (mainLayout)    mainLayout.style.display    = "";
    if (footer)        footer.style.display        = "";
    if (docsPage)      docsPage.hidden              = true;
  }
}

document.querySelectorAll(".nav-tab").forEach(function(tab) {
  tab.addEventListener("click", function() { showPage(tab.dataset.page); });
});

/* ── API Documents ──────────────────────────────────────── */
async function apiUploadDocument(file) {
  var form = new FormData();
  form.append("file", file);
  var res = await fetch("/api/documents/upload", {
    method: "POST",
    headers: authHeaders(),
    body: form
  });
  var data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Upload échoué");
  return data;
}

async function apiListDocuments() {
  var res = await fetch("/api/documents?per_page=50", { headers: authHeaders() });
  if (!res.ok) return null;
  return res.json();
}

async function apiDeleteDocument(id) {
  var res = await fetch("/api/documents/" + id, {
    method: "DELETE",
    headers: authHeaders()
  });
  return res.ok;
}

async function apiAskDocument(docId, question, chatId, language) {
  var res = await fetch("/api/documents/" + docId + "/ask", {
    method: "POST",
    headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
    body: JSON.stringify({ question: question, chat_id: chatId || null, language: language || "fr" })
  });
  var data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Erreur");
  return data;
}

/* ── Upload documents ───────────────────────────────────── */
var docsFileInput = document.getElementById("docs-file-input");
if (docsFileInput) {
  docsFileInput.addEventListener("change", async function(e) {
    var files = Array.from(e.target.files);
    if (!files.length) return;

    var progress = document.getElementById("docs-upload-progress");
    var fill     = document.getElementById("dup-fill");
    var msg      = document.getElementById("dup-msg");

    if (progress) progress.hidden = false;

    for (var i = 0; i < files.length; i++) {
      var file = files[i];
      if (fill) fill.style.width = Math.round(((i) / files.length) * 100) + "%";
      if (msg)  msg.textContent  = "Upload : " + file.name;

      try {
        await apiUploadDocument(file);
        showToast("✅ " + file.name + " stocké", "success", 3000);
      } catch(err) {
        showToast("❌ " + file.name + " : " + err.message, "error", 4000);
      }
    }

    if (fill) fill.style.width = "100%";
    if (msg)  msg.textContent  = "Terminé !";
    setTimeout(function() {
      if (progress) progress.hidden = true;
      if (fill) fill.style.width = "0%";
    }, 1500);

    docsFileInput.value = "";
    loadDocumentsList();
  });
}

/* ── Liste documents ────────────────────────────────────── */
async function loadDocumentsList() {
  var list  = document.getElementById("docs-list");
  var empty = document.getElementById("docs-list-empty");
  if (!list) return;

  list.innerHTML = "<div style='padding:1rem;text-align:center;color:var(--text-muted);font-size:13px;'>Chargement...</div>";

  var data = await apiListDocuments();
  if (!data || !data.items || !data.items.length) {
    list.innerHTML = "";
    if (empty) { empty.style.display = "flex"; list.appendChild(empty); }
    return;
  }

  list.innerHTML = "";
  data.items.forEach(function(doc, idx) {
    var item = document.createElement("div");
    item.className = "doc-item";
    item.dataset.id = doc.id;
    item.style.animationDelay = (idx * 0.05) + "s";
    if (doc.id === currentDocId) item.classList.add("active");

    item.innerHTML =
      "<div class='doc-item-head'>" +
        "<span class='doc-item-badge'>" + esc(doc.file_type) + "</span>" +
        "<span class='doc-item-date'>" + new Date(doc.created_at).toLocaleDateString("fr-FR") + "</span>" +
      "</div>" +
      "<div class='doc-item-name'>📄 " + esc(doc.filename) + "</div>" +
      "<div class='doc-item-meta'>" + (doc.word_count || 0).toLocaleString("fr-FR") + " mots · " + (doc.page_count || 1) + " page(s)</div>" +
      "<button class='doc-item-delete' data-id='" + doc.id + "' title='Supprimer' type='button'>🗑</button>";

    // Clic → ouvrir chat
    item.addEventListener("click", function(e) {
      if (e.target.closest(".doc-item-delete")) return;
      openDocumentChat(doc);
    });

    // Supprimer
    item.querySelector(".doc-item-delete").addEventListener("click", async function(e) {
      e.stopPropagation();
      if (!confirm("Supprimer \"" + doc.filename + "\" et tout son historique ?")) return;
      var ok = await apiDeleteDocument(doc.id);
      if (ok) {
        showToast("Document supprimé", "info", 2500);
        if (currentDocId === doc.id) closeDocumentChat();
        loadDocumentsList();
      }
    });

    list.appendChild(item);
  });
}

/* ── Ouvrir un chat sur un document ─────────────────────── */
function openDocumentChat(doc) {
  currentDocId  = doc.id;
  currentChatId = null;

  // Marquer actif dans la liste
  document.querySelectorAll(".doc-item").forEach(function(el) {
    el.classList.toggle("active", el.dataset.id === doc.id);
  });

  // Mettre à jour le header
  var nameEl = document.getElementById("chat-doc-name");
  var metaEl = document.getElementById("chat-doc-meta");
  if (nameEl) nameEl.textContent = doc.filename;
  if (metaEl) metaEl.textContent = (doc.word_count || 0).toLocaleString("fr-FR") + " mots · " + (doc.page_count || 1) + " page(s)";

  // Vider les messages
  var msgs = document.getElementById("chat-messages");
  if (msgs) {
    msgs.innerHTML = "";
    // Message de bienvenue
    appendMessage("assistant", "Bonjour ! Je suis prêt à répondre à vos questions sur **" + doc.filename + "**. Que souhaitez-vous savoir ?");
  }

  // Afficher le chat
  document.getElementById("chat-empty").hidden  = true;
  document.getElementById("chat-active").hidden = false;

  // Focus input
  setTimeout(function() {
    var input = document.getElementById("chat-input");
    if (input) input.focus();
  }, 200);
}

function closeDocumentChat() {
  currentDocId  = null;
  currentChatId = null;
  document.getElementById("chat-empty").hidden  = false;
  document.getElementById("chat-active").hidden = true;
  document.querySelectorAll(".doc-item").forEach(function(el) { el.classList.remove("active"); });
}

var chatClose = document.getElementById("chat-doc-close");
if (chatClose) chatClose.addEventListener("click", closeDocumentChat);

/* ── Messages ───────────────────────────────────────────── */
function appendMessage(role, content) {
  var msgs = document.getElementById("chat-messages");
  if (!msgs) return;

  var div = document.createElement("div");
  div.className = "chat-msg chat-msg--" + role;

  var avatarText = role === "user" ? "R" : "🤖";
  // Formater le contenu (bold, sauts de ligne)
  var formatted = content
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br/>");

  div.innerHTML =
    "<div class='chat-msg-avatar'>" + (role === "user" ? "👤" : "🤖") + "</div>" +
    "<div class='chat-msg-bubble'>" + formatted + "</div>";

  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

function showTyping() {
  var msgs = document.getElementById("chat-messages");
  if (!msgs) return;
  var typing = document.createElement("div");
  typing.className = "chat-msg chat-msg--assistant";
  typing.id = "chat-typing";
  typing.innerHTML =
    "<div class='chat-msg-avatar'>🤖</div>" +
    "<div class='chat-typing'>" +
      "<div class='chat-typing-dot'></div>" +
      "<div class='chat-typing-dot'></div>" +
      "<div class='chat-typing-dot'></div>" +
    "</div>";
  msgs.appendChild(typing);
  msgs.scrollTop = msgs.scrollHeight;
}

function hideTyping() {
  var t = document.getElementById("chat-typing");
  if (t) t.remove();
}

/* ── Envoyer une question ───────────────────────────────── */
async function sendQuestion(question) {
  if (!currentDocId || !question.trim()) return;

  var input   = document.getElementById("chat-input");
  var sendBtn = document.getElementById("chat-send-btn");
  var langSel = document.getElementById("chat-lang-select");
  var lang    = langSel ? langSel.value : "fr";

  // Masquer suggestions après première question
  var suggestions = document.getElementById("chat-suggestions");
  if (suggestions) suggestions.style.display = "none";

  if (input)   input.value   = "";
  if (sendBtn) sendBtn.disabled = true;

  appendMessage("user", question);
  showTyping();

  try {
    var res = await apiAskDocument(currentDocId, question, currentChatId, lang);
    currentChatId = res.chat_id;
    hideTyping();
    appendMessage("assistant", res.answer);
  } catch(err) {
    hideTyping();
    appendMessage("assistant", "Désolé, une erreur s'est produite. Veuillez réessayer.");
    showToast("Erreur : " + err.message, "error", 4000);
  } finally {
    if (sendBtn) sendBtn.disabled = false;
    if (input)   input.focus();
  }
}

/* ── Input & bouton envoyer ─────────────────────────────── */
var chatInput   = document.getElementById("chat-input");
var chatSendBtn = document.getElementById("chat-send-btn");

if (chatInput) {
  chatInput.addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendQuestion(chatInput.value.trim());
    }
  });
}

if (chatSendBtn) {
  chatSendBtn.addEventListener("click", function() {
    var input = document.getElementById("chat-input");
    if (input) sendQuestion(input.value.trim());
  });
}

/* ── Suggestions rapides ────────────────────────────────── */
document.querySelectorAll(".chat-suggestion").forEach(function(btn) {
  btn.addEventListener("click", function() {
    sendQuestion(btn.dataset.q);
  });
});

/*  Afficher nav si connecté  */
var _origRenderUser = renderUser;
renderUser = function(user) {
  _origRenderUser(user);
  var nav = document.getElementById("header-nav");
  if (nav) nav.hidden = false;
};



}); // DOMContentLoaded

/* 
   INLINE CHATBOT — Questions sur le document
    */

var inlineDocId   = null;
var inlineChatId  = null;
var inlineChatEl  = g("inline-chat");
var icMessages    = g("inline-chat-messages");
var icInput       = g("ic-input");
var icSend        = g("ic-send");
var icSuggestions = g("inline-chat-suggestions");

/* Ouvrir le chatbot après génération du résumé */
function openInlineChat(filename, docId) {
  inlineDocId  = docId || null;
  inlineChatId = null;

  var nameEl = g("inline-chat-name");
  if (nameEl) nameEl.textContent = filename || "Document";

  // Vider les messages
  if (icMessages) icMessages.innerHTML = "";

  // Message de bienvenue
  icAppendMessage("assistant",
    "✦ Résumé généré ! Vous pouvez maintenant me poser des questions précises sur ce document. " +
    "Je réponds uniquement à partir de son contenu — sans hallucination."
  );

  // Afficher les suggestions
  if (icSuggestions) icSuggestions.hidden = false;

  // Afficher le chatbot
  if (inlineChatEl) inlineChatEl.hidden = false;
}

/* Ajouter un message */
function icAppendMessage(role, content) {
  if (!icMessages) return;

  var div = document.createElement("div");
  div.className = "ic-msg ic-msg--" + role;

  var avatar = role === "user" ? "👤" : "✦";
  var formatted = content
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n\n/g, "</p><p>")
    .replace(/\n/g, "<br/>");

  div.innerHTML =
    "<div class='ic-avatar'>" + avatar + "</div>" +
    "<div class='ic-bubble'><p>" + formatted + "</p></div>";

  icMessages.appendChild(div);
  icMessages.scrollTop = icMessages.scrollHeight;
}

function icShowTyping() {
  if (!icMessages) return;
  var t = document.createElement("div");
  t.id = "ic-typing";
  t.className = "ic-typing";
  t.innerHTML = "<div class='ic-dot'></div><div class='ic-dot'></div><div class='ic-dot'></div>";
  icMessages.appendChild(t);
  icMessages.scrollTop = icMessages.scrollHeight;
}

function icHideTyping() {
  var t = g("ic-typing");
  if (t) t.remove();
}

/* Envoyer une question */
async function icSendQuestion(question) {
  if (!question.trim()) return;
  if (!inlineDocId) {
    icAppendMessage("assistant", "⚠️ Aucun document stocké. Connectez-vous pour activer les questions.");
    return;
  }

  // Masquer suggestions après première question
  if (icSuggestions) icSuggestions.hidden = true;

  if (icInput)   icInput.value     = "";
  if (icSend)    icSend.disabled   = true;

  icAppendMessage("user", question);
  icShowTyping();

  try {
    var langSel = g("sel-lang");
    var lang = langSel ? langSel.value : "fr";

    var res = await fetch("/api/documents/" + inlineDocId + "/ask", {
      method: "POST",
      headers: Object.assign({"Content-Type": "application/json"}, authHeaders()),
      body: JSON.stringify({
        question: question,
        chat_id:  inlineChatId || null,
        language: lang
      })
    });

    var data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Erreur");

    inlineChatId = data.chat_id;
    icHideTyping();
    icAppendMessage("assistant", data.answer);

  } catch(err) {
    icHideTyping();
    icAppendMessage("assistant",
      "⚠️ Impossible de répondre : " + err.message +
      "\n\nConseil : connectez-vous pour activer les questions sur document."
    );
  } finally {
    if (icSend) icSend.disabled = false;
    if (icInput) icInput.focus();
  }
}

/* Events */
if (icInput) {
  icInput.addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      icSendQuestion(icInput.value.trim());
    }
  });
}

if (icSend) {
  icSend.addEventListener("click", function() {
    if (icInput) icSendQuestion(icInput.value.trim());
  });
}

if (icSuggestions) {
  icSuggestions.querySelectorAll(".ic-suggestion").forEach(function(btn) {
    btn.addEventListener("click", function() {
      icSendQuestion(btn.dataset.q);
    });
  });
}

/* Hook renderResult — activer le chat intégré après génération */
var _baseRenderResult = renderResult;
renderResult = function(data) {
  _baseRenderResult(data);
  if (data && data.filename) {
    var docId = data.doc_id || data.document_id || null;
    inlineDocId  = docId;
    inlineChatId = null;
    // Message de bienvenue dans le chat intégré
    var msgs = g("inline-chat-messages");
    if (msgs) {
      msgs.innerHTML = "";
      icAppendMessage("assistant",
        "Résumé généré ! Posez-moi des questions précises sur **" + data.filename + "**. " +
        "Je réponds uniquement à partir du contenu de ce document."
      );
    }
    var sugg = g("inline-chat-suggestions");
    if (sugg) sugg.hidden = false;
  }
};

/* Dark mode toggle */
var btnTheme = g("btn-theme-toggle");
var isDark   = localStorage.getItem("dark-mode") === "1";
if (isDark) { document.body.classList.add("dark"); if (btnTheme) btnTheme.textContent = "☀️"; }

if (btnTheme) {
  btnTheme.addEventListener("click", function() {
    isDark = !isDark;
    document.body.classList.toggle("dark", isDark);
    btnTheme.textContent = isDark ? "☀️" : "🌙";
    localStorage.setItem("dark-mode", isDark ? "1" : "0");
  });
}