# Agentic RAG Chatbot

A knowledge assistant that answers questions **only** from documents you upload, and that decides
for itself what to look up. Claude is given three read-only tools over your knowledge base —
search, list, read — and calls them as many times as a question needs (within configurable
limits). Every sentence it finally shows you has been checked against the passages it cites; if
the documents don't cover the question, you get a plain "I couldn't find enough information"
instead of a guess.

```
Question ─► Claude decides what to retrieve ─► read-only tools ─► evidence ledger
         ─► Claude answers with citations ─► citation validation ─► sentence verification
         ─► retry once if needed ─► validated answer (or a safe fallback) ─► you
```

The UI shows what the agent is doing while it works (searching, reading, validating) without
exposing any model reasoning.

## Contents

- [How it works](#how-it-works)
- [Technology](#technology)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Running locally](#running-locally)
- [Using the app](#using-the-app)
- [The agent's tools](#the-agents-tools)
- [Limits](#limits)
- [Guardrails](#guardrails)
- [API](#api)
- [Project layout](#project-layout)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

## How it works

```
Browser — React SPA (light mode):  Ask  ·  Knowledge Base
   │  /api/*  (the Vite dev server proxies to the API: one origin, no CORS)
   ▼
FastAPI  (127.0.0.1:8010)
 INGESTION   POST /api/documents → 202, then a background worker thread
   validate → extract SECTIONS (page · heading · row · record · part) → store sections
   → chunk → embed (Ollama) → index → READY     (any failure → FAILED + a safe reason)

 AGENT RUN   POST /api/ask → Server-Sent Events: run · activity… · result | error
   AgentRun: deadline · tool-call budget · evidence ledger · activity events · cancel flag
     └─ Anthropic SDK tool runner — Claude calls search_knowledge_base / list_documents /
        read_section; every result is recorded in the ledger as citable evidence
   GUARDRAILS: citation validation → sentence split → verifier (2nd Claude call) → code rules
               → retry once without tools → validated answer, or a fixed fallback
───────────────────────────────────────────────────────────────────────────────────
PostgreSQL 17 + pgvector (Docker, 127.0.0.1:5434)   Ollama nomic-embed-text (768-d)   Anthropic API
```

Design principle: **Claude decides what to retrieve; the application decides what may be said.**
The model never sees configuration, secrets or any write capability, and the UI never sees model
text that has not passed validation. The full design (decisions, tool contracts, schema, UI
directions) is in [docs/DESIGN.md](docs/DESIGN.md).

## Technology

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, uvicorn, managed with [uv](https://docs.astral.sh/uv/) |
| Agent | Anthropic Python SDK — beta tool runner (`client.beta.messages.tool_runner`), `@beta_tool`, structured outputs for the verifier, server-side refusal fallback |
| Model | `claude-opus-5-5` by default (`ANTHROPIC_MODEL`), adaptive thinking, effort `high` |
| Embeddings | Ollama `nomic-embed-text`, 768 dimensions |
| Database | PostgreSQL 17 + pgvector in Docker (this project's own container, port 5434) |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, lucide icons |
| Tests | pytest (offline scripted agent runs + database integration + live evals), vitest |

No agent framework (LangChain, LlamaIndex) is used.

## Prerequisites

- Windows, macOS or Linux with **Docker Desktop** (for PostgreSQL + pgvector)
- **Python 3.12** and **uv**
- **Node.js 20+** (24 recommended)
- **Ollama** with the embedding model: `ollama pull nomic-embed-text`
- An **Anthropic API key**

## Setup

1. Configuration — copy the example and fill in real values:

   ```bash
   cp .env.example .env
   ```

   Set `ANTHROPIC_API_KEY`, and choose `POSTGRES_PASSWORD` (it must match the password inside
   `DATABASE_URL`). Everything else has a sensible default; see the comments in `.env.example`.

2. Database — start PostgreSQL with pgvector (reads the `POSTGRES_*` values from `.env`):

   ```bash
   docker compose up -d
   ```

3. Backend dependencies:

   ```bash
   cd backend && uv sync
   ```

4. Frontend dependencies:

   ```bash
   cd frontend && npm install
   ```

5. Sample documents (optional) — build the PDF and DOCX samples:

   ```bash
   uv run --project backend python sample-documents/generate.py
   ```

## Running locally

Backend (creates the tables on first start):

```bash
cd backend && uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8010
```

Frontend:

```bash
cd frontend && npm run dev
```

Open <http://127.0.0.1:5174>. The header shows three status dots (database, embeddings, Claude);
`GET http://127.0.0.1:8010/api/health` returns the same checks plus the non-secret configuration.

## Using the app

1. **Knowledge Base** — drop in PDF, DOCX, Markdown, text, CSV or JSON files (up to
   `MAX_UPLOAD_MB`). Each file is validated, parsed into sections, chunked, embedded and indexed;
   the table shows its status, parser facts (pages, rows and columns, headings) and any failure
   reason. Duplicate content is rejected; originals are not kept.
2. **Ask** — type a question. A run card shows the agent's activity live (question analyzed,
   knowledge base searches with their queries, documents read with their locations, sources
   validated, answer prepared), then the **Answer** and its **Sources**. Expand a source to see
   the exact cited text. After a run the timeline collapses to a summary; "Show activity"
   reopens it.
3. Stop a run with the square button; it cancels the agent server-side.

The agent answers only from what is in the knowledge base. Questions it cannot ground get the
fallback *"I couldn't find enough information in the provided knowledge base to answer this
question."*

## The agent's tools

All three tools are read-only (SELECT statements and one embedding call); they receive a
read-only repository object that has no write methods. Every executed call counts toward the
budget and is shown in the UI.

| Tool | Input | Returns |
|---|---|---|
| `search_knowledge_base(query, document?)` | a focused query (≤ 500 chars), optional document id or file name | the `SEARCH_TOP_K` best chunks at or above `SEARCH_MIN_SIMILARITY`, each as a citable `search_result` block with the document name and location (page, section, rows, records, part) |
| `list_documents()` | — | a JSON list: id, name, type, status, searchable flag, pages / rows + columns / records / sections + outline (headings). Never paths, hashes or settings |
| `read_section(document, location)` | `page:4` · `section:<heading or path>` · `rows:12-18` · `records:3-5` · `part:2` | the exact stored content at that location as a citable block (one text unit per paragraph / row / record), capped at `READ_SECTION_MAX_CHARS` and `READ_MAX_ROWS` with a note on how to continue |

Locations are never guessed: if the parser did not record a page, heading or row, the tool says
so. Tool failures (unknown document, invalid location, out of range) go back to Claude as error
results so it can adapt; a lost database ends the run with a safe error.

## Limits

| Setting | Default | Enforced where |
|---|---|---|
| `MAX_TOOL_CALLS` | 8 | the tool wrapper refuses further calls; the loop is also bounded to `MAX_TOOL_CALLS + 1` Claude requests |
| `MAX_AGENT_TIME_SECONDS` | 90 | checked before every tool execution and before each Claude request (an in-flight request can run until `ANTHROPIC_TIMEOUT_SECONDS`) |
| `MAX_CONSECUTIVE_TOOL_FAILURES` | 3 | the loop stops after that many failed tool results in a row |

When a limit is hit, one final Claude request with tools disabled asks for an answer from the
evidence already retrieved (or the fallback); the result carries `stopped_by` and the UI shows
a short note. Closing the browser connection cancels the run.

## Guardrails

1. **Citations come from the API, not from prose.** Tool results are sent as `search_result`
   blocks with citations enabled, so Claude's final answer carries citations whose `source`,
   block range and `cited_text` are produced by the API.
2. **Citation validation (code).** A citation is kept only if its `source` is in the run's
   evidence ledger, its block range is in bounds, and its cited text equals the ledger's units.
   Document names and locations shown to the user come from the ledger (i.e. the database).
3. **Sentence-level verification.** The draft is split into sentences in code; a second Claude
   call (schema-constrained JSON, no tools) labels each one against the passages it cites; code
   then enforces: every sentence labelled, "supported" requires a valid citation, any
   "unsupported" sentence rejects the draft. Totals, counts and averages the documents don't
   state are rejected by instruction.
4. **Retry once, then fall back.** A rejected draft is rewritten once (same conversation,
   rejected sentences listed, no tools). Still rejected → "unverified" with only the passages
   behind sentences that did pass. No citation at all → not found.
5. **Prompt injection.** Document text is returned to Claude as data blocks; the system prompt
   says it is never an instruction; tools cannot write, change limits, or reach settings; the UI
   renders text nodes only; activity details are sanitised. A document can at most *say*
   something, and anything it says still has to pass verification.
6. **No reasoning exposed.** Thinking blocks are never forwarded; activity labels are generated
   by the application.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | service checks (database, embeddings, Claude) and non-secret configuration |
| POST | `/api/documents` | upload one file (multipart field `file`) → `202`, processed in the background |
| GET | `/api/documents` | list documents with status, counts and metadata |
| GET | `/api/documents/{id}` | one document (metadata includes outline / columns) |
| DELETE | `/api/documents/{id}` | delete a document with its sections and chunks |
| POST | `/api/ask` | `{"question": "…"}` → `text/event-stream` |

`/api/ask` events: `run` (limits) → `activity` (`id`, `kind`, `status: running|done|failed`,
`label`, optional `detail`, `results`, `error`) → exactly one `result` (`status`, `message`,
`segments`, `sources`, `run`) or `error` (`code`, `message`). A comment line `: ping` is sent
every 10 s to keep the connection alive during long requests.

## Project layout

```
agentic-rag/
├── .env.example            every setting with placeholders (copy to .env)
├── docker-compose.yml      PostgreSQL 17 + pgvector on 127.0.0.1:5434
├── docs/                   DESIGN.md (architecture + decisions), ui-directions.html (mockups)
├── sample-documents/       fictional Lakeside Health Partners files + EVAL_QUESTIONS.md + generate.py
├── backend/                Python 3.12 · FastAPI · uv
│   ├── app/
│   │   ├── main.py         app factory, JSON logging, startup checks, error handlers
│   │   ├── config.py       settings from .env (validated once; secrets never logged)
│   │   ├── llm.py          Anthropic client + safe error mapping
│   │   ├── api/            health.py · documents.py · ask.py (SSE)
│   │   ├── db/             schema.sql · read_repository.py (tools' view) · repository.py (writes)
│   │   ├── ingestion/      validation · extractors · sections · chunking · pipeline
│   │   ├── embeddings/     provider protocol + Ollama implementation
│   │   ├── agent/          run.py (limits, ledger, activity) · tools.py · loop.py · prompts.py · service.py
│   │   └── grounding/      citations.py · sentences.py · verifier.py · result.py
│   └── tests/              unit · agent (scripted Claude, real runner + DB) · integration · evals (live)
└── frontend/               React 19 · TypeScript · Vite · Tailwind CSS 4
    └── src/                App, api.ts, askReducer.ts, hooks.ts, pages/, components/
```

## Testing

Offline suite (no Ollama, no Anthropic; needs the Docker PostgreSQL, uses a throw-away
`<db>_test` database):

```bash
cd backend && uv run pytest -q
```

It covers extraction and chunking, upload validation, the evidence ledger and citation
validation, sentence splitting and verdict rules, scripted end-to-end agent runs (single search,
multi-search, cross-document, discovery, section reads, insufficient information, unrelated
questions, hallucination rejection and retry, forged citations, prompt injection, tool
failures, the tool-call budget, the iteration bound, timeouts, cancellation, refusals, API and
database outages), the documents API, malformed documents and the health endpoint. Claude is
replaced by a scripted client that drives the **real** SDK tool runner, tools, repository and
guardrails.

Live evaluation (real Ollama and Claude, costs tokens; build the samples first):

```bash
cd backend && uv run pytest -m live tests/evals -q
```

Frontend:

```bash
cd frontend && npm test && npm run lint && npm run build
```

## Troubleshooting

- **`docker info` fails / Docker Desktop exits right after starting** — its backend log
  (`%LOCALAPPDATA%\Docker\log\host\com.docker.backend.exe.log`) may show
  `listening on unix://…\Docker\run\<name>.sock … The file cannot be accessed by the system`.
  Stale socket files left by an unclean shutdown cannot be deleted; rename the directory that
  holds them (`%LOCALAPPDATA%\Docker\run`, and `%LOCALAPPDATA%\docker-secrets-engine` if named)
  and start Docker Desktop again.
- **Backend exits with "PostgreSQL is unreachable"** — run `docker compose up -d` and wait for
  `docker ps` to show the container as healthy; check `DATABASE_URL` uses port 5434.
- **"EMBEDDING_DIMENSION is 768 but the database stores …"** — the embedding model or
  dimension changed; drop the tables (or the `agentic_pgdata` volume) and upload again.
- **Embeddings dot is red** — start the Ollama app or `ollama serve`, and
  `ollama pull nomic-embed-text`.
- **Claude dot is red** — the key in `.env` is missing or rejected, or the model name is not
  available to your account.
- **Uploads stay "Processing"** — the first embedding call waits for Ollama to load the model;
  a server restart marks interrupted documents as failed so they can be uploaded again.
- **Use `127.0.0.1`, not `localhost`** on Windows: `localhost` may resolve to IPv6 first and
  stall.
