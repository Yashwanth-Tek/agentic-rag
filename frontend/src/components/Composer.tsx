import { Paperclip, SendHorizontal, Square } from 'lucide-react'
import type { RefObject } from 'react'
import { Link } from 'react-router'

const MAX_QUESTION = 2000

interface Props {
  value: string
  onChange: (value: string) => void
  pending: boolean
  disabled?: boolean
  placeholder?: string
  onSubmit: (question: string) => void
  onCancel: () => void
  inputRef?: RefObject<HTMLTextAreaElement | null>
}

export function Composer({ value, onChange, pending, disabled, placeholder, onSubmit, onCancel, inputRef }: Props) {
  const submit = () => {
    const question = value.trim()
    if (!question || pending || disabled) return
    onSubmit(question)
    onChange('')
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
      className="flex items-end gap-2 rounded-2xl border border-border bg-surface p-2 shadow-[0_8px_24px_-18px_rgb(2_32_64/0.5)] transition duration-150 focus-within:border-accent focus-within:ring-[3px] focus-within:ring-accent-light"
    >
      <Link to="/knowledge-base" className="icon-btn size-10 shrink-0 border-0 bg-bg" title="Add documents to the knowledge base" aria-label="Add documents">
        <Paperclip className="size-4" aria-hidden />
      </Link>
      <label htmlFor="question" className="sr-only">
        Ask a question about your knowledge base
      </label>
      <textarea
        ref={inputRef}
        id="question"
        rows={1}
        value={value}
        maxLength={MAX_QUESTION}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            submit()
          }
        }}
        placeholder={placeholder ?? 'Ask a question…'}
        className="field-sizing-content max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2.5 text-[15px] outline-none placeholder:text-faint disabled:text-muted"
      />
      {pending ? (
        <button type="button" onClick={onCancel} className="btn btn-secondary size-10 shrink-0 rounded-xl p-0" aria-label="Stop" title="Stop">
          <Square className="size-4" aria-hidden />
        </button>
      ) : (
        <button type="submit" className="btn btn-primary size-10 shrink-0 rounded-xl p-0" disabled={!value.trim() || disabled} aria-label="Ask" title="Ask">
          <SendHorizontal className="size-[18px]" aria-hidden />
        </button>
      )}
    </form>
  )
}
