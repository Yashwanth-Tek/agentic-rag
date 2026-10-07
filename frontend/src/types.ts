export interface DocumentInfo {
  id: string
  filename: string
  document_type: string
  size_bytes: number
  status: 'uploaded' | 'extracting' | 'embedding' | 'indexing' | 'ready' | 'failed'
  error_message: string | null
  section_count: number
  chunk_count: number
  embedding_model: string | null
  metadata: {
    pages?: number
    rows?: number
    row_range?: string
    columns?: string[]
    records?: number
    sections?: number
    outline?: string[]
    parts?: number
    characters?: number
  }
  created_at: string
  updated_at: string
}

export interface ServiceHealth {
  ok: boolean
  detail: string | null
}

export interface Health {
  services: { database: ServiceHealth; embedding: ServiceHealth; llm: ServiceHealth }
  configuration: {
    embedding: { model: string; model_id: string; dimension: number }
    llm: { model: string; effort: string }
    limits: { max_tool_calls: number; max_agent_time_seconds: number; max_consecutive_tool_failures: number }
    retrieval: { top_k: number; min_similarity: number; read_section_max_chars: number; read_max_rows: number }
    uploads: { max_mb: number; extensions: string[] }
  }
}

export type ActivityKind = 'analyze' | 'search' | 'list' | 'read' | 'review' | 'validate' | 'answer' | 'limit'
export type ActivityStatus = 'running' | 'done' | 'failed'

export interface ActivityStep {
  id: number
  kind: ActivityKind
  status: ActivityStatus
  label: string
  detail?: string
  results?: number
  error?: string
}

export interface Limits {
  max_tool_calls: number
  max_agent_time_seconds: number
}

export interface Segment {
  kind: 'supported' | 'not_in_kb'
  text: string
  sources: number[]
  paragraph_start: boolean
}

export interface Source {
  id: number
  evidence_id: string
  document_id: string
  document_name: string
  location: Record<string, string | number>
  label: string
  excerpt: string
}

export interface RunSummary {
  tool_calls: number
  elapsed_ms: number
  stopped_by: 'tool_calls' | 'time' | 'failures' | null
  attempts: number
  evidence: number
}

export type ResultStatus = 'answered' | 'partial' | 'not_found' | 'unverified' | 'kb_empty'

export interface AskResult {
  status: ResultStatus
  message: string | null
  segments: Segment[]
  sources: Source[]
  run: RunSummary | null
}

export interface AskError {
  code: string
  message: string
}

export type AskEvent =
  | { event: 'run'; limits: Limits }
  | ({ event: 'activity' } & Partial<ActivityStep> & { id: number; status: ActivityStatus })
  | ({ event: 'result' } & AskResult)
  | ({ event: 'error' } & AskError)
