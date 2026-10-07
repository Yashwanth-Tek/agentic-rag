import type { AskEvent, DocumentInfo, Health } from './types'

export class ApiError extends Error {
  code: string
  status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.code = code
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError('NETWORK', 'The server could not be reached. Is the API running?', 0)
  }
  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = 'HTTP_ERROR'
  let message = `The server returned an error (${response.status}).`
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } }
    code = body.error?.code ?? code
    message = body.error?.message ?? message
  } catch {
    // keep the generic message
  }
  return new ApiError(code, message, response.status)
}

export const api = {
  health: () => request<Health>('/api/health'),
  listDocuments: () => request<DocumentInfo[]>('/api/documents'),
  getDocument: (id: string) => request<DocumentInfo>(`/api/documents/${id}`),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<DocumentInfo>('/api/documents', { method: 'POST', body: form })
  },
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: 'DELETE' }),
}

/** POST a question and deliver each Server-Sent Event as it arrives. Resolves when the stream ends. */
export async function askStream(question: string, onEvent: (event: AskEvent) => void, signal: AbortSignal): Promise<void> {
  let response: Response
  try {
    response = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
      signal,
    })
  } catch (error) {
    if (signal.aborted) throw error
    throw new ApiError('NETWORK', 'The server could not be reached. Is the API running?', 0)
  }
  if (!response.ok) throw await toApiError(response)
  if (!response.body) throw new ApiError('STREAM', 'The server sent no response stream.', 0)

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const event = parseSseBlock(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      if (event) onEvent(event)
      boundary = buffer.indexOf('\n\n')
    }
  }
}

/** One SSE block (`event:` + `data:` lines) → the typed event, or null for comments/keep-alives. */
export function parseSseBlock(block: string): AskEvent | null {
  let name = ''
  const data: string[] = []
  for (const rawLine of block.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trim())
  }
  if (!name || data.length === 0) return null
  return { event: name, ...(JSON.parse(data.join('\n')) as object) } as AskEvent
}
