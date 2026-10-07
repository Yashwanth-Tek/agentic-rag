import { AlertCircle, Check, Copy, Info, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'

import { answerText, runDuration, type Run } from '../askReducer'
import { formatDuration } from '../format'
import type { RunSummary } from '../types'
import { ActivityTimeline } from './ActivityTimeline'
import { AnswerPanel } from './AnswerPanel'
import { SourceList } from './SourceList'

type Tab = 'answer' | 'sources' | 'activity'

interface Props {
  run: Run
  onRetry: (question: string) => void
  retryDisabled: boolean
}

/** The agent's reply: one card with Answer · Sources · Activity tabs (Activity while it works). */
export function ResponseCard({ run, onRetry, retryDisabled }: Props) {
  const live = run.status === 'running'
  const [chosen, setChosen] = useState<Tab>('answer')
  const tab: Tab = live ? 'activity' : chosen
  const [now, setNow] = useState(() => Date.now())
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!live) return
    const timer = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(timer)
  }, [live])

  const result = run.result
  const sources = result?.sources ?? []
  const elapsed = result?.run?.elapsed_ms ?? runDuration(run, now)
  const copyable = run.status === 'done' && result !== undefined && result.segments.length > 0

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(answerText(run))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard unavailable: nothing to do
    }
  }

  return (
    <article id={`run-${run.id}`} className="card scroll-mt-4 overflow-hidden animate-fade-in" aria-busy={live} aria-live={live ? 'polite' : undefined}>
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-bg px-3 py-2">
        <div className="flex gap-1 rounded-xl bg-canvas p-1" role="tablist" aria-label="Response sections">
          <TabButton active={tab === 'answer'} disabled={live} onClick={() => setChosen('answer')}>
            Answer
          </TabButton>
          <TabButton active={tab === 'sources'} disabled={live} onClick={() => setChosen('sources')}>
            Sources{sources.length > 0 && <span className="ml-1.5 font-mono text-[11px] text-faint">{sources.length}</span>}
          </TabButton>
          <TabButton active={tab === 'activity'} onClick={() => setChosen('activity')}>
            Activity{run.steps.length > 0 && <span className="ml-1.5 font-mono text-[11px] text-faint">{run.steps.length}</span>}
          </TabButton>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <StatusPill run={run} elapsed={elapsed} />
          {copyable && (
            <button type="button" className="icon-btn size-8" onClick={() => void copy()} aria-label="Copy answer" title="Copy answer">
              {copied ? <Check className="size-4 text-ok" aria-hidden /> : <Copy className="size-4" aria-hidden />}
            </button>
          )}
        </div>
      </div>

      <div className="px-5 py-5 sm:px-6">
        {tab === 'answer' && <AnswerTab run={run} onRetry={onRetry} retryDisabled={retryDisabled} onShowSources={() => setChosen('sources')} />}
        {tab === 'sources' &&
          (sources.length > 0 ? (
            <SourceList sources={sources} />
          ) : (
            <p className="text-sm text-muted">No sources: nothing retrieved could support an answer to this question.</p>
          ))}
        {tab === 'activity' && (
          <ActivityTimeline steps={run.steps} limits={run.limits} elapsedMs={elapsed} toolCalls={result?.run?.tool_calls} />
        )}
      </div>
    </article>
  )
}

function TabButton({ active, disabled, onClick, children }: { active: boolean; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" role="tab" aria-selected={active} className={`tab ${active ? 'active' : ''}`} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  )
}

function StatusPill({ run, elapsed }: { run: Run; elapsed: number }) {
  if (run.status === 'running') {
    return (
      <span className="chip bg-accent-light text-primary">
        <span className="size-1.5 rounded-full bg-accent animate-pulse-dot" aria-hidden /> Working · {formatDuration(elapsed)}
      </span>
    )
  }
  if (run.status === 'error') return <span className="chip bg-err-bg text-err">{run.error?.code === 'CANCELLED' ? 'Stopped' : 'Error'}</span>
  const status = run.result?.status
  if (status === 'answered' || status === 'partial') {
    return (
      <span className="chip bg-ok-bg text-ok">
        <Check className="size-3" strokeWidth={3} aria-hidden /> Verified · {formatDuration(elapsed)}
      </span>
    )
  }
  return <span className="chip border border-border bg-surface text-muted">{status === 'unverified' ? 'Could not verify' : 'Not found'}</span>
}

function AnswerTab({ run, onRetry, retryDisabled, onShowSources }: { run: Run; onRetry: (q: string) => void; retryDisabled: boolean; onShowSources: () => void }) {
  if (run.status === 'error' && run.error) {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-err/25 bg-err-bg px-4 py-3 text-sm text-err">
        <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div className="flex-1">
          <p className="font-semibold">{run.error.message}</p>
          <p className="mono mt-1 text-[11.5px] opacity-80">{run.error.code}</p>
        </div>
        {run.error.code !== 'CANCELLED' && (
          <button type="button" className="btn btn-secondary" onClick={() => onRetry(run.question)} disabled={retryDisabled}>
            <RefreshCw className="size-4" aria-hidden /> Try again
          </button>
        )}
      </div>
    )
  }
  const result = run.result
  if (!result) return null
  const answered = result.status === 'answered' || result.status === 'partial'
  return (
    <div>
      {answered ? (
        <AnswerPanel segments={result.segments} />
      ) : (
        <div className="flex items-start gap-3 rounded-xl border border-border bg-bg px-4 py-3 text-[15px]">
          <Info className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
          <div>
            <p>{result.message}</p>
            {result.sources.length > 0 && (
              <button type="button" className="mt-1 text-sm font-semibold text-accent hover:underline" onClick={onShowSources}>
                View the related passages
              </button>
            )}
          </div>
        </div>
      )}
      {result.run?.stopped_by && <p className="mt-3 text-[12.5px] text-muted">{STOPPED_TEXT[result.run.stopped_by]}</p>}
    </div>
  )
}

const STOPPED_TEXT: Record<NonNullable<RunSummary['stopped_by']>, string> = {
  tool_calls: 'Stopped at the retrieval limit.',
  time: 'Stopped at the time limit.',
  failures: 'Stopped after repeated tool failures.',
}
