import type { ReactNode } from 'react'

interface Props {
  title: string
  /** optional right-aligned tag, e.g. a phase marker */
  tag?: string | undefined
  children: ReactNode
}

export function PanelSection({ title, tag, children }: Props) {
  return (
    <section className="border-b border-rock-700 px-4 py-3">
      <header className="mb-2 flex items-baseline justify-between">
        <h2 className="plate text-[12px] text-chalk-dim">{title}</h2>
        {tag ? <span className="readout text-[10px] text-mute">{tag}</span> : null}
      </header>
      {children}
    </section>
  )
}
