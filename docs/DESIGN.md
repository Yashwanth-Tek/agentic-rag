# Agentic RAG Chatbot — Design (Phase 0, for approval)

Status: **design only, nothing implemented.** This document proposes the architecture, agent
flow, tool contracts, data model, API, UI directions, guardrails, configuration, dependencies and
test plan for a new, standalone agentic RAG chatbot. Every choice that is not forced by the brief
is listed in §14 as **DECISION REQUIRED** with options and a recommendation. Implementation
starts only after those are approved.

Date: 2026-10-06

---

## 0. Boundaries (non-negotiable)

| Rule | How it is honoured |
|---|---|
| Completely separate project | New folder `C:\Users\YashwanthBandaru\projects\agentic-rag` with its own backend, frontend, config, dependencies, database, API, tests, README and design system. |
| Existing chatbot untouched | `~/projects/rag-chatbot` is read-only reference material. Nothing there is modified, imported, or linked. Concepts reused (re-implemented, not copied as a dependency): section-aware extraction, chunk packing of CSV rows, the strict sentence verifier, SSE progress events. |
| No GitHub / no remote | No `git init`, `git commit`, `git push`, branches, PRs, Actions, or registry pushes. The user handles version control later. A `.gitignore` is written so that a later `git init` is safe. |
| Local only | Everything runs on this machine: Postgres+pgvector in Docker, Ollama natively, the Anthropic API over HTTPS. |
| Port plan | API **8010**, UI **5174**, Postgres **5434**. (Existing chatbot: 8000 / 5173 / 5432; native PostgreSQL 17: 5433, no pgvector.) |

---

## 1. Architecture

```
Browser — React SPA, light mode only:  Ask  ·  Knowledge Base
   │  /api/*   (Vite dev server proxies to the API → one origin, no CORS)
   ▼
FastAPI  (Python 3.12, uv)  ·  127.0.0.1:8010
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │ INGESTION   POST /api/documents → 202, then a background worker thread        │
 │   validate → extract SECTIONS (page · heading · row · record · part)          │
 │   → store sections → chunk sections → embed (Ollama) → index → READY         │
 │   Status recorded at each step; any failure → FAILED + a safe reason.        │
 ├──────────────────────────────────────────────────────────────────────────────┤
 │ AGENT RUN   POST /api/ask → SSE: run · activity… · result | error            │
 │                                                                              │
 │   AgentRun (per question): deadline · tool-call budget · evidence ledger ·   │
 │             activity emitter · cancel flag · failure counter                  │
 │        │                                                                     │
 │        ├─ Anthropic SDK tool runner (beta)  — Claude decides what to call    │
 │        │     search_knowledge_base(query, document?)  → embed + pgvector     │
 │        │     list_documents()                          → documents table     │
 │        │     read_section(document, location)          → sections table      │
 │        │     (all read-only; every result is recorded in the ledger)         │
 │        │                                                                     │
 │        └─ final answer with API citations into the returned evidence         │
 │                                                                              │
 │   GUARDRAILS (code has the last word)                                        │
 │     citation validation → sentence split → verifier (2nd Claude call,        │
 │     structured output) → code rules → retry once (no tools) → fallback       │
 └──────────────────────────────────────────────────────────────────────────────┘
PostgreSQL 17 + pgvector (Docker, 127.0.0.1:5434)   Ollama nomic-embed-text (768-d)   Anthropic API
```

### Components

| Component | Responsibility | Talks to |
|---|---|---|
| `api/` | HTTP + SSE endpoints, request validation, safe error mapping | service layer |
| `ingestion/` | validation, extractors (PDF, DOCX, MD, TXT, CSV, JSON), section builder, chunking, pipeline | repository, embedder |
| `embeddings/` | Ollama provider (`/api/embed`), query/document prefixes, dimension check | Ollama |
| `agent/` | tools, evidence ledger, run limits, tool-runner loop, activity events, prompts | Anthropic, repository, embedder |
| `grounding/` | citation validation, sentence split, verifier call, code rules, retry, result assembly | Anthropic |
| `db/` | `schema.sql` + repository (every SQL statement; read methods separated from write methods) | PostgreSQL |
| `frontend/` | Ask page (run cards + live activity), Knowledge Base page, health strip | `/api/*` |

Design principle: **Claude decides what to retrieve; the application decides what may be said.**
The model never sees configuration, secrets, or write capability. The UI never sees model text
that has not passed validation.

---

## 2. Agent flow

```
POST /api/ask {question}
   │
   ├─ validate (1–2000 chars) ── knowledge base has no READY document? ──► result: kb_empty
   │
   ├─ AgentRun created: deadline = now + MAX_AGENT_TIME, budget = MAX_TOOL_CALLS
   │  activity ▸ "Understanding question"
   │
   ├─ tool runner iteration 1 … n   (each iteration = one Claude request)
   │     Claude returns tool_use block(s)
   │        ▸ wrapper checks: cancelled? deadline passed? budget left? fatal error?
   │        ▸ activity "Searching knowledge base «query»" / "Listing documents" /
   │          "Reading <document> · <location>"   (status: running → done | failed)
   │        ▸ tool executes (read-only) → result blocks → evidence ledger E1, E2 …
   │        ▸ results returned to Claude as `search_result` blocks (citable)
   │     Claude returns text only (end_turn)  ──────────────────────────► DRAFT
   │
   ├─ loop ends early when: budget exhausted · deadline passed · 3 consecutive tool
   │  failures · refusal/max_tokens · fatal error · client disconnected
   │        ▸ budget/deadline/failures: one WRAP-UP request with tool_choice "none":
   │          "answer only from the evidence already retrieved, or say you could not
   │           find enough"  ───────────────────────────────────────────► DRAFT
   │        ▸ fatal / refusal / disconnect: stop, no draft
   │
   ├─ GUARDRAILS on DRAFT          activity ▸ "Validating sources"
   │     1. no citation at all ─────────────────────────────────────────► not_found
   │     2. citation validation: every citation must point at a ledger entry
   │        (source URI the app itself generated); others are dropped
   │     3. sentence split (code) + verifier (Claude, structured JSON) + code rules
   │        all sentences labelled · "supported" needs a valid citation ·
   │        any "unsupported" ⇒ rejected
   │     4. rejected ⇒ RETRY once (same conversation, rejected sentences listed,
   │        tool_choice "none") ⇒ back to 2
   │     5. still rejected ⇒ unverified (message + passages behind passing sentences)
   │        no "supported" sentence ⇒ not_found
   │
   └─ result: answered | partial | not_found | unverified | kb_empty | limit notes
        segments (validated sentences + source numbers) · sources (from the ledger,
        i.e. from the database: document name, location, cited text) · run summary
```

### Sequence (typical two-search, one-read question)

```
UI            API/AgentRun           Claude (tool runner)          Tools / DB
 │ POST /ask ──►│                           │                          │
 │◄── run ──────│ system + tools + question►│                          │
 │              │◄─ tool_use: search(q1) ───│                          │
 │◄─ activity ──│ search q1 ───────────────────────────────────────────►│ embed + pgvector
 │◄─ activity ──│◄── 4 results (E1–E4) ────────────────────────────────│
 │              │ tool_result (search_result blocks) ►│                 │
 │              │◄─ tool_use: search(q2), read(doc, rows:12-18) (parallel)
 │◄─ activity×2 │ … E5–E7, E8 ───────────────────────────────────────►│
 │              │ tool_results ────────────►│                          │
 │              │◄─ end_turn: answer text + citations (E2, E8)         │
 │◄─ activity ──│ validate citations · split · verifier call ►│        │
 │              │◄─ verdicts                │                          │
 │◄─ result ────│ segments + sources (names/locations from DB)         │
```

### Why the agent cannot run forever

| Limit | Enforced by | Default |
|---|---|---|
| `MAX_TOOL_CALLS` executed tool calls per question | tool wrapper (returns an error result "budget exhausted" instead of executing) + runner `max_iterations = MAX_TOOL_CALLS + 1` as a hard loop bound | 8 |
| `MAX_AGENT_TIME` seconds | checked before every tool execution and before every new Claude request; in-flight request bounded by `ANTHROPIC_TIMEOUT_SECONDS` × (1 + retries) | 90 s |
| `MAX_CONSECUTIVE_TOOL_FAILURES` | failure counter in AgentRun; reset on success | 3 |
| Unrecoverable error (database down, embedding service down for a search, Anthropic auth/rate limit) | wrapper sets `run.fatal`; loop stops at the next check; endpoint emits a safe `error` event | — |
| Client disconnect | SSE generator sets `run.cancelled`; the worker stops at the next check | — |

Honest note: the SDK runner stops *starting* new iterations when `max_iterations` is reached and
simply returns without a final answer. That is why the wrap-up request exists: it is a separate,
single Claude call with tools disabled (`tool_choice: {"type": "none"}`) on the mirrored
conversation. The same mechanism serves the grounding retry.

---

## 3. Tool contracts

All three tools are Python functions decorated with the SDK's `@beta_tool` (schema generated from
the type hints and docstring; inputs validated before the function runs). They are created per
run by a small factory so each closure holds its own `AgentRun` (budget, ledger, emitter). Each
wrapper performs, in order: cancel/deadline/budget check → `activity: running` → execute → record
evidence → `activity: done` (or `failed`) → return. Errors are raised as `ToolError`, which the
runner converts into a `tool_result` with `is_error: true` so Claude can adapt.

Every tool is **read-only by construction**: the tools receive a `ReadOnlyRepository` object that
exposes SELECT-backed methods only (no insert/update/delete methods exist on it).

### 3.1 `search_knowledge_base(query, document=None)`

| | |
|---|---|
| Purpose | Semantic search over ready documents. Claude writes the query and may call it many times with different wording or a document filter. |
| Input | `query: str` — 1–500 characters. `document: str \| None` — optional document id or exact file name to restrict the search to one document. |
| Behaviour | Embed the query (Ollama, query prefix) → exact cosine search over chunks of READY documents embedded by the current model → keep `SEARCH_TOP_K` best (default 6) at or above `SEARCH_MIN_SIMILARITY` (default 0.50). |
| Output (success) | A text block header, then one `search_result` block per hit: |

```
text:  Found 3 passages for "June readmission target":
       E7  riverside-department-metrics-q2-2026.csv · Rows 12–18 · relevance 0.71
       E8  riverside-discharge-policy.pdf · Page 4 · relevance 0.63
       E9  …
search_result ×3:
  { type: "search_result",
    source:  "kb://3f2a…/rows:12-18?chunk=9b1c…",   ← app-generated, ledger key
    title:   "riverside-department-metrics-q2-2026.csv — Rows 12–18",
    content: [ {type:"text", text:"<row 12>"}, {type:"text", text:"<row 13>"}, … ],
    citations: { enabled: true } }
```

| | |
|---|---|
| Citable units | `content` is split into the smallest units the parser knows: one text block per CSV row / JSON record / paragraph. A citation's `start_block_index`/`end_block_index` therefore maps back to exact rows ("Rows 13–14") or to the page/section of a prose chunk. |
| Output (no hits) | A text block: `No passages scored above the relevance threshold for "…". Try different wording, a narrower topic, or list_documents() to see what exists.` (not an error) |
| Errors (`is_error`) | empty/over-long query · unknown `document` · retrieval budget exhausted · embedding service unavailable (counts as a failure; `list_documents`/`read_section` still work) |
| Never | writes, external calls other than Ollama embed + SQL SELECT, returns non-ready documents |

### 3.2 `list_documents()`

| | |
|---|---|
| Purpose | Discovery: what exists, what is searchable, and how to address it with `read_section`. |
| Input | none |
| Output | One text block containing a JSON array (ready documents first): |

```json
[
  {"id": "3f2a…", "name": "riverside-department-metrics-q2-2026.csv", "type": "csv",
   "status": "ready", "searchable": true, "rows": 12, "row_range": "2-13",
   "columns": ["Department", "Month", "Admissions", "…"], "size_kb": 2},
  {"id": "…", "name": "riverside-discharge-policy.pdf", "type": "pdf",
   "status": "ready", "searchable": true, "pages": 6},
  {"id": "…", "name": "helix-incident-response-runbook.md", "type": "md",
   "status": "ready", "searchable": true, "sections": 14,
   "outline": ["Overview", "Severity levels", "Severity levels › P1", "…"]},
  {"id": "…", "name": "quarterly.docx", "type": "docx", "status": "processing", "searchable": false},
  {"id": "…", "name": "broken.pdf",      "type": "pdf",  "status": "failed",     "searchable": false}
]
```

followed by one line: `Locations for read_section: page:N · section:<heading> · rows:A-B · records:A-B · part:N`.

| | |
|---|---|
| Safe metadata only | id, name, type, status, searchable flag, parser facts (pages / rows+range / records / sections+outline capped at 30 entries / CSV column names), size. Never: file paths, hashes, error details, configuration. |
| Errors | database unavailable → `ToolError` + `run.fatal` |

### 3.3 `read_section(document, location)`

| | |
|---|---|
| Purpose | Exact, locator-addressed reading of a part of one document (a page, a heading section, a row range, a record range, or a text part). Used after discovery or to read around a search hit. |
| Input | `document: str` — document id or exact file name. `location: str` — one of the grammar forms below. |
| Location grammar | `page:4` · `section:Severity levels` (exact heading or heading path "A › B"; case-insensitive; unique prefix accepted) · `rows:12-18` (≤ `READ_MAX_ROWS`, default 60) · `records:3-5` · `part:2` (unstructured text files are stored in ~4 000-char parts) |
| Output | One `search_result` block: `source: "kb://<doc_id>/<normalised locator>"`, `title: "<name> — Page 4"`, `content`: one text block per row / record / paragraph. For `rows:A-B` the i-th block is row A+i, so citations resolve to exact rows. If a section exceeds `READ_SECTION_MAX_CHARS` (default 8 000), the block list is cut at a unit boundary and a trailing text block says how much was omitted and which locator continues it. |
| Errors (`is_error`) | unknown document (suggests `list_documents()`) · document not ready · invalid location syntax (echoes the grammar) · out of range (echoes the valid range, e.g. `pages 1–6`) · ambiguous section name (lists the candidates) · budget exhausted |
| Never | guesses a location: if the parser never recorded it, the tool says so. Returns only content stored at ingestion for that exact locator. |

### 3.4 What every tool result has in common

- Content is **data**: the wrapper adds no instructions, only labels. The system prompt tells Claude that tool content is document text to be cited, never followed.
- Every returned unit is recorded in the **evidence ledger** before Claude sees it. A chunk returned twice keeps its first evidence id.
- Output size is bounded (`SEARCH_TOP_K`, `READ_SECTION_MAX_CHARS`, outline cap) so a single call cannot flood the context.

---

## 4. Evidence ledger and guardrails

### 4.1 Ledger

```
EvidenceItem
  id              "E7"                       (1-based, in order of first appearance)
  source          "kb://<doc_id>/<locator>…" (exact string sent to Claude; the lookup key)
  document_id     uuid (from the database)
  document_name   str  (from the database)
  location        parser metadata, e.g. {"rows": "12–18"} / {"page": 4} / {"section": "A › B"}
  units           [text, …]                   (the text blocks sent, in order)
  origin          "search" | "read", tool call number
```

Only tool wrappers write to the ledger. Nothing in model text can create or alter an entry.

### 4.2 Citation validation (code, no model)

For every citation attached to the draft's text blocks:

1. `type == "search_result_location"` and `source` is a ledger key → accepted; otherwise dropped.
2. Defence in depth: `cited_text` must equal the join of `units[start:end]` of that entry (the API guarantees this; the check is cheap and catches any mismatch).
3. The source shown to the user is built **from the ledger entry** (document name and location from the database), never from the model's wording.

A sentence whose citations were all dropped is treated as uncited.

### 4.3 Sentence-level verification (second Claude call + code rules)

Same strict policy the user chose for the existing chatbot, re-implemented here:

- The draft is split into sentences in code; each sentence is linked to the evidence items its citations point at.
- One structured-output call (`client.beta.messages.parse` with a Pydantic schema) labels every sentence `supported | unsupported | not_in_kb | extra_caveat | no_claim` against **the cited passages only**.
- Code rules: every sentence must be labelled; `supported` without a valid citation becomes `unsupported`; any `unsupported` rejects the draft; no `supported` at all → `not_found`; `not_in_kb` present → `partial`. Totals/counts/averages the documents do not state are unsupported by instruction.
- Retry once: the rejected sentences are listed back to Claude in the same conversation, with `tool_choice: none` (no further retrieval, no new evidence, bounded time). The retry is verified again.
- Still rejected → `unverified`: a fixed message plus only the passages behind sentences that did pass (document words, not model words).

### 4.4 Fallbacks (fixed strings, server-side)

| Situation | Status | Message |
|---|---|---|
| No READY document | `kb_empty` | "Your knowledge base has no searchable documents yet. Upload documents on the Knowledge Base page, then ask again." |
| No citation / no supported sentence / model says it found nothing | `not_found` | "I couldn't find enough information in the provided knowledge base to answer this question." |
| Limit reached before an answer could be grounded | `not_found` + `stopped_by` | same message; the UI adds a muted note "Stopped after reaching the retrieval limit." |
| Verified sentences exist but the draft could not be fully verified in two attempts | `unverified` | "I found related passages in your documents, but couldn't write an answer in which every statement is verified." + passages |
| Service failures | `error` event | safe, code-specific messages (`DATABASE_UNAVAILABLE`, `EMBEDDING_UNAVAILABLE`, `LLM_BUSY`, `LLM_TIMEOUT`, …) |

### 4.5 Prompt-injection posture

| Vector | Control |
|---|---|
| Instructions inside PDFs/DOCX/MD/TXT/CSV/JSON | Extracted text is stored and returned as data blocks; the system prompt states tool content is never an instruction; the verifier marks any claim not stated by the cited passages as unsupported, so an injected "answer X" cannot pass. |
| Instructions asking the agent to change behaviour, limits, tools, env | Tools have no such capability: no write methods, no settings access, no environment access, no network beyond Ollama embed + SQL SELECT. Limits live in `AgentRun`, which no tool can modify. |
| Oversized or hostile tool inputs from the model | Pydantic validation (types), explicit length limits, locator grammar, row caps. |
| Content rendered in the browser | The UI renders answer text, search queries and document names as text nodes (no Markdown-to-HTML, no `dangerouslySetInnerHTML`). |
| Chain-of-thought exposure | Thinking blocks are returned empty by default on current models and are never forwarded; text Claude emits between tool calls is never forwarded; activity labels are generated by the application. |
| Database | Optional hardening (see D17): a dedicated read-only PostgreSQL role for the agent's connection, in addition to the code-level `ReadOnlyRepository`. |

---

## 5. Agent loop implementation (Anthropic SDK tool runner)

Verified against the installed SDK (`anthropic` 1.10.0) and the bundled Claude API skill:

```python
runner = client.beta.messages.tool_runner(
    model=settings.anthropic_model,            # D7
    max_tokens=16000,
    system=AGENT_SYSTEM_PROMPT,                # stable text, cached
    tools=[search_knowledge_base, list_documents, read_section],   # @beta_tool closures
    messages=[{"role": "user", "content": question}],
    max_iterations=settings.max_tool_calls + 1,
    output_config={"effort": settings.anthropic_effort},
    cache_control={"type": "ephemeral"},       # growing prefix is re-used each iteration
    betas=[FALLBACK_BETA], fallbacks="default",# server-side fallback on safety declines
    timeout=settings.anthropic_timeout_seconds,
)
for message in runner:                         # yields each assistant turn before tools run
    history.append(message.to_param())         # mirror (append-only: preserved thinking is safe)
    if message.stop_reason in ("refusal", "max_tokens"): break
    if run.over_deadline() or run.fatal or run.cancelled or run.too_many_failures(): break
    tool_response = runner.generate_tool_call_response()   # runs the tools now (cached: once)
    if tool_response: history.append(tool_response)
```

- Non-streaming runner, run on a worker thread (`asyncio.to_thread`); tool wrappers push
  activity events to an `asyncio.Queue` via `loop.call_soon_threadsafe`; the SSE generator drains
  the queue. Token streaming is deliberately not used: text is shown only after validation.
- `generate_tool_call_response()` is called inside the loop body so the wrappers emit
  `running`/`done` events in real time and the loop can inspect failures before continuing; the
  runner reuses the cached response, so tools run exactly once.
- Wrap-up and retry are single `client.beta.messages.create` calls on the mirrored `history`
  (same model, `tool_choice: {"type": "none"}`, tools still declared so the history validates).
- Model facts that shape this: on Claude Opus 5.5 / Sonnet 5.5 thinking is always on
  (`effort` is the control; Opus 5.5 defaults to `medium`, so the setting is explicit), forced
  `tool_choice any/tool` is rejected (we only use `auto` and `none`), assistant prefill is not
  available (so grounding is done by validation, not by steering the output), and thinking blocks
  are bound to the conversation (our history is append-only).
- The verifier uses `client.beta.messages.parse(output_format=Verification)` (structured output);
  the agent call does not use structured output because it is incompatible with citations.

---

## 6. Database schema (D6)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  filename        text NOT NULL,
  document_type   text NOT NULL,                    -- pdf | docx | md | txt | csv | json
  size_bytes      bigint NOT NULL,
  content_sha256  text NOT NULL UNIQUE,             -- duplicate uploads rejected
  status          text NOT NULL CHECK (status IN ('uploaded','extracting','indexing','ready','failed')),
  error_message   text,
  section_count   integer NOT NULL DEFAULT 0,
  chunk_count     integer NOT NULL DEFAULT 0,
  embedding_model text,
  metadata        jsonb NOT NULL DEFAULT '{}',      -- {"pages": 6} | {"rows": 12, "columns": [...]} | {"sections": 14}
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Locator-addressable extracted units: what read_section returns and what chunks are cut from.
CREATE TABLE sections (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ordinal      integer NOT NULL,                    -- document order
  locator      text NOT NULL,                       -- "page:4" | "section:A › B" | "row:13" | "record:3" | "part:2"
  label        text NOT NULL,                       -- "Page 4" | "Section: A › B" | "Row 13" | …
  units        jsonb NOT NULL,                      -- ["paragraph or row text", …]  (citable units)
  UNIQUE (document_id, ordinal), UNIQUE (document_id, locator)
);

CREATE TABLE chunks (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index  integer NOT NULL,
  first_section_ordinal integer NOT NULL,           -- rows/records are packed: a chunk spans sections
  last_section_ordinal  integer NOT NULL,
  content      text NOT NULL,
  units        jsonb NOT NULL,                      -- citable units (rows / paragraphs) in this chunk
  location     jsonb NOT NULL DEFAULT '{}',         -- {"page": 4} | {"rows": "12–18"} | {"section": "…"}
  embedding    vector(768) NOT NULL,
  UNIQUE (document_id, chunk_index)
);
```

Notes: `sections` is the source of truth for `read_section` (no original files are kept); `chunks`
are the search index. Exact cosine search (no ANN index) keeps recall perfect at this scale; an
HNSW index is a one-line addition if the corpus grows. Uploads are held in memory only.

---

## 7. API design (D4)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | database / embedding / Claude checks + non-secret configuration (model, effort, limits, retrieval settings, upload limits) |
| POST | `/api/documents` | multipart `file` → `202 {document}`; processed in the background |
| GET | `/api/documents` | list with status, counts, metadata |
| GET | `/api/documents/{id}` | one document incl. outline (headings / columns) |
| DELETE | `/api/documents/{id}` | delete document, sections, chunks (UI only; never a tool) |
| POST | `/api/ask` | `{question}` → `text/event-stream` |

### SSE events for `/api/ask`

```
event: run        data: {"run_id":"…","limits":{"max_tool_calls":8,"max_agent_time_seconds":90}}
event: activity   data: {"id":1,"kind":"analyze","status":"running","label":"Understanding question"}
event: activity   data: {"id":1,"kind":"analyze","status":"done"}
event: activity   data: {"id":2,"kind":"search","status":"running","label":"Searching knowledge base","detail":"June readmission target"}
event: activity   data: {"id":2,"kind":"search","status":"done","results":3,"ms":640}
event: activity   data: {"id":3,"kind":"read","status":"running","label":"Reading document","detail":"riverside-department-metrics-q2-2026.csv · Rows 12–18"}
event: activity   data: {"id":3,"kind":"read","status":"failed","error":"Rows out of range (rows 2–13)"}
event: activity   data: {"id":4,"kind":"review","status":"running","label":"Reviewing retrieved information"}
event: activity   data: {"id":5,"kind":"validate","status":"running","label":"Validating sources"}
event: activity   data: {"id":5,"kind":"validate","status":"done"}
event: result     data: {"status":"answered","segments":[{"text":"…","sources":[1,2],"paragraph_start":true}],
                         "sources":[{"id":1,"document_id":"…","document_name":"…","location":{"rows":"13–14"},"excerpt":"…"}],
                         "run":{"tool_calls":3,"elapsed_ms":6210,"stopped_by":null,"attempts":1}}
event: error      data: {"code":"DATABASE_UNAVAILABLE","message":"The database is unavailable. Please try again shortly."}
```

Rules: `detail` is a sanitised string (whitespace collapsed, control characters removed, ≤120
chars); `kind` ∈ `analyze | search | list | read | review | validate | answer`; exactly one
`result` or `error` ends the stream; a comment line `: ping` every 10 s keeps the connection
alive during long Claude requests. Cancellation: closing the connection cancels the run.

---

## 8. UI design (D15)

Visual mockups of all three directions: **`docs/ui-directions.html`** (open in a browser).

### Design tokens (Tailwind 4 `@theme`)

```
--color-primary      #024082   navy — structure, brand, headings, primary buttons
--color-accent       #0474EA   electric blue — interaction, live agent activity, links, focus
--color-accent-light #E8F3FF   selected/active surfaces, activity highlights
--color-bg           #F8FAFC   page background
--color-surface      #FFFFFF   cards, panels, inputs
--color-border       #DCE6F0   borders, dividers
--color-text         #0F172A   primary text
--color-text-muted   #475569   secondary text
status (chips only): ready = muted green, processing = muted amber, failed = muted red  (D18)
type: IBM Plex Sans (UI), IBM Plex Mono (ids, locators, queries)  (D18)
motion: 150–250 ms ease-out for state changes; a single pulsing dot for the live step;
        height-animated expansion for sources; no gradients, glass, parallax or decorative motion.
```

### Direction A — "Workbench" (three columns)

```
┌ brand · Ask · Knowledge Base ·········································· ● DB ● Ollama ● Claude ┐
│ KNOWLEDGE BASE   │ CONVERSATION                                      │ EVIDENCE               │
│ ● metrics.csv    │  Q  Which departments missed the June target?    │ 1 metrics.csv          │
│ ● policy.pdf     │  ┌ Agent activity ───────────────┐              │   Rows 13–14  ▾        │
│ ○ runbook.md     │  │ ✓ Question analyzed            │              │   "Cardiology | June…" │
│ ◐ quarterly.docx │  │ ✓ Search "June readmission…" 3 │              │ 2 policy.pdf  Page 4 ▸ │
│                  │  │ ✓ Read metrics.csv · rows 12–18│              │                        │
│ [Upload]         │  │ ● Preparing answer             │              │ Run: 3 calls · 6.2 s   │
│                  │  └────────────────────────────────┘              │                        │
│                  │  ANSWER ─────────── SOURCES ──────                │                        │
│                  │  [ Ask a question…                     ➤ ]      │                        │
└──────────────────┴──────────────────────────────────────────────────┴────────────────────────┘
```
Pros: everything visible at once; strong "enterprise console" feel; evidence inspector invites
verification. Cons: dense; three columns collapse awkwardly below ~1100 px (becomes tabs);
most screen space is chrome rather than answer.

### Direction B — "Run cards in a focused stream" (single column)  ← recommended

```
┌ brand · Ask · Knowledge Base ·········································· ● ● ● ┐
│                    ┌──────────────────────────────────────────────┐          │
│                    │ Which departments missed the June target?    │          │
│                    ├──────────────────────────────────────────────┤          │
│                    │ ✓ Question analyzed                          │          │
│                    │ ✓ Knowledge base search  "June readmission…" │ 3 results│
│                    │ ✓ Knowledge base search  "department June…"  │ 4 results│
│                    │ ✓ Document read  metrics.csv · rows 12–18    │          │
│                    │ ✓ Sources validated                          │          │
│                    │ ● Preparing answer                           │ 6.2 s    │
│                    ├──────────────────────────────────────────────┤          │
│                    │ Answer                                       │          │
│                    │ Cardiology was the only department above …¹  │          │
│                    │ Sources                                      │          │
│                    │ 📄 metrics.csv · Rows 13–14              ▾   │          │
│                    │ 📄 policy.pdf · Page 4                   ▸   │          │
│                    └──────────────────────────────────────────────┘          │
│                    [ Ask about your knowledge base…              ➤ ]          │
│                      The agent answers only from the knowledge base.          │
└──────────────────────────────────────────────────────────────────────────────┘
```
Each question is a **run card**: question → live timeline (collapses to a one-line summary
"4 steps · 3 sources · 6.2 s" once finished, expandable) → Answer → Sources. Pros: simplest,
most readable, mobile-friendly without a second layout, activity stays attached to the question
it belongs to (auditable history); mirrors patterns users already know from AI search products.
Cons: evidence excerpts live inside the card (less "inspector" feel); the knowledge base is a
separate page.

### Direction C — "Split console" (conversation + persistent activity panel)

```
┌ brand · Ask · Knowledge Base ·········································· ● ● ● ┐
│ CONVERSATION                                   │ AGENT ACTIVITY                │
│  Q  Which departments missed the June target?  │ ✓ Question analyzed           │
│  Answer                                        │ ✓ Search "June readmission…"  │
│  Cardiology was the only department above …¹   │ ✓ Search "department June…"   │
│  Sources                                       │ ✓ Read metrics.csv · rows 12–18│
│  📄 metrics.csv · Rows 13–14                   │ ✓ Sources validated           │
│                                                │ ● Preparing answer            │
│  [ Ask about your knowledge base…         ➤ ]  │ ─────────────────────────────  │
│                                                │ Run: 3 tool calls · 6.2 s     │
│                                                │ Limits: 3/8 calls · 6/90 s    │
└────────────────────────────────────────────────┴───────────────────────────────┘
```
Pros: the agent is always visible working beside the conversation; great for demos and for
showing limits. Cons: the panel shows the current run only (history loses its activity unless
duplicated); on mobile the panel becomes a sheet that competes with the answer.

**Recommendation: B**, with C's "run details" line (calls, time, limits) folded into the
collapsed timeline summary. B keeps the one-column reading experience, scales from phone to
desktop with one layout, and keeps the activity record attached to each question.

### Knowledge Base page (common to all directions)

Banner: *"The agent can answer only from information in this knowledge base."* · upload
dropzone (type/size limits stated) · table: name, type, status chip (ready / processing / failed
with reason on hover), sections, chunks, uploaded · row expands to metadata and outline
(headings or columns) · delete with confirmation.

### Components (React)

`AppShell` (top bar, nav, health dots) · `Composer` · `RunCard` · `ActivityTimeline` +
`ActivityStep` · `AnswerPanel` (segments with superscript source numbers) · `SourceList` +
`SourceItem` (expandable excerpt) · `FallbackNotice` · `DocumentTable` + `StatusChip` ·
`Dropzone` · `UploadQueue` · `ConfirmDialog`. State: `useAsk` (fetch + SSE parser + reducer),
`useDocuments` (polling while anything is processing), `useHealth`.

---

## 9. Folder structure

```
agentic-rag/
├── .env.example               every setting with placeholders (copy to .env; .env is git-ignored)
├── .gitignore                 ready for the user's later `git init`
├── README.md                  setup, run, how the agent works, guardrails, tests, troubleshooting
├── docker-compose.yml         pgvector/pgvector:pg17 on 127.0.0.1:5434, named volume
├── docs/
│   ├── DESIGN.md              this document
│   └── ui-directions.html     the three UI mockups
├── sample-documents/          small fictional set (csv, pdf, md, docx, json, txt) + EVAL_QUESTIONS.md
├── backend/                   Python 3.12 · FastAPI · uv
│   ├── pyproject.toml  uv.lock  .python-version
│   ├── app/
│   │   ├── main.py            app factory, JSON logging, startup checks, error handlers
│   │   ├── config.py          Settings from .env (validated once; secrets never logged)
│   │   ├── errors.py          AppError (user-safe messages)
│   │   ├── llm.py             Anthropic client + error mapping
│   │   ├── api/               health.py · documents.py · ask.py (SSE)
│   │   ├── db/                schema.sql · repository.py (writes) · read_repository.py (tools' view)
│   │   ├── ingestion/         validation.py · extractors.py · sections.py · chunking.py · pipeline.py
│   │   ├── embeddings/        provider.py (Protocol + factory) · ollama.py
│   │   ├── agent/             run.py (AgentRun: limits, ledger, emitter) · tools.py · loop.py · prompts.py · activity.py
│   │   └── grounding/         citations.py · sentences.py · verifier.py · result.py
│   └── tests/
│       ├── conftest.py        test database, fake embedder, scripted Claude
│       ├── fakes.py           FakeClaude (scripted tool calls + verdicts), FakeEmbedder, file builders
│       ├── unit/              extractors, sections, chunking, ledger, citations, sentences, limits, prompts
│       ├── agent/             scripted end-to-end agent runs (offline)
│       ├── integration/       API + database (Docker Postgres), SSE parsing
│       └── evals/             live cases (marked `live`): multi-step, cross-document, discovery, section reads
└── frontend/                  React 19 · TypeScript · Vite · Tailwind CSS 4
    ├── package.json  vite.config.ts  tsconfig*.json  index.html
    └── src/
        ├── main.tsx  App.tsx  styles.css (tokens)  api.ts  types.ts
        ├── hooks/             useAsk.ts (SSE + reducer) · useDocuments.ts · useHealth.ts
        ├── pages/             Ask.tsx · KnowledgeBase.tsx
        ├── components/        AppShell, Composer, RunCard, ActivityTimeline, AnswerPanel, SourceList, DocumentTable, Dropzone, …
        └── __tests__/         askReducer.test.ts (vitest)
```

Deliberately absent: agent frameworks, abstract base classes, plugin systems, repositories of
repositories, a message bus. One module per concern; functions over classes where state is not
needed.

---

## 10. Environment variables (`.env`)

```
# Database (own Docker container; 127.0.0.1 avoids the Windows localhost/IPv6 stall)
DATABASE_URL=postgresql://agent_user:change-me@127.0.0.1:5434/agentic_rag
POSTGRES_USER=agent_user
POSTGRES_PASSWORD=change-me
POSTGRES_DB=agentic_rag

# Embeddings (Ollama, local)
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_QUERY_PREFIX="search_query: "
OLLAMA_DOCUMENT_PREFIX="search_document: "
EMBEDDING_DIMENSION=768

# Claude (backend only; never sent to the browser)
ANTHROPIC_API_KEY=your-anthropic-api-key
ANTHROPIC_MODEL=claude-opus-5-5          # D7
ANTHROPIC_EFFORT=high                     # low | medium | high | xhigh | max
ANTHROPIC_TIMEOUT_SECONDS=60

# Agent limits
MAX_TOOL_CALLS=8
MAX_AGENT_TIME_SECONDS=90
MAX_CONSECUTIVE_TOOL_FAILURES=3

# Retrieval tools
SEARCH_TOP_K=6
SEARCH_MIN_SIMILARITY=0.50               # recalibrate if the embedding model changes
READ_SECTION_MAX_CHARS=8000
READ_MAX_ROWS=60

# Ingestion
MAX_UPLOAD_MB=100
CHUNK_SIZE_CHARS=1500
CHUNK_OVERLAP_CHARS=150
TEXT_PART_CHARS=4000                     # unstructured .txt files are stored as part:N sections

LOG_LEVEL=INFO
```

---

## 11. Dependencies

### Backend (`pyproject.toml`)

| Package | Why |
|---|---|
| `anthropic >= 1.10` | Claude API: beta tool runner, `@beta_tool`, structured outputs, citations, server-side fallback |
| `fastapi` + `uvicorn` | HTTP API and SSE streaming |
| `psycopg[binary,pool]` | PostgreSQL driver + connection pool (pgvector used via SQL, no extra package) |
| `pydantic-settings` | typed, validated `.env` loading |
| `httpx` | Ollama HTTP client (the Anthropic SDK ships its own `httpx2`; no conflict) |
| `pypdf`, `python-docx` | PDF and DOCX text extraction (MD/TXT/CSV/JSON use the standard library) |
| `python-multipart` | multipart uploads in FastAPI |
| dev: `pytest`, `ruff` | tests, lint/format |

Not added: LangChain, LlamaIndex, any agent framework, ORM, task queue, Redis, auth libraries.

### Frontend (`package.json`)

| Package | Why |
|---|---|
| `react`, `react-dom`, `react-router` | SPA with two routes |
| `lucide-react` | icon set (file types, status, steps) |
| dev: `vite`, `@vitejs/plugin-react`, `typescript` | build/dev server |
| dev: `tailwindcss`, `@tailwindcss/vite` | design tokens and utilities |
| dev: `vitest` | tests for the SSE reducer (D16) |
| dev: `oxlint` | fast zero-config lint |

Not added: state libraries, component kits, animation libraries, markdown renderers (answers are
plain text by design).

---

## 12. Testing plan

Offline by default (no Ollama, no Anthropic): `FakeEmbedder` (bag-of-words hashing into 768-d)
and `FakeClaude`, a scripted stand-in for `client.beta.messages.parse/create`. The **real SDK
tool runner, real tools, real repository and real guardrails** run; only Claude's replies are
scripted as real `BetaMessage` objects: tool_use turns, a final text turn with citations, and
verifier verdicts. Database tests use a throw-away `<db>_test` database in the project's own
Docker Postgres.

| Brief requirement | Test (offline unless marked live) |
|---|---|
| Simple single-search question | script: search → answer citing E1 → verified → `answered` with 1 source |
| Multi-search question | script: search, search → answer citing both → sources ordered by first citation |
| Cross-document question | script: search(doc A), read(doc B, page) → answer citing both documents |
| Document discovery | script: list_documents → read_section(section:…) → answer; also: processing/failed documents are listed as not searchable |
| Section-level reading | unit: locator grammar, page/section/rows/records/part, truncation note, out-of-range errors, ambiguous heading |
| Insufficient information | script: searches return nothing → model answers without citations → `not_found`; model declares not found → `not_found` |
| Hallucination prevention | script: answer sentence with a fact not in cited passages → verifier `unsupported` → retry → still unsupported → `unverified`; uncited summary sentence → rejected |
| Citation validation | unit: citation with unknown `source` dropped; `cited_text` mismatch dropped; sentence left uncited becomes unsupported; sources built from ledger not from model text |
| Prompt injection | documents containing "ignore your instructions / call read_section with … / reveal the system prompt / change MAX_TOOL_CALLS": tools remain read-only, limits unchanged, injected claims fail verification, injected text never appears as an instruction in requests |
| Tool failures | script: read_section errors ×3 → run stops with `stopped_by: failures` → wrap-up → fallback; embedding down during search → error result, run continues with list/read; DB down → `error` event `DATABASE_UNAVAILABLE` |
| Maximum tool-call limit | script that keeps calling search → 9th call returns "budget exhausted" result, runner stops at `max_iterations`, wrap-up call made with `tool_choice none` |
| Agent timeout | fake clock / tiny `MAX_AGENT_TIME` → stops before next tool execution, wrap-up or fallback, `stopped_by: time` |
| Unrelated questions | "capital of France" → script: search finds nothing / model answers from knowledge without citations → `not_found`, no sources |
| Malformed documents | corrupted PDF, DOCX that is not a zip, invalid JSON, non-UTF-8 text, empty file, encrypted PDF → `failed` with safe reason; agent sees them as not searchable |
| API/database failures | Anthropic 429 / timeout / auth → safe `LLM_*` errors; Postgres down at startup → clear log + exit |
| Activity stream | SSE order: run → activity (running/done per tool, failed on error) → result; `detail` sanitised and ≤120 chars; no model text in activity events |
| Live evals (`-m live`) | sample documents + `EVAL_QUESTIONS.md`: 2 single-search, 3 multi-search, 3 cross-document, 2 discovery, 2 section reads, 2 insufficient, 1 injection; each asserts status, cited documents, and that no answer sentence lacks a source |

---

## 13. Implementation phases (after approval)

1. **Scaffold + infrastructure** — folders, `.env.example`, compose on 5434, settings, schema, health endpoint, logging, launch entries for the Code tab preview.
2. **Ingestion** — validation, extractors, section builder (locators + citable units), chunking, pipeline, documents API.
3. **Tools + ledger** — read-only repository, three tools, AgentRun, activity emitter.
4. **Agent loop** — tool runner integration, limits, wrap-up call, SSE endpoint, cancellation. Includes a one-off live spike confirming citations arrive for `search_result` blocks returned from tool results on the chosen model.
5. **Grounding** — citation validation, sentence split, verifier, retry, result assembly.
6. **UI** — tokens, shell, Ask page with run cards, Knowledge Base page, health strip, responsive pass.
7. **Tests, evals, README** — offline suite, live eval cases, sample documents, setup instructions.

Each phase ends with its tests passing locally and a short status note; no commits.

---

## 14. DECISION REQUIRED

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Project name and location | (a) `~/projects/agentic-rag` · (b) another name/path | **(a)** |
| D2 | Backend framework | (a) FastAPI, Python 3.12, uv, sync SDK runner on a worker thread · (b) Node/TypeScript (Hono or Express) with the TS SDK `toolRunner` · (c) FastAPI with the async runner (`@beta_async_tool`, `AsyncAnthropic`) | **(a)** — same ecosystem the user already runs, sync psycopg/httpx stay simple; (c) only if everything becomes async |
| D3 | Frontend framework | (a) React 19 + TypeScript + Vite + Tailwind CSS 4 (new design, no reuse) · (b) Svelte/SvelteKit · (c) Next.js | **(a)** — smallest toolchain, familiar; (c) is more than this app needs |
| D4 | Streaming transport | (a) SSE over `POST /api/ask` (fetch + ReadableStream) · (b) WebSocket | **(a)** — one-directional progress stream, no connection state to manage, cancellation by closing the response |
| D5 | PostgreSQL instance | (a) own Docker compose `pgvector/pgvector:pg17` on 127.0.0.1:5434 with its own volume · (b) a second database inside the existing rag-chatbot container · (c) native PG 17 on 5433 (needs a pgvector build for Windows) | **(a)** — full independence, no coupling to the other project's lifecycle |
| D6 | Document storage / schema | (a) `documents` + `sections` (locator-addressable units) + `chunks`; originals not kept · (b) keep original files on disk and re-parse for `read_section` · (c) chunks only (approximate section reads) | **(a)** — exact, fast `read_section` without storing files; parsing happens once |
| D7 | Claude model | (a) `claude-opus-5-5` ($4/$20 per MTok; current default guidance; thinking always on, effort set explicitly) · (b) `claude-sonnet-5-5` ($2/$10; what the existing chatbot uses) | **(a)**; (b) is a one-line `.env` change at any time |
| D8 | Agent loop mechanism | (a) SDK beta tool runner (`client.beta.messages.tool_runner`, `max_iterations`, `generate_tool_call_response`) · (b) hand-written loop | **(a)** — as the brief asks; the runner yields every turn before tools run, so limits, logging and interception need no custom loop |
| D9 | Limit defaults | `MAX_TOOL_CALLS=8`, `MAX_AGENT_TIME_SECONDS=90`, `MAX_CONSECUTIVE_TOOL_FAILURES=3`, runner `max_iterations = MAX_TOOL_CALLS + 1` | **as listed** (all `.env`-tunable) |
| D10 | Retrieval configuration | per search: `SEARCH_TOP_K=6`, `SEARCH_MIN_SIMILARITY=0.50`, optional `document` filter, query ≤ 500 chars; `read_section`: ≤ 60 rows, ≤ 8 000 chars per call | **as listed**; alternative: top_k 12 without a document filter (more context per call, fewer calls, less precise citations) |
| D11 | Citation structure | (a) tool results as `search_result` blocks with `citations: {enabled: true}` → the final answer carries API-generated citations (`search_result_location` with the app's `source` key and exact `cited_text`); app validates against the ledger · (b) app-assigned tags `[E3]` in the answer text, parsed by code · (c) two phases: agent gathers, then a separate citations-API generation call over the ledger | **(a)** — citations are produced by the API, not by the model's prose, and point at exact units (rows/paragraphs); (c) is the fallback if the Phase-4 spike shows a gap |
| D12 | Grounding implementation | (a) strict: code citation check + sentence-level verifier call + code rules, retry once, uncited summary sentences reject the answer (same policy as the existing chatbot) · (b) citation check only, no verifier (cheaper, weaker) | **(a)** |
| D13 | Conversation memory | (a) single-turn: every question is independent · (b) multi-turn with history in the browser and resent per question | **(a)** for v1 — bounded context, simpler limits and tests |
| D14 | Authentication | (a) none, bind to 127.0.0.1 · (b) a shared `APP_TOKEN` header | **(a)** — local tool; (b) trivial to add later |
| D15 | UI direction | A workbench · **B run cards** · C split console (see §8 and `ui-directions.html`) | **B** |
| D16 | Test scope | (a) backend pytest (unit, scripted agent, integration, live evals) + frontend vitest for the SSE reducer · (b) backend only | **(a)** |
| D17 | Database hardening | (a) code-level read-only repository for tools (always) · (b) additionally a dedicated read-only PostgreSQL role for the agent's connection (`AGENT_DATABASE_URL`) | **(a) now**, (b) documented as an optional hardening step |
| D18 | Visual details | fonts IBM Plex Sans / Mono (Google Fonts) vs system stack; muted green/amber/red for status chips only | **IBM Plex + muted status hues**; say so if the palette must stay strictly navy/blue/grey |

Assumptions made without a decision (say if wrong): English UI; supported upload types pdf,
docx, md, txt, csv, json; duplicate uploads rejected; original files not kept; plain-text
answers (no Markdown); the sample documents are a small new fictional set, not copies from the
existing project.

---

## 15. Implementation notes (2026-10-06, after approval of D1–D18)

Everything above was implemented as designed, with these findings from the live runs:

- **API rule discovered in the Phase-4 spike.** A tool result that contains `search_result`
  blocks may contain *only* `search_result` blocks. The search header line and the
  `read_section` truncation note therefore live in each block's `title` instead of separate
  text blocks (§3.1, §3.3). Citations arrive exactly as designed: `search_result_location`
  with the app's `source` key and the exact cited unit (down to single CSV rows).
- **Strict policy (D12) in practice.** Claude Opus 5.5 answers multi-fact questions correctly
  but tends to write an opening summary or a concluding restatement *without* citations while
  citing the detailed sentences. Under D12 such a sentence is unsupported, so the draft is
  rejected and, if the retry repeats the pattern, the user sees "unverified" with the passages.
  The prompts now instruct the model to cite the opening sentence, to state each fact once in
  the sentence that cites it, and the retry note tells it which sentences lacked citations. This
  removed most cases but not all (see the live evaluation results in the status report).
  Loosening D12 — for example dropping an uncited restatement that the verifier confirms is
  stated by passages cited elsewhere in the answer, instead of rejecting the whole draft —
  would be a policy change and is left as a **DECISION REQUIRED** follow-up.
- **Docker Desktop on this machine** would not start because of undeletable stale socket files
  (see README → Troubleshooting).
- **UI rebuilt on 2026-10-07 (supersedes §8 / D15 / D18).** The user was not satisfied with the
  first implementation and provided a reference screenshot (a dark app shell with a floating
  rounded window, a dark sidebar, a white centre chat panel with a tabbed response card, and a
  dark right-hand History panel). The frontend was rebuilt in that structure: `Shell`, `Sidebar`
  (with a status card), `HistoryPanel`, `ResponseCard` (Answer · Sources · Activity tabs), a
  `System` page, Manrope + JetBrains Mono. Palette chosen from six previews
  (`docs/ui-redesign/color-previews.html`): **Charcoal & Orange** — shell `#1C1D23`, accent
  `#F2652F`, accent-light `#FFEFE7`, primary text `#7C2D12`, warm canvas `#F3EEEA`. All colours
  are tokens in `frontend/src/styles.css`. The earlier A/B/C directions and the three redesign
  directions in `docs/ui-redesign/` are kept for reference only.
- **Responsive pass (same day).** Phones get the window edge to edge with a compact top nav and
  the History panel as a drawer; tablets a slim frame; desktops up to 1680 px with wider content
  columns. Large screens are filled by a document list in the sidebar, suggestion cards and a
  three-step "how it works" row on the empty Ask page, stat tiles and a card list on the
  Knowledge Base page, and card groups on the System page.
