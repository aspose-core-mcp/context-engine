"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { Button } from "../components/Button";
import { Tag } from "../components/Tag";
import { cn } from "../lib/cn";
import { Icon } from "../lib/icons";
import type { IconName, Locale } from "../lib/types";
import {
  AdminApiError,
  fetchPublicHowToArticles,
  getAdminApiBaseUrl,
  type HowToOverridePayload,
  type PublishedHowToListResponse,
} from "@/lib/admin-api";

/* ------------------------------------------------------------------ *
 * How-To Knowledge Center — standalone support page (route: /howto).
 *
 * Mono page: renders its OWN root wrapper + chrome (this route is NOT
 * inside the admin console shell) using the `.ht-*` classes + tokens only.
 * No new hex/fonts. Light/dark + EN/RU toggles persist to
 * localStorage["adcs_theme"] / localStorage["adcs_locale"].
 *
 * Features:
 *   1. URL deep-linking + return machinery via next/navigation —
 *      ?article / ?lang / ?from / ?source_label / ?return_to are read on
 *      mount and drive the selected article + a "Back to <label>" link.
 *   2. A real "Open in Studio" entry → /howto/studio.
 *   3. Published-override fetch (public, no auth) layered over the in-file
 *      baseline corpus via TanStack useQuery + fetchPublicHowToArticles.
 *   4. Corpus grouped by topic, each entry carrying an entry label + route
 *      path (the grouped canonical set the admin sections deep-link into).
 *   5. Screenshot slot + zoom Dialog (kit `.modal` overlay).
 *
 * Public-endpoint data flow (in-file fixtures are the offline fallback):
 *   - live success            -> baseline + published overrides applied
 *   - live success but EMPTY   -> baseline only (silent fallback)
 *   - live ERROR               -> baseline only + a dismissible notice
 *   - offline / no backend     -> baseline (the in-file corpus IS the fixture)
 * The baseline corpus is always populated, so no skeleton/empty/error ever
 * hides the interactive UI — fixtures always win.
 * ------------------------------------------------------------------ */

const THEME_KEY = "adcs_theme";
const LOCALE_KEY = "adcs_locale";

/** Visually-hidden style for labels / live-region announcements (kit has no .sr-only class). */
const SR_ONLY: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0,0,0,0)",
  whiteSpace: "nowrap",
  border: 0,
};

/** Bilingual string: EN + RU, EN is the fallback. */
type Loc = { en: string; ru: string };
/** Bilingual list. */
type LocList = { en: string[]; ru: string[] };

type CalloutVariant = "warn" | "info";
/** [variant, title, body] */
type Callout = [CalloutVariant, Loc, Loc];
/** [label, command] */
type Command = [string, string];
/** [title, body] */
type Example = [Loc, Loc];
/** Screenshot: alt + caption, plus an optional override src (Studio asset). */
type Shot = { src?: string; alt: Loc; caption: Loc };

/** Topic groups mirror the canonical `HOW_TO_TOPICS` taxonomy. */
type Topic = "Admin Console" | "Public Pages" | "Onboarding";

interface Article {
  /** Stable id — matches the canonical article IDs admin sections deep-link to. */
  id: string;
  topic: Topic;
  /** Sidebar entry label (bilingual). */
  entryLabel: Loc;
  /** Console section / page this article documents (display chip). */
  section: string;
  /** Route the "Open linked page" / "Back to section" default targets. */
  routePath: string;
  kw: string[];
  title: Loc;
  summary: Loc;
  purpose: LocList;
  callouts: Callout[];
  steps: LocList;
  commands: Command[];
  examples: Example[];
  /** Optional screenshot captures (alt + caption); src derived from id. */
  shots: Shot[];
  /**
   * Curated sister-article ids surfaced as the in-reader "Related how-to
   * articles" button row. Resolved against the live corpus; unknown ids drop out.
   */
  related?: string[];
}

const ART: Article[] = [
  /* ------------------------------- Admin Console ------------------------------- */
  {
    id: "admin-health",
    topic: "Admin Console",
    entryLabel: { en: "Health", ru: "Состояние системы" },
    section: "Health",
    routePath: "/#health",
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
      [
        "info",
        { en: "Not all deps are required", ru: "Не все зависимости обязательны" },
        {
          en: "A dependency may be optional in the current runtime profile.",
          ru: "Зависимость может быть опциональной в текущем профиле.",
        },
      ],
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
    commands: [["Readiness probe", "curl -s /readyz"]],
    examples: [
      [
        { en: "Qdrant required", ru: "Qdrant обязателен" },
        {
          en: "Vector store powers dense retrieval — keep it green.",
          ru: "Векторное хранилище — держите зелёным.",
        },
      ],
    ],
    shots: [
      { alt: { en: "Health dashboard with the dependency readiness grid", ru: "Дашборд здоровья с сеткой готовности зависимостей" }, caption: { en: "Health — KPI strip and dependency drill-down", ru: "Состояние — KPI и детализация зависимостей" } },
    ],
    related: ["admin-critical-events", "admin-snapshots"],
  },
  {
    id: "admin-ingestion-jobs",
    topic: "Admin Console",
    entryLabel: { en: "Ingestion Jobs", ru: "Задания ingestion" },
    section: "Ingestion Jobs",
    routePath: "/#ingestion-jobs",
    kw: ["onboard", "validate", "publish", "ingestion"],
    title: { en: "Onboard a documentation source", ru: "Подключение источника документации" },
    summary: {
      en: "Register a product, validate the pipeline, then publish — without touching live content prematurely.",
      ru: "Зарегистрируйте продукт, проверьте конвейер, затем публикуйте — не трогая живой контент раньше времени.",
    },
    purpose: {
      en: [
        "Bring a new product family onto the platform safely",
        "Catch parser/coverage problems before they reach retrieval",
      ],
      ru: ["Безопасно добавить новый продукт", "Поймать проблемы парсинга до публикации"],
    },
    callouts: [
      [
        "warn",
        { en: "Always run Validate-Only first", ru: "Сначала всегда Validate-Only" },
        {
          en: "Never publish before reviewing chunk output in the review workspace.",
          ru: "Не публикуйте до проверки чанков в review workspace.",
        },
      ],
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
    commands: [["Validate-only run", "adcs ingest validate --product aspose.ocr --kind apiref"]],
    examples: [
      [
        { en: "First-time onboarding", ru: "Первое подключение" },
        {
          en: "New repo, no snapshot → Validate-Only → review → publish.",
          ru: "Новый репозиторий → Validate-Only → проверка → публикация.",
        },
      ],
    ],
    shots: [
      { alt: { en: "Ingestion onboarding form with validate-only queued", ru: "Форма подключения ingestion с очередью validate-only" }, caption: { en: "Ingestion Jobs — onboarding & validate-only run", ru: "Задания ingestion — подключение и запуск validate-only" } },
    ],
    related: ["admin-snapshots", "admin-language-registries", "admin-analytics"],
  },
  {
    id: "admin-snapshots",
    topic: "Admin Console",
    entryLabel: { en: "Snapshots", ru: "Снапшоты" },
    section: "Snapshots",
    routePath: "/#snapshots",
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
      [
        "warn",
        { en: "Rollback re-points live traffic", ru: "Откат меняет живой трафик" },
        {
          en: "It is immediate. Confirm with the typed ROLLBACK gate.",
          ru: "Эффект мгновенный. Подтвердите вводом ROLLBACK.",
        },
      ],
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
    commands: [["Rollback", 'adcs snapshot rollback --to snap_71ad…c03 --reason "incident"']],
    examples: [
      [
        { en: "Bad publish", ru: "Плохая публикация" },
        {
          en: "New snapshot drops coverage → roll back to prior.",
          ru: "Новый снапшот теряет покрытие → откат.",
        },
      ],
    ],
    shots: [
      { alt: { en: "Snapshot compare view with rollback confirmation gate", ru: "Сравнение снапшотов с подтверждением отката" }, caption: { en: "Snapshots — compare & typed rollback gate", ru: "Снапшоты — сравнение и ввод подтверждения отката" } },
    ],
    related: ["admin-ingestion-jobs", "admin-critical-events"],
  },
  {
    id: "admin-critical-events",
    topic: "Admin Console",
    entryLabel: { en: "Critical Events", ru: "Критичные события" },
    section: "Critical Events",
    routePath: "/#critical-events",
    kw: ["incident", "triage", "sla", "escalate"],
    title: { en: "Work an incident from triage to resolution", ru: "Разбор инцидента от триажа до закрытия" },
    summary: {
      en: "Acknowledge, assign, and escalate critical events against their SLA clock.",
      ru: "Подтверждайте, назначайте и эскалируйте критичные события по таймеру SLA.",
    },
    purpose: {
      en: ["Drive every critical event to a clean resolution", "Keep the SLA clock and audit trail honest"],
      ru: ["Довести каждое событие до закрытия", "Соблюсти SLA и вести аудит"],
    },
    callouts: [
      [
        "warn",
        { en: "Escalate before the SLA expires", ru: "Эскалируйте до истечения SLA" },
        {
          en: "If a health check fails for over 5 minutes, page the on-call owner.",
          ru: "Если health check падает дольше 5 минут — поднимите дежурного.",
        },
      ],
    ],
    steps: {
      en: [
        "Open Critical Events → triage queue",
        "Acknowledge the highest-severity open event",
        "Assign an owner and set the next action",
        "Escalate or resolve, then attach the postmortem",
      ],
      ru: [
        "Critical Events → очередь триажа",
        "Подтвердите самое серьёзное событие",
        "Назначьте владельца и следующее действие",
        "Эскалируйте или закройте, приложите постмортем",
      ],
    },
    commands: [["Acknowledge", "adcs events ack --id evt_91c4 --owner on-call"]],
    examples: [
      [
        { en: "Partial publish", ru: "Частичная публикация" },
        {
          en: "Error ratio under 30% → publish proceeds, event opened for review.",
          ru: "Доля ошибок < 30% → публикация идёт, событие открыто для разбора.",
        },
      ],
    ],
    shots: [
      { alt: { en: "Critical events triage queue with SLA countdown", ru: "Очередь триажа критичных событий с таймером SLA" }, caption: { en: "Critical Events — triage queue & SLA clock", ru: "Критичные события — очередь триажа и таймер SLA" } },
    ],
    related: ["admin-health", "admin-snapshots"],
  },
  {
    id: "admin-language-registries",
    topic: "Admin Console",
    entryLabel: { en: "Language Registries", ru: "Языковые реестры" },
    section: "Language Registries",
    routePath: "/#language-registries",
    kw: ["language", "locale", "alias", "registry"],
    title: { en: "Manage languages, locales & aliases", ru: "Управление языками, локалями и алиасами" },
    summary: {
      en: "Enable SDK languages and map external aliases to canonical language IDs.",
      ru: "Включайте SDK-языки и сопоставляйте внешние алиасы с каноническими ID.",
    },
    purpose: {
      en: ["Keep language coverage and aliases consistent", "Avoid silent gaps when a client uses an alias"],
      ru: ["Держать языки и алиасы согласованными", "Избежать пробелов при использовании алиаса"],
    },
    callouts: [
      [
        "info",
        { en: "Aliases are product-scoped", ru: "Алиасы привязаны к продукту" },
        {
          en: "A canonical language ID can carry several external aliases per product.",
          ru: "За одним каноническим ID может стоять несколько внешних алиасов на продукт.",
        },
      ],
    ],
    steps: {
      en: [
        "Open Language Registries → Languages",
        "Enable the SDK languages you serve",
        "Switch to Aliases, map the external IDs",
        "Confirm the dictionary covers each locale",
      ],
      ru: [
        "Language Registries → Languages",
        "Включите нужные SDK-языки",
        "Aliases — сопоставьте внешние ID",
        "Проверьте словарь по локалям",
      ],
    },
    commands: [["List aliases", "adcs registry aliases --product aspose.ocr"]],
    examples: [
      [
        { en: "Python-.NET alias", ru: "Алиас Python-.NET" },
        {
          en: "Map 'python-net' → canonical 'python' so queries resolve.",
          ru: "Сопоставьте 'python-net' → канонический 'python'.",
        },
      ],
    ],
    shots: [
      { alt: { en: "Language registry with the alias mapping table", ru: "Языковой реестр с таблицей сопоставления алиасов" }, caption: { en: "Language Registries — languages & alias mapping", ru: "Языковые реестры — языки и сопоставление алиасов" } },
    ],
    related: ["admin-retrieval-settings", "admin-ingestion-jobs"],
  },
  {
    id: "admin-api-keys-access",
    topic: "Admin Console",
    entryLabel: { en: "API Keys & Access", ru: "API-ключи и доступ" },
    section: "API Keys & Access",
    routePath: "/#api-keys-access",
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
      [
        "warn",
        { en: "The secret is shown once", ru: "Секрет показывается один раз" },
        {
          en: "Copy it before navigating away — it cannot be retrieved.",
          ru: "Скопируйте сразу — потом не восстановить.",
        },
      ],
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
    commands: [["Rotate key", "adcs keys rotate --id adcs_prod_4f2b"]],
    examples: [
      [
        { en: "Contractor access", ru: "Доступ подрядчика" },
        {
          en: "Read-only, single product, disable when done.",
          ru: "Только чтение, один продукт, отключить после.",
        },
      ],
    ],
    shots: [
      { alt: { en: "Key provisioning form with the one-time secret reveal", ru: "Форма выдачи ключа с одноразовым показом секрета" }, caption: { en: "API Keys — provisioning & one-time secret", ru: "API-ключи — выдача и одноразовый секрет" } },
    ],
    related: ["public-integrations", "admin-retrieval-settings"],
  },
  {
    id: "admin-retrieval-settings",
    topic: "Admin Console",
    entryLabel: { en: "Retrieval Settings", ru: "Настройки поиска" },
    section: "Retrieval Settings",
    routePath: "/#retrieval-settings",
    kw: ["retrieval", "top_k", "confidence", "clarify"],
    title: { en: "Tune retrieval per product", ru: "Настройка поиска по продукту" },
    summary: {
      en: "Adjust top-k, context budget, and the low-confidence clarification policy.",
      ru: "Меняйте top-k, бюджет контекста и политику уточнений при низкой уверенности.",
    },
    purpose: {
      en: ["Balance recall against context budget", "Decide when to clarify vs answer"],
      ru: ["Баланс полноты и бюджета контекста", "Когда уточнять, а когда отвечать"],
    },
    callouts: [
      [
        "info",
        { en: "Changes are product-scoped", ru: "Изменения привязаны к продукту" },
        {
          en: "Each product carries its own top-k and clarification policy.",
          ru: "У каждого продукта свой top-k и политика уточнений.",
        },
      ],
    ],
    steps: {
      en: [
        "Open Retrieval Settings, pick the product",
        "Set top-k and max context tokens",
        "Choose the clarification policy",
        "Save — changes apply on the next query",
      ],
      ru: [
        "Retrieval Settings — выберите продукт",
        "Задайте top-k и бюджет токенов",
        "Выберите политику уточнений",
        "Сохраните — применится на след. запросе",
      ],
    },
    commands: [["Inspect settings", "adcs retrieval settings --product aspose.ocr"]],
    examples: [
      [
        { en: "Noisy results", ru: "Шумные результаты" },
        {
          en: "Lower top-k and raise the confidence threshold to clarify sooner.",
          ru: "Снизьте top-k и поднимите порог уверенности для ранних уточнений.",
        },
      ],
    ],
    shots: [
      { alt: { en: "Retrieval settings panel with the per-product sliders", ru: "Панель настроек поиска со слайдерами по продукту" }, caption: { en: "Retrieval Settings — top-k & clarification policy", ru: "Настройки поиска — top-k и политика уточнений" } },
    ],
    related: ["admin-analytics", "admin-language-registries"],
  },
  {
    id: "admin-analytics",
    topic: "Admin Console",
    entryLabel: { en: "Analytics", ru: "Аналитика" },
    section: "Analytics",
    routePath: "/#analytics",
    kw: ["zero", "result", "retrieval", "zr", "analytics"],
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
      [
        "info",
        { en: "Replay detects drift", ru: "Replay ловит дрифт" },
        {
          en: "Compare original evidence vs current results.",
          ru: "Сравните исходные данные с текущими.",
        },
      ],
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
    commands: [["Replay a request", "adcs analytics replay --request req_8c3864e"]],
    examples: [
      [
        { en: "No index data", ru: "Нет индекса" },
        {
          en: "62% of misses → onboard & publish those scopes.",
          ru: "62% промахов → подключить и опубликовать.",
        },
      ],
    ],
    shots: [
      { alt: { en: "Zero-result cockpit with clustered misses and replay", ru: "Кокпит нулевых результатов с кластерами и replay" }, caption: { en: "Analytics — zero-result clusters & replay", ru: "Аналитика — кластеры без результата и replay" } },
    ],
    related: ["admin-sql-explorer", "admin-retrieval-settings", "admin-ingestion-jobs"],
  },
  {
    id: "admin-sql-explorer",
    topic: "Admin Console",
    entryLabel: { en: "SQL Explorer", ru: "SQL Explorer" },
    section: "SQL Explorer",
    routePath: "/#sql-explorer-read-only",
    kw: ["sql", "query", "read-only", "explore"],
    title: { en: "Run a read-only analytics query", ru: "Чтение аналитики через SQL" },
    summary: {
      en: "Explore the analytics store with a bounded, read-only SQL surface and export rows.",
      ru: "Исследуйте аналитику через ограниченный read-only SQL и выгружайте строки.",
    },
    purpose: {
      en: ["Answer ad-hoc questions without a data dump", "Stay inside the read-only safety envelope"],
      ru: ["Отвечать на вопросы без выгрузки БД", "Оставаться в read-only безопасности"],
    },
    callouts: [
      [
        "info",
        { en: "Queries are bounded", ru: "Запросы ограничены" },
        {
          en: "Row caps and a statement timeout protect the analytics store.",
          ru: "Лимит строк и таймаут защищают аналитическое хранилище.",
        },
      ],
    ],
    steps: {
      en: [
        "Open SQL Explorer (read-only)",
        "Write a SELECT against the analytics views",
        "Run, then read the bounded result set",
        "Export to CSV when you need to share",
      ],
      ru: [
        "Откройте SQL Explorer (read-only)",
        "Напишите SELECT по аналитическим вью",
        "Запустите и прочитайте результат",
        "Выгрузите CSV для шаринга",
      ],
    },
    commands: [["Top zero-result reasons", "SELECT zero_result_reason, count(*) FROM ... GROUP BY 1"]],
    examples: [
      [
        { en: "Locale breakdown", ru: "Разбивка по локали" },
        {
          en: "Group requests by doc_locale to spot translation pressure.",
          ru: "Сгруппируйте запросы по doc_locale, чтобы увидеть нагрузку на перевод.",
        },
      ],
    ],
    shots: [
      { alt: { en: "SQL Explorer with a bounded result table and CSV export", ru: "SQL Explorer с ограниченной таблицей и экспортом CSV" }, caption: { en: "SQL Explorer — bounded query & CSV export", ru: "SQL Explorer — ограниченный запрос и экспорт CSV" } },
    ],
    related: ["admin-analytics", "admin-health"],
  },
  /* -------------------------------- Public Pages -------------------------------- */
  {
    id: "public-status",
    topic: "Public Pages",
    entryLabel: { en: "Status Page", ru: "Страница статуса" },
    section: "Status",
    routePath: "/status",
    kw: ["status", "uptime", "coverage", "public"],
    title: { en: "Read the public status page", ru: "Чтение публичной страницы статуса" },
    summary: {
      en: "Confirm platform health, per-service coverage, and MCP-readiness for the public.",
      ru: "Проверьте здоровье платформы, покрытие сервисов и готовность MCP для публики.",
    },
    purpose: {
      en: ["Give integrators a single source of truth", "Surface coverage and readiness transparently"],
      ru: ["Дать интеграторам единый источник правды", "Прозрачно показать покрытие и готовность"],
    },
    callouts: [
      [
        "info",
        { en: "Coverage is per service", ru: "Покрытие — по сервисам" },
        {
          en: "Docs and API reference are tracked as separate services.",
          ru: "Docs и API reference отслеживаются как отдельные сервисы.",
        },
      ],
    ],
    steps: {
      en: [
        "Open the Status page",
        "Read the overall platform indicator",
        "Scan per-service MCP-readiness",
        "Drill into a degraded service for its fix plan",
      ],
      ru: [
        "Откройте страницу Status",
        "Прочитайте общий индикатор",
        "Просмотрите готовность по сервисам",
        "Раскройте деградировавший сервис",
      ],
    },
    commands: [["Status JSON", "curl -s /v1/status"]],
    examples: [
      [
        { en: "Degraded dependency", ru: "Деградация зависимости" },
        {
          en: "Overall stays operational while one optional dep is yellow.",
          ru: "Общий статус «работает», одна опц. зависимость жёлтая.",
        },
      ],
    ],
    shots: [
      { alt: { en: "Public status page with the platform indicator and service rows", ru: "Публичная страница статуса с индикатором и сервисами" }, caption: { en: "Status — platform indicator & per-service coverage", ru: "Status — индикатор платформы и покрытие сервисов" } },
    ],
    related: ["public-integrations", "admin-health"],
  },
  {
    id: "public-integrations",
    topic: "Public Pages",
    entryLabel: { en: "Integrations", ru: "Интеграции" },
    section: "Integrations",
    routePath: "/integrations",
    kw: ["integrations", "config", "mcp", "client"],
    title: { en: "Generate client MCP configs", ru: "Генерация MCP-конфигов клиентов" },
    summary: {
      en: "Produce ready-to-paste MCP config snippets per client and run the self-test.",
      ru: "Сгенерируйте готовые MCP-сниппеты по клиентам и запустите self-test.",
    },
    purpose: {
      en: ["Cut time-to-first-query for new integrators", "Verify a client is wired correctly"],
      ru: ["Сократить время до первого запроса", "Проверить корректность подключения клиента"],
    },
    callouts: [
      [
        "info",
        { en: "streamable-http is the default", ru: "streamable-http по умолчанию" },
        {
          en: "Use sse only when a client explicitly requires it.",
          ru: "Используйте sse только если клиент этого требует.",
        },
      ],
    ],
    steps: {
      en: [
        "Open Integrations → Generate client configs",
        "Pick the product, client, and transport",
        "Generate, then copy the snippet",
        "Run the self-test to confirm readiness",
      ],
      ru: [
        "Integrations → Generate client configs",
        "Выберите продукт, клиент, транспорт",
        "Сгенерируйте и скопируйте сниппет",
        "Запустите self-test",
      ],
    },
    commands: [["Config export", "curl -s '/v1/integrations/mcp-configs?product_id=aspose.ocr'"]],
    examples: [
      [
        { en: "Cursor setup", ru: "Настройка Cursor" },
        {
          en: "Drop the snippet into .cursor/mcp.json and reload.",
          ru: "Вставьте сниппет в .cursor/mcp.json и перезагрузите.",
        },
      ],
    ],
    shots: [
      { alt: { en: "Integrations generator with per-client config cards", ru: "Генератор интеграций с карточками конфигов клиентов" }, caption: { en: "Integrations — config generator & self-test", ru: "Интеграции — генератор конфигов и self-test" } },
    ],
    related: ["onboarding-overview", "public-status", "admin-api-keys-access"],
  },
  /* --------------------------------- Onboarding --------------------------------- */
  {
    id: "onboarding-overview",
    topic: "Onboarding",
    entryLabel: { en: "Onboarding Overview", ru: "Обзор онбординга" },
    section: "Onboarding",
    routePath: "/onboarding",
    kw: ["onboarding", "getting-started", "first-query", "quickstart"],
    title: { en: "Go from zero to first grounded answer", ru: "От нуля до первого ответа с источниками" },
    summary: {
      en: "Connect a client, run a starter query, and confirm the answer is citation-backed.",
      ru: "Подключите клиент, выполните стартовый запрос и проверьте цитаты в ответе.",
    },
    purpose: {
      en: ["Get a new operator productive in minutes", "Prove the grounding loop end to end"],
      ru: ["Быстро ввести нового оператора", "Доказать работу цепочки grounding"],
    },
    callouts: [
      [
        "info",
        { en: "Start with a starter pack", ru: "Начните со starter pack" },
        {
          en: "Each pack bundles a config, a starter prompt, and first queries.",
          ru: "Каждый pack содержит конфиг, стартовый промпт и первые запросы.",
        },
      ],
    ],
    steps: {
      en: [
        "Open Onboarding and pick a starter pack",
        "Install the client config from the bundle",
        "Run the starter prompt against your client",
        "Confirm the answer carries citations",
      ],
      ru: [
        "Откройте Onboarding, выберите pack",
        "Установите конфиг клиента из набора",
        "Запустите стартовый промпт",
        "Проверьте цитаты в ответе",
      ],
    },
    commands: [["Starter packs", "curl -s '/v1/onboarding/starter-packs?product_id=aspose.ocr'"]],
    examples: [
      [
        { en: "First query", ru: "Первый запрос" },
        {
          en: "Ask how to recognize text from a PDF; expect a cited snippet.",
          ru: "Спросите про распознавание текста из PDF; ждите сниппет с цитатой.",
        },
      ],
    ],
    shots: [
      { alt: { en: "Onboarding starter pack with config bundle and first queries", ru: "Стартовый набор онбординга с конфигом и первыми запросами" }, caption: { en: "Onboarding — starter pack & first grounded query", ru: "Онбординг — стартовый набор и первый запрос с источниками" } },
    ],
    related: ["public-integrations", "public-status"],
  },
];

/** Topic display order — mirrors the canonical HOW_TO_TOPICS taxonomy. */
const TOPIC_ORDER: Topic[] = ["Admin Console", "Public Pages", "Onboarding"];

/** Screenshot src follows the canonical convention `/howto/screenshots/<id>.png`. */
function shotSrc(articleId: string): string {
  return `/howto/screenshots/${articleId}.png`;
}

/** Localised UI strings, EN fallback. */
const UI = {
  searchPlaceholder: { en: "Search articles…", ru: "Поиск статей…" },
  noMatch: { en: "No articles match", ru: "Ничего не найдено" },
  why: { en: "Why this exists", ru: "Зачем это" },
  steps: { en: "Workflow steps", ru: "Шаги" },
  commands: { en: "Commands", ru: "Команды" },
  examples: { en: "Examples", ru: "Примеры" },
  related: { en: "Related how-to articles", ru: "Связанные how-to статьи" },
  quickLinks: {
    en: "Quick links for this admin section",
    ru: "Быстрые ссылки для этого раздела админки",
  },
  screenshots: { en: "Screenshots", ru: "Скриншоты" },
  capture: { en: "Screen capture", ru: "Скриншот экрана" },
  console: { en: "Console", ru: "В консоль" },
  openedFrom: { en: "Opened from", ru: "Открыто из раздела" },
  studio: { en: "Open in Studio", ru: "Открыть в Studio" },
  openLinked: { en: "Open linked page", ru: "Открыть связанную страницу" },
  incompleteTranslation: {
    en: "Translation for this article is incomplete. English fallback is shown for missing fragments.",
    ru: "Перевод этой статьи неполный. Для недостающих фрагментов показан английский.",
  },
  overridesUnavailable: {
    en: "Showing baseline content — published edits from Studio could not be loaded.",
    ru: "Показан базовый контент — опубликованные правки из Studio не загрузились.",
  },
} as const;

const BRAND = { name: "How-To Center", sub: "ADCS knowledge base" };

const STUDIO_HREF = "/howto/studio";

/** Normalise a `?lang` value to a supported locale, else null. */
function normalizeLocale(value: string | null): Locale | null {
  return value === "en" || value === "ru" ? value : null;
}

/** Turn a section id like "ingestion-jobs" into "Ingestion Jobs" for the back link. */
function humanizeSection(value: string | null): string | null {
  if (!value) return null;
  return value
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

/* ------------------------------------------------------------------ *
 * Published-override merge.
 *
 * The public endpoint returns HowToOverridePayload per article_id; we
 * layer ONLY the fields it carries over the in-file baseline article, so
 * Studio edits surface without a deploy. Offline / empty / error → the
 * baseline article is returned unchanged (it is the fixture).
 * ------------------------------------------------------------------ */

function calloutVariant(level: HowToOverridePayload["callouts"][number]["level"]): CalloutVariant {
  return level === "warning" ? "warn" : "info";
}

function applyOverride(base: Article, ov: HowToOverridePayload | undefined): Article {
  if (!ov) return base;
  return {
    ...base,
    entryLabel: ov.entry_label,
    title: ov.title,
    summary: ov.summary,
    purpose: ov.purpose,
    steps: ov.workflow,
    callouts: ov.callouts.map(
      (c): Callout => [calloutVariant(c.level), c.title, { en: c.body.en.join(" "), ru: c.body.ru.join(" ") }],
    ),
    commands: ov.commands.map((c): Command => [c.label.en || c.command, c.command]),
    examples: ov.examples.map(
      (e): Example => [e.title, { en: e.bullets.en.join(" "), ru: e.bullets.ru.join(" ") }],
    ),
    shots: ov.screenshots.map((s): Shot => ({
      // Studio-uploaded assets are served under /v1/howto/assets/ — prefix the
      // admin API base so they resolve; other
      // srcs (absolute / already-prefixed) pass through untouched.
      src: s.src.startsWith("/v1/howto/assets/") ? `${getAdminApiBaseUrl()}${s.src}` : s.src,
      alt: s.alt,
      caption: s.caption,
    })),
  };
}

/** Whether the article still has untranslated fragments for the active locale. */
function hasLocaleGaps(a: Article, locale: Locale): boolean {
  if (locale === "en") return false;
  const txt = (o: Loc) => !o.ru.trim();
  const lines = (o: LocList) => o.ru.length === 0 || o.ru.some((l) => !l.trim());
  return (
    txt(a.entryLabel) ||
    txt(a.title) ||
    txt(a.summary) ||
    lines(a.purpose) ||
    lines(a.steps) ||
    a.callouts.some(([, t, b]) => txt(t) || txt(b)) ||
    a.examples.some(([t, b]) => txt(t) || txt(b))
  );
}

export default function HowToPage() {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();

  // Hydration-safe: start at defaults, then sync from URL / localStorage in effects.
  const [locale, setLocale] = useState<Locale>("en");
  const [dark, setDark] = useState(false);
  const [active, setActive] = useState<string>(ART[0].id);
  const [query, setQuery] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const [liveMsg, setLiveMsg] = useState("");
  const [zoom, setZoom] = useState<{ src: string; caption: string; alt: string } | null>(null);
  const [overrideNoticeDismissed, setOverrideNoticeDismissed] = useState(false);

  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const zoomRef = useRef<HTMLDivElement>(null);
  const zoomCloseRef = useRef<HTMLButtonElement>(null);

  // Published overrides (public endpoint, no auth). Always enabled; offline /
  // error → baseline corpus wins (it is the fixture), so the UI never empties.
  const overridesQuery = useQuery<PublishedHowToListResponse>({
    queryKey: ["public-howto-articles"],
    queryFn: () => fetchPublicHowToArticles(),
    staleTime: 60_000,
  });

  const overrideById = useMemo(() => {
    const map = new Map<string, HowToOverridePayload>();
    for (const item of overridesQuery.data?.articles ?? []) {
      map.set(item.article_id, item.published);
    }
    return map;
  }, [overridesQuery.data?.articles]);

  // Effective corpus: baseline with any published override layered on.
  const articles = useMemo(
    () => ART.map((a) => applyOverride(a, overrideById.get(a.id))),
    [overrideById],
  );

  // ── URL deep-linking: ?article / ?lang on mount + when params change ──
  useEffect(() => {
    const fromQuery = normalizeLocale(searchParams.get("lang"));
    if (fromQuery) {
      setLocale(fromQuery);
      return;
    }
    try {
      const stored = normalizeLocale(localStorage.getItem(LOCALE_KEY));
      if (stored) setLocale(stored);
    } catch {
      /* storage unavailable — keep default */
    }
  }, [searchParams]);

  useEffect(() => {
    const articleParam = searchParams.get("article");
    if (articleParam && ART.some((a) => a.id === articleParam)) {
      setActive(articleParam);
    }
  }, [searchParams]);

  useEffect(() => {
    try {
      if (localStorage.getItem(THEME_KEY) === "dark") setDark(true);
    } catch {
      /* keep default */
    }
  }, []);

  // Keep <html lang> in step with the chosen locale.
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  useEffect(
    () => () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    },
    [],
  );

  const L = useCallback((o: Loc): string => (o[locale] != null ? o[locale] : o.en) || "", [locale]);
  const LL = useCallback(
    (o: LocList): string[] => (o[locale]?.length ? o[locale] : o.en) || [],
    [locale],
  );
  const U = useCallback((o: Loc): string => o[locale] || o.en, [locale]);

  // ── URL writer: keep ?article + ?lang in sync, preserve context params ──
  const updateUrl = useCallback(
    (articleId: string, nextLocale: Locale) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("article", articleId);
      params.set("lang", nextLocale);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const selectArticle = useCallback(
    (articleId: string) => {
      setActive(articleId);
      updateUrl(articleId, locale);
    },
    [locale, updateUrl],
  );

  const toggleTheme = useCallback(() => {
    setDark((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(THEME_KEY, next ? "dark" : "light");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const toggleLocale = useCallback(() => {
    setLocale((prev) => {
      const next: Locale = prev === "en" ? "ru" : "en";
      try {
        localStorage.setItem(LOCALE_KEY, next);
      } catch {
        /* ignore */
      }
      updateUrl(active, next);
      return next;
    });
  }, [active, updateUrl]);

  const copyCommand = useCallback((id: string, cmd: string) => {
    const announce = () => {
      setCopied(id);
      setLiveMsg("Copied to clipboard");
      if (copyTimer.current) clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => {
        setCopied(null);
        setLiveMsg("");
      }, 1500);
    };
    // Prefer the async Clipboard API; fall back silently (no error surfaces if
    // clipboard is unavailable — feedback still shows).
    try {
      if (navigator.clipboard?.writeText) {
        void navigator.clipboard.writeText(cmd).then(announce, announce);
        return;
      }
    } catch {
      /* fall through to legacy path */
    }
    try {
      const ta = document.createElement("textarea");
      ta.value = cmd;
      ta.setAttribute("readonly", "");
      ta.style.position = "absolute";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch {
        /* ignore */
      }
      ta.remove();
    } catch {
      /* ignore */
    }
    announce();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return articles.filter(
      (a) =>
        !q ||
        L(a.title).toLowerCase().includes(q) ||
        L(a.entryLabel).toLowerCase().includes(q) ||
        a.kw.some((k) => k.includes(q)) ||
        a.section.toLowerCase().includes(q),
    );
  }, [articles, query, L]);

  /** Grouped by topic, preserving display order; empty groups dropped. */
  const grouped = useMemo(
    () =>
      TOPIC_ORDER.map((topic) => ({
        topic,
        items: filtered.filter((a) => a.topic === topic),
      })).filter((g) => g.items.length > 0),
    [filtered],
  );

  const current = articles.find((a) => a.id === active) ?? articles[0];

  // ── Return machinery: ?return_to drives a "Back to <label>" link; the
  // label prefers ?source_label, then a humanized ?from, then the section. ──
  const returnTo = searchParams.get("return_to");
  const sourceLabel = searchParams.get("source_label");
  const fromSection = searchParams.get("from");
  // Section the operator arrived from (deep-link provenance). Distinct from
  // `backLabel`: this is null when there is no source context, so the
  // "Opened from" chip only renders when the reader was opened from a section.
  const openedFrom = sourceLabel ?? humanizeSection(fromSection);
  const backLabel = openedFrom ?? current.section;

  // ── In-reader cross-article navigation ──
  // Related: curated sister ids resolved against the live corpus (unknown drop).
  const relatedArticles = useMemo(
    () =>
      (current.related ?? [])
        .map((id) => articles.find((a) => a.id === id))
        .filter((a): a is Article => Boolean(a)),
    [current.related, articles],
  );
  // Contextual "Quick links for this admin section": auto-scoped to the active
  // article's topic (its console section), current article shown as active.
  const contextualArticles = useMemo(
    () => articles.filter((a) => a.topic === current.topic),
    [articles, current.topic],
  );

  // ── Screenshot zoom modal: focus trap + Esc/overlay close (kit pattern). ──
  useEffect(() => {
    if (!zoom) return;
    zoomCloseRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setZoom(null);
        return;
      }
      if (e.key !== "Tab" || !zoomRef.current) return;
      const focusable = zoomRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [zoom]);

  const localeGap = hasLocaleGaps(current, locale);
  // Live-only error: surface a dismissible notice (overrides could not load),
  // but only when the query truly errored — offline disabled queries do not.
  const overridesErrored =
    overridesQuery.isError && !overrideNoticeDismissed && (overridesQuery.data?.articles?.length ?? 0) === 0;
  const overridesErrorMessage =
    overridesQuery.error instanceof AdminApiError ? overridesQuery.error.message : null;

  return (
    <div className={cn("adcs", "t-mono", dark && "theme-dark")}>
      <div className="ht-shell">
        <aside className="ht-side" aria-label="Article navigation">
          <header className="ht-brand">
            <div className="side-logo" aria-hidden="true">
              A
            </div>
            <div>
              <div className="side-brand-name">{BRAND.name}</div>
              <div className="side-brand-sub">{BRAND.sub}</div>
            </div>
          </header>

          <div className="ht-search">
            <div className="input">
              <label style={SR_ONLY} htmlFor="ht-q">
                {U(UI.searchPlaceholder)}
              </label>
              <input
                id="ht-q"
                type="search"
                className="inputctl"
                placeholder={U(UI.searchPlaceholder)}
                autoComplete="off"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
          </div>

          <nav className="ht-list" id="ht-list" aria-label="Articles">
            {grouped.length === 0 ? (
              <div className="muted-note" style={{ padding: 12 }}>
                {U(UI.noMatch)}
              </div>
            ) : (
              grouped.map((group) => (
                <div key={group.topic} style={{ marginBottom: 6 }}>
                  <div className="ht-h" style={{ margin: "10px 11px 6px" }}>
                    {group.topic}
                  </div>
                  {group.items.map((a) => (
                    <button
                      key={a.id}
                      type="button"
                      className={cn("ht-li", a.id === active && "on")}
                      aria-current={a.id === active ? "true" : undefined}
                      onClick={() => selectArticle(a.id)}
                      // A <button> (not <a>, for a11y) lacks the UA anchor
                      // geometry; restore a full-width,
                      // left-aligned row so .ht-li:hover / .ht-li.on background +
                      // inset accent rail span the rail and the section label
                      // does not center under the title.
                      style={{ width: "100%", textAlign: "left" }}
                    >
                      <span className="ht-li-t">{L(a.entryLabel)}</span>
                      <span className="ht-li-s">{a.routePath}</span>
                    </button>
                  ))}
                </div>
              ))
            )}
          </nav>
        </aside>

        <main className="ht-main">
          <div className="ht-top">
            <a className="ql-back" href={returnTo || "/"}>
              <Icon name="arrow" />
              <span>{returnTo ? `${locale === "ru" ? "Назад: " : "Back to "}${backLabel}` : U(UI.console)}</span>
            </a>
            <div className="ht-top-r">
              <a
                className="locale-btn"
                href={STUDIO_HREF}
                aria-label={U(UI.studio)}
                style={{ textDecoration: "none" }}
              >
                <Icon name="review" />
                <span>{U(UI.studio)}</span>
              </a>
              <button
                type="button"
                className="locale-btn"
                id="ht-locale"
                aria-label={
                  locale === "en" ? "Switch language to Russian" : "Switch language to English"
                }
                onClick={toggleLocale}
              >
                <span className="dot" />
                <span>{locale.toUpperCase()}</span>
              </button>
              <button
                type="button"
                className="icon-btn"
                id="ht-theme"
                aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
                aria-pressed={dark}
                onClick={toggleTheme}
              >
                <Icon name={dark ? "moon" : "sun"} />
              </button>
            </div>
          </div>

          <div id="ht-article">
            {localeGap ? (
              <div
                className="ht-callout warn"
                role="note"
                style={{ margin: "20px 28px 0", maxWidth: 760 }}
              >
                <Icon name="translate" />
                <div>
                  <div className="hc-b">{U(UI.incompleteTranslation)}</div>
                </div>
              </div>
            ) : null}

            {overridesErrored ? (
              <div
                className="ht-callout info"
                role="status"
                style={{ margin: "20px 28px 0", maxWidth: 760, alignItems: "center" }}
              >
                <Icon name="info" />
                <div style={{ flex: 1 }}>
                  <div className="hc-b">{overridesErrorMessage ?? U(UI.overridesUnavailable)}</div>
                </div>
                <button
                  type="button"
                  className="hcmd-copy"
                  onClick={() => void overridesQuery.refetch()}
                  style={{ marginRight: 6 }}
                >
                  {locale === "ru" ? "Повторить" : "Retry"}
                </button>
                <button
                  type="button"
                  className="x"
                  aria-label="Dismiss"
                  onClick={() => setOverrideNoticeDismissed(true)}
                >
                  <Icon name="x" />
                </button>
              </div>
            ) : null}

            <ArticleView
              article={current}
              locale={locale}
              L={L}
              LL={LL}
              U={U}
              copied={copied}
              onCopy={copyCommand}
              returnTo={returnTo}
              backLabel={backLabel}
              openedFrom={openedFrom}
              relatedArticles={relatedArticles}
              contextualArticles={contextualArticles}
              onSelect={selectArticle}
              onZoom={(src, caption, alt) => setZoom({ src, caption, alt })}
            />
          </div>
        </main>
      </div>

      {/* Screenshot zoom Dialog — kit `.modal` overlay (focus-trapped). */}
      {zoom ? (
        <div
          className="modal-overlay"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setZoom(null);
          }}
        >
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ht-zoom-title"
            ref={zoomRef}
            style={{ width: "min(880px,94vw)" }}
          >
            <div className="modal-head">
              <div className="mi" style={{ background: "var(--surface-2)", color: "var(--fg)" }}>
                <Icon name="camera" />
              </div>
              <div className="modal-title" id="ht-zoom-title">
                {zoom.caption}
              </div>
              <button
                type="button"
                className="x"
                aria-label="Close"
                onClick={() => setZoom(null)}
                ref={zoomCloseRef}
              >
                <Icon name="x" />
              </button>
            </div>
            <div className="modal-body">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={zoom.src}
                alt={zoom.alt}
                style={{
                  width: "100%",
                  display: "block",
                  borderRadius: "var(--radius)",
                  border: "1px solid var(--border)",
                  background: "var(--surface-2)",
                }}
              />
            </div>
          </div>
        </div>
      ) : null}

      <p role="status" aria-live="polite" style={SR_ONLY}>
        {liveMsg}
      </p>
    </div>
  );
}

interface ArticleViewProps {
  article: Article;
  locale: Locale;
  L: (o: Loc) => string;
  LL: (o: LocList) => string[];
  U: (o: Loc) => string;
  copied: string | null;
  onCopy: (id: string, cmd: string) => void;
  returnTo: string | null;
  backLabel: string;
  /** Source-section label when the reader was opened from a section, else null. */
  openedFrom: string | null;
  /** Curated sister articles for the "Related how-to articles" row. */
  relatedArticles: Article[];
  /** Same-section articles for the "Quick links" row (current = active). */
  contextualArticles: Article[];
  /** Switch the active article (drives related/quick-link buttons). */
  onSelect: (articleId: string) => void;
  onZoom: (src: string, caption: string, alt: string) => void;
}

function ArticleView({
  article: a,
  locale,
  L,
  LL,
  U,
  copied,
  onCopy,
  returnTo,
  backLabel,
  openedFrom,
  relatedArticles,
  contextualArticles,
  onSelect,
  onZoom,
}: ArticleViewProps) {
  const ru = locale === "ru";
  return (
    <article className="ht-article" aria-labelledby="ht-title">
      <div className="ht-meta">
        <Tag>{a.section}</Tag>
        {openedFrom ? (
          <Tag>{`${U(UI.openedFrom)} ${openedFrom}`}</Tag>
        ) : null}
        {a.kw.slice(0, 3).map((k) => (
          <Tag key={k}>{k}</Tag>
        ))}
      </div>
      <h1 id="ht-title">{L(a.title)}</h1>
      <p className="ht-summary">{L(a.summary)}</p>

      {a.callouts.map(([variant, t, b], i) => {
        const iconName: IconName = variant === "warn" ? "alert" : "info";
        return (
          <div className={cn("ht-callout", variant)} key={i} role="note">
            <Icon name={iconName} />
            <div>
              <div className="hc-t">{L(t)}</div>
              <div className="hc-b">{L(b)}</div>
            </div>
          </div>
        );
      })}

      <div className="ht-h">{U(UI.why)}</div>
      <ul className="ht-purpose">
        {LL(a.purpose).map((p, i) => (
          <li key={i}>{p}</li>
        ))}
      </ul>

      <div className="ht-h">{U(UI.steps)}</div>
      <ol className="ht-steps">
        {LL(a.steps).map((s, i) => (
          <li key={i}>
            <span>{s}</span>
          </li>
        ))}
      </ol>

      <div className="ht-h">{U(UI.commands)}</div>
      {a.commands.map(([label, cmd]) => {
        const cmdId = `${a.id}::${label}`;
        const isCopied = copied === cmdId;
        return (
          <div className="ht-cmd" key={label}>
            <div className="hcmd-h">
              <span>{label}</span>
              <button
                type="button"
                className="hcmd-copy"
                aria-label={isCopied ? `${label} copied to clipboard` : `Copy command: ${label}`}
                onClick={() => onCopy(cmdId, cmd)}
              >
                {isCopied ? "Copied" : "Copy"}
              </button>
            </div>
            <pre>{cmd}</pre>
          </div>
        );
      })}

      <div className="ht-h">{U(UI.examples)}</div>
      {a.examples.map(([t, b], i) => (
        <div className="ht-example" key={i}>
          <div className="he-t">{L(t)}</div>
          <div className="he-b">{L(b)}</div>
        </div>
      ))}

      <div className="ht-screens">
        <div className="ht-h">{U(UI.screenshots)}</div>
        {a.shots.length > 0 ? (
          a.shots.map((shot, i) => {
            const src = shot.src ?? shotSrc(a.id);
            const altText = L(shot.alt);
            const capText = L(shot.caption);
            return (
              <div className="ht-shot" key={i}>
                <button
                  type="button"
                  className="ht-shot-ph"
                  onClick={() => onZoom(src, capText, altText)}
                  aria-label={`${capText} — ${ru ? "увеличить" : "zoom"}`}
                  style={{ width: "100%", cursor: "zoom-in" }}
                >
                  <Icon name="camera" />
                  <span>{capText}</span>
                </button>
              </div>
            );
          })
        ) : (
          <div className="ht-shot">
            <div className="ht-shot-ph">
              <Icon name="grid" />
              <span>{U(UI.capture)}</span>
            </div>
          </div>
        )}
      </div>

      {relatedArticles.length > 0 ? (
        <nav aria-label={U(UI.related)}>
          <div className="ht-h">{U(UI.related)}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {relatedArticles.map((rel) => (
              <Button
                key={rel.id}
                size="sm"
                variant="btn-ghost"
                onClick={() => onSelect(rel.id)}
              >
                {L(rel.entryLabel)}
              </Button>
            ))}
          </div>
        </nav>
      ) : null}

      {contextualArticles.length > 0 ? (
        <nav aria-label={U(UI.quickLinks)}>
          <div className="ht-h">{U(UI.quickLinks)}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {contextualArticles.map((ctx) => {
              const isCurrent = ctx.id === a.id;
              return (
                <Button
                  key={ctx.id}
                  size="sm"
                  variant={isCurrent ? "btn-primary" : "btn-ghost"}
                  aria-current={isCurrent ? "true" : undefined}
                  onClick={() => onSelect(ctx.id)}
                >
                  {L(ctx.entryLabel)}
                </Button>
              );
            })}
          </div>
        </nav>
      ) : null}

      <div className="ht-back">
        <a href={returnTo || a.routePath}>
          <Icon name="arrow" />{" "}
          {returnTo
            ? ru
              ? `Назад: ${backLabel}`
              : `Back to ${backLabel}`
            : ru
              ? "Открыть связанную страницу"
              : `Open ${a.section}`}
        </a>
      </div>
    </article>
  );
}
