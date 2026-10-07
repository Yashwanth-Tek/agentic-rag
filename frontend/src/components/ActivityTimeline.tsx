import { AlertTriangle, Eye, FileText, List, PenLine, Search, ShieldCheck, Sparkles } from 'lucide-react'
import type { ComponentType } from 'react'

import { formatDuration } from '../format'
import type { ActivityKind, ActivityStep, Limits } from '../types'

const ICONS: Record<ActivityKind, ComponentType<{ className?: string }>> = {
  analyze: Sparkles,
  search: Search,
  list: List,
  read: FileText,
  review: Eye,
  validate: ShieldCheck,
  answer: PenLine,
  limit: AlertTriangle,
}

const TOOL_BADGE: Partial<Record<ActivityKind, string>> = { search: 'SEARCH', list: 'LIST', read: 'READ' }

/** Past-tense labels once a step has finished; the server's label describes the step in progress. */
const DONE_LABELS: Record<ActivityKind, string> = {
  analyze: 'Question analyzed',
  search: 'Knowledge base search',
  list: 'Documents listed',
  read: 'Document read',
  review: 'Retrieved information reviewed',
  validate: 'Sources validated',
  answer: 'Answer prepared',
  limit: 'Limit reached',
}

interface Props {
  steps: ActivityStep[]
  limits?: Limits
  elapsedMs: number
  toolCalls?: number
}

export function ActivityTimeline({ steps, limits, elapsedMs, toolCalls }: Props) {
  const calls = toolCalls ?? steps.filter((s) => TOOL_BADGE[s.kind] && s.status !== 'running').length
  return (
    <div>
      <ol className="space-y-1" aria-label="Agent activity">
        {steps.map((step) => (
          <Step key={step.id} step={step} />
        ))}
        {steps.length === 0 && <li className="text-sm text-muted">Starting…</li>}
      </ol>
      {limits && (
        <div className="mt-5 grid gap-3 border-t border-border pt-4 sm:grid-cols-2">
          <Gauge label="Tool calls" value={`${calls} / ${limits.max_tool_calls}`} ratio={calls / limits.max_tool_calls} />
          <Gauge
            label="Time"
            value={`${formatDuration(elapsedMs)} / ${limits.max_agent_time_seconds} s`}
            ratio={elapsedMs / 1000 / limits.max_agent_time_seconds}
          />
        </div>
      )}
    </div>
  )
}

function Step({ step }: { step: ActivityStep }) {
  const Icon = ICONS[step.kind] ?? Sparkles
  const badge = TOOL_BADGE[step.kind]
  return (
    <li className="flex items-start gap-3 rounded-xl px-2 py-2 animate-fade-in">
      <Marker status={step.status} />
      <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
        <span className={`inline-flex items-center gap-1.5 text-[14px] font-semibold ${tone(step.status)}`}>
          <Icon className="size-3.5 opacity-80" aria-hidden />
          {label(step)}
        </span>
        {badge && <span className="type-badge">{badge}</span>}
        {step.detail && <span className="mono min-w-0 truncate text-muted">{step.detail}</span>}
        {step.status === 'done' && step.results !== undefined && (
          <span className="ml-auto text-[12px] text-faint">{step.results === 1 ? '1 result' : `${step.results} results`}</span>
        )}
        {step.status === 'failed' && step.error && <span className="basis-full text-[12.5px] text-err">{step.error}</span>}
      </div>
    </li>
  )
}

function label(step: ActivityStep): string {
  if (step.status === 'running') return step.label || DONE_LABELS[step.kind]
  if (step.status === 'failed') return `${step.label || DONE_LABELS[step.kind]} failed`
  if (step.kind === 'limit' || step.kind === 'answer') return step.label || DONE_LABELS[step.kind]
  return DONE_LABELS[step.kind] ?? step.label
}

function tone(status: ActivityStep['status']): string {
  if (status === 'running') return 'text-accent'
  if (status === 'failed') return 'text-err'
  return 'text-ink'
}

function Marker({ status }: { status: ActivityStep['status'] }) {
  if (status === 'running') {
    return (
      <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border-2 border-accent bg-surface" aria-hidden>
        <span className="size-1.5 rounded-full bg-accent animate-pulse-dot" />
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border-2 border-err bg-surface text-[11px] font-black text-err" aria-hidden>
        !
      </span>
    )
  }
  return (
    <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-accent" aria-hidden>
      <svg viewBox="0 0 12 12" className="size-2.5 text-white">
        <path d="M2.5 6.5l2.2 2.2L9.5 3.7" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  )
}

function Gauge({ label, value, ratio }: { label: string; value: string; ratio: number }) {
  const width = `${Math.min(100, Math.max(0, ratio * 100))}%`
  return (
    <div className="text-[12px] text-muted">
      <div className="mb-1.5 flex justify-between">
        <span>{label}</span>
        <span className="mono text-ink">{value}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-border">
        <div className="h-full rounded-full bg-accent transition-[width] duration-300" style={{ width }} />
      </div>
    </div>
  )
}
