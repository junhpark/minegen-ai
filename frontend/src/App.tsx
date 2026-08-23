import { TopBar } from '@/components/layout/TopBar'
import { LeftPanel } from '@/components/layout/LeftPanel'
import { RightPanel } from '@/components/layout/RightPanel'
import { BottomBar } from '@/components/layout/BottomBar'
import { MineCanvas } from '@/scene/MineCanvas'

/**
 * Main layout (SRS §41):
 *
 *   ┌──────────────────────────────────────────────┐
 *   │ TopBar: brand + mode tabs + backend status    │
 *   ├────────┬──────────────────────────┬───────────┤
 *   │ Left   │        3D viewer         │ Inspector │
 *   ├────────┴──────────────────────────┴───────────┤
 *   │ 4D timeline                                   │
 *   └──────────────────────────────────────────────┘
 */
export default function App() {
  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <LeftPanel />
        <main className="min-w-0 flex-1">
          <MineCanvas />
        </main>
        <RightPanel />
      </div>
      <BottomBar />
    </div>
  )
}
