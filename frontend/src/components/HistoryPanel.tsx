import { AlertCircle, Check, CircleDashed, Sparkles, Trash2 } from 'lucide-react'

import { HISTORY_LIMIT, type Run } from '../askReducer'
import { plural } from '../format'

interface Props {
  runs: Run[]
  readyCount: number
  onSelect: (run: Run) => void
  onClear: () => void
}

export function HistoryPanel({ runs, readyCount, onSelect, onClear }: Props) {
  const ordered = [...runs].reverse()
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between px-2 pt-2 pb-4">
        <h2 className="text-[15px] font-extrabold tracking-tight text-white">History</h2>
        <span className="font-mono text-[12px] text-white/50">
          {runs.length}/{HISTORY_LIMIT}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-0.5">
        {ordered.length === 0 ? (
          <EmptyHistory readyCount={readyCount} />
        ) : (
          <ul className="space-y-2">
            {ordered.map((run) => {
              const { label, tone } = describe(run)
              return (
                <li key={run.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(run)}
                    className="w-full rounded-[14px] bg-surface p-3 text-left transition duration-150 outline-none hover:bg-accent-light focus-visible:ring-[3px] focus-visible:ring-accent"
                  >
                    <span className="flex items-center gap-2">
                      <Mark tone={tone} />
                      <span className="text-[13px] font-bold text-ink">{label}</span>
                    </span>
                    <span className="mt-1 line-clamp-2 block pl-7 text-[12px] leading-5 text-muted">{run.question}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <button
        type="button"
        onClick={onClear}
        disabled={runs.length === 0}
        className="mt-3 flex items-center justify-center gap-2 rounded-xl border border-shell-edge px-3 py-2.5 text-[13px] font-semibold text-white/80 transition hover:bg-shell-soft hover:text-white disabled:opacity-40"
      >
        <Trash2 className="size-4" aria-hidden /> Clear history
      </button>
    </div>
  )
}

function EmptyHistory({ readyCount }: { readyCount: number }) {
  return (
    <div className="rounded-[14px] bg-shell-soft p-4 text-[12.5px] text-white/60">
      <Sparkles className="size-5 text-accent" aria-hidden />
      <p className="mt-2 font-bold text-white">No questions yet</p>
      <p className="mt-0.5">{plural(readyCount, 'document')} ready</p>
    </div>
  )
}

type Tone = 'live' | 'ok' | 'info' | 'err'

function describe(run: Run): { label: string; tone: Tone } {
  if (run.status === 'running') return { label: 'Working…', tone: 'live' }
  if (run.status === 'error') return { label: run.error?.code === 'CANCELLED' ? 'Stopped' : 'Error', tone: 'err' }
  switch (run.result?.status) {
    case 'answered':
      return { label: 'Verified answer', tone: 'ok' }
    case 'partial':
      return { label: 'Partly answered', tone: 'ok' }
    case 'unverified':
      return { label: 'Could not verify', tone: 'info' }
    case 'kb_empty':
      return { label: 'No documents', tone: 'info' }
    default:
      return { label: 'Not found', tone: 'info' }
  }
}

function Mark({ tone }: { tone: Tone }) {
  const base = 'flex size-5 shrink-0 items-center justify-center rounded-md'
  if (tone === 'live') return <span className={`${base} bg-accent-light`}><span className="size-2 rounded-full bg-accent animate-pulse-dot" aria-hidden /></span>
  if (tone === 'ok') return <span className={`${base} bg-accent text-white`}><Check className="size-3.5" strokeWidth={3} aria-hidden /></span>
  if (tone === 'err') return <span className={`${base} bg-err-bg text-err`}><AlertCircle className="size-3.5" aria-hidden /></span>
  return <span className={`${base} border border-border text-faint`}><CircleDashed className="size-3.5" aria-hidden /></span>
}
