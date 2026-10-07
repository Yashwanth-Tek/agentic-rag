import { useCallback, useEffect, useRef, useState } from 'react'

import { api, ApiError, askStream } from './api'
import { reduceRuns, type Run, type RunAction } from './askReducer'
import { isProcessing } from './format'
import type { AskError, DocumentInfo, Health } from './types'

function toAskError(error: unknown): AskError {
  if (error instanceof ApiError) return { code: error.code, message: error.message }
  return { code: 'UNKNOWN', message: 'Something went wrong. Please try again.' }
}

/** Questions and their live runs. One question at a time; closing the stream cancels the agent. */
export function useAsk() {
  const [runs, setRuns] = useState<Run[]>([])
  const controller = useRef<AbortController | null>(null)
  const dispatch = useCallback((action: RunAction) => setRuns((previous) => reduceRuns(previous, action)), [])

  const ask = useCallback(
    async (question: string) => {
      const id = crypto.randomUUID()
      const signal = new AbortController()
      controller.current = signal
      dispatch({ type: 'start', id, question, at: Date.now() })
      try {
        await askStream(question, (event) => dispatch({ type: 'event', id, event, at: Date.now() }), signal.signal)
        dispatch({ type: 'end', id, at: Date.now() })
      } catch (error) {
        const failure = signal.signal.aborted ? { code: 'CANCELLED', message: 'Stopped.' } : toAskError(error)
        dispatch({ type: 'fail', id, error: failure, at: Date.now() })
      } finally {
        if (controller.current === signal) controller.current = null
      }
    },
    [dispatch],
  )

  const cancel = useCallback(() => controller.current?.abort(), [])
  const clear = useCallback(() => {
    controller.current?.abort()
    dispatch({ type: 'clear' })
  }, [dispatch])
  useEffect(() => () => controller.current?.abort(), [])

  return { runs, pending: runs.some((run) => run.status === 'running'), ask, cancel, clear }
}

/** The document list, polled while anything is still processing. */
export function useDocuments() {
  const [documents, setDocuments] = useState<DocumentInfo[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      setDocuments(await api.listDocuments())
      setError(null)
    } catch (caught) {
      setError(toAskError(caught).message)
    }
  }, [])

  useEffect(() => {
    // Fetching on mount is a sync with an external system; the state update happens after the await.
    // oxlint-disable-next-line react/set-state-in-effect
    void refresh()
  }, [refresh])

  const busy = documents?.some(isProcessing) ?? false
  useEffect(() => {
    if (!busy) return
    const timer = window.setInterval(() => void refresh(), 1500)
    return () => window.clearInterval(timer)
  }, [busy, refresh])

  const remove = useCallback(
    async (id: string) => {
      await api.deleteDocument(id)
      await refresh()
    },
    [refresh],
  )

  return { documents, error, refresh, remove }
}

export interface Upload {
  id: string
  name: string
  size: number
  status: 'queued' | 'uploading' | 'accepted' | 'rejected'
  message?: string
}

/** Uploads run one at a time; each is either accepted (processing continues server-side) or rejected. */
export function useUploads(onAccepted: () => void) {
  const [uploads, setUploads] = useState<Upload[]>([])
  const queue = useRef<{ id: string; file: File }[]>([])
  const running = useRef(false)

  const pump = useCallback(async () => {
    if (running.current) return
    running.current = true
    while (queue.current.length) {
      const { id, file } = queue.current.shift()!
      setUploads((previous) => previous.map((u) => (u.id === id ? { ...u, status: 'uploading' } : u)))
      try {
        await api.upload(file)
        setUploads((previous) => previous.map((u) => (u.id === id ? { ...u, status: 'accepted' } : u)))
        onAccepted()
      } catch (error) {
        const message = toAskError(error).message
        setUploads((previous) => previous.map((u) => (u.id === id ? { ...u, status: 'rejected', message } : u)))
      }
    }
    running.current = false
  }, [onAccepted])

  const add = useCallback(
    (files: FileList | File[]) => {
      const entries = Array.from(files).map((file) => ({ id: crypto.randomUUID(), file }))
      queue.current.push(...entries)
      setUploads((previous) => [
        ...previous,
        ...entries.map(({ id, file }) => ({ id, name: file.name, size: file.size, status: 'queued' as const })),
      ])
      void pump()
    },
    [pump],
  )

  const dismiss = useCallback((id: string) => setUploads((previous) => previous.filter((u) => u.id !== id)), [])

  return { uploads, add, dismiss }
}

/** Service health, refreshed every 30 seconds. */
export function useHealth() {
  const [health, setHealth] = useState<Health | null>(null)
  const [unreachable, setUnreachable] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const next = await api.health()
        if (!cancelled) {
          setHealth(next)
          setUnreachable(false)
        }
      } catch {
        if (!cancelled) setUnreachable(true)
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), 30_000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  return { health, unreachable }
}
