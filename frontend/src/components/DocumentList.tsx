import { ChevronDown, Trash2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { documentFacts, formatBytes, formatDate, isProcessing, plural, statusText } from '../format'
import type { DocumentInfo } from '../types'

interface Props {
  documents: DocumentInfo[] | null
  onDelete: (document: DocumentInfo) => void
  filtered?: boolean
}

/** One card per document; wraps from a single row on desktop to stacked rows on phones. */
export function DocumentList({ documents, onDelete, filtered }: Props) {
  const [open, setOpen] = useState<string | null>(null)

  if (documents === null) return <p className="py-8 text-center text-sm text-muted">Loading documents…</p>
  if (documents.length === 0) {
    return (
      <div className="card px-6 py-10 text-center">
        <p className="font-bold">{filtered ? 'No documents match' : 'No documents yet'}</p>
        <p className="mt-1 text-sm text-muted">
          {filtered ? 'Try a different name.' : 'Upload PDF, Word, Markdown, text, CSV or JSON files to build the knowledge base.'}
        </p>
      </div>
    )
  }

  return (
    <ul className="space-y-2.5" aria-label="Documents">
      {documents.map((document) => {
        const expanded = open === document.id
        return (
          <li key={document.id} className="card overflow-hidden">
            <div className="flex items-start gap-3 px-3.5 py-3 sm:items-center sm:px-4">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-light font-mono text-[10.5px] font-bold tracking-[0.04em] text-primary" aria-hidden>
                {document.document_type.toUpperCase()}
              </span>

              <button
                type="button"
                onClick={() => setOpen(expanded ? null : document.id)}
                aria-expanded={expanded}
                className="min-w-0 flex-1 text-left outline-none focus-visible:text-primary"
              >
                <span className="block truncate text-[14px] font-bold">{document.filename}</span>
                <span className="mt-0.5 block truncate text-[12.5px] text-muted">
                  {document.status === 'failed' ? document.error_message : documentFacts(document) || '—'}
                </span>
                <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted sm:hidden">
                  <StatusChip document={document} />
                  <span className="mono">{formatBytes(document.size_bytes)}</span>
                  <span className="mono">{formatDate(document.created_at)}</span>
                </span>
              </button>

              <div className="hidden items-center gap-5 sm:flex">
                <StatusChip document={document} />
                <Meta label="sections" value={document.status === 'ready' ? String(document.section_count) : '—'} />
                <Meta label="chunks" value={document.status === 'ready' ? String(document.chunk_count) : '—'} />
                <Meta label="size" value={formatBytes(document.size_bytes)} wide />
                <Meta label="uploaded" value={formatDate(document.created_at)} wide />
              </div>

              <div className="flex shrink-0 items-center gap-1">
                <button type="button" className="icon-btn size-8 border-0" onClick={() => setOpen(expanded ? null : document.id)} aria-label={expanded ? 'Hide details' : 'Show details'}>
                  <ChevronDown className={`size-4 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`} aria-hidden />
                </button>
                <button
                  type="button"
                  className="icon-btn size-8 border-0"
                  onClick={() => onDelete(document)}
                  disabled={isProcessing(document)}
                  aria-label={`Delete ${document.filename}`}
                >
                  <Trash2 className="size-4" aria-hidden />
                </button>
              </div>
            </div>

            <div className={`grid transition-[grid-template-rows] duration-200 ease-out ${expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
              <div className="overflow-hidden">
                <div className="border-t border-border bg-bg px-4 py-4">
                  <Details document={document} />
                </div>
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function Meta({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <span className={`${wide ? 'hidden xl:block' : 'hidden lg:block'} text-right`}>
      <span className="label block text-[10px]">{label}</span>
      <span className="mono block text-ink">{value}</span>
    </span>
  )
}

export function StatusChip({ document }: { document: DocumentInfo }) {
  const tone =
    document.status === 'ready' ? 'bg-ok-bg text-ok' : document.status === 'failed' ? 'bg-err-bg text-err' : 'bg-warn-bg text-warn'
  return (
    <span className={`chip ${tone}`} title={document.error_message ?? undefined}>
      {isProcessing(document) && <span className="size-1.5 rounded-full bg-current animate-pulse-dot" aria-hidden />}
      {statusText(document)}
    </span>
  )
}

function Details({ document }: { document: DocumentInfo }) {
  const m = document.metadata
  return (
    <div className="grid gap-4 text-[13.5px] md:grid-cols-2 [&>*]:min-w-0">
      <dl className="space-y-1.5">
        <Row name="ID">
          <span className="mono break-all">{document.id}</span>
        </Row>
        <Row name="Indexed">{document.status === 'ready' ? `${plural(document.section_count, 'section')} · ${plural(document.chunk_count, 'chunk')}` : '—'}</Row>
        {m.characters !== undefined && <Row name="Characters">{m.characters.toLocaleString()}</Row>}
        {document.error_message && (
          <Row name="Problem">
            <span className="text-err">{document.error_message}</span>
          </Row>
        )}
      </dl>
      <div className="space-y-3">
        {m.columns && (
          <div>
            <p className="label mb-1.5">Columns</p>
            <p className="mono leading-6 text-muted">{m.columns.join(' · ')}</p>
          </div>
        )}
        {m.outline && m.outline.length > 0 && (
          <div>
            <p className="label mb-1.5">Outline</p>
            <ul className="mono max-h-48 space-y-0.5 overflow-y-auto leading-6 text-muted">
              {m.outline.map((heading, index) => (
                <li key={index} className="truncate">
                  {heading}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

function Row({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="w-28 shrink-0 text-muted sm:w-32">{name}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}
