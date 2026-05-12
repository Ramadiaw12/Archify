<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20&height=220&section=header&text=DocSummarizer&fontSize=64&fontColor=fff&animation=twinkling&fontAlignY=38&desc=Production-Grade%20NLP%20Document%20Summarization%20Agent&descAlignY=58&descSize=18" width="100%"/>

<br/>

<p>
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white"/>
  <img src="https://img.shields.io/badge/LangGraph-1.0+-FF6B35?style=for-the-badge&logo=langchain&logoColor=white"/>
  <img src="https://img.shields.io/badge/Groq-LLM-F55036?style=for-the-badge&logo=groq&logoColor=white"/>
  <img src="https://img.shields.io/badge/RAG-ChromaDB-8A2BE2?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/PostgreSQL-Auth-336791?style=for-the-badge&logo=postgresql&logoColor=white"/>
  <img src="https://img.shields.io/badge/uv-Package%20Manager-DE5FE9?style=for-the-badge"/>
</p>

<p>
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square"/>
  <img src="https://img.shields.io/badge/Status-Production%20Ready-brightgreen?style=flat-square"/>
  <img src="https://img.shields.io/badge/PRs-Welcome-blue?style=flat-square"/>
  <img src="https://img.shields.io/badge/Auth-Google%20OAuth%20%2B%20JWT-orange?style=flat-square"/>
</p>

<br/>

> **DocSummarizer** is a production-grade NLP agent that transforms any document —
> PDF, Word, lesson, report — into a structured, precise, multilingual summary.
> Powered by **RAG + LangGraph + Groq** with a clean REST API, web interface,
> and secure authentication (Google OAuth + JWT + PostgreSQL).

<br/>

[**🚀 Quick Start**](#-quick-start) · [**🏗 Architecture**](#-architecture) · [**🔄 Pipeline**](#-pipeline-workflow) · [**📡 API**](#-api-reference) · [**🔐 Auth**](#-authentication)

<br/>

</div>

---

## 📋 Table of Contents

- [✨ Features](#-features)
- [🏗 Architecture](#-architecture)
- [🔄 Pipeline Workflow](#-pipeline-workflow)
- [📁 Project Structure](#-project-structure)
- [⚡ Quick Start](#-quick-start)
- [⚙️ Configuration](#️-configuration)
- [🔐 Authentication](#-authentication)
- [📡 API Reference](#-api-reference)
- [🧩 Core Components](#-core-components)
- [🔒 Security](#-security)
- [🗺 Roadmap](#-roadmap)
- [👩‍💻 Author](#-author)

---

## ✨ Features

<table>
<tr>
<td width="50%">

### 🤖 AI-Powered Pipeline
- **RAG** — ChromaDB + SentenceTransformers (local)
- **LangGraph** — Stateful 5-node agent graph
- **Groq LLM** — `llama-3.3-70b-versatile`, fast inference
- **Auto-routing** — Detects document type, adapts strategy
- **Multilingual** — FR · EN · AR · ES output

</td>
<td width="50%">

### 🔐 Secure Authentication
- **Google OAuth 2.0** — One-click sign in
- **Email / Password** — bcrypt hashing (rounds=12)
- **JWT tokens** — Access (15min) + Refresh (7 days)
- **Token rotation** — Automatic refresh on expiry
- **Brute-force protection** — Rate limiting + lockout

</td>
</tr>
<tr>
<td width="50%">

### 📄 Document Support
- ✅ PDF (pdfplumber)
- ✅ Word `.docx` / `.doc`
- ✅ Markdown `.md`
- ✅ Plain text `.txt`
- ✅ Rich Text `.rtf`
- 🔒 Deleted immediately after processing

</td>
<td width="50%">

### 🎛 Summary Styles
| Style | Description |
|-------|-------------|
| `concis` | 2–3 paragraphs |
| `detaille` | 4–6 paragraphs |
| `bullet` | Numbered key points |
| `executif` | Executive report |
| `pedagogique` | Student revision sheet |

</td>
</tr>
</table>

---

## 🏗 Architecture

```mermaid
graph TB
    subgraph CLIENT["🌐 Client Layer"]
        UI[Web Interface<br/>HTML · CSS · JS]
        AUTH_UI[Auth Modal<br/>Login · Register · Google]
    end

    subgraph SERVER["⚡ FastAPI Server"]
        EP_SUMMARIZE[POST /api/summarize]
        EP_AUTH[/auth/* endpoints]
        EP_HISTORY[GET /api/summaries]
        STATIC[Static Files<br/>index.html · style.css · app.js]
    end

    subgraph AUTH["🔐 Auth Layer"]
        GOOGLE[Google OAuth 2.0]
        JWT[JWT Tokens<br/>Access + Refresh]
        BCRYPT[bcrypt Password<br/>rounds=12]
        RATE[Rate Limiter<br/>Sliding Window]
    end

    subgraph AGENT["🧠 LangGraph Agent"]
        N1[chunk_and_embed]
        N2[retrieve]
        N3[classify]
        N4[route]
        N5[summarize]
        N1 --> N2 --> N3 --> N4 --> N5
    end

    subgraph RAG["🔍 RAG Components"]
        CHROMA[ChromaDB<br/>Vector Store]
        ST[SentenceTransformers<br/>all-MiniLM-L6-v2]
        CHUNKER[TextChunker<br/>800w + 100w overlap]
    end

    subgraph DB["🗄️ PostgreSQL"]
        USERS[users table]
        SESSIONS[sessions table]
        SUMMARIES[summaries table]
    end

    subgraph LLM["⚡ Groq"]
        GROQ[llama-3.3-70b-versatile<br/>temperature=0]
    end

    UI --> EP_SUMMARIZE
    AUTH_UI --> EP_AUTH
    EP_AUTH --> AUTH
    AUTH --> DB
    EP_SUMMARIZE --> AGENT
    N1 --> RAG
    N2 --> CHROMA
    N5 --> LLM
    N3 --> LLM
    EP_SUMMARIZE --> DB
    EP_HISTORY --> DB

    style CLIENT fill:#3D1A14,stroke:#A63226,color:#F5EFE6
    style SERVER fill:#5C2A1F,stroke:#A63226,color:#F5EFE6
    style AUTH fill:#7A3B2E,stroke:#D4B896,color:#F5EFE6
    style AGENT fill:#A63226,stroke:#D4B896,color:#F5EFE6
    style RAG fill:#3D1A14,stroke:#D4B896,color:#F5EFE6
    style DB fill:#5C2A1F,stroke:#D4B896,color:#F5EFE6
    style LLM fill:#7A3B2E,stroke:#A63226,color:#F5EFE6
```

---

## 🔄 Pipeline Workflow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant FE as 🌐 Frontend
    participant API as ⚡ FastAPI
    participant AUTH as 🔐 Auth
    participant DP as 📄 DocumentParser
    participant RAG as 🔍 ChromaDB
    participant LG as 🧠 LangGraph
    participant GROQ as ⚡ Groq LLM
    participant DB as 🗄️ PostgreSQL

    User->>FE: Upload document + options
    FE->>API: POST /api/summarize + Bearer token

    API->>AUTH: Validate JWT (optional)
    AUTH-->>API: UserPublic | None

    API->>API: Validate file (ext, size)
    API->>API: Save to /tmp with UUID

    API->>DP: parse(file_path)
    DP->>DP: Detect format & extract text
    DP-->>API: ParsedDocument {text, pages, words}

    API->>LG: run_agent(text, options)

    Note over LG: Node 1 — chunk_and_embed
    LG->>RAG: TextChunker.chunk(text)
    RAG-->>LG: chunks[] (800w + 100w overlap)

    Note over LG: Node 2 — retrieve
    LG->>RAG: ChromaDB.from_texts(chunks)
    RAG-->>LG: top-5 relevant chunks

    Note over LG: Node 3 — classify
    LG->>GROQ: Classify document type
    GROQ-->>LG: {type, domain, complexity}

    Note over LG: Node 4 — route
    LG->>LG: Select summarization strategy

    Note over LG: Node 5 — summarize
    LG->>GROQ: Generate structured JSON summary
    GROQ-->>LG: {summary, key_points, topics...}

    LG-->>API: AgentState (final)
    API->>API: Delete tmp file

    opt User is authenticated
        API->>DB: INSERT INTO summaries
        DB-->>API: summary_id
    end

    API-->>FE: JSON Response
    FE-->>User: Render summary + stats + history
```

---

## 🔀 LangGraph State Machine

```mermaid
stateDiagram-v2
    [*] --> chunk_and_embed : raw_text

    chunk_and_embed --> retrieve : chunks[]
    chunk_and_embed --> ERROR : empty document

    retrieve --> classify : RAG context (top-5)

    classify --> route : groq_meta {type, domain}

    route --> summarize : strategy selected
    note right of route
        court | pedagogique
        scientifique | rapport_formel
        general
    end note

    summarize --> [*] : AgentState
    note right of summarize
        summary · key_points
        sentiment · complexity
        main_topics
    end note

    summarize --> ERROR : Groq failure
    ERROR --> [*] : error message
```

---

## 📁 Project Structure

```
DocSummarizer/
│
├── 📄 pyproject.toml              # uv dependencies
├── 🔐 .env.example                # Environment variables template
├── 📖 README.md
│
├── backend/
│   ├── ⚙️  config.py              # Centralized settings (pydantic-settings)
│   ├── 📄 document_parser.py      # PDF · DOCX · TXT · MD · RTF extraction
│   ├── 🔍 rag.py                  # TextChunker · ChromaDB · EmbeddingEngine
│   ├── 🧠 agent.py                # LangGraph 5-node pipeline
│   ├── ⚡ main.py                  # FastAPI server + all endpoints
│   │
│   ├── auth/
│   │   ├── 🔑 security.py         # bcrypt + JWT generation/validation
│   │   ├── 🌐 google.py           # Google OAuth 2.0 flow
│   │   ├── 🔧 service.py          # Auth business logic
│   │   └── 🛣️  router.py          # Auth endpoints
│   │
│   ├── db/
│   │   ├── 🗄️  database.py        # SQLAlchemy async engine + sessions
│   │   └── 📋 models.py           # User · Session · Summary ORM models
│   │
│   └── middleware/
│       ├── 🔒 auth_dep.py         # FastAPI auth dependencies
│       └── 🛡️  rate_limit.py      # Sliding window rate limiter
│
└── frontend/
    ├── 🌐 index.html              # Semantic HTML5 + auth modal
    ├── 🎨 style.css               # Beige · Rouge · Blanc palette
    └── ⚙️  app.js                  # Auth · Upload · Pipeline · Results
```

---

## ⚡ Quick Start

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | ≥ 3.12 | [python.org](https://python.org) |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| PostgreSQL | ≥ 14 | `sudo apt install postgresql` |
| Groq API Key | — | [console.groq.com](https://console.groq.com) (free) |

### Installation

```bash
# 1. Clone
git clone https://github.com/Ramadiaw12/Archify.git
cd Archify

# 2. Install dependencies
uv sync

# 3. Setup PostgreSQL
sudo -u postgres psql -c "CREATE USER docuser WITH PASSWORD 'yourpassword';"
sudo -u postgres psql -c "CREATE DATABASE docsummarizer OWNER docuser;"

# 4. Configure environment
cp .env.example backend/.env
nano backend/.env
```

**`backend/.env`:**
```env
# Groq (required)
GROQ_API_KEY=gsk_xxxxxxxxxxxx
GROQ_MODEL=llama-3.3-70b-versatile

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://docuser:yourpassword@localhost:5432/docsummarizer

# JWT — generate with: openssl rand -hex 32
JWT_SECRET_KEY=your-secret-key-here

# Google OAuth (optional)
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxx
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback
```

```bash
# 5. Start
cd backend
uv run python main.py
```

```
[Config] GROQ        : ✅
[Config] DATABASE    : postgresql+asyncpg://...
[Config] JWT         : ✅
[Config] GOOGLE_AUTH : ✅
✅  DocSummarizer démarré → http://localhost:8000
🤖  Groq : llama-3.3-70b-versatile
🔐  Google OAuth : ✅
```

Open **http://localhost:8000** 🚀

---

## ⚙️ Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_API_KEY` | *(required)* | Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | LLM model |
| `DATABASE_URL` | *(required)* | PostgreSQL async URL |
| `JWT_SECRET_KEY` | *(required)* | JWT signing secret |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local embedding model |
| `CHUNK_SIZE` | `800` | RAG chunk size (words) |
| `CHUNK_OVERLAP` | `100` | Overlap between chunks |
| `TOP_K_CHUNKS` | `5` | Retrieved chunks per query |
| `MAX_FILE_SIZE_MB` | `20` | Max upload size |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | JWT access token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | JWT refresh token TTL |

---

## 🔐 Authentication

### Flow Diagram

```mermaid
graph LR
    A[User] -->|Email + Password| B[POST /auth/register]
    A -->|Email + Password| C[POST /auth/login]
    A -->|Click Google| D[GET /auth/google/login]

    B --> E[bcrypt hash]
    C --> F[bcrypt verify]
    D --> G[Google OAuth 2.0]

    E --> H[Create JWT tokens]
    F --> H
    G --> I[Verify ID token]
    I --> H

    H --> J[access_token 15min]
    H --> K[refresh_token 7 days]

    J --> L[Protected endpoints]
    K --> M[POST /auth/refresh]
    M --> H
```

### Security Measures

| Feature | Implementation |
|---------|----------------|
| Password hashing | bcrypt (rounds=12) |
| Token type | JWT HS256 |
| Access token TTL | 15 minutes |
| Refresh token TTL | 7 days (stored in DB) |
| Token rotation | Automatic on refresh |
| Brute-force protection | 5 attempts → 15min lockout |
| Rate limiting | 10 login/15min · 5 register/h |
| File security | UUID naming + immediate deletion |
| Anti-enumeration | Same error for wrong email/password |

---

## 📡 API Reference

### `POST /api/summarize`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | File | *required* | Document to analyze |
| `style` | string | `concis` | Summary style |
| `lang` | string | `fr` | Output language (fr/en/ar/es) |
| `detail_level` | int 1–5 | `3` | Verbosity level |
| `include_keypoints` | bool | `true` | Extract key points |
| `include_stats` | bool | `true` | Include figures |
| `include_conclusion` | bool | `true` | Add conclusion |

**Response:**
```json
{
  "success": true,
  "summary_id": "uuid-if-authenticated",
  "summary": "Ce rapport présente...",
  "key_points": ["Point 1", "Point 2"],
  "document_type": "Rapport financier",
  "sentiment": "positif",
  "complexity": "intermédiaire",
  "main_topics": ["Finance", "Stratégie"],
  "stats": {
    "word_count_original": 4820,
    "word_count_summary": 210,
    "compression_ratio": 95.6,
    "chunk_count": 7,
    "read_time_min": 24
  },
  "pipeline": {
    "route": "rapport_formel",
    "language": "fr",
    "model": "llama-3.3-70b-versatile",
    "provider": "Groq"
  }
}
```

### Auth Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/auth/register` | Email/password registration |
| `POST` | `/auth/login` | Email/password login |
| `POST` | `/auth/logout` | Revoke refresh token |
| `POST` | `/auth/refresh` | Rotate tokens |
| `GET` | `/auth/me` | Get current user profile |
| `GET` | `/auth/google/login` | Redirect to Google OAuth |
| `GET` | `/auth/google/callback` | Google OAuth callback |
| `GET` | `/api/summaries` | Get user's summary history |
| `GET` | `/api/health` | Server health check |

---

## 🧩 Core Components

### RAG Pipeline — `rag.py`

```python
# ChromaDB for vector storage — no dimension mismatch
vectorstore = Chroma.from_texts(
    texts=chunks,
    embedding=SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2"),
    client=chromadb.EphemeralClient(),
)
results = vectorstore.similarity_search(auto_query, k=5)
```

### LangGraph Agent — `agent.py`

```python
builder = StateGraph(AgentState)
builder.add_node("chunk_and_embed", node_chunk_and_embed)
builder.add_node("retrieve",        node_retrieve)       # ChromaDB
builder.add_node("classify",        node_classify)       # Groq fast
builder.add_node("route",           node_route)          # Heuristic
builder.add_node("summarize",       node_summarize)      # Groq main
builder.add_edge(START, "chunk_and_embed")
# ... → retrieve → classify → route → summarize → END
graph = builder.compile()
```

### Groq Integration — `agent.py`

```python
# Native Groq client — no LangChain dependency
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
response = client.chat.completions.create(
    model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt_with_rag_context},
    ],
    temperature=0,
    max_tokens=2048,
)
```

---

## 🔒 Security

| Concern | Implementation |
|---------|----------------|
| File storage | UUID filenames, deleted after processing |
| Path traversal | Extension whitelist + UUID |
| SQL injection | SQLAlchemy ORM (parameterized queries) |
| Password storage | bcrypt, never plaintext |
| Token revocation | Refresh tokens stored in DB |
| CORS | Configurable origins |
| Rate limiting | Per-IP sliding window |

---

## 🗺 Roadmap

- [x] RAG pipeline with ChromaDB
- [x] LangGraph 5-node agent
- [x] Groq LLM integration (llama-3.3-70b)
- [x] Multi-format document support
- [x] Multilingual output (FR, EN, AR, ES)
- [x] Google OAuth 2.0
- [x] Email/password authentication
- [x] PostgreSQL + SQLAlchemy async
- [x] JWT with refresh token rotation
- [x] Summary history per user
- [ ] Streaming response (SSE)
- [ ] Docker + docker-compose
- [ ] Alembic migrations
- [ ] Export to PDF / DOCX
- [ ] Batch processing
- [ ] Conversation mode on document

---

## 👩‍💻 Author

<div align="center">

<table>
<tr>
<td align="center" style="padding:20px">
<br/>
<strong style="font-size:20px">DIAWANE Ramatoulaye</strong>
<br/><br/>
<a href="mailto:rdiawane2001@gmail.com">
  <img src="https://img.shields.io/badge/Gmail-rdiawane2001%40gmail.com-D14836?style=for-the-badge&logo=gmail&logoColor=white"/>
</a>
<br/><br/>
<a href="https://github.com/Ramadiaw12/Archify">
  <img src="https://img.shields.io/badge/GitHub-Ramadiaw12%2FArchify-181717?style=for-the-badge&logo=github&logoColor=white"/>
</a>
</td>
</tr>
</table>

</div>

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20&height=120&section=footer" width="100%"/>

**Built with ❤️ by DIAWANE Ramatoulaye**

**RAG · LangGraph · Groq · FastAPI · PostgreSQL · uv**

</div>