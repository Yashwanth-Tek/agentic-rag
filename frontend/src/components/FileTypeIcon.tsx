import { File, FileJson, FileSpreadsheet, FileText } from 'lucide-react'

export function FileTypeIcon({ name, className }: { name: string; className?: string }) {
  const extension = name.split('.').pop()?.toLowerCase()
  if (extension === 'csv') return <FileSpreadsheet className={className} aria-hidden />
  if (extension === 'json') return <FileJson className={className} aria-hidden />
  if (extension === 'pdf' || extension === 'docx' || extension === 'md' || extension === 'markdown' || extension === 'txt') {
    return <FileText className={className} aria-hidden />
  }
  return <File className={className} aria-hidden />
}
