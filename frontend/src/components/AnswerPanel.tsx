import type { Segment } from '../types'

type Block = { kind: 'paragraph'; segments: Segment[] } | { kind: 'list'; items: Segment[][] }

/** Validated sentences grouped into paragraphs (lines starting with "- " become list items),
 *  each sentence carrying its source numbers. */
export function AnswerPanel({ segments }: { segments: Segment[] }) {
  const blocks = groupBlocks(segments)
  return (
    <div className="space-y-3.5 text-[15.5px] leading-[1.75]">
      {blocks.map((block, index) =>
        block.kind === 'list' ? (
          <ul key={index} className="space-y-1.5 pl-5">
            {block.items.map((item, i) => (
              <li key={i} className="list-disc marker:text-accent">
                <Sentences segments={item} stripBullet />
              </li>
            ))}
          </ul>
        ) : (
          <p key={index}>
            <Sentences segments={block.segments} />
          </p>
        ),
      )}
    </div>
  )
}

function groupBlocks(segments: Segment[]): Block[] {
  const paragraphs: Segment[][] = []
  for (const segment of segments) {
    if (segment.paragraph_start || paragraphs.length === 0) paragraphs.push([segment])
    else paragraphs[paragraphs.length - 1].push(segment)
  }
  const blocks: Block[] = []
  for (const paragraph of paragraphs) {
    if (paragraph[0]?.text.startsWith('- ')) {
      const last = blocks[blocks.length - 1]
      if (last?.kind === 'list') last.items.push(paragraph)
      else blocks.push({ kind: 'list', items: [paragraph] })
    } else {
      blocks.push({ kind: 'paragraph', segments: paragraph })
    }
  }
  return blocks
}

function Sentences({ segments, stripBullet }: { segments: Segment[]; stripBullet?: boolean }) {
  return (
    <>
      {segments.map((segment, i) => (
        <span key={i} className={segment.kind === 'not_in_kb' ? 'text-muted italic' : ''}>
          {i > 0 && ' '}
          {stripBullet && i === 0 ? segment.text.replace(/^- /, '') : segment.text}
          {segment.sources.map((n) => (
            <span key={n} className="cite">
              {n}
            </span>
          ))}
        </span>
      ))}
    </>
  )
}
