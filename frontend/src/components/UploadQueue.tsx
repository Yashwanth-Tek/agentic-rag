import { Check, X } from 'lucide-react'

import { formatBytes } from '../format'
import type { Upload } from '../hooks'

export function UploadQueue({ uploads, onDismiss }: { uploads: Upload[]; onDismiss: (id: string) => void }) {
  if (uploads.length === 0) return null
  return (
    <ul className="mt-3 space-y-1.5" aria-label="Uploads">
      {uploads.map((upload) => (
        <li key={upload.id} className="card flex items-center gap-3 px-3.5 py-2 text-sm animate-fade-in">
          <StatusMark status={upload.status} />
          <span className="min-w-0 flex-1 truncate font-semibold">{upload.name}</span>
          <span className="mono text-muted">{formatBytes(upload.size)}</span>
          <span className={`text-[12px] ${upload.status === 'rejected' ? 'text-err' : 'text-muted'}`}>
            {upload.status === 'queued' && 'Waiting'}
            {upload.status === 'uploading' && 'Uploading…'}
            {upload.status === 'accepted' && 'Accepted, processing'}
            {upload.status === 'rejected' && upload.message}
          </span>
          {(upload.status === 'accepted' || upload.status === 'rejected') && (
            <button type="button" className="icon-btn size-7 border-0" onClick={() => onDismiss(upload.id)} aria-label="Dismiss">
              <X className="size-3.5" aria-hidden />
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}

function StatusMark({ status }: { status: Upload['status'] }) {
  if (status === 'accepted') return <Check className="size-4 text-ok" aria-hidden />
  if (status === 'rejected') return <X className="size-4 text-err" aria-hidden />
  return <span className="size-2 rounded-full bg-accent animate-pulse-dot" aria-hidden />
}
