import { Upload } from 'lucide-react'
import { useRef, useState } from 'react'

interface Props {
  onFiles: (files: FileList | File[]) => void
  extensions: string[] | null
  maxMb: number | null
}

export function Dropzone({ onFiles, extensions, maxMb }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault()
        setOver(false)
        if (event.dataTransfer.files.length) onFiles(event.dataTransfer.files)
      }}
      className={`flex flex-wrap items-center justify-between gap-4 rounded-2xl border-[1.5px] border-dashed px-5 py-5 transition-colors duration-150 ${
        over ? 'border-accent bg-accent-light' : 'border-faint/60 bg-surface'
      }`}
    >
      <div className="flex items-center gap-3">
        <span className="flex size-10 items-center justify-center rounded-xl bg-accent-light text-accent" aria-hidden>
          <Upload className="size-[18px]" />
        </span>
        <div>
          <p className="text-[14.5px] font-bold">Drop files here</p>
          <p className="text-[12.5px] text-muted">
            {(extensions ?? ['.pdf', '.docx', '.md', '.txt', '.csv', '.json']).map((e) => e.replace('.', '').toUpperCase()).join(' · ')}
            {maxMb ? ` · up to ${maxMb} MB` : ''}
          </p>
        </div>
      </div>
      <button type="button" className="btn btn-secondary" onClick={() => input.current?.click()}>
        Browse files
      </button>
      <input
        ref={input}
        type="file"
        multiple
        accept={extensions?.join(',')}
        className="sr-only"
        onChange={(event) => {
          if (event.target.files?.length) onFiles(event.target.files)
          event.target.value = ''
        }}
      />
    </div>
  )
}
