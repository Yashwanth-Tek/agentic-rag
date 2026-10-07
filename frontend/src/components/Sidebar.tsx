import { Activity, ArrowUpRight, Eraser, Library, MessageSquare } from 'lucide-react'
import type { ReactNode } from 'react'
import { NavLink } from 'react-router'

import { isProcessing } from '../format'
import type { DocumentInfo, Health } from '../types'

const SIDEBAR_DOCUMENTS = 8

interface Props {
  documents: DocumentInfo[]
  health: Health | null
  unreachable: boolean
  pending: boolean
  hasRuns: boolean
  onClear: () => void
}

export function Sidebar({ documents, health, unreachable, pending, hasRuns, onClear }: Props) {
  const ready = documents.filter((d) => d.status === 'ready').length
  return (
    <div className="flex min-h-0 flex-1 flex-col px-1 py-2">
      <div className="mb-5 flex items-center gap-3 px-2">
        <BrandMark live={pending} />
        <p className="truncate text-[15px] font-extrabold tracking-tight text-white">Knowledge Agent</p>
      </div>

      <nav className="flex flex-col gap-1" aria-label="Pages">
        <Item to="/" icon={<MessageSquare className="size-[17px]" aria-hidden />}>
          Ask
        </Item>
        <Item to="/knowledge-base" icon={<Library className="size-[17px]" aria-hidden />}>
          Knowledge Base
          <span className="ml-auto rounded-full bg-accent px-2 py-0.5 font-mono text-[11px] font-bold text-white">{ready}</span>
        </Item>
        <Item to="/system" icon={<Activity className="size-[17px]" aria-hidden />}>
          System
        </Item>
      </nav>

      {/* The knowledge base at a glance: what the agent can draw on right now. */}
      <div className="mt-6 flex min-h-0 flex-1 flex-col">
        <p className="label mb-2 px-3 text-white/40">Documents</p>
        {documents.length === 0 ? (
          <NavLink to="/knowledge-base" className="px-3 text-[12.5px] font-semibold text-white/60 hover:text-white">
            Add documents
          </NavLink>
        ) : (
          <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto pr-1">
            {documents.slice(0, SIDEBAR_DOCUMENTS).map((document) => (
              <li key={document.id}>
                <NavLink
                  to="/knowledge-base"
                  className="flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-[12.5px] text-white/75 transition hover:bg-shell-soft hover:text-white"
                  title={document.filename}
                >
                  <span className="w-9 shrink-0 rounded bg-white/10 text-center font-mono text-[9.5px] font-bold tracking-[0.04em] text-white/80">
                    {document.document_type.toUpperCase()}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{document.filename}</span>
                  <StatusDot document={document} />
                </NavLink>
              </li>
            ))}
          </ul>
        )}
        {documents.length > SIDEBAR_DOCUMENTS && (
          <NavLink to="/knowledge-base" className="mt-1 px-3 text-[12px] font-semibold text-white/60 hover:text-white">
            View all {documents.length} documents
          </NavLink>
        )}
      </div>

      <div className="mt-4 flex flex-col gap-3">
        <StatusCard health={health} unreachable={unreachable} />
        <button type="button" className="nav-item disabled:opacity-40" onClick={onClear} disabled={!hasRuns}>
          <Eraser className="size-[17px]" aria-hidden /> Clear conversation
        </button>
      </div>
    </div>
  )
}

/** Compact navigation for phones and tablets, rendered at the top of the content panel. */
export function MobileNav({ readyCount, pending }: { readyCount: number; pending: boolean }) {
  const link = ({ isActive }: { isActive: boolean }) =>
    `inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-semibold ${
      isActive ? 'bg-accent-light text-primary' : 'text-muted hover:bg-bg'
    }`
  return (
    <div className="flex items-center gap-2 overflow-x-auto border-b border-border px-3 py-2 [scrollbar-width:none]">
      <BrandMark live={pending} small />
      <span className="mr-1 hidden shrink-0 text-sm font-extrabold tracking-tight sm:inline">Knowledge Agent</span>
      <NavLink to="/" end className={link}>
        <MessageSquare className="size-3.5" aria-hidden /> Ask
      </NavLink>
      <NavLink to="/knowledge-base" className={link}>
        <Library className="size-3.5" aria-hidden /> Documents <span className="font-mono text-[11px]">{readyCount}</span>
      </NavLink>
      <NavLink to="/system" className={link}>
        <Activity className="size-3.5" aria-hidden /> System
      </NavLink>
    </div>
  )
}

function Item({ to, icon, children }: { to: string; icon: ReactNode; children: ReactNode }) {
  return (
    <NavLink to={to} end className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
      {icon}
      {children}
    </NavLink>
  )
}

function StatusDot({ document }: { document: DocumentInfo }) {
  const tone = document.status === 'ready' ? 'bg-[#6EE7B7]' : document.status === 'failed' ? 'bg-[#FCA5A5]' : 'bg-[#FCD34D] animate-pulse-dot'
  return <span className={`size-[7px] shrink-0 rounded-full ${tone}`} aria-label={isProcessing(document) ? 'processing' : document.status} />
}

export function BrandMark({ live, small }: { live: boolean; small?: boolean }) {
  return (
    <span
      className={`relative inline-flex shrink-0 items-center justify-center rounded-[10px] bg-accent ${small ? 'size-7 rounded-lg' : 'size-9'}`}
      aria-hidden
    >
      <span
        className={`rounded-full border-2 border-white border-r-transparent ${small ? 'size-3.5' : 'size-4'} ${live ? 'animate-spin [animation-duration:1.1s]' : ''}`}
      />
    </span>
  )
}

/** The sidebar's bottom card: service health and the active limits, at a glance. */
function StatusCard({ health, unreachable }: { health: Health | null; unreachable: boolean }) {
  const services = health?.services
  const rows: [string, boolean][] = [
    ['Database', !unreachable && (services?.database.ok ?? false)],
    ['Embeddings', !unreachable && (services?.embedding.ok ?? false)],
    ['Claude', !unreachable && (services?.llm.ok ?? false)],
  ]
  const allOk = rows.every(([, ok]) => ok)
  return (
    <NavLink
      to="/system"
      className="block rounded-[18px] bg-[linear-gradient(145deg,var(--color-accent)_0%,var(--color-accent-deep)_100%)] p-4 text-white shadow-[0_16px_30px_-18px_var(--color-accent)] transition hover:brightness-105"
    >
      <p className="flex items-center justify-between text-[15px] font-extrabold tracking-tight">
        {unreachable ? 'API unreachable' : allOk ? 'System ready' : 'Needs attention'}
        <ArrowUpRight className="size-4 opacity-80" aria-hidden />
      </p>
      <ul className="mt-2.5 space-y-1 text-[12.5px] text-white/85">
        {rows.map(([name, ok]) => (
          <li key={name} className="flex items-center gap-2">
            <i className={`size-[7px] rounded-full ${ok ? 'bg-[#6EE7B7]' : 'bg-[#FCA5A5]'}`} aria-hidden />
            {name}
          </li>
        ))}
      </ul>
    </NavLink>
  )
}
