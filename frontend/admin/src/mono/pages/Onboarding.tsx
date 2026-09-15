"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { Tag } from "../components/Tag";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { IconName, Locale } from "../lib/types";

/* ============================================================================
 * Onboarding Knowledge Base — standalone support page (route /onboarding).
 * Reuses the How-To engine with an onboarding brand and opens on the
 * onboarding article (register → validate → review → publish).
 * ==========================================================================*/

type LocaleText = Record<Locale, string>;
type LocaleList = Record<Locale, string[]>;
type CalloutVariant = "warn" | "info";

interface Callout {
  variant: CalloutVariant;
  title: LocaleText;
  body: LocaleText;
}
interface Command {
  label: string;
  cmd: string;
}
interface Example {
  title: LocaleText;
  body: LocaleText;
}
interface Article {
  id: string;
  section: string;
  kw: string[];
  title: LocaleText;
  summary: LocaleText;
  purpose: LocaleList;
  callouts: Callout[];
  steps: LocaleList;
  commands: Command[];
  examples: Example[];
}

/** Console hash route a given article's "Back to <section>" link points at. */
const SECTION_HASH: Record<string, string> = {
  "Ingestion Jobs": "ingestion",
  "Content Coverage": "coverage",
  Snapshots: "snapshots",
  Analytics: "analytics",
  "API Keys & Access": "apikeys",
  Health: "health",
};

const ART: Article[] = [
  {
    id: "onboard",
    section: "Ingestion Jobs",
    kw: ["onboard", "validate", "publish"],
    title: {
      en: "Onboard a documentation source",
      ru: "Подключение источника документации",
    },
    summary: {
      en: "Register a product, validate the pipeline, then publish — without touching live content prematurely.",
      ru: "Зарегистрируйте продукт, проверьте конвейер, затем публикуйте — не трогая живой контент раньше времени.",
    },
    purpose: {
      en: [
        "Bring a new product family onto the platform safely",
        "Catch parser/coverage problems before they reach retrieval",
      ],
      ru: [
        "Безопасно добавить новый продукт",
        "Поймать проблемы парсинга до публикации",
      ],
    },
    callouts: [
      {
        variant: "warn",
        title: { en: "Always run Validate-Only first", ru: "Сначала всегда Validate-Only" },
        body: {
          en: "Never publish before reviewing chunk output in the review workspace.",
          ru: "Не публикуйте до проверки чанков в review workspace.",
        },
      },
    ],
    steps: {
      en: [
        "Open Ingestion Jobs → Onboarding",
        "Fill product identity, repository layout, language hints",
        "Register — a Validate-Only run is queued automatically",
        "Open History & Review, inspect the transformation chain",
        "Publish once the publish-safety gate passes",
      ],
      ru: [
        "Откройте Ingestion Jobs → Onboarding",
        "Заполните идентичность, layout, языки",
        "Зарегистрируйте — запустится Validate-Only",
        "Откройте History & Review, проверьте цепочку",
        "Опубликуйте после прохождения gate",
      ],
    },
    commands: [
      {
        label: "Validate-only run",
        cmd: "adcs ingest validate --product aspose.ocr --kind apiref",
      },
    ],
    examples: [
      {
        title: { en: "First-time onboarding", ru: "Первое подключение" },
        body: {
          en: "New repo, no snapshot → Validate-Only → review → publish.",
          ru: "Новый репозиторий → Validate-Only → проверка → публикация.",
        },
      },
    ],
  },
  {
    id: "coverage",
    section: "Content Coverage",
    kw: ["coverage", "gap", "mcp-ready"],
    title: { en: "Diagnose coverage gaps", ru: "Диагностика пробелов покрытия" },
    summary: {
      en: "Read the readiness table and triage gaps by root cause and severity.",
      ru: "Читайте таблицу готовности и сортируйте пробелы по причине и серьёзности.",
    },
    purpose: {
      en: [
        "Understand why a scope is not MCP-ready",
        "Prioritise remediation across a product family",
      ],
      ru: ["Понять, почему scope не MCP-ready", "Приоритизировать исправления"],
    },
    callouts: [
      {
        variant: "info",
        title: { en: "Most gaps share one cause", ru: "У большинства пробелов одна причина" },
        body: {
          en: "“No recent runtime signal” usually means: never ingested.",
          ru: "«No recent runtime signal» обычно значит: не было ингестии.",
        },
      },
    ],
    steps: {
      en: [
        "Scan the four summary tiles",
        "Expand a row to read diagnostics & fix plan",
        "Use the triage section, filter by severity",
        "Jump to Ingestion to remediate",
      ],
      ru: [
        "Просмотрите 4 плитки",
        "Раскройте строку — диагностика и план",
        "Используйте triage по серьёзности",
        "Перейдите в Ingestion",
      ],
    },
    commands: [{ label: "Check readiness", cmd: "adcs coverage status --product aspose.3d" }],
    examples: [
      {
        title: { en: "Degraded after working", ru: "Деградация" },
        body: {
          en: "Was ready, now warning → re-publish snapshot.",
          ru: "Был готов, теперь warning → переопубликуйте снапшот.",
        },
      },
    ],
  },
  {
    id: "rollback",
    section: "Snapshots",
    kw: ["rollback", "publish", "snapshot"],
    title: { en: "Publish & roll back safely", ru: "Безопасная публикация и откат" },
    summary: {
      en: "Promote a snapshot, compare revisions, and execute a controlled rollback.",
      ru: "Активируйте снапшот, сравните ревизии, выполните контролируемый откат.",
    },
    purpose: {
      en: ["Change live retrieval without surprises", "Keep an audit trail of every switch"],
      ru: ["Менять выдачу без сюрпризов", "Хранить аудит каждого переключения"],
    },
    callouts: [
      {
        variant: "warn",
        title: { en: "Rollback re-points live traffic", ru: "Откат меняет живой трафик" },
        body: {
          en: "It is immediate. Confirm with the typed ROLLBACK gate.",
          ru: "Эффект мгновенный. Подтвердите вводом ROLLBACK.",
        },
      },
    ],
    steps: {
      en: [
        "Open Snapshots → Active & Compare",
        "Select two snapshots, Compare",
        "Go to Rollback, choose target & reason",
        "Type ROLLBACK to confirm",
      ],
      ru: [
        "Snapshots → Active & Compare",
        "Выберите два, Compare",
        "Rollback — цель и причина",
        "Введите ROLLBACK",
      ],
    },
    commands: [
      { label: "Rollback", cmd: 'adcs snapshot rollback --to snap_71ad…c03 --reason "incident"' },
    ],
    examples: [
      {
        title: { en: "Bad publish", ru: "Плохая публикация" },
        body: {
          en: "New snapshot drops coverage → roll back to prior.",
          ru: "Новый снапшот теряет покрытие → откат.",
        },
      },
    ],
  },
  {
    id: "zero-result",
    section: "Analytics",
    kw: ["zero", "result", "retrieval", "zr"],
    title: { en: "Triage zero-result waves", ru: "Разбор волн нулевых результатов" },
    summary: {
      en: "Cluster no-results by root cause and replay requests against the current index.",
      ru: "Группируйте нулевые результаты по причине и переигрывайте запросы.",
    },
    purpose: {
      en: ["Find the highest-impact failure mode fast", "Turn a complaint into a guided fix"],
      ru: ["Быстро найти главный сбой", "Превратить жалобу в исправление"],
    },
    callouts: [
      {
        variant: "info",
        title: { en: "Replay detects drift", ru: "Replay ловит дрифт" },
        body: {
          en: "Compare original evidence vs current results.",
          ru: "Сравните исходные данные с текущими.",
        },
      },
    ],
    steps: {
      en: [
        "Open Analytics → Zero-result cockpit",
        "Act on the highest-impact cluster",
        "Open Issue inbox, select a request",
        "Replay, then Create fix draft",
      ],
      ru: [
        "Analytics → Zero-result cockpit",
        "Возьмите крупнейший кластер",
        "Issue inbox → запрос",
        "Replay → Create fix draft",
      ],
    },
    commands: [{ label: "Replay a request", cmd: "adcs analytics replay --request req_8c3864e" }],
    examples: [
      {
        title: { en: "No index data", ru: "Нет индекса" },
        body: {
          en: "62% of misses → onboard & publish those scopes.",
          ru: "62% промахов → подключить и опубликовать.",
        },
      },
    ],
  },
  {
    id: "keys",
    section: "API Keys & Access",
    kw: ["keys", "token", "scope", "rotate"],
    title: { en: "Provision & rotate API keys", ru: "Выдача и ротация API-ключей" },
    summary: {
      en: "Issue narrowly-scoped keys, copy the one-time secret, and rotate on a schedule.",
      ru: "Выдавайте узкие ключи, копируйте одноразовый секрет, ротация по расписанию.",
    },
    purpose: {
      en: ["Limit blast radius per integration", "Keep an immutable governance log"],
      ru: ["Ограничить радиус поражения", "Хранить неизменяемый журнал"],
    },
    callouts: [
      {
        variant: "warn",
        title: { en: "The secret is shown once", ru: "Секрет показывается один раз" },
        body: {
          en: "Copy it before navigating away — it cannot be retrieved.",
          ru: "Скопируйте сразу — потом не восстановить.",
        },
      },
    ],
    steps: {
      en: [
        "Open API Keys → Key provisioning",
        "Set owner, product scope, scopes",
        "Create key, copy the secret",
        "Rotate or disable from the registry",
      ],
      ru: [
        "API Keys → Key provisioning",
        "Владелец, продукт, scopes",
        "Создать ключ, скопировать секрет",
        "Ротация/отключение в реестре",
      ],
    },
    commands: [{ label: "Rotate key", cmd: "adcs keys rotate --id adcs_prod_4f2b" }],
    examples: [
      {
        title: { en: "Contractor access", ru: "Доступ подрядчика" },
        body: {
          en: "Read-only, single product, disable when done.",
          ru: "Только чтение, один продукт, отключить после.",
        },
      },
    ],
  },
  {
    id: "health",
    section: "Health",
    kw: ["health", "dependency", "readiness"],
    title: { en: "Read the health dashboard", ru: "Чтение дашборда здоровья" },
    summary: {
      en: "Confirm uptime, dependency readiness, and error rate in 15 seconds.",
      ru: "Проверьте аптайм, готовность зависимостей и ошибки за 15 секунд.",
    },
    purpose: {
      en: ["Give an all-clear before standup", "Spot a degraded dependency early"],
      ru: ["Дать «всё чисто» перед стендапом", "Заметить деградацию рано"],
    },
    callouts: [
      {
        variant: "info",
        title: { en: "Not all deps are required", ru: "Не все зависимости обязательны" },
        body: {
          en: "A dependency may be optional in the current runtime profile.",
          ru: "Зависимость может быть опциональной в текущем профиле.",
        },
      },
    ],
    steps: {
      en: [
        "Scan the KPI strip",
        "Open a component for drill-down diagnostics",
        "Check the operation scope preview",
        "Jump to Indexes for topology",
      ],
      ru: [
        "Просмотрите KPI",
        "Откройте компонент для диагностики",
        "Проверьте scope-preview",
        "Перейдите в Indexes",
      ],
    },
    commands: [{ label: "Readiness probe", cmd: "curl -s /readyz" }],
    examples: [
      {
        title: { en: "Qdrant required", ru: "Qdrant обязателен" },
        body: {
          en: "Vector store powers dense retrieval — keep it green.",
          ru: "Векторное хранилище — держите зелёным.",
        },
      },
    ],
  },
];

/**
 * Onboarding brand. Locale-invariant — same text in every locale.
 */
const BRAND = {
  name: { en: "Onboarding KB", ru: "Onboarding KB" },
  sub: {
    en: "Bring a new product onto ADCS",
    ru: "Bring a new product onto ADCS",
  },
} as const;

/** This page opens on the onboarding article (window.__htStart === 'onboard'). */
const START_ID = "onboard";

const THEME_KEY = "adcs_theme";
const LOCALE_KEY = "adcs_locale";

const UI = {
  searchPlaceholder: { en: "Search articles…", ru: "Поиск статей…" },
  noMatch: { en: "No articles match", ru: "Ничего не найдено" },
  console: { en: "Console", ru: "В консоль" },
  why: { en: "Why this exists", ru: "Зачем это" },
  steps: { en: "Workflow steps", ru: "Шаги" },
  commands: { en: "Commands", ru: "Команды" },
  examples: { en: "Examples", ru: "Примеры" },
  screenshots: { en: "Screenshots", ru: "Скриншоты" },
  capture: { en: "Screen capture", ru: "Скриншот экрана" },
  copy: { en: "Copy", ru: "Копировать" },
  copied: { en: "Copied", ru: "Скопировано" },
  back: { en: "Back to", ru: "Назад к разделу" },
} as const;

function pick(o: LocaleText, l: Locale): string {
  return o[l] ?? o.en;
}
function pickList(o: LocaleList, l: Locale): string[] {
  return o[l] ?? o.en;
}

function Callouts({ items, locale }: { items: Callout[]; locale: Locale }) {
  return (
    <>
      {items.map((c, i) => (
        <div key={i} className={cn("ht-callout", c.variant)}>
          <Icon name={c.variant === "warn" ? "alert" : "info"} />
          <div>
            <div className="hc-t">{pick(c.title, locale)}</div>
            <div className="hc-b">{pick(c.body, locale)}</div>
          </div>
        </div>
      ))}
    </>
  );
}

function CommandBlock({ command, locale }: { command: Command; locale: Locale }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const onCopy = useCallback(() => {
    const text = command.cmd;
    const flagCopied = () => {
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1500);
    };
    // Only surface "Copied" when the write actually succeeds; on a
    // non-secure context (no navigator.clipboard) or a rejected write we
    // leave the label untouched rather than reporting a false success.
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(flagCopied, () => {});
    }
  }, [command.cmd]);

  return (
    <div className="ht-cmd">
      <div className="hcmd-h">
        <span>{command.label}</span>
        <button type="button" className="hcmd-copy" onClick={onCopy} aria-live="polite">
          {copied ? UI.copied[locale] : UI.copy[locale]}
        </button>
      </div>
      <pre>{command.cmd}</pre>
    </div>
  );
}

function ArticleView({ article, locale }: { article: Article; locale: Locale }) {
  const heading = (label: ReactNode) => <div className="ht-h">{label}</div>;
  const backHash = SECTION_HASH[article.section] ?? "health";
  const backLabel =
    locale === "ru" ? UI.back.ru : `${UI.back.en} ${article.section}`;

  return (
    <div className="ht-article">
      <div className="ht-meta">
        <Tag>{article.section}</Tag>
        {article.kw.slice(0, 3).map((k) => (
          <Tag key={k}>{k}</Tag>
        ))}
      </div>
      <h1>{pick(article.title, locale)}</h1>
      <p className="ht-summary">{pick(article.summary, locale)}</p>

      <Callouts items={article.callouts} locale={locale} />

      {heading(UI.why[locale])}
      <ul className="ht-purpose">
        {pickList(article.purpose, locale).map((p, i) => (
          <li key={i}>{p}</li>
        ))}
      </ul>

      {heading(UI.steps[locale])}
      <ol className="ht-steps">
        {pickList(article.steps, locale).map((s, i) => (
          <li key={i}>
            <span>{s}</span>
          </li>
        ))}
      </ol>

      {heading(UI.commands[locale])}
      {article.commands.map((c) => (
        <CommandBlock key={c.label} command={c} locale={locale} />
      ))}

      {heading(UI.examples[locale])}
      {article.examples.map((ex, i) => (
        <div key={i} className="ht-example">
          <div className="he-t">{pick(ex.title, locale)}</div>
          <div className="he-b">{pick(ex.body, locale)}</div>
        </div>
      ))}

      <div className="ht-screens">
        {heading(UI.screenshots[locale])}
        <div className="ht-shot">
          <div className="ht-shot-ph">
            <Icon name="grid" />
            <span>{UI.capture[locale]}</span>
          </div>
        </div>
      </div>

      <div className="ht-back">
        <a href={`/#${backHash}`}>
          <Icon name="arrow" /> {backLabel}
        </a>
      </div>
    </div>
  );
}

export default function OnboardingPage() {
  const [activeId, setActiveId] = useState<string>(START_ID);
  const [query, setQuery] = useState("");
  // Hydration-safe: start at defaults, sync from localStorage after mount.
  const [locale, setLocale] = useState<Locale>("en");
  const [dark, setDark] = useState(false);

  useEffect(() => {
    try {
      const t = localStorage.getItem(THEME_KEY);
      if (t === "dark") setDark(true);
      const l = localStorage.getItem(LOCALE_KEY);
      if (l === "ru" || l === "en") setLocale(l);
    } catch {
      /* storage unavailable — keep defaults */
    }
  }, []);

  // Reflect locale on <html lang>.
  useEffect(() => {
    if (typeof document !== "undefined") document.documentElement.lang = locale;
  }, [locale]);

  const toggleTheme = useCallback(() => {
    setDark((d) => {
      const next = !d;
      try {
        localStorage.setItem(THEME_KEY, next ? "dark" : "light");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const toggleLocale = useCallback(() => {
    setLocale((l) => {
      const next: Locale = l === "en" ? "ru" : "en";
      try {
        localStorage.setItem(LOCALE_KEY, next);
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ART;
    return ART.filter(
      (a) =>
        pick(a.title, locale).toLowerCase().includes(q) ||
        a.kw.some((k) => k.includes(q)) ||
        a.section.toLowerCase().includes(q),
    );
  }, [query, locale]);

  const active = ART.find((a) => a.id === activeId) ?? ART[0];
  const themeIcon: IconName = dark ? "moon" : "sun";

  return (
    <div className={cn("adcs", "t-mono", dark && "theme-dark")}>
      <div className="ht-shell">
        <aside className="ht-side" aria-label="Knowledge base navigation">
          <header className="ht-brand">
            <div className="side-logo" aria-hidden="true">
              A
            </div>
            <div>
              <div className="side-brand-name">{pick(BRAND.name, locale)}</div>
              <div className="side-brand-sub">{pick(BRAND.sub, locale)}</div>
            </div>
          </header>

          <div className="ht-search">
            <div className="input">
              <input
                id="ht-q"
                className="inputctl"
                type="search"
                placeholder={UI.searchPlaceholder[locale]}
                aria-label={UI.searchPlaceholder[locale]}
                autoComplete="off"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
          </div>

          <nav className="ht-list" aria-label="Articles">
            {matches.length === 0 ? (
              <div className="muted-note" style={{ padding: 12 }}>
                {UI.noMatch[locale]}
              </div>
            ) : (
              matches.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  className={cn("ht-li", a.id === activeId && "on")}
                  aria-current={a.id === activeId ? "page" : undefined}
                  onClick={() => setActiveId(a.id)}
                >
                  <span className="ht-li-t">{pick(a.title, locale)}</span>
                  <span className="ht-li-s">{a.section}</span>
                </button>
              ))
            )}
          </nav>
        </aside>

        <main className="ht-main">
          <div className="ht-top">
            <a className="ql-back" href="/">
              <Icon name="arrow" />
              <span>{UI.console[locale]}</span>
            </a>
            <div className="ht-top-r">
              <button
                type="button"
                className="locale-btn"
                onClick={toggleLocale}
                aria-label={`Language: ${locale.toUpperCase()} — switch to ${(locale === "en" ? "ru" : "en").toUpperCase()}`}
              >
                <span className="dot" aria-hidden="true" />
                <span>{locale.toUpperCase()}</span>
              </button>
              <button
                type="button"
                className="icon-btn"
                onClick={toggleTheme}
                aria-pressed={dark}
                aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
              >
                <Icon name={themeIcon} />
              </button>
            </div>
          </div>

          <ArticleView article={active} locale={locale} />
        </main>
      </div>
    </div>
  );
}
