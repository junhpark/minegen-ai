import { create } from 'zustand'

/**
 * PR-3 round 4 — UI locale (Park: "한국어가 default로 나오도록").
 *
 * The UI is authored in English (the source strings stay the keys the tests
 * assert) and rendered through `tr()` (`i18n/t.ts`), which looks the English
 * string up in the Korean dictionary (`i18n/ko.ts`) when the locale is
 * `ko`. The DEFAULT is Korean; `VITE_DEFAULT_LOCALE=en` pins English (the
 * vitest and e2e environments do, so every English assertion keeps its
 * meaning), and the person's choice is remembered per browser
 * (`localStorage`, never a scenario field). The locale is presentation
 * state only: it changes no request, no artifact, no stage.
 */
export type Locale = 'ko' | 'en'
export const LOCALES: readonly Locale[] = ['ko', 'en']
export const LOCALE_LABEL: Record<Locale, string> = { ko: '한국어', en: 'English' }

const STORAGE_KEY = 'minegen.locale'

/** the locale the app starts in: the stored choice, else the build default (ko) */
export function resolveDefaultLocale(
  envValue: string | undefined,
  stored: string | null | undefined,
): Locale {
  if (stored === 'ko' || stored === 'en') return stored
  if (envValue === 'ko' || envValue === 'en') return envValue
  return 'ko'
}

function readStored(): string | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function writeStored(locale: Locale): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    /* a blocked storage keeps the session choice only */
  }
}

function applyLang(locale: Locale): void {
  if (typeof document !== 'undefined') document.documentElement.lang = locale
}

interface LocaleState {
  locale: Locale
  setLocale: (locale: Locale) => void
}

const initial = resolveDefaultLocale(import.meta.env.VITE_DEFAULT_LOCALE, readStored())
applyLang(initial)

export const useLocaleStore = create<LocaleState>()((set) => ({
  locale: initial,
  setLocale: (locale) => {
    writeStored(locale)
    applyLang(locale)
    set({ locale })
  },
}))

/** the current locale outside React (formatters, pure helpers) */
export function currentLocale(): Locale {
  return useLocaleStore.getState().locale
}
