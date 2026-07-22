import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { detectInitialLanguage } from "./language";
import { en } from "./resources/en";
import { zhTW } from "./resources/zhTW";

const initialLanguage = detectInitialLanguage();

void i18n.use(initReactI18next).init({
  resources: {
    en,
    "zh-TW": zhTW
  },
  lng: initialLanguage,
  fallbackLng: "en",
  supportedLngs: ["en", "zh-TW"],
  defaultNS: "common",
  ns: Object.keys(en),
  interpolation: {
    escapeValue: false
  },
  react: {
    useSuspense: false
  }
});

document.documentElement.lang = initialLanguage;

export default i18n;
export { en, zhTW };
