/** Pure state for the Ask page: one Run per question, updated event by event. */

import type { ActivityStep, AskError, AskEvent, AskResult, Limits } from './types'

export const HISTORY_LIMIT = 50

export interface Run {
  id: string
  question: string
  status: 'running' | 'done' | 'error'
  steps: ActivityStep[]
  limits?: Limits
  result?: AskResult
  error?: AskError
  startedAt: number
  finishedAt?: number
}

export type RunAction =
  | { type: 'start'; id: string; question: string; at: number }
  | { type: 'event'; id: string; event: AskEvent; at: number }
  | { type: 'fail'; id: string; error: AskError; at: number }
  | { type: 'end'; id: string; at: number }
  | { type: 'clear' }

export const STREAM_CLOSED: AskError = {
  code: 'STREAM_CLOSED',
  message: 'The connection closed before an answer arrived. Please try again.',
}

export function reduceRuns(runs: Run[], action: RunAction): Run[] {
  switch (action.type) {
    case 'start': {
      const run: Run = { id: action.id, question: action.question, status: 'running', steps: [], startedAt: action.at }
      return [...runs.slice(-(HISTORY_LIMIT - 1)), run]
    }
    case 'event':
      return runs.map((run) => (run.id === action.id ? applyEvent(run, action.event, action.at) : run))
    case 'fail':
      return runs.map((run) =>
        run.id === action.id && run.status === 'running'
          ? { ...run, status: 'error', error: action.error, steps: settle(run.steps, 'failed'), finishedAt: action.at }
          : run,
      )
    case 'end':
      // The stream ended normally; a run still marked running never received its result.
      return runs.map((run) =>
        run.id === action.id && run.status === 'running'
          ? { ...run, status: 'error', error: STREAM_CLOSED, steps: settle(run.steps, 'failed'), finishedAt: action.at }
          : run,
      )
    case 'clear':
      return []
  }
}

export function applyEvent(run: Run, event: AskEvent, at: number): Run {
  switch (event.event) {
    case 'run':
      return { ...run, limits: event.limits }
    case 'activity': {
      const { event: _kind, ...update } = event
      const existing = run.steps.find((step) => step.id === update.id)
      const steps = existing
        ? run.steps.map((step) => (step.id === update.id ? { ...step, ...update } : step))
        : [...run.steps, { kind: 'analyze', label: '', ...update } as ActivityStep]
      return { ...run, steps }
    }
    case 'result': {
      const { event: _kind, ...result } = event
      return { ...run, status: 'done', result, steps: settle(run.steps, 'done'), finishedAt: at }
    }
    case 'error': {
      const { event: _kind, ...error } = event
      return { ...run, status: 'error', error, steps: settle(run.steps, 'failed'), finishedAt: at }
    }
  }
}

/** Once a run is over, nothing can still be running. */
function settle(steps: ActivityStep[], status: 'done' | 'failed'): ActivityStep[] {
  return steps.map((step) => (step.status === 'running' ? { ...step, status } : step))
}

export function runDuration(run: Run, now: number): number {
  return (run.finishedAt ?? now) - run.startedAt
}

/** The plain text of a validated answer, for copying. */
export function answerText(run: Run): string {
  const result = run.result
  if (!result) return ''
  if (result.segments.length === 0) return result.message ?? ''
  const lines: string[] = []
  for (const segment of result.segments) {
    const refs = segment.sources.length ? ` [${segment.sources.join(', ')}]` : ''
    if (segment.paragraph_start || lines.length === 0) lines.push(segment.text + refs)
    else lines[lines.length - 1] += ` ${segment.text}${refs}`
  }
  const sources = result.sources.map((s) => `[${s.id}] ${s.document_name}${s.label ? ` — ${s.label}` : ''}`)
  return `${lines.join('\n\n')}\n\nSources\n${sources.join('\n')}`
}
