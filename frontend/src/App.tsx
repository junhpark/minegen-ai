import { TopBar } from '@/components/layout/TopBar'
import { LeftPanel } from '@/components/layout/LeftPanel'
import { RightPanel } from '@/components/layout/RightPanel'
import { BottomBar } from '@/components/layout/BottomBar'
import { MineCanvas } from '@/scene/MineCanvas'
import { useViewerStore } from '@/stores/viewerStore'

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
 *
 * WALKTHROUGH is immersive: panels and the timeline bar are hidden and the
 * canvas takes the full area. Every other mode keeps this layout exactly.
 */
export default function App() {
  const walkthrough = useViewerStore((s) => s.mode) === 'WALKTHROUGH'
  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        {walkthrough ? null : <LeftPanel />}
        <main className="min-w-0 flex-1">
          <MineCanvas />
        </main>
        {walkthrough ? null : <RightPanel />}
      </div>
      {walkthrough ? null : <BottomBar />}
    </div>
  )
}
