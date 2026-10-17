import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { useLocaleStore } from './i18n/locale'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

/**
 * PR-3 round 4 — the app tree is keyed by the UI locale: switching the
 * language remounts the whole tree, so every `tr()` call (plain function,
 * no hook) renders the new language. Stores and the query cache live
 * outside React and survive the remount; only ephemeral view state
 * (open disclosures, a pointer-locked walk) restarts.
 */
export function Root() {
  const locale = useLocaleStore((s) => s.locale)
  return (
    <QueryClientProvider client={queryClient}>
      <App key={locale} />
    </QueryClientProvider>
  )
}
