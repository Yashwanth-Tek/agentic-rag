import { FileText, Library, Plus, RefreshCw, Search, ShieldCheck, Square } from 'lucide-react'
import { Fragment, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'

import { Composer } from '../components/Composer'
import { FileTypeIcon } from '../components/FileTypeIcon'
import { ResponseCard } from '../components/ResponseCard'
import { PanelHeader } from '../components/Shell'
import type { useAsk } from '../hooks'
import type { DocumentInfo } from '../types'

interface Props {
  ask: ReturnType<typeof useAsk>
  documents: DocumentInfo[] // ready documents only
}

export function Ask({ ask, documents }: Props) {
  const [draft, setDraft] = useState('')
  const input = useRef<HTMLTextAreaElement>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const ready = documents.length > 0
  const last = ask.runs[ask.runs.length - 1]

  useEffect(() => {
    if (ask.runs.length) bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [ask.runs.length])

  const pick = (question: string) => {
    setDraft(question)
    input.current?.focus()
  }

  return (
    <>
      <PanelHeader title="Ask">
        <button type="button" className="btn btn-ghost" onClick={ask.clear} disabled={ask.runs.length === 0}>
          <Plus className="size-4" aria-hidden /> <span className="hidden sm:inline">New chat</span>
        </button>
      </PanelHeader>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-3 py-4 sm:px-6 sm:py-6 lg:px-8">
        {ask.runs.length === 0 ? (
          <Welcome ready={ready} documents={documents} onPick={pick} />
        ) : (
          <div className="mx-auto flex w-full max-w-[1000px] flex-col gap-3 sm:gap-4 2xl:max-w-[1120px]">
            {ask.runs.map((run) => (
              <Fragment key={run.id}>
                <QuestionBubble text={run.question} />
                <ResponseCard run={run} onRetry={(question) => void ask.ask(question)} retryDisabled={ask.pending} />
              </Fragment>
            ))}
            {last && (
              <div className="flex justify-center pt-1">
                {last.status === 'running' ? (
                  <button type="button" className="btn btn-pill" onClick={ask.cancel}>
                    <Square className="size-3.5" aria-hidden /> Stop
                  </button>
                ) : (
                  <button type="button" className="btn btn-pill" onClick={() => void ask.ask(last.question)} disabled={ask.pending}>
                    <RefreshCw className="size-3.5" aria-hidden /> Ask again
                  </button>
                )}
              </div>
            )}
            <div ref={bottom} />
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-border bg-surface px-3 py-3 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-[1000px] 2xl:max-w-[1120px]">
          <Composer
            value={draft}
            onChange={setDraft}
            inputRef={input}
            pending={ask.pending}
            disabled={!ready}
            placeholder={ready ? undefined : 'Add documents first…'}
            onSubmit={(question) => void ask.ask(question)}
            onCancel={ask.cancel}
          />
        </div>
      </div>
    </>
  )
}

function QuestionBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[88%] rounded-2xl rounded-br-md bg-accent-light px-4 py-2.5 text-[15px] font-semibold text-primary">{text}</p>
    </div>
  )
}

const STEPS = [
  { icon: Search, label: 'Searches' },
  { icon: FileText, label: 'Reads' },
  { icon: ShieldCheck, label: 'Verifies' },
]

function Welcome({ ready, documents, onPick }: { ready: boolean; documents: DocumentInfo[]; onPick: (q: string) => void }) {
  return (
    <div className="mx-auto my-auto w-full max-w-[1000px] py-2 sm:py-4 2xl:max-w-[1120px]">
      <div className="text-center">
        <h2 className="text-[28px] leading-tight font-extrabold tracking-tight text-primary sm:text-[34px]">What would you like to know?</h2>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {STEPS.map(({ icon: Icon, label }) => (
            <span key={label} className="inline-flex items-center gap-1.5 rounded-full border border-border bg-bg px-3 py-1 text-[12.5px] font-semibold text-muted">
              <Icon className="size-3.5 text-accent" aria-hidden />
              {label}
            </span>
          ))}
        </div>
      </div>

      {ready ? (
        <div className="mt-8 grid min-w-0 gap-2.5 sm:grid-cols-2 xl:grid-cols-3 [&>*]:min-w-0">
          {documents.slice(0, 6).map((document) => {
            const question = `What does ${document.filename} cover?`
            return (
              <button
                key={document.id}
                type="button"
                onClick={() => onPick(question)}
                className="card flex w-full min-w-0 items-center gap-3 px-4 py-3 text-left transition duration-150 hover:border-accent/50 hover:bg-accent-light/40"
              >
                <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-accent-light text-primary" aria-hidden>
                  <FileTypeIcon name={document.filename} className="size-4" />
                </span>
                <span className="min-w-0 truncate text-[13.5px] font-semibold">{question}</span>
              </button>
            )
          })}
        </div>
      ) : (
        <div className="mt-8 text-center">
          <Link to="/knowledge-base" className="btn btn-primary">
            <Library className="size-4" aria-hidden /> Add documents
          </Link>
        </div>
      )}
    </div>
  )
}
