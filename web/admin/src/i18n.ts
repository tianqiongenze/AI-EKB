import { zhCN, type TranslationKey } from "./locales/zh-CN";
import { en } from "./locales/en";

export type Locale = "zh-CN" | "en";
export type { TranslationKey };

const STORAGE_KEY = "ekb.admin.locale";
const DEFAULT_LOCALE: Locale = "zh-CN";

const dictionaries: Record<Locale, Record<TranslationKey, string>> = {
  "zh-CN": zhCN,
  en,
};

function isLocale(value: unknown): value is Locale {
  return value === "zh-CN" || value === "en";
}

function readStoredLocale(): Locale {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isLocale(stored) ? stored : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

let currentLocale: Locale = readStoredLocale();

export function getLocale(): Locale {
  return currentLocale;
}

export function setLocale(locale: Locale): void {
  currentLocale = locale;
  try {
    window.localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // localStorage 不可用时仅保留内存态
  }
}

export type TParams = Record<string, string | number>;

/** 极简翻译：t(key) 或 t(key, { name: value })，占位符写作 {name}。 */
export function t(key: TranslationKey, params?: TParams): string {
  const dict = dictionaries[currentLocale] ?? dictionaries[DEFAULT_LOCALE];
  let text: string = dict[key] ?? dictionaries[DEFAULT_LOCALE][key] ?? key;
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.replaceAll(`{${name}}`, String(value));
    }
  }
  return text;
}
