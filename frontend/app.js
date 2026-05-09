/**
 * app.js — DocSummarizer
 *
 * Modules :
 *  1. État global
 *  2. Gestion du fichier (drag & drop, validation)
 *  3. Contrôles d'options (select, range, toggles)
 *  4. Animation du pipeline NLP
 *  5. Appel API + gestion des erreurs
 *  6. Rendu des résultats (4 onglets)
 *  7. Utilitaires
 */

"use strict";

/* ══════════════════════════════════════════════════════════════
   1. ÉTAT GLOBAL
   ══════════════════════════════════════════════════════════════ */

const state = {
  file:         null,   // File object sélectionné
  processing:   false,
  result:       null,   // Dernière réponse de l'API
  activeTab:    "summary",
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
};

/* Raccourcis DOM */
const $ = id => document.getElementById(id);

const dropzone    = $("dropzone");
const fileInput   = $("file-input");
const filePreview = $("file-preview");
const fileCard    = $("file-card");
const selStyle    = $("sel-style");
const selLang     = $("sel-lang");
const rangeDetail = $("range-detail");
const rangeVal    = $("range-val");
const togglesCt   = $("toggles");
const progressArea= $("progress-area");
const progressFill= $("progress-fill");
const progressMsg = $("progress-msg");
const alertArea   = $("alert-area");
const btnGo       = $("btn-go");
const emptyState  = $("empty-state");
const resultPanel = $("result-panel");
const resultBadges= $("result-badges");
const tabBody     = $("tab-body");
const btnCopy     = $("btn-copy");

/* ══════════════════════════════════════════════════════════════
   2. GESTION DU FICHIER
   ══════════════════════════════════════════════════════════════ */

const ALLOWED = [".pdf",".doc",".docx",".txt",".md",".rtf"];
const MAX_MB  = 20;

/* Drag & drop */
dropzone.addEventListener("dragover", e => {
  e.preventDefault();
  dropzone.classList.add("drag-over");
});

dropzone.addEventListener("dragleave", () => {
  dropzone.classList.remove("drag-over");
});

dropzone.addEventListener("drop", e => {
  e.preventDefault();
  dropzone.classList.remove("drag-over");
  const files = [...e.dataTransfer.files];
  if (files.length) setFile(files[0]);
});

fileInput.addEventListener("change", e => {
  if (e.target.files.length) setFile(e.target.files[0]);
});

/* Accessibilité clavier */
dropzone.addEventListener("keydown", e => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fileInput.click();
  }
});

/**
 * Valide et enregistre le fichier.
 * @param {File} file
 */
function setFile(file) {
  const ext = "." + file.name.split(".").pop().toLowerCase();

  if (!ALLOWED.includes(ext)) {
    showAlert(`Format non supporté (${ext}). Acceptés : ${ALLOWED.join(", ")}`);
    return;
  }
  if (file.size > MAX_MB * 1024 * 1024) {
    showAlert(`Fichier trop volumineux. Maximum : ${MAX_MB} Mo.`);
    return;
  }

  clearAlert();
  state.file = file;
  renderFileCard(file);
  updateBtn();
}

/** Affiche la carte du fichier sélectionné. */
function renderFileCard(file) {
  const ext  = file.name.split(".").pop().toUpperCase();
  const icons = { PDF:"📄", DOC:"📝", DOCX:"📝", TXT:"📋", MD:"📋", RTF:"📋" };
  const icon  = icons[ext] || "📁";

  fileCard.innerHTML = `
    <span class="fc-icon">${icon}</span>
    <span class="fc-name" title="${esc(file.name)}">${esc(file.name)}</span>
    <span class="fc-size">${fmtSize(file.size)}</span>
    <button class="fc-remove" type="button" aria-label="Retirer le fichier">✕</button>
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
   3. CONTRÔLES D'OPTIONS
   ══════════════════════════════════════════════════════════════ */

selStyle.addEventListener("change", () => { state.options.style = selStyle.value; });
selLang.addEventListener("change",  () => { state.options.lang  = selLang.value;  });

rangeDetail.addEventListener("input", () => {
  const v = parseInt(rangeDetail.value, 10);
  state.options.detail = v;
  rangeVal.textContent = `${v} / 5`;
  rangeDetail.setAttribute("aria-valuenow", v);
});

togglesCt.addEventListener("click", e => {
  const btn = e.target.closest(".toggle");
  if (!btn) return;
  btn.classList.toggle("on");
  state.options[btn.dataset.key] = btn.classList.contains("on");
});

/* ══════════════════════════════════════════════════════════════
   4. PIPELINE — ANIMATION
   ══════════════════════════════════════════════════════════════ */

/**
 * Remet tous les steps du pipeline à l'état initial.
 */
function resetPipeline() {
  for (let i = 0; i < 6; i++) setPipe(i, null);
}

/**
 * Met à jour l'état visuel d'un step.
 * @param {number} i
 * @param {"active"|"done"|null} status
 */
function setPipe(i, status) {
  const el = $(`pipe-${i}`);
  if (!el) return;
  el.classList.remove("active", "done");
  if (status) el.classList.add(status);
}

/**
 * Lance l'animation des 6 étapes pendant le traitement.
 * Chaque step reste "active" pendant `ms` ms puis passe en "done".
 * @returns {Promise<void>}
 */
async function animatePipeline() {
  const steps = [
    { label: "Extraction du texte…",         ms: 700  },
    { label: "Chunking RAG…",                ms: 800  },
    { label: "Génération des embeddings…",   ms: 900  },
    { label: "Classification Groq…",         ms: 600  },
    { label: "Routage LangGraph…",           ms: 500  },
    { label: "Génération Claude LLM…",       ms: 1300 },
  ];

  for (let i = 0; i < steps.length; i++) {
    setPipe(i, "active");
    setProgress(Math.round((i / steps.length) * 88), steps[i].label);
    await sleep(steps[i].ms);
    setPipe(i, "done");
  }
}

/* ══════════════════════════════════════════════════════════════
   5. APPEL API
   ══════════════════════════════════════════════════════════════ */

btnGo.addEventListener("click", run);

async function run() {
  if (state.processing || !state.file) return;

  state.processing = true;
  clearAlert();
  resetPipeline();
  hideResult();

  /* UI — chargement */
  btnGo.disabled = true;
  btnGo.setAttribute("aria-disabled", "true");
  btnGo.innerHTML = `<span class="spinner" aria-hidden="true"></span>Traitement en cours…`;
  progressArea.hidden = false;
  setProgress(0, "Initialisation…");

  /* Lancer l'animation en parallèle */
  const anim = animatePipeline();

  try {
    /* Construire le FormData */
    const form = new FormData();
    form.append("file",                state.file);
    form.append("style",               state.options.style);
    form.append("lang",                state.options.lang);
    form.append("detail_level",        String(state.options.detail));
    form.append("include_keypoints",   String(state.options.keypoints));
    form.append("include_stats",       String(state.options.stats));
    form.append("include_quotes",      String(state.options.quotes));
    form.append("include_entities",    String(state.options.entities));
    form.append("include_conclusion",  String(state.options.conclusion));

    /* Appel API — même origine que le frontend */
    const res = await fetch("/api/summarize", {
      method: "POST",
      body: form,
    });

    /* Attendre la fin de l'animation avant d'afficher */
    await anim;

    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: `Erreur HTTP ${res.status}` }));
      throw new Error(body.detail || `Erreur HTTP ${res.status}`);
    }

    const data = await res.json();
    state.result = data;

    setProgress(100, "Résumé généré ✓");
    await sleep(300);

    progressArea.hidden = true;
    renderResult(data);

  } catch (err) {
    await anim.catch(() => {});    // absorber l'animation
    resetPipeline();
    progressArea.hidden = true;
    showAlert(err.message || "Une erreur inattendue s'est produite.");
  } finally {
    state.processing = false;
    btnGo.disabled = !state.file;
    btnGo.setAttribute("aria-disabled", state.file ? "false" : "true");
    btnGo.innerHTML = "✦ &nbsp; Analyser et générer le résumé";
  }
}

/* ══════════════════════════════════════════════════════════════
   6. AFFICHAGE DES RÉSULTATS
   ══════════════════════════════════════════════════════════════ */

/** Affiche le panneau de résultats. */
function renderResult(data) {
  /* Badges en-tête */
  const sentimentClass = {
    positif: "res-badge-pos",
    négatif: "res-badge-neg",
    negatif: "res-badge-neg",
  }[data.sentiment] || "res-badge-neu";

  const complexityClass = {
    simple:           "res-badge-cx-s",
    intermédiaire:    "res-badge-cx-i",
    complexe:         "res-badge-cx-c",
  }[data.complexity] || "res-badge-cx-i";

  resultBadges.innerHTML = `
    <span class="res-badge res-badge-type">${esc(data.document_type || "Document")}</span>
    <span class="res-badge ${sentimentClass}">${esc(data.sentiment || "neutre")}</span>
    <span class="res-badge ${complexityClass}">${esc(data.complexity || "intermédiaire")}</span>
  `;

  /* Activer l'onglet résumé par défaut */
  state.activeTab = "summary";
  syncTabs();
  renderTab("summary", data);

  /* Afficher le panneau */
  emptyState.hidden = true;
  resultPanel.hidden = false;
  resultPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/** Synchronise les classes des boutons d'onglets. */
function syncTabs() {
  document.querySelectorAll(".tab").forEach(tab => {
    const active = tab.dataset.tab === state.activeTab;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
}

/** Délégation de clics sur les onglets. */
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    state.activeTab = tab.dataset.tab;
    syncTabs();
    renderTab(tab.dataset.tab, state.result);
  });
});

/**
 * Rend le contenu de l'onglet actif.
 * @param {"summary"|"keypoints"|"stats"|"pipeline"} tab
 * @param {Object} data
 */
function renderTab(tab, data) {
  if (!data) return;

  switch (tab) {

    /* ── Résumé ──────────────────────────────────────────────── */
    case "summary":
      tabBody.innerHTML = `<p class="summary-text">${esc(data.summary || "")}</p>`;
      break;

    /* ── Points clés ─────────────────────────────────────────── */
    case "keypoints": {
      const kps = data.key_points || [];
      if (!kps.length) {
        tabBody.innerHTML = `<p style="color:var(--c-br-400);font-size:13px;">Aucun point clé extrait.</p>`;
        break;
      }
      tabBody.innerHTML = `
        <ul class="kp-list">
          ${kps.map(kp => `
            <li class="kp-item">
              <div class="kp-dot" aria-hidden="true"></div>
              <span class="kp-text">${esc(kp)}</span>
            </li>
          `).join("")}
        </ul>
      `;
      break;
    }

    /* ── Statistiques ────────────────────────────────────────── */
    case "stats": {
      const s = data.stats || {};
      const topics = data.main_topics || [];

      tabBody.innerHTML = `
        <div class="stats-grid">
          <div class="stat-box">
            <span class="stat-val">${fmt(s.word_count_original)}</span>
            <div class="stat-lbl">Mots (doc)</div>
          </div>
          <div class="stat-box">
            <span class="stat-val">${fmt(s.word_count_summary)}</span>
            <div class="stat-lbl">Mots (résumé)</div>
          </div>
          <div class="stat-box">
            <span class="stat-val">${s.compression_ratio != null ? s.compression_ratio.toFixed(0) + "%" : "N/A"}</span>
            <div class="stat-lbl">Compression</div>
          </div>
          <div class="stat-box">
            <span class="stat-val">${s.page_count ?? 1}</span>
            <div class="stat-lbl">Page(s)</div>
          </div>
          <div class="stat-box">
            <span class="stat-val">${(data.key_points || []).length}</span>
            <div class="stat-lbl">Points clés</div>
          </div>
          <div class="stat-box">
            <span class="stat-val">${s.read_time_min ?? 1} min</span>
            <div class="stat-lbl">Temps lecture</div>
          </div>
        </div>
        ${topics.length ? `
          <div>
            <p style="font-size:11px;font-family:var(--f-mono);text-transform:uppercase;
                      letter-spacing:.4px;color:var(--c-br-400);margin-bottom:8px;">
              Sujets principaux
            </p>
            <div class="topics-row">
              ${topics.map(t => `<span class="topic-chip">${esc(t)}</span>`).join("")}
            </div>
          </div>
        ` : ""}
      `;
      break;
    }

    /* ── Pipeline ────────────────────────────────────────────── */
    case "pipeline": {
      const p = data.pipeline || {};
      const g = p.groq_meta || {};
      const rows = [
        ["Modèle LLM",          p.llm_model       || "Claude"],
        ["Embedding (RAG)",     p.embedding_model  || "all-MiniLM-L6-v2"],
        ["Route détectée",      p.route            || "-"],
        ["Langue de sortie",    p.language         || "-"],
        ["Chunks RAG",          data.stats?.chunk_count ?? "-"],
        ["Groq activé",         p.groq_used ? "Oui" : "Non (clé absente)"],
        ["Type doc (Groq)",     g.document_type    || "-"],
        ["Domaine (Groq)",      g.domain           || "-"],
      ];

      tabBody.innerHTML = `
        <div class="pipe-rows">
          ${rows.map(([lbl, val]) => `
            <div class="pipe-row">
              <span class="pipe-row-lbl">${esc(lbl)}</span>
              <span class="pipe-row-val">${esc(String(val))}</span>
            </div>
          `).join("")}
        </div>
      `;
      break;
    }
  }
}

/** Cache le panneau résultat et réaffiche l'état vide. */
function hideResult() {
  resultPanel.hidden = true;
  emptyState.hidden  = false;
}

/* ── Copier ────────────────────────────────────────────────────── */

btnCopy.addEventListener("click", () => {
  if (!state.result?.summary) return;
  navigator.clipboard.writeText(state.result.summary).then(() => {
    btnCopy.textContent = "✅ Copié !";
    setTimeout(() => { btnCopy.innerHTML = "📋 Copier"; }, 2000);
  }).catch(() => showAlert("Impossible de copier (permission refusée)."));
});

/* ══════════════════════════════════════════════════════════════
   7. UTILITAIRES
   ══════════════════════════════════════════════════════════════ */

/** Active/désactive le bouton principal selon l'état. */
function updateBtn() {
  const ok = !!state.file && !state.processing;
  btnGo.disabled = !ok;
  btnGo.setAttribute("aria-disabled", String(!ok));
}

/** Met à jour la barre de progression. */
function setProgress(pct, msg) {
  const clamped = Math.min(100, Math.max(0, pct));
  progressFill.style.width = `${clamped}%`;
  progressFill.parentElement.setAttribute("aria-valuenow", Math.round(clamped));
  progressMsg.textContent = msg;
}

/** Affiche un message d'erreur dans la zone d'alerte. */
function showAlert(msg) {
  alertArea.innerHTML = `
    <div class="alert alert-error">
      ⚠️ &nbsp;${esc(msg)}
    </div>
  `;
}

/** Efface la zone d'alerte. */
function clearAlert() { alertArea.innerHTML = ""; }

/** Formate un nombre d'octets en Ko/Mo lisible. */
function fmtSize(bytes) {
  if (bytes < 1024)         return `${bytes} o`;
  if (bytes < 1024 * 1024)  return `${Math.round(bytes / 1024)} Ko`;
  return `${(bytes / 1048576).toFixed(1)} Mo`;
}

/** Formate un entier avec séparateurs de milliers. */
function fmt(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString("fr-FR");
}

/** Échappe les caractères HTML pour éviter les injections XSS. */
function esc(str) {
  return String(str)
    .replace(/&/g,  "&amp;")
    .replace(/</g,  "&lt;")
    .replace(/>/g,  "&gt;")
    .replace(/"/g,  "&quot;")
    .replace(/'/g,  "&#39;");
}

/** Pause asynchrone. */
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }