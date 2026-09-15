import type { Locale } from "./types";

/**
 * Shell-chrome localization seed (EN default, RU overrides). Keys: `zone.<EnglishLabel>`, `nav.<sectionKey>`,
 * `tb.<control>`. Section bodies localize progressively; extend RU as needed.
 */
const RU: Record<string, string> = {
  "zone.Operations": "Операции",
  "zone.Observability": "Наблюдаемость",
  "zone.Settings": "Настройки",
  "nav.workspaces": "Рабочие пространства",
  "nav.health": "Здоровье",
  "nav.indexes": "Индексы и топология",
  "nav.coverage": "Покрытие контента",
  "nav.ingestion": "Задачи ингестии",
  "nav.snapshots": "Снапшоты",
  "nav.critical": "Критичные события",
  "nav.runtime": "Runtime Guard и MCP",
  "nav.logs": "Логи и трейсы",
  "nav.analytics": "Аналитика",
  "nav.campaigns": "Кампании покрытия",
  "nav.sql": "SQL Explorer",
  "nav.retrieval": "Настройки поиска",
  "nav.languages": "Реестры языков",
  "nav.apikeys": "API-ключи и доступ",
  "nav.config": "История конфигурации",
  "nav.quality": "Проверки качества",
  "tb.search": "Поиск…",
  "tb.compact": "Плотно",
  "tb.comfortable": "Просторно",
  "tb.guidance": "Подсказки",
  "tb.off": "Выкл",
  "tb.operational": "Работает",
};

const TABLES: Record<Exclude<Locale, "en">, Record<string, string>> = { ru: RU };

/** Resolve a localized string; falls back to the provided English text. */
export function translate(locale: Locale, key: string, fallback: string): string {
  if (locale !== "en") {
    const v = TABLES[locale]?.[key];
    if (v != null) return v;
  }
  return fallback;
}
