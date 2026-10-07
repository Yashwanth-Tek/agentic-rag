import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router'

import type { Run } from './askReducer'
import { HistoryPanel } from './components/HistoryPanel'
import { Shell } from './components/Shell'
import { MobileNav, Sidebar } from './components/Sidebar'
import { useAsk, useDocuments, useHealth, useUploads } from './hooks'
import { Ask } from './pages/Ask'
import { KnowledgeBase } from './pages/KnowledgeBase'
import { System } from './pages/System'

export default function App() {
  // State lives here so uploads, polling and the conversation survive page switches.
  const documents = useDocuments()
  const uploads = useUploads(documents.refresh)
  const health = useHealth()
  const ask = useAsk()
  const [historyOpen, setHistoryOpen] = useState(() => window.innerWidth >= 1280)

  // The history panel is a drawer below 1280px: never leave it open when the window shrinks.
  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth < 1280) setHistoryOpen(false)
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const all = documents.documents ?? []
  const ready = all.filter((d) => d.status === 'ready')
  const uploadLimits = health.health?.configuration.uploads ?? null

  const jumpToRun = useCallback((run: Run) => {
    document.getElementById(`run-${run.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    if (window.innerWidth < 1280) setHistoryOpen(false)
  }, [])

  return (
    <Shell
      sidebar={
        <Sidebar
          documents={all}
          health={health.health}
          unreachable={health.unreachable}
          pending={ask.pending}
          hasRuns={ask.runs.length > 0}
          onClear={ask.clear}
        />
      }
      mobileNav={<MobileNav readyCount={ready.length} pending={ask.pending} />}
      history={<HistoryPanel runs={ask.runs} readyCount={ready.length} onSelect={jumpToRun} onClear={ask.clear} />}
      historyOpen={historyOpen}
      onToggleHistory={() => setHistoryOpen((open) => !open)}
    >
      <Routes>
        <Route path="/" element={<Ask ask={ask} documents={ready} />} />
        <Route
          path="/knowledge-base"
          element={<KnowledgeBase documents={documents} uploads={uploads} limits={uploadLimits} />}
        />
        <Route path="/system" element={<System health={health.health} unreachable={health.unreachable} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}
