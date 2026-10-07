import { PanelRightClose, PanelRightOpen } from 'lucide-react'
import type { ReactNode } from 'react'

import { ShellContext, useShell } from '../shellContext'

interface Props {
  sidebar: ReactNode
  mobileNav: ReactNode
  history: ReactNode
  historyOpen: boolean
  onToggleHistory: () => void
  children: ReactNode
}

/** The floating dark window: sidebar · white content panel · history panel.
 *  Phones get the window edge to edge; tablets a slim frame; desktops the full three columns. */
export function Shell({ sidebar, mobileNav, history, historyOpen, onToggleHistory, children }: Props) {
  return (
    <ShellContext.Provider value={{ historyOpen, toggleHistory: onToggleHistory }}>
      <div className="mx-auto flex h-dvh max-w-[1680px] p-0 sm:p-3 lg:p-4">
        <div
          className={`grid min-h-0 w-full gap-2 bg-shell p-2 sm:gap-3 sm:rounded-[26px] sm:p-3 lg:gap-4 lg:rounded-[30px] lg:p-4 lg:grid-cols-[236px_minmax(0,1fr)] 2xl:grid-cols-[256px_minmax(0,1fr)] ${
            historyOpen ? 'xl:grid-cols-[236px_minmax(0,1fr)_280px] 2xl:grid-cols-[256px_minmax(0,1fr)_300px]' : ''
          }`}
          style={{ gridTemplateRows: 'minmax(0, 1fr)' }}
        >
          <aside className="hidden min-h-0 flex-col lg:flex">{sidebar}</aside>

          <section className="relative flex min-h-0 flex-col overflow-hidden rounded-[18px] bg-surface sm:rounded-[22px]">
            <div className="lg:hidden">{mobileNav}</div>
            {children}
          </section>

          {historyOpen && (
            <>
              <aside className="hidden min-h-0 flex-col xl:flex">{history}</aside>
              {/* Below xl the history panel is a drawer over the content. */}
              <div className="fixed inset-0 z-30 xl:hidden" role="dialog" aria-label="History">
                <button type="button" className="absolute inset-0 bg-shell/60" onClick={onToggleHistory} aria-label="Close history" />
                <div className="absolute inset-y-2 right-2 flex w-[300px] max-w-[88vw] flex-col rounded-[22px] bg-shell p-3 shadow-2xl sm:inset-y-3 sm:right-3">
                  {history}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </ShellContext.Provider>
  )
}

/** The content panel's header: page title on the left, actions and the history toggle on the right. */
export function PanelHeader({ title, children }: { title: string; children?: ReactNode }) {
  const { historyOpen, toggleHistory } = useShell()
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-3 sm:h-16 sm:gap-3 sm:px-6 [@media(max-height:520px)]:h-12">
      <h1 className="truncate text-[15px] font-extrabold tracking-tight">{title}</h1>
      <div className="ml-auto flex items-center gap-2">
        {children}
        <button type="button" className="icon-btn" onClick={toggleHistory} aria-label={historyOpen ? 'Hide history' : 'Show history'} title="History">
          {historyOpen ? <PanelRightClose className="size-4" aria-hidden /> : <PanelRightOpen className="size-4" aria-hidden />}
        </button>
      </div>
    </header>
  )
}
