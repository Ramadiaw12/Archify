# backend/agent.py
"""
Agent LangGraph — Pipeline de résumé de documents.

LLM utilisé : Groq (LLaMA) UNIQUEMENT. Pas de Claude, pas d'Anthropic, pas de xAI.

Graphe d'états :
  [START]
     │
     ▼
  chunk_and_embed   ← Découpage RAG + embeddings
     │
     ▼
  retrieve          ← Retrieval des passages pertinents (cosinus)
     │
     ▼
  classify          ← Groq llama3-8b : type de doc, domaine (rapide)
     │
     ▼
  route             ← Heuristique : choisit la stratégie de résumé
     │
     ▼
  summarize         ← Groq llama3-70b : génère le résumé JSON
     │
     ▼
  [END]
"""

import json
import re
from typing import Any

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from config import settings
from rag import TextChunker, EmbeddingEngine, VectorStore, Chunk


# ── État du graphe LangGraph ─────────────────────────────────────────────────

class AgentState(TypedDict):
    # ── Entrées ──────────────────────────────────────────────────────────────
    raw_text:     str
    filename:     str
    style:        str    # concis | detaille | bullet | executif | pedagogique
    language:     str    # fr | en | ar | es
    detail_level: int    # 1–5
    include:      dict   # {keypoints, stats, quotes, entities, conclusion}

    # ── État interne pipeline ─────────────────────────────────────────────────
    chunks:     list[dict]   # sérialisable : [{"text","index","embedding"}]
    context:    str          # passages RAG assemblés pour le LLM
    route:      str          # rapport_formel | pedagogique | scientifique | general | court
    groq_meta:  dict         # résultat de la classification Groq rapide

    # ── Sorties finales ───────────────────────────────────────────────────────
    summary:       str
    key_points:    list[str]
    document_type: str
    sentiment:     str
    complexity:    str
    main_topics:   list[str]
    error:         str


def _defaults() -> AgentState:
    """Valeurs par défaut de l'état initial."""
    return AgentState(
        raw_text="", filename="", style="concis", language="fr",
        detail_level=3, include={},
        chunks=[], context="", route="general", groq_meta={},
        summary="", key_points=[], document_type="Document",
        sentiment="neutre", complexity="intermédiaire", main_topics=[],
        error="",
    )


def _parse_json(text: str) -> dict:
    """
    Parse du JSON même si le modèle a ajouté du markdown ou du texte autour.
    Tente plusieurs stratégies de nettoyage.
    """
    # Supprimer les blocs markdown ```json ... ```
    cleaned = re.sub(r"```json\s*", "", text)
    cleaned = re.sub(r"```\s*", "", cleaned).strip()

    # Tentative 1 : JSON direct
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Tentative 2 : extraire le premier bloc { ... }
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {}


# ── Nœud 1 : Chunking + Embedding ───────────────────────────────────────────

def node_chunk_and_embed(state: AgentState) -> AgentState:
    """
    Découpe le texte en chunks puis génère leurs embeddings via RAG.
    Les embeddings sont stockés comme listes de floats (sérialisables JSON).
    """
    chunker = TextChunker(
        chunk_size=settings.chunk_size,
        overlap=settings.chunk_overlap,
    )
    raw_chunks = chunker.chunk(state["raw_text"])

    if not raw_chunks:
        return {**state, "error": "Le document est vide après extraction."}

    # Générer les embeddings pour tous les chunks en une seule passe
    engine = EmbeddingEngine(settings.embedding_model)
    embeddings = engine.embed(raw_chunks)

    chunks_data = [
        {
            "text":      text,
            "index":     i,
            "embedding": emb,
        }
        for i, (text, emb) in enumerate(zip(raw_chunks, embeddings))
    ]

    return {**state, "chunks": chunks_data}


# ── Nœud 2 : Retrieval RAG ───────────────────────────────────────────────────

def node_retrieve(state: AgentState) -> AgentState:
    """
    Sélectionne les chunks les plus pertinents par similarité cosinus.

    CORRECTION BUG dimension :
    On utilise embed_with_query() qui encode chunks et requête
    ENSEMBLE avec le même vocabulaire → vecteurs de même dimension.
    """
    if not state["chunks"]:
        return state

    chunk_texts = [c["text"] for c in state["chunks"]]

    # Requête automatique = premiers 150 mots du document
    auto_query = " ".join(state["raw_text"].split()[:150])

    # ✅ Encoder chunks + requête ensemble (même espace vectoriel)
    engine = EmbeddingEngine(settings.embedding_model)
    chunk_embeddings, query_embedding = engine.embed_with_query(chunk_texts, auto_query)

    # Construire le VectorStore avec les embeddings recalculés
    store = VectorStore()
    chunk_objects = [
        Chunk(text=c["text"], index=c["index"], embedding=emb)
        for c, emb in zip(state["chunks"], chunk_embeddings)
    ]
    store.add_chunks(chunk_objects)

    # Récupérer les top-K chunks
    top_chunks = store.search(query_embedding, top_k=settings.top_k_chunks)

    # Assembler le contexte pour le LLM
    context = "\n\n---\n\n".join(
        f"[Extrait {c.index + 1}]\n{c.text}"
        for c in top_chunks
    )

    return {**state, "context": context}


# ── Nœud 3 : Classification Groq (rapide) ────────────────────────────────────

def node_classify(state: AgentState) -> AgentState:
    """
    Utilise Groq llama3-8b (rapide) pour classifier le document :
    type, domaine, complexité estimée.
    """
    if not settings.groq_api_key:
        return state

    try:
        from groq import Groq
        client = Groq(api_key=settings.groq_api_key)

        preview = " ".join(state["raw_text"].split()[:300])
        prompt = (
            "Analyse ce début de document. "
            "Réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans texte autour :\n"
            '{"detected_language":"fr|en|ar|es|autre",'
            '"document_type":"rapport|lecon|article|livre|email|autre",'
            '"domain":"informatique|medecine|droit|economie|education|science|autre",'
            '"complexity":"simple|intermediaire|complexe"}\n\n'
            f"Texte : {preview}"
        )

        resp = client.chat.completions.create(
            model=settings.groq_model_fast,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content or ""
        meta = _parse_json(raw)
        return {**state, "groq_meta": meta}

    except Exception:
        # Ne jamais bloquer le pipeline si la classification échoue
        return state


# ── Nœud 4 : Routage LangGraph ───────────────────────────────────────────────

def node_route(state: AgentState) -> AgentState:
    """
    Choisit la stratégie de résumé selon le type de document.
    Combine heuristiques textuelles + métadonnées Groq.
    """
    text_lower = state["raw_text"].lower()
    word_count = len(state["raw_text"].split())
    groq = state.get("groq_meta", {})
    doc_type = groq.get("document_type", "")

    if word_count < 300:
        route = "court"
    elif doc_type == "lecon" or any(
        kw in text_lower for kw in [
            "cours", "leçon", "chapitre", "exercice",
            "objectif pédagogique", "compétence", "apprentissage",
            "définition", "exemple", "tp ", "td ",
        ]
    ):
        route = "pedagogique"
    elif doc_type == "article" or any(
        kw in text_lower for kw in [
            "abstract", "introduction", "méthode", "résultats",
            "conclusion", "hypothèse", "étude", "analyse statistique",
            "références", "bibliographie",
        ]
    ):
        route = "scientifique"
    elif doc_type == "rapport" or any(
        kw in text_lower for kw in [
            "rapport", "executive summary", "recommandation",
            "synthèse", "bilan", "annexe", "tableau de bord",
        ]
    ):
        route = "rapport_formel"
    else:
        route = "general"

    return {**state, "route": route}


# ── Nœud 5 : Résumé Groq (llama3-70b) ───────────────────────────────────────

def node_summarize(state: AgentState) -> AgentState:
    """
    Génère le résumé structuré en JSON via Groq llama3-70b-8192.

    LLM : Groq uniquement. Pas de Claude, pas d'Anthropic, pas de xAI.
    """
    if not settings.groq_api_key:
        return {
            **state,
            "error": (
                "GROQ_API_KEY non définie. "
                "Ajoutez-la dans votre fichier .env\n"
                "Obtenir une clé gratuite : https://console.groq.com/"
            ),
        }

    from groq import Groq

    # ── Préparation du prompt ─────────────────────────────────────────────────

    lang_map = {
        "fr": "français",
        "en": "anglais",
        "ar": "arabe",
        "es": "espagnol",
    }
    lang_label = lang_map.get(state["language"], "français")

    style_map = {
        "concis":      "un résumé concis et percutant en 2-3 paragraphes",
        "detaille":    "un résumé détaillé et exhaustif en 4-6 paragraphes",
        "bullet":      "une synthèse en liste de points clés numérotés",
        "executif":    "un rapport exécutif structuré (contexte, analyse, recommandations)",
        "pedagogique": "une fiche de révision claire et accessible à un étudiant",
    }
    style_label = style_map.get(state["style"], style_map["concis"])

    route_hints = {
        "court":          "Document court — aller directement à l'essentiel.",
        "pedagogique":    "Document pédagogique — mettre en valeur les concepts et la progression.",
        "scientifique":   "Article scientifique — souligner méthode, résultats, limites.",
        "rapport_formel": "Rapport formel — structurer contexte, analyse, recommandations.",
        "general":        "Document général — synthèse équilibrée.",
    }
    route_hint = route_hints.get(state["route"], route_hints["general"])

    include = state.get("include", {})
    inclusions = []
    if include.get("keypoints", True):
        inclusions.append("3 à 7 points clés extraits du document")
    if include.get("stats"):
        inclusions.append("les chiffres et statistiques importants")
    if include.get("quotes"):
        inclusions.append("1 à 3 citations directes marquantes (entre guillemets)")
    if include.get("entities"):
        inclusions.append("les entités nommées : personnes, organisations, lieux")
    if include.get("conclusion", True):
        inclusions.append("une conclusion synthétique en 1-2 phrases")

    inclusions_str = "\n- ".join(inclusions) if inclusions else "résumé général"

    prompt = f"""Tu es un agent expert en analyse documentaire NLP utilisant RAG + LangGraph.

RÈGLES ABSOLUES :
1. Réponds UNIQUEMENT en {lang_label}.
2. Réponds UNIQUEMENT avec un objet JSON valide. Zéro texte avant ou après. Pas de markdown.
3. Ne jamais inventer d'informations absentes du document.
4. Niveau de détail : {state['detail_level']}/5.
5. Stratégie : {route_hint}

FORMAT JSON (respecter exactement ces clés) :
{{
  "summary": "Résumé principal",
  "key_points": ["Point 1", "Point 2", "Point 3"],
  "document_type": "Type précis du document",
  "sentiment": "positif|neutre|négatif",
  "complexity": "simple|intermédiaire|complexe",
  "main_topics": ["Sujet 1", "Sujet 2", "Sujet 3"]
}}

---

TÂCHE : Génère {style_label}.

ÉLÉMENTS À INCLURE :
- {inclusions_str}

PASSAGES CLÉS SÉLECTIONNÉS PAR RAG :
{state['context'][:4000]}

DÉBUT DU DOCUMENT :
{state['raw_text'][:2500]}

Génère l'objet JSON maintenant :"""

    # ── Appel Groq ────────────────────────────────────────────────────────────

    try:
        client = Groq(api_key=settings.groq_api_key)

        response = client.chat.completions.create(
            model=settings.groq_model_main,   # llama3-70b-8192
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.3,
        )

        raw = response.choices[0].message.content or ""
        parsed = _parse_json(raw)

        if not parsed:
            # Fallback : retourner le texte brut comme résumé
            return {
                **state,
                "summary":       raw.strip(),
                "key_points":    [],
                "document_type": "Document",
                "sentiment":     "neutre",
                "complexity":    "intermédiaire",
                "main_topics":   [],
            }

        return {
            **state,
            "summary":       parsed.get("summary", ""),
            "key_points":    parsed.get("key_points", []),
            "document_type": parsed.get("document_type", "Document"),
            "sentiment":     parsed.get("sentiment", "neutre"),
            "complexity":    parsed.get("complexity", "intermédiaire"),
            "main_topics":   parsed.get("main_topics", []),
        }

    except Exception as e:
        return {**state, "error": f"Erreur Groq : {e}"}


# ── Construction du graphe LangGraph ─────────────────────────────────────────

def build_graph() -> Any:
    """Construit et compile le graphe LangGraph."""
    builder = StateGraph(AgentState)

    builder.add_node("chunk_and_embed", node_chunk_and_embed)
    builder.add_node("retrieve",        node_retrieve)
    builder.add_node("classify",        node_classify)
    builder.add_node("route",           node_route)
    builder.add_node("summarize",       node_summarize)

    builder.add_edge(START,             "chunk_and_embed")
    builder.add_edge("chunk_and_embed", "retrieve")
    builder.add_edge("retrieve",        "classify")
    builder.add_edge("classify",        "route")
    builder.add_edge("route",           "summarize")
    builder.add_edge("summarize",       END)

    return builder.compile()


# Graphe compilé — réutilisé pour chaque requête
graph = build_graph()


# ── Fonction publique ─────────────────────────────────────────────────────────

def run_agent(
    raw_text:     str,
    filename:     str,
    style:        str = "concis",
    language:     str = "fr",
    detail_level: int = 3,
    include:      dict | None = None,
) -> AgentState:
    """
    Lance le pipeline complet sur un texte extrait.

    Args:
        raw_text:     texte brut issu du DocumentParser
        filename:     nom original du fichier
        style:        style du résumé
        language:     langue de sortie
        detail_level: niveau de détail 1–5
        include:      options d'inclusion {keypoints, stats, quotes, entities, conclusion}

    Returns:
        AgentState final avec summary, key_points, etc.
    """
    initial: AgentState = {
        **_defaults(),
        "raw_text":     raw_text,
        "filename":     filename,
        "style":        style,
        "language":     language,
        "detail_level": detail_level,
        "include":      include or {},
    }

    return graph.invoke(initial)