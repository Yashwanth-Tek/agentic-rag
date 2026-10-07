import { Check, Cpu, Database, Gauge, Sparkles, Upload, X } from 'lucide-react'
import type { ComponentType, ReactNode } from 'react'

import { PanelHeader } from '../components/Shell'
import type { Health } from '../types'

interface Props {
  health: Health | null
  unreachable: boolean
}

/** Read-only view of service health and the non-secret configuration the API reports. */
export function System({ health, unreachable }: Props) {
  const services = health?.services
  const configuration = health?.configuration
  const rows: [string, string, boolean, string | null][] = [
    ['Database', 'PostgreSQL + pgvector', !unreachable && (services?.database.ok ?? false), services?.database.detail ?? null],
    ['Embeddings', 'Ollama', !unreachable && (services?.embedding.ok ?? false), services?.embedding.detail ?? null],
    ['Claude', 'Anthropic API', !unreachable && (services?.llm.ok ?? false), services?.llm.detail ?? null],
  ]

  return (
    <>
      <PanelHeader title="System" />
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-6 sm:py-6 lg:px-8">
        <div className="mx-auto max-w-[1120px] space-y-6">
          {unreachable && (
            <p className="rounded-xl border border-err/25 bg-err-bg px-4 py-3 text-sm font-semibold text-err">
              The API is unreachable. Start the backend and reload this page.
            </p>
          )}

          <section>
            <p className="label mb-3">Services</p>
            <div className="grid gap-3 sm:grid-cols-3">
              {rows.map(([name, kind, ok, detail]) => (
                <div key={name} className="card flex items-start gap-3 px-4 py-4">
                  <span className={`flex size-9 shrink-0 items-center justify-center rounded-xl ${ok ? 'bg-ok-bg text-ok' : 'bg-err-bg text-err'}`} aria-hidden>
                    {ok ? <Check className="size-4" strokeWidth={3} /> : <X className="size-4" strokeWidth={3} />}
                  </span>
                  <div className="min-w-0">
                    <p className="text-[14px] font-bold">{name}</p>
                    <p className="text-[12px] text-muted">{kind}</p>
                    {!ok && <p className="mt-1.5 text-[12.5px] text-err">{detail ?? 'Not reachable.'}</p>}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {configuration && (
            <section>
              <p className="label mb-3">Configuration</p>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                <Group icon={Gauge} title="Agent limits" note="Enforced by the application on every question.">
                  <Row name="Tool calls" value={String(configuration.limits.max_tool_calls)} />
                  <Row name="Time" value={`${configuration.limits.max_agent_time_seconds} s`} />
                  <Row name="Consecutive failures" value={String(configuration.limits.max_consecutive_tool_failures)} />
                </Group>
                <Group icon={Sparkles} title="Claude" note="The model that decides what to retrieve and writes the answer.">
                  <Row name="Model" value={configuration.llm.model} />
                  <Row name="Effort" value={configuration.llm.effort} />
                </Group>
                <Group icon={Cpu} title="Retrieval" note="What each search and read may return.">
                  <Row name="Results per search" value={String(configuration.retrieval.top_k)} />
                  <Row name="Minimum similarity" value={String(configuration.retrieval.min_similarity)} />
                  <Row name="Read limit" value={`${configuration.retrieval.read_section_max_chars.toLocaleString()} chars`} />
                  <Row name="Rows per read" value={String(configuration.retrieval.read_max_rows)} />
                </Group>
                <Group icon={Database} title="Embeddings" note="Vectors used for semantic search.">
                  <Row name="Model" value={configuration.embedding.model_id} />
                  <Row name="Dimension" value={String(configuration.embedding.dimension)} />
                </Group>
                <Group icon={Upload} title="Uploads" note="Accepted on the Knowledge Base page.">
                  <Row name="Maximum size" value={`${configuration.uploads.max_mb} MB`} />
                  <Row name="Types" value={configuration.uploads.extensions.join(' ')} />
                </Group>
              </div>
            </section>
          )}
        </div>
      </div>
    </>
  )
}

function Group({ icon: Icon, title, children }: { icon: ComponentType<{ className?: string }>; title: string; note?: string; children: ReactNode }) {
  return (
    <div className="card px-4 py-4">
      <div className="flex items-center gap-2.5">
        <span className="flex size-8 items-center justify-center rounded-lg bg-accent-light text-accent" aria-hidden>
          <Icon className="size-4" />
        </span>
        <p className="text-[14px] font-bold">{title}</p>
      </div>
      <dl className="mt-3 space-y-1.5 border-t border-border pt-3">{children}</dl>
    </div>
  )
}

function Row({ name, value }: { name: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-[13px]">
      <dt className="text-muted">{name}</dt>
      <dd className="mono text-right break-all text-ink">{value}</dd>
    </div>
  )
}
