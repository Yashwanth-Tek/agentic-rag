import type { DocumentInfo } from './types'

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

export function formatDate(iso: string): string {
  const date = new Date(iso)
  const today = new Date()
  const sameDay = date.toDateString() === today.toDateString()
  const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  if (sameDay) return `today ${time}`
  return `${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ${time}`
}

/** Parser facts about a document, e.g. "6 pages" or "12 rows · 7 columns". */
export function documentFacts(document: DocumentInfo): string {
  const m = document.metadata
  const parts: string[] = []
  if (m.pages !== undefined) parts.push(plural(m.pages, 'page'))
  if (m.rows !== undefined) parts.push(plural(m.rows, 'row'))
  if (m.columns) parts.push(plural(m.columns.length, 'column'))
  if (m.records !== undefined) parts.push(plural(m.records, 'record'))
  if (m.sections !== undefined) parts.push(plural(m.sections, 'section'))
  if (m.parts !== undefined) parts.push(plural(m.parts, 'part'))
  return parts.join(' · ')
}

export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

export const PROCESSING_STATUSES = new Set(['uploaded', 'extracting', 'embedding', 'indexing'])

export function isProcessing(document: DocumentInfo): boolean {
  return PROCESSING_STATUSES.has(document.status)
}

export function statusText(document: DocumentInfo): string {
  switch (document.status) {
    case 'ready':
      return 'Ready'
    case 'failed':
      return 'Failed'
    case 'uploaded':
      return 'Queued'
    case 'extracting':
      return 'Extracting'
    case 'embedding':
      return 'Embedding'
    case 'indexing':
      return 'Indexing'
  }
}
