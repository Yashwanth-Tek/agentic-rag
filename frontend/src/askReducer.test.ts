import { describe, expect, it } from 'vitest'

import { parseSseBlock } from './api'
import { reduceRuns, STREAM_CLOSED, type Run } from './askReducer'
import type { AskEvent } from './types'

const started: Run[] = reduceRuns([], { type: 'start', id: 'r1', question: 'Q?', at: 1000 })

function after(events: AskEvent[], runs: Run[] = started): Run {
  return events.reduce((state, event) => reduceRuns(state, { type: 'event', id: 'r1', event, at: 2000 }), runs)[0]
}

describe('reduceRuns', () => {
  it('starts a running run with no steps', () => {
    expect(started[0]).toMatchObject({ id: 'r1', question: 'Q?', status: 'running', steps: [] })
  })

  it('records limits from the run event', () => {
    const run = after([{ event: 'run', limits: { max_tool_calls: 8, max_agent_time_seconds: 90 } }])
    expect(run.limits).toEqual({ max_tool_calls: 8, max_agent_time_seconds: 90 })
  })

  it('merges activity updates by id and keeps their order', () => {
    const run = after([
      { event: 'activity', id: 1, kind: 'analyze', status: 'running', label: 'Understanding question' },
      { event: 'activity', id: 2, kind: 'search', status: 'running', label: 'Searching knowledge base', detail: 'q' },
      { event: 'activity', id: 1, status: 'done' },
      { event: 'activity', id: 2, status: 'done', results: 3 },
    ])
    expect(run.steps).toEqual([
      { id: 1, kind: 'analyze', status: 'done', label: 'Understanding question' },
      { id: 2, kind: 'search', status: 'done', label: 'Searching knowledge base', detail: 'q', results: 3 },
    ])
  })

  it('marks a failed step with its error', () => {
    const run = after([
      { event: 'activity', id: 3, kind: 'read', status: 'running', label: 'Reading document', detail: 'x · page:9' },
      { event: 'activity', id: 3, status: 'failed', error: 'no page 9' },
    ])
    expect(run.steps[0]).toMatchObject({ status: 'failed', error: 'no page 9', detail: 'x · page:9' })
  })

  it('finishes on result and settles running steps', () => {
    const run = after([
      { event: 'activity', id: 1, kind: 'validate', status: 'running', label: 'Validating sources' },
      { event: 'result', status: 'answered', message: null, segments: [], sources: [], run: null },
    ])
    expect(run.status).toBe('done')
    expect(run.result?.status).toBe('answered')
    expect(run.steps[0].status).toBe('done')
    expect(run.finishedAt).toBe(2000)
  })

  it('finishes on error and fails running steps', () => {
    const run = after([
      { event: 'activity', id: 1, kind: 'search', status: 'running', label: 'Searching knowledge base' },
      { event: 'error', code: 'LLM_BUSY', message: 'busy' },
    ])
    expect(run.status).toBe('error')
    expect(run.error).toEqual({ code: 'LLM_BUSY', message: 'busy' })
    expect(run.steps[0].status).toBe('failed')
  })

  it('treats a stream that ends without a result as an error, but not a finished run', () => {
    const ended = reduceRuns(started, { type: 'end', id: 'r1', at: 3000 })[0]
    expect(ended.status).toBe('error')
    expect(ended.error).toBe(STREAM_CLOSED)

    const done = after([{ event: 'result', status: 'not_found', message: 'x', segments: [], sources: [], run: null }])
    const stillDone = reduceRuns([done], { type: 'end', id: 'r1', at: 3000 })[0]
    expect(stillDone.status).toBe('done')
  })

  it('ignores events for other runs and clears everything', () => {
    const runs = reduceRuns(started, { type: 'event', id: 'other', event: { event: 'error', code: 'X', message: 'x' }, at: 1 })
    expect(runs[0].status).toBe('running')
    expect(reduceRuns(runs, { type: 'clear' })).toEqual([])
  })
})

describe('parseSseBlock', () => {
  it('parses event and data lines and ignores comments', () => {
    expect(parseSseBlock('event: activity\ndata: {"id":1,"status":"done"}')).toEqual({ event: 'activity', id: 1, status: 'done' })
    expect(parseSseBlock(': ping')).toBeNull()
    expect(parseSseBlock('')).toBeNull()
  })

  it('tolerates carriage returns', () => {
    expect(parseSseBlock('event: run\r\ndata: {"limits":{"max_tool_calls":8,"max_agent_time_seconds":90}}\r')).toEqual({
      event: 'run',
      limits: { max_tool_calls: 8, max_agent_time_seconds: 90 },
    })
  })
})
