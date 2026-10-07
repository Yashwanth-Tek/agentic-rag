import { ChevronDown } from 'lucide-react'
import { useState } from 'react'

import type { Source } from '../types'
import { FileTypeIcon } from './FileTypeIcon'

/** Only sources that exist in the retrieved evidence are ever listed; excerpts are the cited text. */
export function SourceList({ sources }: { sources: Source[] }) {
  return (
    <ol className="space-y-2.5" aria-label="Sources">
      {sources.map((source) => (
        <SourceItem key={source.id} source={source} />
      ))}
    </ol>
  )
}

function SourceItem({ source }: { source: Source }) {
  const [open, setOpen] = useState(false)
  const hasExcerpt = source.excerpt.length > 0
  const type = source.document_name.split('.').pop()?.toUpperCase() ?? 'DOC'
  return (
    <li className="rounded-xl border border-border bg-surface">
      <button
        type="button"
        onClick={() => hasExcerpt && setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-3.5 py-3 text-left outline-none focus-visible:ring-[3px] focus-visible:ring-accent-light"
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary font-mono text-[12px] font-bold text-white">{source.id}</span>
        <FileTypeIcon name={source.document_name} className="size-4 shrink-0 text-muted" />
        <span className="min-w-0 flex-1 truncate text-[14px] font-bold">{source.document_name}</span>
        <span className="type-badge hidden sm:inline-flex">{type}</span>
        {hasExcerpt && (
          <ChevronDown className={`size-4 shrink-0 text-faint transition-transform duration-200 sm:order-last ${open ? 'rotate-180' : ''}`} aria-hidden />
        )}
        {/* On phones the location drops to its own line; on wider screens it sits inline. */}
        {source.label && (
          <span className="mono min-w-0 basis-full truncate pl-10 text-muted sm:basis-auto sm:max-w-[40%] sm:pl-0">{source.label}</span>
        )}
      </button>
      <div className={`grid transition-[grid-template-rows] duration-200 ease-out ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}>
        <div className="overflow-hidden">
          <blockquote className="mx-3.5 mb-3.5 rounded-r-lg border-l-[3px] border-accent bg-bg px-3.5 py-2.5 text-[13.5px] leading-6 text-muted">
            {source.excerpt}
          </blockquote>
        </div>
      </div>
    </li>
  )
}
