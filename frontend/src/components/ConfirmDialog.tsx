import { useEffect, useRef } from 'react'

interface Props {
  title: string
  body: string
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({ title, body, confirmLabel, onConfirm, onCancel }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const element = dialog.current
    element?.showModal()
    return () => element?.close()
  }, [])

  return (
    <dialog
      ref={dialog}
      onClose={onCancel}
      onClick={(event) => {
        if (event.target === dialog.current) onCancel()
      }}
      className="m-auto w-[min(92vw,26rem)] rounded-xl border border-border bg-surface p-0 text-ink shadow-xl backdrop:bg-ink/30"
    >
      <div className="p-5">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="mt-2 text-sm leading-6 text-muted">{body}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className="btn btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn bg-err text-white hover:bg-[#9c3a34]" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  )
}
