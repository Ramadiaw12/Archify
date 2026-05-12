"use strict";

document.addEventListener("DOMContentLoaded", function() {

/* ── ETAT ─────────────────────────────────────────────────── */
var state = {
  file: null, processing: false, result: null, activeTab: "summary",
  options: { style:"concis", lang:"fr", detail:3, keypoints:true, stats:true, quotes:false, entities:false, conclusion:true },
  user: null, access_token: null, refresh_token: null
};

/* ── DOM ──────────────────────────────────────────────────── */
function g(id) { return document.getElementById(id); }

var dropzone      = g("dropzone");
var fileInput     = g("file-input");
var filePreview   = g("file-preview");
var fileCard      = g("file-card");
var selStyle      = g("sel-style");
var selLang       = g("sel-lang");
var rangeDetail   = g("range-detail");
var rangeVal      = g("range-val");
var togglesCt     = g("toggles");
var progressArea  = g("progress-area");
var progressFill  = g("progress-fill");
var progressMsg   = g("progress-msg");
var alertArea     = g("alert-area");
var btnGo         = g("btn-go");
var emptyState    = g("empty-state");
var resultPanel   = g("result-panel");
var resultBadges  = g("result-badges");
var tabBody       = g("tab-body");
var btnCopy       = g("btn-copy");
var headerAuth    = g("header-auth");
var historySection= g("history-section");
var historyList   = g("history-list");
var modalOverlay  = g("modal-overlay");
var modalClose    = g("modal-close");
var panelLogin    = g("panel-login");
var panelRegister = g("panel-register");
var loginEmail    = g("login-email");
var loginPassword = g("login-password");
var loginError    = g("login-error");
var btnLogin      = g("btn-login");
var regName       = g("reg-name");
var regEmail      = g("reg-email");
var regPassword   = g("reg-password");
var registerError = g("register-error");
var btnRegister   = g("btn-register");
var profileDropdown = g("profile-dropdown");
var profileAvatar   = g("profile-avatar");
var profileName     = g("profile-name");
var profileEmail    = g("profile-email");

/* ── TOKENS ───────────────────────────────────────────────── */
function saveTokens(a, r) {
  state.access_token = a;
  state.refresh_token = r;
  localStorage.setItem("access_token", a);
  localStorage.setItem("refresh_token", r);
}
function loadTokens() {
  state.access_token  = localStorage.getItem("access_token");
  state.refresh_token = localStorage.getItem("refresh_token");
}
function clearTokens() {
  state.access_token = null;
  state.refresh_token = null;
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
}
function authHeaders() {
  if (state.access_token) return { "Authorization": "Bearer " + state.access_token };
  return {};
}

/* ── API ──────────────────────────────────────────────────── */
async function apiLogin(email, password) {
  var res = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email, password: password })
  });
  var data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Connexion echouee");
  return data;
}

async function apiRegister(email, password, full_name) {
  var res = await fetch("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email, password: password, full_name: full_name })
  });
  var data = await res.json();
  if (!res.ok) {
    var msg = typeof data.detail === "object" ? (data.detail.message || "Erreur") : (data.detail || "Erreur");
    throw new Error(msg);
  }
  return data;
}

async function apiMe() {
  var res = await fetch("/auth/me", { headers: authHeaders() });
  if (!res.ok) return null;
  return res.json();
}

async function apiLogout() {
  if (!state.refresh_token) return;
  await fetch("/auth/logout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: state.refresh_token })
  });
}

async function apiRefresh() {
  if (!state.refresh_token) return false;
  var res = await fetch("/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: state.refresh_token })
  });
  if (!res.ok) return false;
  var data = await res.json();
  saveTokens(data.access_token, data.refresh_token);
  return true;
}

async function apiSummaries() {
  var res = await fetch("/api/summaries?page=1&per_page=5", { headers: authHeaders() });
  if (!res.ok) return null;
  return res.json();
}

/* ── AUTH UI ──────────────────────────────────────────────── */
async function initAuth() {
  var params     = new URLSearchParams(window.location.search);
  var urlAccess  = params.get("access_token");
  var urlRefresh = params.get("refresh_token");
  var authError  = params.get("auth_error");

  if (authError) {
    showAlert("Connexion Google echouee : " + authError);
    window.history.replaceState({}, "", "/");
  }
  if (urlAccess && urlRefresh) {
    saveTokens(urlAccess, urlRefresh);
    window.history.replaceState({}, "", "/");
  }

  loadTokens();

  if (!state.access_token) {
    renderGuest();
    return;
  }

  var user = await apiMe();
  if (user) {
    state.user = user;
    renderUser(user);
    loadHistory();
  } else {
    var ok = await apiRefresh();
    if (ok) {
      var u2 = await apiMe();
      if (u2) { state.user = u2; renderUser(u2); loadHistory(); return; }
    }
    clearTokens();
    renderGuest();
  }
}

function renderGuest() {
  headerAuth.innerHTML =
    '<button class="btn-auth-outline" id="btn-open-login" type="button">Connexion</button>' +
    '<button class="btn-auth-solid" id="btn-open-register" type="button">S\'inscrire</button>';
  g("btn-open-login").addEventListener("click", function() { openModal("login"); });
  g("btn-open-register").addEventListener("click", function() { openModal("register"); });
  if (historySection) historySection.hidden = true;
}

function renderUser(user) {
  var initials = user.full_name
    ? user.full_name.split(" ").map(function(w) { return w[0]; }).join("").slice(0,2).toUpperCase()
    : user.email[0].toUpperCase();
  var avatar = user.avatar_url
    ? '<img src="' + esc(user.avatar_url) + '" class="avatar-img" alt=""/>'
    : '<div class="avatar-initials">' + esc(initials) + '</div>';
  headerAuth.innerHTML =
    '<button class="btn-profile" id="btn-profile" type="button">' +
    avatar +
    '<span class="profile-display-name">' + esc(user.full_name || user.email) + '</span>' +
    '<span class="chevron">&#9662;</span>' +
    '</button>';
  g("btn-profile").addEventListener("click", toggleDropdown);
  if (profileName)  profileName.textContent  = user.full_name || "";
  if (profileEmail) profileEmail.textContent = user.email;
  if (profileAvatar) profileAvatar.innerHTML = avatar;
}

function toggleDropdown() {
  var btn  = g("btn-profile");
  var rect = btn.getBoundingClientRect();
  profileDropdown.style.top   = (rect.bottom + 8) + "px";
  profileDropdown.style.right = (window.innerWidth - rect.right) + "px";
  profileDropdown.hidden = !profileDropdown.hidden;
}

document.addEventListener("click", function(e) {
  if (profileDropdown && !profileDropdown.hidden &&
      !profileDropdown.contains(e.target) &&
      !e.target.closest("#btn-profile")) {
    profileDropdown.hidden = true;
  }
});

g("btn-history").addEventListener("click", function() {
  profileDropdown.hidden = true;
  if (historySection) historySection.scrollIntoView({ behavior: "smooth" });
});

g("btn-logout").addEventListener("click", async function() {
  profileDropdown.hidden = true;
  await apiLogout();
  clearTokens();
  state.user = null;
  renderGuest();
  if (historySection) historySection.hidden = true;
  if (historyList) historyList.innerHTML = "";
});

/* ── MODAL ────────────────────────────────────────────────── */
function openModal(tab) {
  tab = tab || "login";
  switchTab(tab);
  modalOverlay.hidden = false;
  document.body.style.overflow = "hidden";
  if (tab === "login" && loginEmail) loginEmail.focus();
  else if (regName) regName.focus();
}

function closeModal() {
  modalOverlay.hidden = true;
  document.body.style.overflow = "";
  if (loginError)    loginError.hidden    = true;
  if (registerError) registerError.hidden = true;
}

function switchTab(tab) {
  document.querySelectorAll(".modal-tab").forEach(function(t) {
    t.classList.toggle("active", t.dataset.modalTab === tab);
  });
  panelLogin.hidden    = (tab !== "login");
  panelRegister.hidden = (tab !== "register");
}

modalClose.addEventListener("click", closeModal);
modalOverlay.addEventListener("click", function(e) {
  if (e.target === modalOverlay) closeModal();
});
document.querySelectorAll(".modal-tab").forEach(function(t) {
  t.addEventListener("click", function() { switchTab(t.dataset.modalTab); });
});

btnLogin.addEventListener("click", async function() {
  var email    = loginEmail.value.trim();
  var password = loginPassword.value;
  if (!email || !password) { showFormError(loginError, "Remplissez tous les champs."); return; }
  btnLogin.disabled    = true;
  btnLogin.textContent = "Connexion...";
  loginError.hidden    = true;
  try {
    var data = await apiLogin(email, password);
    saveTokens(data.access_token, data.refresh_token);
    var user = await apiMe();
    if (user) { state.user = user; renderUser(user); loadHistory(); }
    closeModal();
  } catch(err) {
    showFormError(loginError, err.message);
  } finally {
    btnLogin.disabled    = false;
    btnLogin.textContent = "Se connecter";
  }
});

btnRegister.addEventListener("click", async function() {
  var name     = regName.value.trim();
  var email    = regEmail.value.trim();
  var password = regPassword.value;
  if (!name || !email || !password) { showFormError(registerError, "Remplissez tous les champs."); return; }
  btnRegister.disabled    = true;
  btnRegister.textContent = "Creation...";
  registerError.hidden    = true;
  try {
    var data = await apiRegister(email, password, name);
    saveTokens(data.access_token, data.refresh_token);
    var user = await apiMe();
    if (user) { state.user = user; renderUser(user); loadHistory(); }
    closeModal();
  } catch(err) {
    showFormError(registerError, err.message);
  } finally {
    btnRegister.disabled    = false;
    btnRegister.textContent = "Creer mon compte";
  }
});

loginPassword.addEventListener("keydown", function(e) { if (e.key === "Enter") btnLogin.click(); });
regPassword.addEventListener("keydown",   function(e) { if (e.key === "Enter") btnRegister.click(); });

/* ── HISTORIQUE ───────────────────────────────────────────── */
async function loadHistory() {
  if (!historySection || !historyList) return;
  historySection.hidden = false;
  historyList.innerHTML = '<p style="color:var(--text-muted);font-size:13px;">Chargement...</p>';
  var data = await apiSummaries();
  if (!data || !data.items || !data.items.length) {
    historyList.innerHTML = '<p style="color:var(--text-muted);font-size:13px;">Aucun resume sauvegarde.</p>';
    return;
  }
  historyList.innerHTML = data.items.map(function(s) {
    return '<div class="history-item">' +
      '<div class="history-item-head">' +
      '<span class="history-badge">' + esc(s.file_type) + '</span>' +
      '<span class="history-date">' + new Date(s.created_at).toLocaleDateString("fr-FR") + '</span>' +
      '</div>' +
      '<div class="history-filename">' + esc(s.filename) + '</div>' +
      '<div class="history-preview">' + esc(s.summary) + '</div>' +
      '</div>';
  }).join("");
}

/* ── UPLOAD ───────────────────────────────────────────────── */
var ALLOWED = [".pdf",".doc",".docx",".txt",".md",".rtf"];

dropzone.addEventListener("dragover",  function(e) { e.preventDefault(); dropzone.classList.add("drag-over"); });
dropzone.addEventListener("dragleave", function()  { dropzone.classList.remove("drag-over"); });
dropzone.addEventListener("drop", function(e) {
  e.preventDefault(); dropzone.classList.remove("drag-over");
  if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", function(e) { if (e.target.files.length) setFile(e.target.files[0]); });
dropzone.addEventListener("keydown", function(e) {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
});

function setFile(file) {
  var ext = "." + file.name.split(".").pop().toLowerCase();
  if (ALLOWED.indexOf(ext) === -1) { showAlert("Format non supporte : " + ext); return; }
  if (file.size > 20 * 1024 * 1024) { showAlert("Fichier trop volumineux (max 20 Mo)."); return; }
  clearAlert();
  state.file = file;
  renderFileCard(file);
  updateBtn();
}

function renderFileCard(file) {
  var icons = { PDF:"document", DOC:"document", DOCX:"document", TXT:"document", MD:"document", RTF:"document" };
  var ext = file.name.split(".").pop().toUpperCase();
  fileCard.innerHTML =
    '<span class="fc-icon">&#128196;</span>' +
    '<span class="fc-name" title="' + esc(file.name) + '">' + esc(file.name) + '</span>' +
    '<span class="fc-size">' + fmtSize(file.size) + '</span>' +
    '<button class="fc-remove" type="button">&#x2715;</button>';
  fileCard.querySelector(".fc-remove").addEventListener("click", function() {
    state.file = null;
    fileInput.value = "";
    filePreview.hidden = true;
    updateBtn();
  });
  filePreview.hidden = false;
}

/* ── OPTIONS ──────────────────────────────────────────────── */
selStyle.addEventListener("change",  function() { state.options.style  = selStyle.value; });
selLang.addEventListener("change",   function() { state.options.lang   = selLang.value; });
rangeDetail.addEventListener("input",function() {
  state.options.detail = parseInt(rangeDetail.value, 10);
  rangeVal.textContent = rangeDetail.value + " / 5";
});
togglesCt.addEventListener("click", function(e) {
  var btn = e.target.closest(".toggle");
  if (!btn) return;
  btn.classList.toggle("on");
  state.options[btn.dataset.key] = btn.classList.contains("on");
});

/* ── PIPELINE ─────────────────────────────────────────────── */
function resetPipeline() { for (var i = 0; i < 6; i++) setPipe(i, null); }
function setPipe(i, s) {
  var el = g("pipe-" + i);
  if (!el) return;
  el.classList.remove("active", "done");
  if (s) el.classList.add(s);
}
async function animatePipeline() {
  var steps = [
    { label:"Extraction...",    ms:700  },
    { label:"Chunking RAG...",  ms:800  },
    { label:"Embeddings...",    ms:900  },
    { label:"Groq classify...", ms:600  },
    { label:"LangGraph...",     ms:500  },
    { label:"Generation...",    ms:1400 }
  ];
  for (var i = 0; i < steps.length; i++) {
    setPipe(i, "active");
    setProgress(Math.round((i / steps.length) * 88), steps[i].label);
    await sleep(steps[i].ms);
    setPipe(i, "done");
  }
}

/* ── ANALYSE ──────────────────────────────────────────────── */
btnGo.addEventListener("click", run);

async function run() {
  if (state.processing || !state.file) return;
  state.processing = true;
  clearAlert(); resetPipeline(); hideResult();
  btnGo.disabled  = true;
  btnGo.innerHTML = '<span class="spinner"></span>Traitement...';
  progressArea.hidden = false;
  setProgress(0, "Initialisation...");
  var anim = animatePipeline();
  try {
    var form = new FormData();
    form.append("file",               state.file);
    form.append("style",              state.options.style);
    form.append("lang",               state.options.lang);
    form.append("detail_level",       String(state.options.detail));
    form.append("include_keypoints",  String(state.options.keypoints));
    form.append("include_stats",      String(state.options.stats));
    form.append("include_quotes",     String(state.options.quotes));
    form.append("include_entities",   String(state.options.entities));
    form.append("include_conclusion", String(state.options.conclusion));
    var res = await fetch("/api/summarize", { method:"POST", headers:authHeaders(), body:form });
    await anim;
    if (!res.ok) {
      var b = await res.json().catch(function() { return { detail: "Erreur " + res.status }; });
      throw new Error(b.detail || "Erreur " + res.status);
    }
    var data = await res.json();
    state.result = data;
    setProgress(100, "Resume genere !"); await sleep(300);
    progressArea.hidden = true;
    renderResult(data);
    if (state.user) loadHistory();
  } catch(err) {
    await anim.catch(function(){});
    resetPipeline();
    progressArea.hidden = true;
    showAlert(err.message);
  } finally {
    state.processing = false;
    btnGo.disabled   = !state.file;
    btnGo.innerHTML  = "&#10022; &nbsp;Analyser et generer le resume";
  }
}

/* ── RESULTATS ────────────────────────────────────────────── */
function renderResult(data) {
  var sc = {positif:"res-badge-pos", negatif:"res-badge-neg"}[data.sentiment] || "res-badge-neu";
  var cc = {simple:"res-badge-cx-s", intermediaire:"res-badge-cx-i", complexe:"res-badge-cx-c"}[data.complexity] || "res-badge-cx-i";
  resultBadges.innerHTML =
    '<span class="res-badge res-badge-type">' + esc(data.document_type || "Document") + '</span>' +
    '<span class="res-badge ' + sc + '">' + esc(data.sentiment || "neutre") + '</span>' +
    '<span class="res-badge ' + cc + '">' + esc(data.complexity || "") + '</span>' +
    (data.summary_id ? '<span class="res-badge res-badge-saved">&#128190; Sauvegarde</span>' : "");
  state.activeTab = "summary";
  syncTabs();
  renderTab("summary", data);
  emptyState.hidden  = true;
  resultPanel.hidden = false;
  resultPanel.scrollIntoView({ behavior:"smooth", block:"nearest" });
}

function syncTabs() {
  document.querySelectorAll(".tab").forEach(function(t) {
    t.classList.toggle("active", t.dataset.tab === state.activeTab);
  });
}

document.querySelectorAll(".tab").forEach(function(tab) {
  tab.addEventListener("click", function() {
    state.activeTab = tab.dataset.tab;
    syncTabs();
    renderTab(tab.dataset.tab, state.result);
  });
});

function renderTab(tab, data) {
  if (!data) return;
  if (tab === "summary") {
    tabBody.innerHTML = '<p class="summary-text">' + esc(data.summary || "") + '</p>';
    return;
  }
  if (tab === "keypoints") {
    var kps = data.key_points || [];
    tabBody.innerHTML = kps.length
      ? '<ul class="kp-list">' + kps.map(function(kp) {
          return '<li class="kp-item"><div class="kp-dot"></div><span class="kp-text">' + esc(kp) + '</span></li>';
        }).join("") + '</ul>'
      : '<p style="color:var(--text-muted);font-size:13px;">Aucun point cle.</p>';
    return;
  }
  if (tab === "stats") {
    var s = data.stats || {};
    tabBody.innerHTML =
      '<div class="stats-grid">' +
      '<div class="stat-box"><span class="stat-val">' + fmt(s.word_count_original) + '</span><div class="stat-lbl">Mots (doc)</div></div>' +
      '<div class="stat-box"><span class="stat-val">' + fmt(s.word_count_summary)  + '</span><div class="stat-lbl">Mots (resume)</div></div>' +
      '<div class="stat-box"><span class="stat-val">' + (s.compression_ratio != null ? s.compression_ratio.toFixed(0) + "%" : "N/A") + '</span><div class="stat-lbl">Compression</div></div>' +
      '<div class="stat-box"><span class="stat-val">' + (s.page_count || 1) + '</span><div class="stat-lbl">Page(s)</div></div>' +
      '<div class="stat-box"><span class="stat-val">' + (data.key_points || []).length + '</span><div class="stat-lbl">Points cles</div></div>' +
      '<div class="stat-box"><span class="stat-val">' + (s.read_time_min || 1) + ' min</span><div class="stat-lbl">Lecture</div></div>' +
      '</div>';
    return;
  }
  if (tab === "pipeline") {
    var p = data.pipeline || {};
    var rows = [
      ["Modele", p.model || "Groq"],
      ["Route",  p.route || "-"],
      ["Langue", p.language || "-"],
      ["Sauvegarde", data.summary_id ? "Oui" : "Non"]
    ];
    tabBody.innerHTML = '<div class="pipe-rows">' + rows.map(function(r) {
      return '<div class="pipe-row"><span class="pipe-row-lbl">' + esc(r[0]) + '</span><span class="pipe-row-val">' + esc(String(r[1])) + '</span></div>';
    }).join("") + '</div>';
  }
}

function hideResult() { resultPanel.hidden = true; emptyState.hidden = false; }

btnCopy.addEventListener("click", function() {
  if (!state.result || !state.result.summary) return;
  navigator.clipboard.writeText(state.result.summary).then(function() {
    btnCopy.textContent = "Copie !";
    setTimeout(function() { btnCopy.innerHTML = "&#128203; Copier"; }, 2000);
  });
});

/* ── UTILITAIRES ──────────────────────────────────────────── */
function updateBtn() { btnGo.disabled = !state.file || state.processing; }
function setProgress(pct, msg) { progressFill.style.width = Math.min(100, pct) + "%"; progressMsg.textContent = msg; }
function showAlert(msg) { alertArea.innerHTML = '<div class="alert alert-error">&#9888; &nbsp;' + esc(msg) + '</div>'; }
function clearAlert() { alertArea.innerHTML = ""; }
function showFormError(el, msg) { el.textContent = msg; el.hidden = false; }
function fmtSize(b) { if (b < 1024) return b + " o"; if (b < 1048576) return Math.round(b/1024) + " Ko"; return (b/1048576).toFixed(1) + " Mo"; }
function fmt(n) { return n != null ? Number(n).toLocaleString("fr-FR") : "--"; }
function esc(s) { return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;"); }
function sleep(ms) { return new Promise(function(r) { setTimeout(r, ms); }); }

/* ── INIT ─────────────────────────────────────────────────── */
initAuth();

}); // DOMContentLoaded