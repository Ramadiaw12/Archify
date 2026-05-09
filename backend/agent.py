# backend/agent.py
"""
Agent LangGraph — Orchestration du pipeline de résumé.

Graphe d'états :
  [START]
     │
     ▼
  chunk_and_embed      ← Découpage + embeddings RAG
     │
     ▼
  retrieve             ← Retrieval des passages pertinents
     │
     ▼
  classify             ← Groq : type de doc, langue, complexité (optionnel)
     │
     ▼
  route                ← Choisit la stratégie de résumé
     │
     ▼
  summarize            ← Claude : génère le résumé JSON structuré
     │
     ▼
  [END]

Chaque nœud est une fonction pure (AgentState → AgentState).
LangGraph gère la transition entre les nœuds.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Annotated, Any

from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from config import settings
from rag import TextChunker, EmbeddingEngine, VectorStore, Chunk


# ── État du graphe ────────────────────────────────────────────────────────────
# TypedDict pour LangGraph (doit être sérialisable)

class AgentState(TypedDict):
    # Entrées
    raw_text: str
    filename: str
    style: str            # concis | detaille | bullet | executif | pedagogique
    language: str         # fr | en | ar | es
    detail_level: int     # 1–5
    include: dict         # {keypoints, stats, quotes, entities, conclusion}

    # État interne du pipeline
    chunks: list[dict]         # [{"text": ..., "index": ..., "embedding": ...}]
    context: str               # Passages RAG assemblés pour le LLM
    route: str                 # rapport_formel | pedagogique | scientifique | general | court
    groq_meta: dict            # Métadonnées Groq (type, domaine, complexité)

    # Sorties finales
    summary: str
    key_points: list[str]
    document_type: str
    sentiment: str
    complexity: str
    main_topics: list[str]
    error: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state_defaults() -> AgentState:
    """Valeurs par défaut de l'état (utilisé à l'initialisation)."""
    return AgentState(
        raw_text="", filename="", style="concis", language="fr",
        detail_level=3, include={},
        chunks=[], context="", route="general", groq_meta={},
        summary="", key_points=[], document_type="Document",
        sentiment="neutre", complexity="intermédiaire", main_topics=[],
        error="",
    )


def _parse_json_safe(text: str) -> dict:
    """Tente de parser du JSON même si le modèle a ajouté du markdown."""
    cleaned = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Chercher le premier bloc JSON dans le texte
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return {}


# ── Nœuds du graphe ───────────────────────────────────────────────────────────

def node_chunk_and_embed(state: AgentState) -> AgentState:
    """
    Nœud 1 — RAG : Chunking + Embedding
    Découpe le texte brut en chunks, génère leurs vecteurs d'embedding.
    """
    chunker = TextChunker(
        chunk_size=settings.chunk_size,
        overlap=settings.chunk_overlap,
    )
    engine = EmbeddingEngine(settings.embedding_model)

    raw_chunks = chunker.chunk(state["raw_text"])
    if not raw_chunks:
        return {**state, "error": "Texte vide après découpage."}

    texts = [c for c in raw_chunks]
    embeddings = engine.embed(texts)

    chunks_data = [
        {"text": text, "index": i, "embedding": emb}
        for i, (text, emb) in enumerate(zip(texts, embeddings))
    ]

    return {**state, "chunks": chunks_data}


def node_retrieve(state: AgentState) -> AgentState:
    """
    Nœud 2 — RAG : Retrieval
    Embed une requête automatique (début du doc) et récupère
    les top-K chunks les plus proches par similarité cosinus.
    """
    if not state["chunks"]:
        return state

    engine = EmbeddingEngine(settings.embedding_model)
    store = VectorStore()

    # Reconstruire les objets Chunk depuis les dicts sérialisables
    chunk_objects = [
        Chunk(text=c["text"], index=c["index"], embedding=c["embedding"])
        for c in state["chunks"]
    ]
    store.add_chunks(chunk_objects)

    # Requête automatique = résumé heuristique des 120 premiers mots
    auto_query = " ".join(state["raw_text"].split()[:120])
    query_emb = engine.embed([auto_query])[0]

    top_chunks = store.search(query_emb, top_k=settings.top_k_chunks)

    # Assembler le contexte pour le LLM
    context = "\n\n---\n\n".join(
        f"[Extrait {c.index + 1}]\n{c.text}" for c in top_chunks
    )

    return {**state, "context": context}


def node_classify(state: AgentState) -> AgentState:
    """
    Nœud 3 — Groq (optionnel)
    Classification rapide du document : type, domaine, complexité.
    Si GROQ_API_KEY n'est pas définie, ce nœud est transparant.
    """
    if not settings.groq_api_key:
        return state  # Rien à faire, Groq désactivé

    try:
        from groq import Groq
        client = Groq(api_key=settings.groq_api_key)

        preview = " ".join(state["raw_text"].split()[:300])
        prompt = (
            "Analyse ce début de document. Réponds UNIQUEMENT en JSON valide, "
            "sans markdown :\n"
            '{"detected_language":"fr|en|ar|es|autre",'
            '"document_type":"rapport|lecon|article|livre|email|autre",'
            '"domain":"informatique|médecine|droit|économie|éducation|autre",'
            '"complexity":"simple|intermédiaire|complexe"}\n\n'
            f"Texte : {preview}"
        )

        resp = client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content or ""
        meta = _parse_json_safe(raw)
        return {**state, "groq_meta": meta}

    except Exception:
        # Ne pas bloquer le pipeline si Groq échoue
        return state


def node_route(state: AgentState) -> AgentState:
    """
    Nœud 4 — Routage LangGraph
    Analyse heuristique du contenu pour choisir la stratégie de résumé.
    Prend en compte les métadonnées Groq si disponibles.
    """
    text_lower = state["raw_text"].lower()
    word_count = len(state["raw_text"].split())
    groq = state.get("groq_meta", {})

    # Priorité aux métadonnées Groq
    doc_type = groq.get("document_type", "")

    if word_count < 300:
        route = "court"
    elif doc_type == "lecon" or any(
        kw in text_lower
        for kw in ["cours", "leçon", "chapitre", "exercice", "objectif pédagogique",
                   "compétence", "apprentissage"]
    ):
        route = "pedagogique"
    elif doc_type == "article" or any(
        kw in text_lower
        for kw in ["abstract", "résumé", "méthode", "résultats", "conclusion",
                   "hypothèse", "étude", "analyse statistique"]
    ):
        route = "scientifique"
    elif doc_type == "rapport" or any(
        kw in text_lower
        for kw in ["rapport", "introduction", "executive summary", "recommandation",
                   "conclusion", "annexe"]
    ):
        route = "rapport_formel"
    else:
        route = "general"

    return {**state, "route": route}


def node_summarize(state: AgentState) -> AgentState:
    """
    Nœud 5 — Claude (Anthropic)
    Génère le résumé structuré en JSON à partir du contexte RAG.
    """
    if not settings.anthropic_api_key:
        return {**state, "error": "ANTHROPIC_API_KEY non définie."}

    import anthropic

    # ── Construction des prompts ──────────────────────────────────────────────

    lang_map = {"fr": "français", "en": "anglais", "ar": "arabe", "es": "espagnol"}
    lang_label = lang_map.get(state["language"], "français")

    style_map = {
        "concis":      "un résumé concis et percutant en 2-3 paragraphes",
        "detaille":    "un résumé détaillé et exhaustif en 4-6 paragraphes",
        "bullet":      "une synthèse structurée en liste de points clés numérotés",
        "executif":    "un rapport exécutif professionnel avec introduction, analyse et recommandations",
        "pedagogique": "une fiche de révision claire et pédagogique, accessible à un étudiant",
    }
    style_label = style_map.get(state["style"], style_map["concis"])

    route_context = {
        "court":         "Document court — aller à l'essentiel immédiatement.",
        "pedagogique":   "Document pédagogique — mettre en valeur les concepts clés et la progression.",
        "scientifique":  "Article scientifique — souligner méthodologie, résultats et limites.",
        "rapport_formel":"Rapport formel — structurer avec contexte, analyse et recommandations.",
        "general":       "Document général — synthèse équilibrée.",
    }
    route_hint = route_context.get(state["route"], route_context["general"])

    include = state.get("include", {})
    inclusions = []
    if include.get("keypoints", True):
        inclusions.append("3 à 7 points clés extraits verbatim du document")
    if include.get("stats"):
        inclusions.append("les chiffres et statistiques importants mentionnés")
    if include.get("quotes"):
        inclusions.append("1 à 3 citations directes marquantes (entre guillemets)")
    if include.get("entities"):
        inclusions.append("les entités nommées : personnes, organisations, lieux")
    if include.get("conclusion", True):
        inclusions.append("une conclusion synthétique en 1-2 phrases")

    system_prompt = f"""Tu es un agent expert en analyse documentaire et NLP.
Tu utilises un pipeline RAG (Retrieval-Augmented Generation) avec LangGraph pour extraire \
les informations les plus pertinentes d'un document.

RÈGLES STRICTES :
1. Réponds UNIQUEMENT en {lang_label}.
2. Réponds UNIQUEMENT avec un objet JSON valide. Aucun texte avant ou après.
3. Ne jamais inventer d'informations absentes du document fourni.
4. Niveau de détail demandé : {state['detail_level']}/5.
5. Contexte de routage : {route_hint}

FORMAT JSON OBLIGATOIRE (respecter exactement ces clés) :
{{
  "summary": "Résumé principal selon le style demandé",
  "key_points": ["Point 1", "Point 2", "Point 3"],
  "document_type": "Type précis du document",
  "sentiment": "positif|neutre|négatif",
  "complexity": "simple|intermédiaire|complexe",
  "main_topics": ["Sujet 1", "Sujet 2", "Sujet 3"]
}}"""

    user_prompt = f"""Génère {style_label} de ce document.

ÉLÉMENTS À INCLURE :
- {chr(10) + '- '.join(inclusions) if inclusions else 'résumé général'}

PASSAGES LES PLUS PERTINENTS (sélectionnés par RAG) :
{state['context'][:4000]}

DÉBUT DU DOCUMENT COMPLET :
{state['raw_text'][:2500]}

Génère l'objet JSON maintenant."""

    # ── Appel API ─────────────────────────────────────────────────────────────

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=settings.claude_model,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text.strip()
        parsed = _parse_json_safe(raw)

        if not parsed:
            # Fallback : retourner le texte brut comme résumé
            return {
                **state,
                "summary": raw,
                "key_points": [],
                "document_type": "Document",
                "sentiment": "neutre",
                "complexity": "intermédiaire",
                "main_topics": [],
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
        return {**state, "error": f"Erreur Claude : {e}"}


# ── Construction du graphe LangGraph ──────────────────────────────────────────

def build_graph() -> Any:
    """
    Construit et compile le graphe LangGraph.

    Retourne un CompiledGraph prêt à être invoqué avec .invoke(state).
    """
    builder = StateGraph(AgentState)

    # Ajouter les nœuds
    builder.add_node("chunk_and_embed", node_chunk_and_embed)
    builder.add_node("retrieve",        node_retrieve)
    builder.add_node("classify",        node_classify)
    builder.add_node("route",           node_route)
    builder.add_node("summarize",       node_summarize)

    # Définir les transitions (arêtes)
    builder.add_edge(START,             "chunk_and_embed")
    builder.add_edge("chunk_and_embed", "retrieve")
    builder.add_edge("retrieve",        "classify")
    builder.add_edge("classify",        "route")
    builder.add_edge("route",           "summarize")
    builder.add_edge("summarize",       END)

    return builder.compile()


# Graphe compilé — singleton réutilisé pour chaque requête
graph = build_graph()


# ── Fonction d'entrée publique ─────────────────────────────────────────────────

def run_agent(
    raw_text: str,
    filename: str,
    style: str = "concis",
    language: str = "fr",
    detail_level: int = 3,
    include: dict | None = None,
) -> AgentState:
    """
    Lance l'agent LangGraph sur un texte extrait.

    Args:
        raw_text:     texte brut issu du DocumentParser
        filename:     nom original du fichier
        style:        style du résumé (concis/detaille/bullet/executif/pedagogique)
        language:     langue de sortie (fr/en/ar/es)
        detail_level: niveau de détail 1–5
        include:      dict {keypoints, stats, quotes, entities, conclusion}

    Returns:
        AgentState final après exécution complète du graphe
    """
    initial_state: AgentState = {
        **_state_defaults(),
        "raw_text":     raw_text,
        "filename":     filename,
        "style":        style,
        "language":     language,
        "detail_level": detail_level,
        "include":      include or {},
    }

    final_state: AgentState = graph.invoke(initial_state)
    return final_state