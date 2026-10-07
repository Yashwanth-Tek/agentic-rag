import { Info, Search, Upload } from 'lucide-react'
import { useRef, useState } from 'react'

import { ConfirmDialog } from '../components/ConfirmDialog'
import { DocumentList } from '../components/DocumentList'
import { Dropzone } from '../components/Dropzone'
import { PanelHeader } from '../components/Shell'
import { UploadQueue } from '../components/UploadQueue'
import { isProcessing } from '../format'
import type { useDocuments, useUploads } from '../hooks'
import type { DocumentInfo } from '../types'

interface Props {
  documents: ReturnType<typeof useDocuments>
  uploads: ReturnType<typeof useUploads>
  limits: { max_mb: number; extensions: string[] } | null
}

export function KnowledgeBase({ documents, uploads, limits }: Props) {
  const [pendingDelete, setPendingDelete] = useState<DocumentInfo | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const picker = useRef<HTMLInputElement>(null)

  const confirmDelete = async () => {
    if (!pendingDelete) return
    try {
      await documents.remove(pendingDelete.id)
      setDeleteError(null)
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : 'Could not delete the document.')
    } finally {
      setPendingDelete(null)
    }
  }

  const all = documents.documents ?? []
  const needle = query.trim().toLowerCase()
  const visible = documents.documents?.filter((d) => !needle || d.filename.toLowerCase().includes(needle)) ?? null
  const stats = {
    total: all.length,
    ready: all.filter((d) => d.status === 'ready').length,
    processing: all.filter(isProcessing).length,
    failed: all.filter((d) => d.status === 'failed').length,
    chunks: all.reduce((sum, d) => sum + d.chunk_count, 0),
  }

  return (
    <>
      <PanelHeader title="Knowledge Base">
        <label className="relative hidden md:block">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search documents"
            aria-label="Search documents"
            className="h-9 w-52 rounded-full border border-border bg-bg pr-3 pl-9 text-[13px] outline-none placeholder:text-faint focus:border-accent focus:ring-[3px] focus:ring-accent-light lg:w-64"
          />
        </label>
        <button type="button" className="btn btn-primary" onClick={() => picker.current?.click()}>
          <Upload className="size-4" aria-hidden /> <span className="hidden sm:inline">Upload</span>
        </button>
        <input
          ref={picker}
          type="file"
          multiple
          accept={limits?.extensions.join(',')}
          className="sr-only"
          onChange={(event) => {
            if (event.target.files?.length) uploads.add(event.target.files)
            event.target.value = ''
          }}
        />
      </PanelHeader>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-6 sm:py-6 lg:px-8">
        <div className="mx-auto max-w-[1120px] space-y-4 sm:space-y-5">
          <div className="grid grid-cols-2 gap-2.5 sm:gap-3 lg:grid-cols-4">
            <Stat label="Documents" value={stats.total} />
            <Stat label="Ready" value={stats.ready} tone="ok" />
            <Stat label={stats.failed > 0 ? 'Failed' : 'Processing'} value={stats.failed > 0 ? stats.failed : stats.processing} tone={stats.failed > 0 ? 'err' : stats.processing > 0 ? 'warn' : undefined} />
            <Stat label="Chunks indexed" value={stats.chunks} />
          </div>

          <label className="relative block md:hidden">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" aria-hidden />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search documents"
              aria-label="Search documents"
              className="h-10 w-full rounded-xl border border-border bg-bg pr-3 pl-9 text-[14px] outline-none placeholder:text-faint focus:border-accent focus:ring-[3px] focus:ring-accent-light"
            />
          </label>

          <p className="flex items-center gap-2 text-[13px] text-muted">
            <Info className="size-4 shrink-0 text-accent" aria-hidden />
            The agent answers only from these documents.
          </p>

          <Dropzone onFiles={uploads.add} extensions={limits?.extensions ?? null} maxMb={limits?.max_mb ?? null} />
          <UploadQueue uploads={uploads.uploads} onDismiss={uploads.dismiss} />

          {deleteError && <p className="text-sm text-err">{deleteError}</p>}
          {documents.error && <p className="text-sm text-err">{documents.error}</p>}

          <DocumentList documents={visible} onDelete={setPendingDelete} filtered={needle.length > 0} />
        </div>
      </div>

      {pendingDelete && (
        <ConfirmDialog
          title="Delete document?"
          body={`“${pendingDelete.filename}” and everything indexed from it will be removed. The agent will no longer be able to use it.`}
          confirmLabel="Delete"
          onConfirm={() => void confirmDelete()}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: 'ok' | 'warn' | 'err' }) {
  const color = tone === 'ok' ? 'text-ok' : tone === 'warn' ? 'text-warn' : tone === 'err' ? 'text-err' : 'text-ink'
  return (
    <div className="card px-4 py-3">
      <p className="label">{label}</p>
      <p className={`mt-1 font-mono text-[22px] font-semibold leading-none ${color}`}>{value.toLocaleString()}</p>
    </div>
  )
}
