# backend/agent.py
"""
Agent LangGraph — Pipeline de résumé de documents.

LLM : Client Groq NATIF (pas LangChain) pour éviter le bug httpx/proxies.
  from groq import Groq
  client = Groq(api_key=os.getenv("GROQ_API_KEY"))
  response = client.chat.completions.create(
      model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
      messages=[...],
      temperature=0,
  )

Graphe LangGraph :
  [START] → chunk_and_embed → retrieve → classify → route → summarize → [END]
"""

import json
import os
import re
from typing import Any

from groq import Groq
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from config import settings
from rag import chunker, rag_engine, Chunk

# ── Client Groq natif ─────────────────────────────────────────────────────────

def _get_client() -> Groq:
    """
    Retourne le client Groq natif.
    Utilise os.getenv() directement — plus fiable que pydantic-settings.
    """
    return Groq(api_key=os.getenv("GROQ_API_KEY"))


def _chat(messages: list[dict], max_tokens: int = 2048) -> str:
    """
    Appel simplifié au client Groq natif.

    Args:
        messages   : liste de dicts {"role": "user"|"system", "content": "..."}
        max_tokens : limite de tokens en sortie

    Returns:
        Contenu texte de la réponse
    """
    client   = _get_client()
    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        messages=messages,
        temperature=0,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


# ── État du graphe LangGraph ─────────────────────────────────────────────────

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
    """Découpe le texte en chunks."""
    raw_chunks = chunker.chunk(state["raw_text"])

    if not raw_chunks:
        return {**state, "error": "Le document est vide après extraction."}

    chunks_data = [
        {"text": text, "index": i}
        for i, text in enumerate(raw_chunks)
    ]
    return {**state, "chunks": chunks_data}

# ── Nœud 2 : Retrieval RAG ───────────────────────────────────────────────────

def node_retrieve(state: AgentState) -> AgentState:
    """Récupère les chunks pertinents via ChromaDB."""
    if not state["chunks"]:
        return state

    chunk_texts = [c["text"] for c in state["chunks"]]
    _, context  = rag_engine.retrieve(chunk_texts, top_k=settings.top_k_chunks)

    return {**state, "context": context}

# ── Nœud 3 : Classification Groq ────────────────────────────────────────────

def node_classify(state: AgentState) -> AgentState:
    """Classe le document (type, domaine, complexité) via Groq natif."""
    if not os.getenv("GROQ_API_KEY"):
        return state

    try:
        preview = " ".join(state["raw_text"].split()[:300])
        raw     = _chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu es un classificateur de documents. "
                        "Réponds UNIQUEMENT avec un objet JSON valide, "
                        "sans markdown, sans texte autour."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Analyse ce début de document et retourne :\n"
                        '{"document_type":"rapport|lecon|article|livre|email|autre",'
                        '"domain":"informatique|medecine|droit|economie|education|science|autre",'
                        '"complexity":"simple|intermediaire|complexe"}\n\n'
                        f"Texte : {preview}"
                    ),
                },
            ],
            max_tokens=150,
        )
        meta = _parse_json(raw)
        return {**state, "groq_meta": meta}

    except Exception:
        return state   # Ne jamais bloquer le pipeline


# ── Nœud 4 : Routage ────────────────────────────────────────────────────────

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
            "références", "bibliographie",
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


# ── Nœud 5 : Résumé Groq ────────────────────────────────────────────────────

def node_summarize(state: AgentState) -> AgentState:
    """
    Génère le résumé JSON structuré via le client Groq natif.

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        messages=[{"role": "system", ...}, {"role": "user", ...}],
        temperature=0,
    )
    """
    if not os.getenv("GROQ_API_KEY"):
        return {
            **state,
            "error": (
                "GROQ_API_KEY manquante.\n"
                "Ajoutez-la dans backend/.env\n"
                "Clé gratuite : https://console.groq.com/"
            ),
        }

    # ── Construction du prompt ────────────────────────────────────────────────

    lang_map = {
        "fr": "français",
        "en": "anglais",
        "ar": "arabe",
        "es": "espagnol",
    }
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

    include       = state.get("include", {})
    inclusions    = []
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

    system_content = f"""Tu es un agent expert en analyse documentaire NLP (pipeline RAG + LangGraph).

RÈGLES STRICTES :
1. Réponds UNIQUEMENT en {lang_label}.
2. Réponds UNIQUEMENT avec un objet JSON valide. Aucun texte avant ou après.
3. N'invente aucune information absente du document.
4. Niveau de détail : {state['detail_level']}/5.
5. {route_hint}

FORMAT JSON OBLIGATOIRE :
{{
  "summary": "Résumé principal",
  "key_points": ["Point 1", "Point 2", "Point 3"],
  "document_type": "Type du document",
  "sentiment": "positif|neutre|négatif",
  "complexity": "simple|intermédiaire|complexe",
  "main_topics": ["Sujet 1", "Sujet 2"]
}}"""

    user_content = f"""Génère {style_label} de ce document.

ÉLÉMENTS À INCLURE :
- {inclusions_str}

PASSAGES CLÉS SÉLECTIONNÉS PAR RAG :
{state['context'][:4000]}

DÉBUT DU DOCUMENT :
{state['raw_text'][:2500]}

JSON :"""

    # ── Appel Groq natif ──────────────────────────────────────────────────────

    try:
        raw    = _chat(
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user",   "content": user_content},
            ],
            max_tokens=2048,
        )
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


# ── Construction du graphe LangGraph ─────────────────────────────────────────

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


# Graphe compilé — réutilisé pour toutes les requêtes
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
    """Lance le pipeline complet sur un texte extrait."""
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