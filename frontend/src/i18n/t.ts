import { KO } from './ko'
import { currentLocale, useLocaleStore, type Locale } from './locale'

/**
 * `tr(text, vars?)` — the ONE translation call. `text` is the English source
 * string (the key); when the locale is `ko` and the dictionary knows it, the
 * Korean entry is returned, otherwise the English text itself (a missing
 * entry is visible, never an empty string). `{name}` placeholders are
 * substituted AFTER the lookup, so a dictionary entry may reorder them
 * (`'{n} levels'` → `'{n}개 레벨'`). Pure and synchronous: components call it
 * at render time through `useT()` so a locale switch re-renders them.
 */
export type Vars = Record<string, string | number>

export function translate(text: string, locale: Locale, vars?: Vars): string {
  const base = locale === 'ko' ? (KO[text] ?? text) : text
  if (!vars) return base
  return base.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m))
}

export function tr(text: string, vars?: Vars): string {
  return translate(text, currentLocale(), vars)
}

/** render-time translator bound to the live locale (re-renders on switch) */
export function useT(): (text: string, vars?: Vars) => string {
  const locale = useLocaleStore((s) => s.locale)
  return (text, vars) => translate(text, locale, vars)
}
