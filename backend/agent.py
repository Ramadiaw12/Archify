# backend/agent.py
"""
Agent LangGraph — Pipeline de résumé de documents.
LLM : Groq (modèle configuré dans .env via GROQ_MODEL)

Graphe :
  [START] → chunk_and_embed → retrieve → classify → route → summarize → [END]
"""

import json
import re
from typing import Any

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from config import settings
from rag import TextChunker, EmbeddingEngine, VectorStore, Chunk


# ── État du graphe ────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    # Entrées
    raw_text:     str
    filename:     str
    style:        str
    language:     str
    detail_level: int
    include:      dict

    # Pipeline interne
    chunks:    list[dict]
    context:   str
    route:     str
    groq_meta: dict

    # Sorties
    summary:       str
    key_points:    list[str]
    document_type: str
    sentiment:     str
    complexity:    str
    main_topics:   list[str]
    error:         str


def _defaults() -> AgentState:
    return AgentState(
        raw_text="", filename="", style="concis", language="fr",
        detail_level=3, include={},
        chunks=[], context="", route="general", groq_meta={},
        summary="", key_points=[], document_type="Document",
        sentiment="neutre", complexity="intermédiaire", main_topics=[],
        error="",
    )


def _parse_json(text: str) -> dict:
    """Parse JSON en nettoyant le markdown si présent."""
    cleaned = re.sub(r"```json\s*|```\s*", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return {}


# ── Nœud 1 : Chunking + Embedding ────────────────────────────────────────────

def node_chunk_and_embed(state: AgentState) -> AgentState:
    """Découpe le texte en chunks et génère leurs embeddings."""
    chunker = TextChunker(
        chunk_size=settings.chunk_size,
        overlap=settings.chunk_overlap,
    )
    raw_chunks = chunker.chunk(state["raw_text"])

    if not raw_chunks:
        return {**state, "error": "Le document est vide après extraction."}

    engine = EmbeddingEngine(settings.embedding_model)
    embeddings = engine.embed(raw_chunks)

    chunks_data = [
        {"text": text, "index": i, "embedding": emb}
        for i, (text, emb) in enumerate(zip(raw_chunks, embeddings))
    ]
    return {**state, "chunks": chunks_data}


# ── Nœud 2 : Retrieval RAG ────────────────────────────────────────────────────

def node_retrieve(state: AgentState) -> AgentState:
    """
    Sélectionne les chunks les plus pertinents.
    Utilise embed_with_query() pour garantir la même dimension
    entre les embeddings des chunks et celui de la requête.
    """
    if not state["chunks"]:
        return state

    chunk_texts = [c["text"] for c in state["chunks"]]
    auto_query  = " ".join(state["raw_text"].split()[:150])

    engine = EmbeddingEngine(settings.embedding_model)
    chunk_embeddings, query_embedding = engine.embed_with_query(chunk_texts, auto_query)

    store = VectorStore()
    store.add_chunks([
        Chunk(text=c["text"], index=c["index"], embedding=emb)
        for c, emb in zip(state["chunks"], chunk_embeddings)
    ])

    top_chunks = store.search(query_embedding, top_k=settings.top_k_chunks)
    context = "\n\n---\n\n".join(
        f"[Extrait {c.index + 1}]\n{c.text}" for c in top_chunks
    )
    return {**state, "context": context}


# ── Nœud 3 : Classification Groq ─────────────────────────────────────────────

def node_classify(state: AgentState) -> AgentState:
    """Classe rapidement le document (type, domaine, complexité) via Groq."""
    if not settings.groq_api_key:
        return state

    try:
        from groq import Groq
        client = Groq(api_key=settings.groq_api_key)

        preview = " ".join(state["raw_text"].split()[:300])
        prompt = (
            "Analyse ce début de document. "
            "Réponds UNIQUEMENT avec un JSON valide, sans markdown, sans texte autour :\n"
            '{"document_type":"rapport|lecon|article|livre|email|autre",'
            '"domain":"informatique|medecine|droit|economie|education|science|autre",'
            '"complexity":"simple|intermediaire|complexe"}\n\n'
            f"Texte : {preview}"
        )

        resp = client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.1,
        )
        raw  = resp.choices[0].message.content or ""
        meta = _parse_json(raw)
        return {**state, "groq_meta": meta}

    except Exception:
        return state  # Ne pas bloquer le pipeline


# ── Nœud 4 : Routage ─────────────────────────────────────────────────────────

def node_route(state: AgentState) -> AgentState:
    """Choisit la stratégie de résumé selon le type de document."""
    text_lower = state["raw_text"].lower()
    word_count = len(state["raw_text"].split())
    doc_type   = state.get("groq_meta", {}).get("document_type", "")

    if word_count < 300:
        route = "court"
    elif doc_type == "lecon" or any(
        kw in text_lower for kw in [
            "cours", "leçon", "chapitre", "exercice",
            "objectif", "compétence", "apprentissage", "tp ", "td ",
        ]
    ):
        route = "pedagogique"
    elif doc_type == "article" or any(
        kw in text_lower for kw in [
            "abstract", "méthode", "résultats", "hypothèse",
            "références", "bibliographie", "analyse statistique",
        ]
    ):
        route = "scientifique"
    elif doc_type == "rapport" or any(
        kw in text_lower for kw in [
            "rapport", "executive summary", "recommandation",
            "synthèse", "bilan", "annexe",
        ]
    ):
        route = "rapport_formel"
    else:
        route = "general"

    return {**state, "route": route}


# ── Nœud 5 : Résumé via Groq ─────────────────────────────────────────────────

def node_summarize(state: AgentState) -> AgentState:
    """Génère le résumé structuré JSON via Groq (modèle lu depuis .env)."""
    if not settings.groq_api_key:
        return {
            **state,
            "error": (
                "GROQ_API_KEY manquante dans votre fichier .env\n"
                "Obtenez une clé gratuite sur : https://console.groq.com/"
            ),
        }

    from groq import Groq

    lang_map = {"fr": "français", "en": "anglais", "ar": "arabe", "es": "espagnol"}
    lang_label = lang_map.get(state["language"], "français")

    style_map = {
        "concis":      "un résumé concis en 2-3 paragraphes",
        "detaille":    "un résumé détaillé en 4-6 paragraphes",
        "bullet":      "une liste de points clés numérotés",
        "executif":    "un rapport exécutif (contexte, analyse, recommandations)",
        "pedagogique": "une fiche de révision accessible à un étudiant",
    }
    style_label = style_map.get(state["style"], style_map["concis"])

    route_hints = {
        "court":          "Document court — aller directement à l'essentiel.",
        "pedagogique":    "Document pédagogique — mettre en valeur les concepts clés.",
        "scientifique":   "Article scientifique — souligner méthode, résultats, limites.",
        "rapport_formel": "Rapport — structurer contexte, analyse, recommandations.",
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
        inclusions.append("1 à 3 citations directes (entre guillemets)")
    if include.get("entities"):
        inclusions.append("entités nommées : personnes, organisations, lieux")
    if include.get("conclusion", True):
        inclusions.append("une conclusion en 1-2 phrases")

    inclusions_str = "\n- ".join(inclusions) if inclusions else "résumé général"

    prompt = f"""Tu es un agent expert en analyse documentaire.

RÈGLES :
1. Réponds UNIQUEMENT en {lang_label}.
2. Réponds UNIQUEMENT avec un objet JSON valide. Aucun texte avant ou après.
3. N'invente aucune information absente du document.
4. Niveau de détail : {state['detail_level']}/5.
5. {route_hint}

FORMAT JSON :
{{
  "summary": "Résumé principal",
  "key_points": ["Point 1", "Point 2", "Point 3"],
  "document_type": "Type du document",
  "sentiment": "positif|neutre|négatif",
  "complexity": "simple|intermédiaire|complexe",
  "main_topics": ["Sujet 1", "Sujet 2"]
}}

---

TÂCHE : Génère {style_label}.

ÉLÉMENTS À INCLURE :
- {inclusions_str}

PASSAGES CLÉS (sélectionnés par RAG) :
{state['context'][:4000]}

DÉBUT DU DOCUMENT :
{state['raw_text'][:2500]}

JSON :"""

    try:
        client   = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.3,
        )
        raw    = response.choices[0].message.content or ""
        parsed = _parse_json(raw)

        if not parsed:
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


# ── Graphe LangGraph ──────────────────────────────────────────────────────────

def build_graph() -> Any:
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


graph = build_graph()


def run_agent(
    raw_text:     str,
    filename:     str,
    style:        str = "concis",
    language:     str = "fr",
    detail_level: int = 3,
    include:      dict | None = None,
) -> AgentState:
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