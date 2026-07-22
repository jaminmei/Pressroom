export const SUPPORTED_LANGUAGES = ["en", "zh-TW"] as const;

export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export const LANGUAGE_STORAGE_KEY = "dc.language";
export const DEFAULT_LANGUAGE: SupportedLanguage = "en";

export function isSupportedLanguage(value: unknown): value is SupportedLanguage {
  return typeof value === "string" && SUPPORTED_LANGUAGES.includes(value as SupportedLanguage);
}

export function resolveInitialLanguage(
  storedLanguage: unknown,
  browserLanguages: readonly string[] = []
): SupportedLanguage {
  if (isSupportedLanguage(storedLanguage)) {
    return storedLanguage;
  }

  return browserLanguages.some((language) => /^zh(?:-|$)/i.test(language))
    ? "zh-TW"
    : DEFAULT_LANGUAGE;
}

export function readStoredLanguage(): string | null {
  try {
    return window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function persistLanguage(language: SupportedLanguage): void {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Browser storage is optional; the in-memory language still changes.
  }
}

export function detectInitialLanguage(): SupportedLanguage {
  const languages = typeof navigator === "undefined"
    ? []
    : navigator.languages?.length
      ? navigator.languages
      : navigator.language
        ? [navigator.language]
        : [];

  return resolveInitialLanguage(
    typeof window === "undefined" ? null : readStoredLanguage(),
    languages
  );
}
