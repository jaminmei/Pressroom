import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import i18n from "./index";
import {
  DEFAULT_LANGUAGE,
  isSupportedLanguage,
  persistLanguage,
  type SupportedLanguage
} from "./language";

export interface LanguageController {
  language: SupportedLanguage;
  setLanguage: (language: SupportedLanguage) => Promise<void>;
}

export function useLanguage(): LanguageController {
  const { i18n: reactiveI18n } = useTranslation();
  const language = isSupportedLanguage(reactiveI18n.resolvedLanguage)
    ? reactiveI18n.resolvedLanguage
    : DEFAULT_LANGUAGE;

  const setLanguage = useCallback(async (nextLanguage: SupportedLanguage) => {
    persistLanguage(nextLanguage);
    document.documentElement.lang = nextLanguage;
    await i18n.changeLanguage(nextLanguage);
  }, []);

  return { language, setLanguage };
}
