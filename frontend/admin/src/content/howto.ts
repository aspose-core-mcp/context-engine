"use client";

export type HowToLocale = "en" | "ru";
export type HowToTopic = "Admin Console" | "Public Pages" | "Onboarding";
export type HowToArticleId =
  | "admin-health"
  | "admin-health-runtime-guard"
  | "admin-health-dependencies-topology"
  | "admin-health-content-coverage"
  | "admin-ingestion-jobs"
  | "admin-ingestion-onboarding"
  | "admin-ingestion-execution"
  | "admin-ingestion-review-workspace"
  | "admin-snapshots"
  | "admin-snapshots-rollback"
  | "admin-snapshots-cleanup"
  | "admin-critical-events"
  | "admin-critical-events-lifecycle"
  | "admin-critical-events-history"
  | "admin-language-registries"
  | "admin-language-registries-dictionaries"
  | "admin-language-registries-aliases"
  | "admin-api-keys-access"
  | "admin-api-keys-provisioning"
  | "admin-api-keys-governance"
  | "admin-retrieval-settings"
  | "admin-analytics"
  | "admin-analytics-capacity-forecast"
  | "admin-analytics-usefulness-feedback"
  | "admin-analytics-zero-result-cockpit"
  | "admin-sql-explorer"
  | "admin-sql-explorer-query-workflow"
  | "admin-logs-traces"
  | "admin-config-history-rollback"
  | "admin-quality-reviews"
  | "admin-quality-reviews-policy"
  | "admin-quality-reviews-runs"
  | "admin-quality-reviews-run-diff"
  | "public-status"
  | "public-integrations"
  | "onboarding-overview";

export type LocalizedText = Record<HowToLocale, string>;
export type LocalizedLines = Record<HowToLocale, string[]>;

export type HowToExample = {
  id: string;
  title: LocalizedText;
  bullets: LocalizedLines;
};

export type HowToScreenshot = {
  id: string;
  src: string;
  alt: LocalizedText;
  caption: LocalizedText;
};

export type HowToCallout = {
  id: string;
  level: "info" | "warning" | "success";
  title: LocalizedText;
  body: LocalizedLines;
};

export type HowToCommand = {
  id: string;
  label: LocalizedText;
  description: LocalizedText;
  command: string;
};

export type HowToArticle = {
  id: HowToArticleId;
  slug: string;
  topic: HowToTopic;
  routePath: string;
  entryLabel: LocalizedText;
  title: LocalizedText;
  summary: LocalizedText;
  purpose: LocalizedLines;
  workflow: LocalizedLines;
  callouts?: HowToCallout[];
  commands?: HowToCommand[];
  examples: HowToExample[];
  screenshots: HowToScreenshot[];
  relatedArticleIds: HowToArticleId[];
  keywords: string[];
  adminSectionIds?: string[];
};

export type HowToArticleOverridePayload = {
  entry_label: LocalizedText;
  title: LocalizedText;
  summary: LocalizedText;
  purpose: LocalizedLines;
  workflow: LocalizedLines;
  callouts: HowToCallout[];
  commands: HowToCommand[];
  examples: HowToExample[];
  screenshots: HowToScreenshot[];
};

export type HowToArticleOverrideEnvelope = {
  article_id: string;
  draft: HowToArticleOverridePayload | null;
  draft_updated_at: string | null;
  draft_updated_by: string | null;
  published: HowToArticleOverridePayload | null;
  published_updated_at: string | null;
  published_updated_by: string | null;
};

export type BuildHowToHrefOptions = {
  locale?: HowToLocale;
  sourceSectionId?: string;
  sourceLabel?: string;
  returnTo?: string;
};

function localizedText(en: string, ru: string): LocalizedText {
  return { en, ru };
}

function localizedLines(en: string[], ru: string[]): LocalizedLines {
  return { en, ru };
}

function screenshot(
  id: string,
  articleId: HowToArticleId,
  altEn: string,
  altRu: string,
  captionEn: string,
  captionRu: string,
): HowToScreenshot {
  return {
    id,
    src: `/howto/screenshots/${articleId}.png`,
    alt: localizedText(altEn, altRu),
    caption: localizedText(captionEn, captionRu),
  };
}

function example(
  id: string,
  titleEn: string,
  titleRu: string,
  bulletsEn: string[],
  bulletsRu: string[],
): HowToExample {
  return {
    id,
    title: localizedText(titleEn, titleRu),
    bullets: localizedLines(bulletsEn, bulletsRu),
  };
}

function callout(
  id: string,
  level: "info" | "warning" | "success",
  titleEn: string,
  titleRu: string,
  bodyEn: string[],
  bodyRu: string[],
): HowToCallout {
  return {
    id,
    level,
    title: localizedText(titleEn, titleRu),
    body: localizedLines(bodyEn, bodyRu),
  };
}

function command(
  id: string,
  labelEn: string,
  labelRu: string,
  descriptionEn: string,
  descriptionRu: string,
  value: string,
): HowToCommand {
  return {
    id,
    label: localizedText(labelEn, labelRu),
    description: localizedText(descriptionEn, descriptionRu),
    command: value,
  };
}

export const HOW_TO_ARTICLES: readonly HowToArticle[] = [
  {
    id: "admin-health",
    slug: "admin-health",
    topic: "Admin Console",
    routePath: "/#health",
    entryLabel: localizedText("Health", "Состояние системы"),
    title: localizedText(
      "Admin Console: Health, Readiness, and MCP Coverage",
      "Админка: здоровье системы, readiness и покрытие MCP",
    ),
    summary: localizedText(
      "Use this page first to understand whether ADCS is healthy, why it might be degraded, and which documentation or API-reference services are currently MCP-ready.",
      "Эта страница нужна в первую очередь, чтобы понять, в каком состоянии находится ADCS, почему сервис может быть degraded, и какие documentation/API-reference сервисы сейчас готовы для MCP.",
    ),
    purpose: localizedLines(
      [
        "Confirm that core dependencies such as PostgreSQL, Redis, Qdrant, and OpenSearch are reachable.",
        "See exact not-ready reasons and the recommended fix plan before you start operational actions.",
        "Review MCP content coverage by product and repository, including ready/not-ready status and scope metadata.",
      ],
      [
        "Подтвердить, что базовые зависимости, такие как PostgreSQL, Redis, Qdrant и OpenSearch, доступны.",
        "Увидеть точные причины not-ready и рекомендуемый план исправления до начала любых операционных действий.",
        "Проверить покрытие MCP по продуктам и репозиториям, включая ready/not-ready статус и метаданные scope.",
      ],
    ),
    workflow: localizedLines(
      [
        "Open Health and check the top KPI cards first.",
        "Inspect dependency summaries and fix-plan steps if any card is not healthy.",
        "Use the MCP Content Services Coverage table to verify that the target docs/apiref scope has an active snapshot.",
        "If a service is not ready, stop and fix health before running publish, rollback, or onboarding operations.",
      ],
      [
        "Откройте Health и сначала проверьте верхние KPI-карточки.",
        "Если есть нештатный статус, просмотрите summary зависимости и шаги fix plan.",
        "Используйте таблицу MCP Content Services Coverage, чтобы убедиться, что для нужного docs/apiref scope существует active snapshot.",
        "Если сервис not ready, сначала исправьте health, а уже потом запускайте publish, rollback или onboarding.",
      ],
    ),
    callouts: [
      callout(
        "health-callout-1",
        "warning",
        "Stop here if the target scope is not ready",
        "Остановитесь здесь, если target scope не ready",
        [
          "Do not publish or rollback blindly when MCP readiness is red or unknown.",
          "Use the fix plan first, then re-check the coverage row for the target repo_id.",
        ],
        [
          "Не запускайте publish или rollback вслепую, если MCP readiness красный или unknown.",
          "Сначала выполните fix plan, затем повторно проверьте coverage row для нужного repo_id.",
        ],
      ),
    ],
    commands: [
      command(
        "health-command-1",
        "Open public status page",
        "Открыть public status page",
        "Useful when you want to compare private admin health with the external status surface.",
        "Полезно, когда нужно сравнить приватный admin health с внешней status surface.",
        "open http://127.0.0.1:3000/status",
      ),
    ],
    examples: [
      example(
        "health-example-1",
        "Before a publish run",
        "Перед publish-запуском",
        [
          "Verify that system readiness is healthy.",
          "Confirm that the target product row shows MCP-ready status.",
          "Only after that move to Ingestion Jobs or Snapshots.",
        ],
        [
          "Проверьте, что system readiness имеет healthy статус.",
          "Убедитесь, что строка нужного продукта имеет MCP-ready статус.",
          "Только после этого переходите в Ingestion Jobs или Snapshots.",
        ],
      ),
      example(
        "health-example-2",
        "When a product owner sees not-ready",
        "Когда product owner видит not-ready",
        [
          "Open the row for the affected repo_id.",
          "Read the fix-plan bullets and the latest ingestion signal.",
          "Then coordinate a validate-only or publish action only after the root cause is clear.",
        ],
        [
          "Откройте строку с проблемным repo_id.",
          "Прочитайте пункты fix plan и последний ingestion signal.",
          "Только после ясного понимания причины координируйте validate-only или publish.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-health-main",
        "admin-health",
        "Health section of the admin console with readiness, dependencies, and MCP coverage.",
        "Раздел Health в админке с readiness, зависимостями и MCP coverage.",
        "Main Health view used for first-line operational checks.",
        "Основной экран Health для первичной операционной проверки.",
      ),
    ],
    relatedArticleIds: [
      "admin-health-runtime-guard",
      "admin-health-content-coverage",
      "admin-snapshots",
      "public-status",
    ],
    keywords: ["health", "readiness", "mcp coverage", "dependencies", "fix plan"],
    adminSectionIds: ["health"],
  },
  {
    id: "admin-health-runtime-guard",
    slug: "admin-health-runtime-guard",
    topic: "Admin Console",
    routePath: "/#health",
    entryLabel: localizedText("Health: Runtime Guard", "Состояние: защита runtime"),
    title: localizedText(
      "Admin Console: MCP Revisions and Abuse Guard",
      "Админка: fallback MCP-ревизий и защита от злоупотреблений",
    ),
    summary: localizedText(
      "Use this deep-dive when the platform negotiates older MCP revisions too often, or when you need to tune anti-abuse thresholds without destabilizing legitimate traffic.",
      "Используйте эту deep-dive инструкцию, когда платформа слишком часто переключается на старые MCP revision или когда нужно настроить anti-abuse пороги без вреда для легитимного трафика.",
    ),
    purpose: localizedLines(
      [
        "Explain what MCP fallback ratio means and when it signals protocol compatibility problems.",
        "Show how Abuse Guard modes, limits, and allowlists affect traffic handling.",
        "Connect runtime policy tuning with tracing, alert rules, and deploy-safety diagnostics.",
      ],
      [
        "Объяснить, что означает MCP fallback ratio и когда он сигнализирует о проблемах protocol compatibility.",
        "Показать, как режимы, лимиты и allowlist Abuse Guard влияют на обработку трафика.",
        "Связать настройку runtime policy с tracing, alert rules и deploy-safety диагностикой.",
      ],
    ),
    workflow: localizedLines(
      [
        "Check fallback ratio, negotiated revisions, and fallback reasons first.",
        "Review current Abuse Guard mode and live thresholds before changing anything.",
        "Tune one control at a time, then validate the effect through metrics, traces, and recent decisions.",
        "Escalate only if fallback or abuse patterns continue after the safer observe-only tuning pass.",
      ],
      [
        "Сначала проверьте fallback ratio, negotiated revisions и причины fallback.",
        "Перед изменениями просмотрите текущий режим Abuse Guard и активные thresholds.",
        "Меняйте по одному параметру и затем проверяйте эффект через metrics, traces и recent decisions.",
        "Переходите к более жестким мерам только если проблемы fallback или abuse сохраняются после безопасной настройки observe-only.",
      ],
    ),
    callouts: [
      callout(
        "health-runtime-callout-1",
        "warning",
        "Do not jump to enforce mode blindly",
        "Не переходите к enforce mode вслепую",
        [
          "Observe-only should remain the default while you are still learning real traffic patterns.",
          "A sudden move to enforce can block legitimate IDE or agent workloads if thresholds are not yet calibrated.",
        ],
        [
          "Observe-only должен оставаться режимом по умолчанию, пока вы еще изучаете реальные traffic patterns.",
          "Резкий переход в enforce может заблокировать легитимные IDE или agent workloads, если thresholds еще не откалиброваны.",
        ],
      ),
    ],
    commands: [
      command(
        "health-runtime-command-1",
        "Open the public status surface",
        "Открыть public status surface",
        "Use this to compare private fallback signals with what external developers currently see.",
        "Используйте это, чтобы сравнить внутренние fallback signals с тем, что сейчас видят внешние разработчики.",
        "open http://127.0.0.1:3000/status",
      ),
    ],
    examples: [
      example(
        "health-runtime-example-1",
        "Fallback spike after a client update",
        "Всплеск fallback после обновления клиента",
        [
          "Check whether one revision suddenly dominates the fallback chart.",
          "Inspect fallback reasons to separate protocol mismatch from backend issues.",
          "Keep Abuse Guard stable until you confirm the spike is not caused by noisy retries from a single client.",
        ],
        [
          "Проверьте, не доминирует ли одна revision в fallback chart.",
          "Изучите fallback reasons, чтобы отделить protocol mismatch от backend-проблем.",
          "Не меняйте Abuse Guard, пока не подтвердите, что всплеск не вызван шумными retry от одного клиента.",
        ],
      ),
      example(
        "health-runtime-example-2",
        "Tuning allowlist for test traffic",
        "Настройка allowlist для тестового трафика",
        [
          "Add the dedicated fingerprint or hashed IP to the allowlist.",
          "Re-run the scenario and confirm decisions move from blocked/warn to allowed.",
          "Keep the allowlist minimal and documented.",
        ],
        [
          "Добавьте в allowlist нужный fingerprint или hashed IP.",
          "Повторите сценарий и убедитесь, что decisions сменились с blocked/warn на allowed.",
          "Держите allowlist минимальным и документированным.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-health-runtime-guard-main",
        "admin-health-runtime-guard",
        "Runtime guard panel with MCP fallback telemetry and Abuse Guard controls.",
        "Панель runtime guard с MCP fallback telemetry и настройками Abuse Guard.",
        "Use this panel when investigating revision fallback or live traffic protection behavior.",
        "Используйте эту панель при расследовании revision fallback или поведения live traffic protection.",
      ),
    ],
    relatedArticleIds: ["admin-health", "admin-health-dependencies-topology", "public-status"],
    keywords: ["mcp revisions", "fallback ratio", "abuse guard", "observe-only", "enforce"],
    adminSectionIds: ["health"],
  },
  {
    id: "admin-health-dependencies-topology",
    slug: "admin-health-dependencies-topology",
    topic: "Admin Console",
    routePath: "/#health",
    entryLabel: localizedText("Health: Dependencies & Topology", "Состояние: зависимости и топология"),
    title: localizedText(
      "Admin Console: Component Status and Index Topology",
      "Админка: статус компонентов и топология индексов",
    ),
    summary: localizedText(
      "This article explains how to interpret dependency readiness, fix-plan drill-down, and the currently active shard/replica/retention policy for the data plane.",
      "Эта статья объясняет, как интерпретировать dependency readiness, fix-plan drill-down и текущую активную политику shard/replica/retention для data plane.",
    ),
    purpose: localizedLines(
      [
        "Diagnose which dependency is actually blocking readiness.",
        "Explain what the topology policy means for durability, cleanup, and scale behavior.",
        "Tie dependency failures to operator next steps and infrastructure expectations.",
      ],
      [
        "Диагностировать, какая именно зависимость реально блокирует readiness.",
        "Объяснить, что topology policy означает для durability, cleanup и scale behavior.",
        "Связать отказы зависимостей с следующими действиями оператора и ожиданиями от инфраструктуры.",
      ],
    ),
    workflow: localizedLines(
      [
        "Start with the dependency drill-down and isolate the not-ready service.",
        "Read the fix-plan summary before opening infra tools or restarting anything.",
        "Check the topology panel to confirm the environment profile and retention envelope match your expectation.",
        "Only after that escalate to infra-level investigation or cleanup actions.",
      ],
      [
        "Начните с dependency drill-down и выделите not-ready сервис.",
        "Прочитайте fix-plan summary до открытия infra-инструментов или перезапусков.",
        "Проверьте topology panel, чтобы подтвердить, что environment profile и retention envelope совпадают с ожиданиями.",
        "Только после этого переходите к infra-level расследованию или cleanup действиям.",
      ],
    ),
    examples: [
      example(
        "health-dependencies-example-1",
        "Qdrant not ready during publish preparation",
        "Qdrant not ready перед подготовкой publish",
        [
          "Select `qdrant` in the dependency drill-down.",
          "Read the reason and fix plan instead of restarting unrelated services.",
          "Verify topology settings only after the dependency itself is back to ready.",
        ],
        [
          "Выберите `qdrant` в dependency drill-down.",
          "Прочитайте reason и fix plan вместо перезапуска несвязанных сервисов.",
          "Проверяйте topology settings только после того, как сама зависимость вернулась в ready.",
        ],
      ),
      example(
        "health-dependencies-example-2",
        "Unexpected cleanup behavior",
        "Неожиданное поведение cleanup",
        [
          "Open the topology card and confirm retention limits for inactive snapshots.",
          "Check whether the current environment profile differs from what you expected.",
          "Only then investigate cleanup previews or policy exports.",
        ],
        [
          "Откройте topology card и подтвердите retention limits для inactive snapshots.",
          "Проверьте, не отличается ли текущий environment profile от ожидаемого.",
          "Только после этого исследуйте cleanup previews или policy exports.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-health-dependencies-topology-main",
        "admin-health-dependencies-topology",
        "Dependency status and topology policy panels in the Health section.",
        "Панели dependency status и topology policy в разделе Health.",
        "Use these panels to understand why readiness failed and how the data plane is configured.",
        "Используйте эти панели, чтобы понять причину readiness failure и конфигурацию data plane.",
      ),
    ],
    relatedArticleIds: ["admin-health", "admin-health-runtime-guard", "admin-snapshots-cleanup"],
    keywords: ["dependency status", "fix plan", "topology", "shards", "replicas", "retention"],
    adminSectionIds: ["health"],
  },
  {
    id: "admin-health-content-coverage",
    slug: "admin-health-content-coverage",
    topic: "Admin Console",
    routePath: "/#health",
    entryLabel: localizedText("Health: Content Coverage", "Состояние: покрытие контента"),
    title: localizedText(
      "Admin Console: MCP Content Services Coverage",
      "Админка: покрытие MCP-контент-сервисов",
    ),
    summary: localizedText(
      "Use this article when you need to answer the core product question: which docs/apiref services are actually ready to serve MCP requests right now, and why some are not.",
      "Используйте эту статью, когда нужно ответить на главный продуктовый вопрос: какие docs/apiref сервисы действительно готовы обслуживать MCP-запросы прямо сейчас и почему некоторые из них не готовы.",
    ),
    purpose: localizedLines(
      [
        "Explain the MCP-ready/total counters and service-health mix.",
        "Show how to filter by product or repo_id and interpret row-level status colors.",
        "Tie not-ready states to concrete next actions such as validate, publish, runtime checks, or incident review.",
      ],
      [
        "Объяснить счетчики MCP-ready/total и service-health mix.",
        "Показать, как фильтровать по product или repo_id и интерпретировать row-level status colors.",
        "Связать not-ready статусы с конкретными следующими действиями: validate, publish, runtime checks или incident review.",
      ],
    ),
    workflow: localizedLines(
      [
        "Start with the top counters to understand overall service coverage.",
        "Filter to the product or repo_id you care about.",
        "Read the action hint and fix-plan summary for yellow/red rows before touching ingestion.",
        "Confirm active snapshot and latest ingestion state before declaring a service ready.",
      ],
      [
        "Начните с верхних счетчиков, чтобы понять общий coverage сервисов.",
        "Отфильтруйте нужный product или repo_id.",
        "До запуска ingestion прочитайте action hint и fix-plan summary для yellow/red строк.",
        "Подтвердите active snapshot и последнее ingestion state перед тем, как считать сервис ready.",
      ],
    ),
    callouts: [
      callout(
        "health-coverage-callout-1",
        "info",
        "A snapshot is necessary but not always sufficient",
        "Snapshot необходим, но не всегда достаточен",
        [
          "A service can still be not-ready if runtime signals are stale or the last operation failed.",
        ],
        [
          "Сервис все еще может быть not-ready, если runtime signals устарели или последняя операция завершилась ошибкой.",
        ],
      ),
    ],
    examples: [
      example(
        "health-coverage-example-1",
        "Docs ready, API reference not ready",
        "Docs ready, API reference not ready",
        [
          "Filter by product_id to compare both rows side by side.",
          "Inspect which row has no active snapshot or a failed latest operation.",
          "Recover the missing source kind before telling developers the product is fully available through MCP.",
        ],
        [
          "Отфильтруйте по product_id, чтобы сравнить обе строки рядом.",
          "Проверьте, у какой строки нет active snapshot или последняя операция failed.",
          "Восстановите недостающий source kind до того, как сообщать разработчикам о полной доступности продукта через MCP.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-health-content-coverage-main",
        "admin-health-content-coverage",
        "MCP Content Services Coverage table with filters and readiness counters.",
        "Таблица MCP Content Services Coverage с фильтрами и readiness counters.",
        "Use this panel to answer whether a product is truly available via MCP.",
        "Используйте эту панель, чтобы понять, действительно ли продукт доступен через MCP.",
      ),
    ],
    relatedArticleIds: ["admin-health", "admin-ingestion-execution", "public-status"],
    keywords: ["coverage", "mcp ready", "repo status", "active snapshot", "not ready"],
    adminSectionIds: ["health"],
  },
  {
    id: "admin-ingestion-jobs",
    slug: "admin-ingestion-jobs",
    topic: "Admin Console",
    routePath: "/#ingestion-jobs",
    entryLabel: localizedText("Ingestion Jobs", "Задания ingestion"),
    title: localizedText(
      "Admin Console: Ingestion Jobs and Product Onboarding",
      "Админка: задания ingestion и onboarding продуктов",
    ),
    summary: localizedText(
      "This page controls source onboarding, validate-only runs, publish runs, and detailed review of conversion artifacts before content reaches MCP consumers.",
      "Эта страница управляет onboarding источников, validate-only и publish запусками, а также детальным review conversion artifacts до того, как контент попадет к MCP-потребителям.",
    ),
    purpose: localizedLines(
      [
        "Register new documentation and API-reference repositories.",
        "Run validate-only checks before publish.",
        "Inspect detailed review artifacts: raw markdown, normalized documents, chunk records, and manifest previews.",
      ],
      [
        "Регистрировать новые documentation и API-reference репозитории.",
        "Запускать validate-only проверки до publish.",
        "Просматривать детальные review artifacts: raw markdown, normalized documents, chunk records и manifest previews.",
      ],
    ),
    workflow: localizedLines(
      [
        "Add or select the target product scope.",
        "Run Validate-Only first and inspect warnings or failed items.",
        "Review generated artifacts in the detailed review workspace.",
        "Trigger Publish only when validate-only output is clean and the target scope is healthy.",
      ],
      [
        "Добавьте или выберите нужный продуктовый scope.",
        "Сначала запустите Validate-Only и изучите warnings и failed items.",
        "Просмотрите сгенерированные artifacts в detailed review workspace.",
        "Запускайте Publish только тогда, когда validate-only чистый, а target scope healthy.",
      ],
    ),
    callouts: [
      callout(
        "ingestion-callout-1",
        "info",
        "Validate-only should be the default operator move",
        "Validate-only должен быть действием по умолчанию",
        [
          "Use publish only after you have reviewed artifacts, warnings, and the target health state.",
        ],
        [
          "Используйте publish только после review artifacts, warnings и состояния target health.",
        ],
      ),
    ],
    commands: [
      command(
        "ingestion-command-1",
        "Open the repo validation contract",
        "Открыть контракт валидации репозитория",
        "Use the CLI check before onboarding or after changing source registry metadata.",
        "Используйте CLI-проверку до onboarding или после изменения source registry metadata.",
        "make source-validate",
      ),
      command(
        "ingestion-command-2",
        "Regenerate detected layouts",
        "Переопределить detected layouts",
        "Useful when repository structure changed and screenshot/article guidance needs to stay aligned with the live parser behavior.",
        "Полезно, когда структура repository изменилась и инструкция должна соответствовать актуальному parser behavior.",
        "make source-detect-layouts-write",
      ),
    ],
    examples: [
      example(
        "ingestion-example-1",
        "Onboarding a new product family",
        "Onboarding нового product family",
        [
          "Fill in product identity and repository URLs.",
          "Use bootstrap options to auto-run layout detection and validate-only.",
          "Confirm that created repo_ids appear in the result summary.",
        ],
        [
          "Заполните identity продукта и repository URLs.",
          "Используйте bootstrap options для авто-запуска layout detection и validate-only.",
          "Убедитесь, что созданные repo_ids появились в result summary.",
        ],
      ),
      example(
        "ingestion-example-2",
        "Reviewing a failed parse",
        "Разбор failed parse",
        [
          "Open the latest operation_id.",
          "Inspect parse warnings and failed items in the review workspace.",
          "Correct the source, layout, or prompt strategy before retrying.",
        ],
        [
          "Откройте последний operation_id.",
          "Просмотрите parse warnings и failed items в review workspace.",
          "Исправьте source, layout или prompt strategy перед повторной попыткой.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-ingestion-main",
        "admin-ingestion-jobs",
        "Ingestion Jobs section with onboarding and operation controls.",
        "Раздел Ingestion Jobs с onboarding и operation controls.",
        "Use this screen to onboard repositories, validate content, and publish snapshots.",
        "Используйте этот экран для onboarding репозиториев, проверки контента и публикации snapshots.",
      ),
    ],
    relatedArticleIds: [
      "admin-ingestion-onboarding",
      "admin-ingestion-execution",
      "admin-ingestion-review-workspace",
      "onboarding-overview",
    ],
    keywords: ["ingestion", "validate", "publish", "onboarding", "review artifacts"],
    adminSectionIds: ["ingestion-jobs"],
  },
  {
    id: "admin-ingestion-onboarding",
    slug: "admin-ingestion-onboarding",
    topic: "Admin Console",
    routePath: "/#ingestion-jobs",
    entryLabel: localizedText("Ingestion: Onboarding", "Ingestion: подключение репозиториев"),
    title: localizedText(
      "Admin Console: Add New Product Repositories",
      "Админка: добавление новых репозиториев продукта",
    ),
    summary: localizedText(
      "This deep-dive explains how to register a new product family correctly, what each onboarding field means, and how bootstrap automation should be used safely.",
      "Эта deep-dive инструкция объясняет, как правильно зарегистрировать новый product family, что означает каждое поле onboarding и как безопасно использовать bootstrap automation.",
    ),
    purpose: localizedLines(
      [
        "Explain product identity, family, family_dir, repository URLs, and programming-language hints.",
        "Reduce ambiguity when a product owner adds docs/apiref repositories for the first time.",
        "Connect registry write, auto layout detection, and validate-only bootstrap into one operational story.",
      ],
      [
        "Объяснить product identity, family, family_dir, repository URLs и programming-language hints.",
        "Снизить неоднозначность, когда product owner впервые добавляет docs/apiref repositories.",
        "Связать registry write, auto layout detection и validate-only bootstrap в одну операционную историю.",
      ],
    ),
    workflow: localizedLines(
      [
        "Define stable product identity first: product_id, product_name, product_family.",
        "Bind the exact source repositories and the exact top-level product_family_dir.",
        "Add language hints only if they improve understanding of the future folder hierarchy.",
        "Use auto layout detection and validate-only bootstrap, then review the result before any publish.",
      ],
      [
        "Сначала определите стабильную product identity: product_id, product_name, product_family.",
        "Привяжите точные source repositories и точный top-level product_family_dir.",
        "Добавляйте language hints только если они реально помогают понять будущую folder hierarchy.",
        "Используйте auto layout detection и validate-only bootstrap, затем проверяйте результат до любого publish.",
      ],
    ),
    examples: [
      example(
        "ingestion-onboarding-example-1",
        "New Aspose product family",
        "Новый Aspose product family",
        [
          "Set `product_id=aspose.omr` and `product_family=aspose`.",
          "Use the exact folder anchor `Aspose.OMR` as `product_family_dir`.",
          "Register both docs and apiref repositories before running bootstrap automation.",
        ],
        [
          "Установите `product_id=aspose.omr` и `product_family=aspose`.",
          "Используйте точный folder anchor `Aspose.OMR` как `product_family_dir`.",
          "Зарегистрируйте и docs, и apiref repositories до запуска bootstrap automation.",
        ],
      ),
      example(
        "ingestion-onboarding-example-2",
        "Unknown programming-language naming",
        "Неизвестное именование programming language",
        [
          "Add only the hints you really expect to see under the family tree.",
          "Do not hardcode speculative languages just to fill the form.",
          "Let layout detection confirm the real structure after registration.",
        ],
        [
          "Добавляйте только те hints, которые вы реально ожидаете увидеть в family tree.",
          "Не заполняйте форму спекулятивными language values просто ради полноты.",
          "Пусть layout detection подтвердит реальную структуру после регистрации.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-ingestion-onboarding-main",
        "admin-ingestion-onboarding",
        "Onboarding wizard and product repository registration form inside Ingestion Jobs.",
        "Onboarding wizard и форма регистрации product repositories внутри Ingestion Jobs.",
        "Use this panel when adding a product that does not yet exist in repo dropdowns.",
        "Используйте эту панель, когда добавляете продукт, которого еще нет в repo dropdowns.",
      ),
    ],
    relatedArticleIds: ["admin-ingestion-jobs", "onboarding-overview", "admin-language-registries"],
    keywords: ["product onboarding", "product family dir", "repo registration", "bootstrap automation"],
    adminSectionIds: ["ingestion-jobs"],
  },
  {
    id: "admin-ingestion-execution",
    slug: "admin-ingestion-execution",
    topic: "Admin Console",
    routePath: "/#ingestion-jobs",
    entryLabel: localizedText("Ingestion: Validate & Publish", "Ingestion: проверка и публикация"),
    title: localizedText(
      "Admin Console: Validate-Only, Publish, and Batch Ingestion",
      "Админка: validate-only, publish и batch-ingestion",
    ),
    summary: localizedText(
      "Use this article to choose the correct ingestion mode, understand the difference between safe validation and publish, and decide when batch execution is justified.",
      "Используйте эту статью, чтобы выбрать правильный режим ingestion, понять разницу между безопасной валидацией и publish, и решить, когда batch execution действительно оправдан.",
    ),
    purpose: localizedLines(
      [
        "Clarify the operational difference between Validate-Only and Trigger Publish.",
        "Explain when to use single-repository execution versus batch mode.",
        "Provide a safe operator sequence that minimizes accidental bad publishes.",
      ],
      [
        "Прояснить операционную разницу между Validate-Only и Trigger Publish.",
        "Объяснить, когда использовать single-repository execution, а когда batch mode.",
        "Дать безопасную последовательность действий оператора, которая минимизирует accidental bad publishes.",
      ],
    ),
    workflow: localizedLines(
      [
        "Choose one repo first unless you already trust the exact source set and parser behavior.",
        "Run Validate-Only, inspect review output, and confirm health/coverage state.",
        "Use Trigger Publish only after validation and quality evidence are green.",
        "Use Batch Validate/Batch Publish only when the same action is intended for several repositories and the blast radius is understood.",
      ],
      [
        "Сначала выбирайте один repo, если вы еще не доверяете точному набору sources и parser behavior.",
        "Запускайте Validate-Only, проверяйте review output и подтверждайте health/coverage state.",
        "Используйте Trigger Publish только после того, как validation и quality evidence стали зелеными.",
        "Используйте Batch Validate/Batch Publish только когда одно и то же действие нужно для нескольких repositories и blast radius понятен.",
      ],
    ),
    callouts: [
      callout(
        "ingestion-execution-callout-1",
        "warning",
        "Batch is a force multiplier, not a shortcut",
        "Batch — это усилитель, а не shortcut",
        [
          "Batch mode repeats mistakes faster. Use it only after you understand what one-repo validation already showed.",
        ],
        [
          "Batch mode быстрее размножает ошибки. Используйте его только после того, как понимаете результаты one-repo validation.",
        ],
      ),
    ],
    examples: [
      example(
        "ingestion-execution-example-1",
        "Routine content refresh",
        "Плановое обновление контента",
        [
          "Pick one repo and run Validate-Only after the latest source sync.",
          "If nothing regressed, repeat on the remaining repos through Batch Validate.",
          "Only then publish the validated set.",
        ],
        [
          "Выберите один repo и запустите Validate-Only после последнего source sync.",
          "Если регрессий нет, повторите действие для остальных repo через Batch Validate.",
          "Только после этого публикуйте проверенный набор.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-ingestion-execution-main",
        "admin-ingestion-execution",
        "Single-repository and batch ingestion controls inside Ingestion Jobs.",
        "Элементы single-repository и batch ingestion внутри Ingestion Jobs.",
        "Use this panel to run Validate-Only or Publish with the smallest safe blast radius.",
        "Используйте эту панель, чтобы запускать Validate-Only или Publish с минимально безопасным blast radius.",
      ),
    ],
    relatedArticleIds: ["admin-ingestion-jobs", "admin-health-content-coverage", "admin-ingestion-review-workspace"],
    keywords: ["validate only", "trigger publish", "batch ingestion", "single repo", "blast radius"],
    adminSectionIds: ["ingestion-jobs"],
  },
  {
    id: "admin-ingestion-review-workspace",
    slug: "admin-ingestion-review-workspace",
    topic: "Admin Console",
    routePath: "/#ingestion-jobs",
    entryLabel: localizedText("Ingestion: Review Workspace", "Ingestion: рабочее место review"),
    title: localizedText(
      "Admin Console: Detailed Review Workspace",
      "Админка: рабочее место detailed review",
    ),
    summary: localizedText(
      "This is the operator guide for reviewing what ingestion actually produced: raw markdown, parsed pages, chunk records, review artifacts, and staging manifests.",
      "Это руководство оператора по проверке того, что ingestion реально произвел: raw markdown, parsed pages, chunk records, review artifacts и staging manifests.",
    ),
    purpose: localizedLines(
      [
        "Explain the inspection chain from raw source to staged retrieval payloads.",
        "Show which preview to open when a run fails, warns, or looks semantically weak.",
        "Reduce guesswork before retrying source changes, parser changes, or publish actions.",
      ],
      [
        "Объяснить цепочку инспекции от raw source до staged retrieval payloads.",
        "Показать, какой preview открывать, когда run failed, warned или выглядит семантически слабым.",
        "Снизить угадывание перед повтором source changes, parser changes или publish действий.",
      ],
    ),
    workflow: localizedLines(
      [
        "Focus one repository result first.",
        "Inspect Parsed Page and Raw Markdown together to validate source parsing.",
        "Inspect Chunk Record and Review Artifact to understand retrieval payload quality.",
        "Inspect Staging Manifest Preview last to see what will actually move toward published scope.",
      ],
      [
        "Сначала сфокусируйтесь на одном repository result.",
        "Проверяйте Parsed Page и Raw Markdown вместе, чтобы валидировать source parsing.",
        "Проверяйте Chunk Record и Review Artifact, чтобы понять качество retrieval payload.",
        "В конце проверяйте Staging Manifest Preview, чтобы увидеть, что реально пойдет к published scope.",
      ],
    ),
    examples: [
      example(
        "ingestion-review-example-1",
        "Parser warning investigation",
        "Расследование parser warning",
        [
          "Open Raw Markdown and Parsed Page side by side.",
          "Confirm whether headings, code blocks, and metadata were extracted as expected.",
          "Then decide whether the problem is in source structure or parser behavior.",
        ],
        [
          "Откройте Raw Markdown и Parsed Page рядом.",
          "Подтвердите, что headings, code blocks и metadata были извлечены как ожидалось.",
          "После этого решайте, проблема в source structure или parser behavior.",
        ],
      ),
      example(
        "ingestion-review-example-2",
        "Weak retrieval output despite clean parsing",
        "Слабый retrieval output при чистом parsing",
        [
          "Inspect Chunk Record and Review Artifact rather than only parser warnings.",
          "Look for missing anchors, oversized chunks, or weak payload structure.",
          "Then refine chunking or conversion expectations before republishing.",
        ],
        [
          "Проверяйте Chunk Record и Review Artifact, а не только parser warnings.",
          "Ищите missing anchors, oversized chunks или слабую payload structure.",
          "После этого уточняйте chunking или conversion expectations перед republish.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-ingestion-review-workspace-main",
        "admin-ingestion-review-workspace",
        "Detailed review workspace with previews for parsed pages, raw markdown, chunk records, and staging manifests.",
        "Detailed review workspace с preview для parsed pages, raw markdown, chunk records и staging manifests.",
        "Use this workspace to understand exactly what ingestion produced before publishing.",
        "Используйте этот workspace, чтобы точно понять результат ingestion до публикации.",
      ),
    ],
    relatedArticleIds: ["admin-ingestion-jobs", "admin-ingestion-execution", "admin-quality-reviews"],
    keywords: ["review workspace", "raw markdown", "chunk record", "staging manifest", "review artifact"],
    adminSectionIds: ["ingestion-jobs"],
  },
  {
    id: "admin-snapshots",
    slug: "admin-snapshots",
    topic: "Admin Console",
    routePath: "/#snapshots",
    entryLabel: localizedText("Snapshots", "Снапшоты"),
    title: localizedText(
      "Admin Console: Snapshots, Promotion, Rollback, and Cleanup",
      "Админка: снапшоты, продвижение, откат и очистка",
    ),
    summary: localizedText(
      "Use this page to inspect active and inactive snapshots, promote a target snapshot, compare revisions, run rollback, or clean up obsolete inactive snapshots.",
      "Эта страница используется для просмотра активных и неактивных снапшотов, продвижения целевого снапшота, сравнения ревизий, отката и очистки устаревших неактивных снапшотов.",
    ),
    purpose: localizedLines(
      [
        "Track which snapshot is active for every product/language/version/source kind.",
        "Compare snapshots before promotion or rollback.",
        "Run safe retention cleanup with preview, risk summary, and execution history.",
      ],
      [
        "Отслеживать, какой снапшот активен для каждого продукта/языка/версии/типа источника.",
        "Сравнивать снапшоты перед продвижением или откатом.",
        "Запускать безопасную очистку по retention-политике с предварительным просмотром, анализом рисков и историей выполнения.",
      ],
    ),
    workflow: localizedLines(
      [
        "Filter snapshots by product, language, and version.",
        "Use Compare or Rollback only after verifying health and ingestion history.",
        "For cleanup, preview first and verify that active snapshots remain protected.",
        "Record a meaningful reason for rollback or cleanup actions.",
      ],
      [
        "Фильтруйте снапшоты по продукту, языку и версии.",
        "Используйте сравнение или откат только после проверки состояния системы и истории индексации.",
        "Для очистки сначала запускайте предварительный просмотр и проверяйте, что активные снапшоты защищены.",
        "Указывайте осмысленную причину для операций отката и очистки.",
      ],
    ),
    callouts: [
      callout(
        "snapshots-callout-1",
        "success",
        "Promote only after validation evidence is green",
        "Продвигайте снапшот только после зелёного результата валидации",
        [
          "Snapshot operations are safe only when the corresponding ingestion and quality review evidence is already clean.",
        ],
        [
          "Операции со снапшотами безопасны только тогда, когда результаты индексации и ревью качества уже чистые.",
        ],
      ),
    ],
    examples: [
      example(
        "snapshots-example-1",
        "Promoting a newly published snapshot",
        "Продвижение нового опубликованного снапшота",
        [
          "Compare the target snapshot with the current active one.",
          "Confirm the target contains the expected source revision.",
          "Promote only after validate-only and publish checks are complete.",
        ],
        [
          "Сравните целевой снапшот с текущим активным.",
          "Подтвердите, что целевой снапшот содержит ожидаемую ревизию исходных данных.",
          "Выполняйте продвижение только после полного цикла проверки и публикации.",
        ],
      ),
      example(
        "snapshots-example-2",
        "Cleanup of old inactive snapshots",
        "Очистка старых неактивных снапшотов",
        [
          "Preview the cleanup scope first.",
          "Read the risk summary and retained protected scopes.",
          "Execute cleanup only when the preview matches your retention goal.",
        ],
        [
          "Сначала запустите предварительный просмотр области очистки.",
          "Прочитайте анализ рисков и защищённые области.",
          "Выполняйте очистку только когда предварительный просмотр совпадает с вашей целью по хранению.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-snapshots-main",
        "admin-snapshots",
        "Snapshots section with active snapshot selection and cleanup controls.",
        "Раздел снапшотов с выбором активного снапшота и элементами управления очисткой.",
        "This view is used for compare, promote, rollback, and cleanup operations.",
        "Этот экран используется для сравнения, продвижения, отката и очистки снапшотов.",
      ),
    ],
    relatedArticleIds: [
      "admin-snapshots-rollback",
      "admin-snapshots-cleanup",
      "admin-ingestion-jobs",
      "admin-config-history-rollback",
    ],
    keywords: ["snapshots", "rollback", "promotion", "cleanup", "retention"],
    adminSectionIds: ["snapshots"],
  },
  {
    id: "admin-snapshots-rollback",
    slug: "admin-snapshots-rollback",
    topic: "Admin Console",
    routePath: "/#snapshots",
    entryLabel: localizedText("Snapshots: Rollback", "Снапшоты: откат"),
    title: localizedText(
      "Admin Console: Runtime Snapshot Rollback",
      "Админка: откат runtime-снапшота",
    ),
    summary: localizedText(
      "Use this article when you need to reverse the active runtime snapshot for a scope and must understand the confirmation contract, audit trail, and blast radius before acting.",
      "Используйте эту статью, когда нужно вернуть предыдущий активный снапшот для заданной области и требуется понять процедуру подтверждения, журнал аудита и зону поражения до выполнения действия.",
    ),
    purpose: localizedLines(
      [
        "Explain when rollback is appropriate versus when republish or compare is safer.",
        "Document the mandatory confirmation flow and reason capture.",
        "Show how to verify the result through audit records and active snapshot state.",
      ],
      [
        "Объяснить, когда откат действительно уместен, а когда безопаснее повторная публикация или сравнение.",
        "Задокументировать обязательную процедуру подтверждения и фиксацию причины.",
        "Показать, как проверять результат через записи аудита и состояние активного снапшота.",
      ],
    ),
    workflow: localizedLines(
      [
        "Confirm the target scope and choose the exact rollback target snapshot.",
        "Write a reason that will still make sense later in audit history.",
        "Type the confirmation token and execute rollback only after checking that the target is not already active.",
        "Verify the before/after result and read the latest rollback audit row.",
      ],
      [
        "Подтвердите целевую область и выберите точный целевой снапшот для отката.",
        "Запишите причину так, чтобы она оставалась понятной позже в журнале аудита.",
        "Введите текст подтверждения и выполняйте откат только после проверки, что целевой снапшот ещё не активен.",
        "Проверьте результат до/после и прочитайте последнюю запись аудита отката.",
      ],
    ),
    callouts: [
      callout(
        "snapshot-rollback-callout-1",
        "warning",
        "Rollback is a runtime switch, not a documentation note",
        "Откат — это переключение рантайма, а не заметка в документации",
        [
          "The action changes what end users receive immediately for the selected scope.",
        ],
        [
          "Это действие немедленно меняет то, что получают конечные пользователи в выбранной области.",
        ],
      ),
    ],
    examples: [
      example(
        "snapshot-rollback-example-1",
        "Rollback after bad publish",
        "Откат после неудачной публикации",
        [
          "Identify the previous healthy snapshot from the list.",
          "Use rollback only after Health and Ingestion evidence confirm the current active snapshot is the problem.",
          "Record a reason that references the incident or review evidence.",
        ],
        [
          "Определите предыдущий исправный снапшот из списка.",
          "Используйте откат только после того, как данные о состоянии системы и индексации подтвердили проблему текущего активного снапшота.",
          "Запишите причину со ссылкой на инцидент или результат ревью.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-snapshots-rollback-main",
        "admin-snapshots-rollback",
        "Runtime rollback controls and audit preview in the Snapshots section.",
        "Элементы управления откатом и предварительного просмотра аудита в разделе снапшотов.",
        "Use this panel when switching back to an older snapshot under controlled confirmation.",
        "Используйте эту панель, когда нужно вернуться к старому снапшоту через контролируемое подтверждение.",
      ),
    ],
    relatedArticleIds: ["admin-snapshots", "admin-config-history-rollback", "admin-health"],
    keywords: ["snapshot rollback", "runtime switch", "audit trail", "active snapshot"],
    adminSectionIds: ["snapshots"],
  },
  {
    id: "admin-snapshots-cleanup",
    slug: "admin-snapshots-cleanup",
    topic: "Admin Console",
    routePath: "/#snapshots",
    entryLabel: localizedText("Snapshots: Cleanup", "Снапшоты: очистка"),
    title: localizedText(
      "Admin Console: Snapshot Cleanup and Retention History",
      "Админка: очистка снапшотов и история retention",
    ),
    summary: localizedText(
      "This article explains how cleanup preview and execution work, how retention policy protects active scopes, and how to validate cleanup history after destructive actions.",
      "Эта статья объясняет, как работают предварительный просмотр и выполнение очистки, как политика хранения защищает активные области и как проверять историю очистки после деструктивных операций.",
    ),
    purpose: localizedLines(
      [
        "Explain the retention envelope before destructive cleanup begins.",
        "Show why preview is mandatory and how to interpret risk summary and delete candidates.",
        "Connect execution results with cleanup audit history and topology policy.",
      ],
      [
        "Объяснить границы хранения до начала деструктивной очистки.",
        "Показать, почему предварительный просмотр обязателен и как интерпретировать анализ рисков и кандидатов на удаление.",
        "Связать результаты выполнения с историей аудита очистки и политикой топологии.",
      ],
    ),
    workflow: localizedLines(
      [
        "Filter the cleanup scope if needed by source kind.",
        "Run Preview Cleanup first and read the candidate counts and risk summary.",
        "Execute cleanup only when the preview matches your expectation and the reason is recorded.",
        "Verify execution output and check the latest cleanup history entries.",
      ],
      [
        "При необходимости отфильтруйте область очистки по типу источника.",
        "Сначала запустите предварительный просмотр очистки и прочитайте количество кандидатов и анализ рисков.",
        "Выполняйте очистку только когда результат просмотра соответствует ожиданиям и причина записана.",
        "Проверьте результат выполнения и затем посмотрите последние записи истории очистки.",
      ],
    ),
    examples: [
      example(
        "snapshot-cleanup-example-1",
        "Routine retention cleanup",
        "Плановый retention cleanup",
        [
          "Preview the cleanup after confirming the current retention limits in topology policy.",
          "Check that only inactive snapshots appear in delete candidates.",
          "Execute cleanup and save the audit id for later reference.",
        ],
        [
          "Запустите предварительный просмотр очистки после подтверждения текущих лимитов хранения в политике топологии.",
          "Проверьте, что в кандидаты на удаление попали только неактивные снапшоты.",
          "Выполните очистку и сохраните идентификатор аудита для последующей ссылки.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-snapshots-cleanup-main",
        "admin-snapshots-cleanup",
        "Snapshot cleanup preview and history controls in the Snapshots section.",
        "Элементы предварительного просмотра очистки и истории в разделе снапшотов.",
        "Use this panel to validate retention impact before deleting inactive snapshots.",
        "Используйте эту панель, чтобы проверить влияние политики хранения до удаления неактивных снапшотов.",
      ),
    ],
    relatedArticleIds: ["admin-snapshots", "admin-health-dependencies-topology", "admin-health"],
    keywords: ["snapshot cleanup", "retention", "preview cleanup", "destructive action", "cleanup history"],
    adminSectionIds: ["snapshots"],
  },
  {
    id: "admin-critical-events",
    slug: "admin-critical-events",
    topic: "Admin Console",
    routePath: "/#critical-events",
    entryLabel: localizedText("Critical Events", "Критичные события"),
    title: localizedText(
      "Admin Console: Critical Events, SLA, and Response Actions",
      "Админка: critical events, SLA и response actions",
    ),
    summary: localizedText(
      "This page is the operational incident queue for partial publish, blocked publish, and other high-signal failures that require acknowledgement or escalation.",
      "Эта страница представляет собой операционную очередь инцидентов для partial publish, blocked publish и других высокосигнальных ошибок, требующих acknowledgement или escalation.",
    ),
    purpose: localizedLines(
      [
        "Review the severity, SLA timer, and lifecycle state of critical operational events.",
        "Assign an owner, acknowledge, mute, snooze, escalate, or resolve events with an audit trail.",
        "Prepare postmortem follow-up once the event is resolved.",
      ],
      [
        "Проверять severity, SLA timer и lifecycle state критичных operational events.",
        "Назначать owner, выполнять acknowledge, mute, snooze, escalate или resolve с audit trail.",
        "Готовить postmortem follow-up после разрешения события.",
      ],
    ),
    workflow: localizedLines(
      [
        "Start with the newest unresolved event.",
        "Read the event message, impacted products, and lifecycle hints.",
        "Select the least destructive response first: acknowledge or assign owner.",
        "Escalate only if the timer or business impact requires wider action.",
      ],
      [
        "Начинайте с самого нового неразрешенного события.",
        "Прочитайте сообщение события, затронутые продукты и lifecycle hints.",
        "Сначала выбирайте наименее деструктивный ответ: acknowledge или assign owner.",
        "Escalate выполняйте только если этого требуют таймер или бизнес-воздействие.",
      ],
    ),
    commands: [
      command(
        "analytics-command-1",
        "Run full UI governance gate",
        "Запустить полный UI governance gate",
        "Useful after large UX changes, including how-to content or admin layout updates.",
        "Полезно после крупных UX-изменений, включая how-to content или обновления admin layout.",
        "make admin-ui-regression-gates",
      ),
    ],
    examples: [
      example(
        "events-example-1",
        "Partial publish event",
        "Событие partial publish",
        [
          "Acknowledge the event to mark that it is being handled.",
          "Read the impacted product list and ingestion logs.",
          "Decide whether a rollback, republish, or owner escalation is required.",
        ],
        [
          "Сделайте acknowledge, чтобы отметить, что событие взято в работу.",
          "Прочитайте список затронутых продуктов и ingestion logs.",
          "Определите, нужен ли rollback, republish или escalation на владельца.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-critical-events-main",
        "admin-critical-events",
        "Critical Events section with lifecycle actions and SLA indicators.",
        "Раздел Critical Events с lifecycle actions и SLA indicators.",
        "Use this queue to triage and track high-signal operational incidents.",
        "Используйте эту очередь для triage и отслеживания высокосигнальных operational incidents.",
      ),
    ],
    relatedArticleIds: [
      "admin-critical-events-lifecycle",
      "admin-critical-events-history",
      "admin-health",
      "admin-logs-traces",
    ],
    keywords: ["critical events", "sla", "incident", "escalation", "postmortem"],
    adminSectionIds: ["critical-events"],
  },
  {
    id: "admin-critical-events-lifecycle",
    slug: "admin-critical-events-lifecycle",
    topic: "Admin Console",
    routePath: "/#critical-events",
    entryLabel: localizedText("Critical Events: Lifecycle", "Критичные события: жизненный цикл"),
    title: localizedText(
      "Admin Console: Incident Lifecycle Actions",
      "Админка: действия жизненного цикла для инцидентов",
    ),
    summary: localizedText(
      "This deep-dive explains how to work an active incident from first triage through acknowledge, assign, escalate, and resolve without losing SLA context.",
      "Эта deep-dive статья объясняет, как вести активный инцидент от первого triage до acknowledge, assign, escalate и resolve без потери SLA контекста.",
    ),
    purpose: localizedLines(
      [
        "Explain what each lifecycle action changes operationally.",
        "Show how owner assignment, severity override, and escalation affect follow-up expectations.",
        "Keep operators from using destructive or noisy actions too early.",
      ],
      [
        "Объяснить, что именно меняет каждое lifecycle action на операционном уровне.",
        "Показать, как owner assignment, severity override и escalation влияют на дальнейшие ожидания.",
        "Не допускать слишком раннего использования деструктивных или шумных действий.",
      ],
    ),
    workflow: localizedLines(
      [
        "Read the newest unresolved event and confirm the affected scope first.",
        "Use acknowledge or assign before escalation whenever the issue is still being understood.",
        "Apply mute or snooze only when the alert noise is known and temporary.",
        "Resolve only after the evidence in Health, Ingestion, or Snapshots shows the incident is no longer active.",
      ],
      [
        "Сначала прочитайте самое новое неразрешенное событие и подтвердите затронутый scope.",
        "Используйте acknowledge или assign до escalation, пока проблема еще изучается.",
        "Применяйте mute или snooze только когда природа шума понятна и временная.",
        "Выполняйте resolve только после того, как evidence в Health, Ingestion или Snapshots подтвердило исчезновение инцидента.",
      ],
    ),
    examples: [
      example(
        "critical-events-lifecycle-example-1",
        "Escalate only after owner assignment stalls",
        "Escalate только после того, как owner assignment не помог",
        [
          "Assign an owner first and wait for the expected follow-up window.",
          "Escalate when the SLA keeps shrinking or the blast radius expands.",
          "Record the reason so the postmortem can reconstruct why the escalation happened.",
        ],
        [
          "Сначала назначьте owner и дождитесь ожидаемого окна реакции.",
          "Переходите к escalate, когда SLA продолжает сокращаться или blast radius растет.",
          "Запишите причину, чтобы postmortem мог восстановить логику escalation.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-critical-events-lifecycle-main",
        "admin-critical-events-lifecycle",
        "Lifecycle action controls for a critical event row.",
        "Элементы lifecycle actions в строке critical event.",
        "Use this panel to decide which incident action is appropriate right now.",
        "Используйте эту панель, чтобы выбрать правильное действие по инциденту прямо сейчас.",
      ),
    ],
    relatedArticleIds: ["admin-critical-events", "admin-logs-traces", "admin-health"],
    keywords: ["incident lifecycle", "acknowledge", "assign", "escalate", "resolve", "sla"],
    adminSectionIds: ["critical-events"],
  },
  {
    id: "admin-critical-events-history",
    slug: "admin-critical-events-history",
    topic: "Admin Console",
    routePath: "/#critical-events",
    entryLabel: localizedText("Critical Events: Action History", "Критичные события: история действий"),
    title: localizedText(
      "Admin Console: Recent Notification Actions",
      "Админка: Recent Notification Actions",
    ),
    summary: localizedText(
      "Use this article to understand how the event action history should be read and how it supports audit, handoff, and post-incident review.",
      "Используйте эту статью, чтобы понять, как читать историю действий по событиям и как она помогает аудиту, handoff и post-incident review.",
    ),
    purpose: localizedLines(
      [
        "Explain which actor performed which incident action and when.",
        "Preserve continuity between shifts and between product owners and superusers.",
        "Use request_id and timestamps to pivot into Logs & Traces when needed.",
      ],
      [
        "Объяснить, какой actor выполнил какое действие по инциденту и когда.",
        "Сохранять непрерывность между сменами и между product owners и superusers.",
        "Использовать request_id и timestamps для перехода в Logs & Traces при необходимости.",
      ],
    ),
    workflow: localizedLines(
      [
        "Open the incident row first, then compare it with the latest actions below.",
        "Use the action list to verify who muted, reassigned, or resolved the event.",
        "Follow the request_id into Logs & Traces if the action context is incomplete.",
      ],
      [
        "Сначала откройте строку инцидента, затем сравните ее с последними действиями ниже.",
        "Используйте список действий, чтобы проверить, кто выполнил mute, reassignment или resolve.",
        "Переходите по request_id в Logs & Traces, если контекст действия неполный.",
      ],
    ),
    examples: [
      example(
        "critical-events-history-example-1",
        "Reconstructing an overnight incident",
        "Восстановление ночного инцидента",
        [
          "Start from the latest action row.",
          "Identify the actor, request_id, and timestamp.",
          "Then open the main incident row and continue in Logs & Traces if the sequence still looks ambiguous.",
        ],
        [
          "Начните с последней строки действия.",
          "Определите actor, request_id и timestamp.",
          "Затем откройте основную строку инцидента и переходите в Logs & Traces, если последовательность все еще неоднозначна.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-critical-events-history-main",
        "admin-critical-events-history",
        "Recent critical event actions and audit timeline.",
        "Последние действия по critical events и audit timeline.",
        "Use this action history to confirm what was already done and by whom.",
        "Используйте эту историю действий, чтобы понять, что уже сделано и кем.",
      ),
    ],
    relatedArticleIds: ["admin-critical-events", "admin-logs-traces"],
    keywords: ["incident history", "audit trail", "request id", "handoff"],
    adminSectionIds: ["critical-events"],
  },
  {
    id: "admin-language-registries",
    slug: "admin-language-registries",
    topic: "Admin Console",
    routePath: "/#language-registries",
    entryLabel: localizedText("Language Registries", "Языковые реестры"),
    title: localizedText(
      "Language Registries: Products, Languages & Locales",
      "Языковые реестры: продукты, языки и локали",
    ),
    summary: localizedText(
      "This page is the central hub for managing everything related to programming languages and documentation locales in ADCS. At the top you see the full product catalog — all registered products with their repositories and SDK languages. Below that are two reference dictionaries (programming languages and documentation locales) and a section for per-product aliases that handle naming differences between repositories.",
      "Эта страница — центральный хаб для управления всем, что связано с языками программирования и локалями документации в ADCS. Вверху вы видите полный каталог продуктов — все зарегистрированные продукты с их репозиториями и SDK-языками. Ниже расположены два справочных словаря (языки программирования и локали документации) и раздел алиасов, которые решают проблему разного именования в репозиториях.",
    ),
    purpose: localizedLines(
      [
        "View the complete product catalog: which products are registered, how many repositories each has, and which SDK languages they support.",
        "Manage the master dictionaries of programming languages and documentation locales that the entire system uses for filtering and indexing.",
        "Set up aliases so that products with non-standard folder naming (e.g. 'csharp' instead of 'net') work correctly without modifying source repositories.",
        "Only system administrators (superuser keys) can modify dictionaries. This protects data integrity when multiple admins share the system.",
      ],
      [
        "Просматривать полный каталог продуктов: какие продукты зарегистрированы, сколько у каждого репозиториев и какие SDK-языки поддерживаются.",
        "Управлять мастер-словарями языков программирования и локалей документации, которые вся система использует для фильтрации и индексирования.",
        "Настраивать алиасы, чтобы продукты с нестандартным именованием папок (например 'csharp' вместо 'net') работали корректно без изменения исходных репозиториев.",
        "Изменять словари могут только системные администраторы (superuser-ключи). Это защищает целостность данных, когда системой пользуются несколько админов.",
      ],
    ),
    workflow: localizedLines(
      [
        "Start by reviewing the Products table to see what is already registered and which SDK languages each product uses.",
        "If you need to add a new programming language or locale, open the Canonical Dictionaries section and add it there first.",
        "If a product repository uses a different folder name for an existing language, create a per-product alias instead of a new dictionary entry.",
        "After making changes, verify that ingestion and retrieval still work correctly by running a validate-only ingestion job.",
      ],
      [
        "Начните с просмотра таблицы продуктов, чтобы увидеть, что уже зарегистрировано и какие SDK-языки использует каждый продукт.",
        "Если нужно добавить новый язык программирования или локаль, откройте раздел Canonical Dictionaries и добавьте его сначала там.",
        "Если репозиторий продукта использует другое имя папки для существующего языка, создайте алиас для продукта вместо новой записи в словаре.",
        "После внесения изменений убедитесь, что ingestion и retrieval работают корректно, запустив валидационный ingestion job.",
      ],
    ),
    examples: [
      example(
        "registries-example-1",
        "Typical workflow: onboarding a new product",
        "Типичный процесс: подключение нового продукта",
        [
          "Check the Products table — if the product is not there yet, register its docs and apiref repositories on the Ingestion Jobs page first.",
          "Open the language dictionary accordion — confirm all SDK languages the product supports are already listed.",
          "If the product uses non-standard naming (e.g. folder called 'dotnet' for .NET), add an alias mapping 'dotnet' → 'net' for that specific product.",
          "Run a validate-only ingestion to confirm everything resolves correctly before publishing.",
        ],
        [
          "Проверьте таблицу продуктов — если продукта ещё нет, сначала зарегистрируйте его docs и apiref репозитории на странице Ingestion Jobs.",
          "Откройте раскрывашку с языками — убедитесь, что все SDK-языки, поддерживаемые продуктом, уже есть в списке.",
          "Если продукт использует нестандартное именование (например, папка 'dotnet' для .NET), добавьте алиас 'dotnet' → 'net' для этого конкретного продукта.",
          "Запустите validate-only ingestion, чтобы убедиться, что всё разрешается корректно перед публикацией.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-language-registries-main",
        "admin-language-registries",
        "Language Registries page showing the products table, language and locale dictionaries, and alias management.",
        "Страница Language Registries с таблицей продуктов, словарями языков и локалей, и управлением алиасами.",
        "Start from the products table at the top to understand the current state, then scroll down to dictionaries and aliases.",
        "Начните с таблицы продуктов наверху, чтобы понять текущее состояние, затем прокрутите вниз к словарям и алиасам.",
      ),
    ],
    relatedArticleIds: [
      "admin-language-registries-dictionaries",
      "admin-language-registries-aliases",
      "admin-ingestion-jobs",
      "onboarding-overview",
    ],
    keywords: ["language registries", "aliases", "locales", "canonical ids", "products", "SDK languages"],
    adminSectionIds: ["language-registries"],
  },
  {
    id: "admin-language-registries-dictionaries",
    slug: "admin-language-registries-dictionaries",
    topic: "Admin Console",
    routePath: "/#language-registries",
    entryLabel: localizedText("Language Registries: Dictionaries", "Языковые реестры: словари"),
    title: localizedText(
      "Canonical Language & Locale Dictionaries",
      "Канонические словари языков и локалей",
    ),
    summary: localizedText(
      "The canonical dictionaries define the master list of SDK programming languages and documentation locales recognized by ADCS. Every product, repository, and retrieval query ultimately resolves against these dictionaries. Adding a new entry here means the system will accept it as a valid filter dimension across ingestion, indexing, and retrieval.",
      "Канонические словари задают мастер-список SDK-языков программирования и локалей документации, которые распознаёт ADCS. Каждый продукт, репозиторий и поисковый запрос в конечном счёте разрешается относительно этих словарей. Добавление новой записи означает, что система примет её как допустимое измерение фильтрации в ingestion, indexing и retrieval.",
    ),
    purpose: localizedLines(
      [
        "Provide a single source of truth for all valid programming language and locale identifiers used across the platform.",
        "Ensure consistent filtering: retrieval queries, ingestion pipelines, and the admin UI all reference the same set of canonical IDs.",
        "Prevent fragmentation — without a canonical dictionary, different products could use incompatible names for the same language (e.g. 'csharp' vs 'dotnet' vs 'net').",
        "Support the alias system: product-specific naming variations are mapped back to these canonical entries.",
      ],
      [
        "Единый источник истины для всех идентификаторов языков и локалей на платформе.",
        "Гарантирует согласованную фильтрацию: retrieval-запросы, ingestion-пайплайны и админка ссылаются на один набор canonical ID.",
        "Предотвращает фрагментацию — без словаря разные продукты могут использовать несовместимые имена для одного языка.",
        "Обеспечивает работу системы алиасов: product-specific варианты именования маппятся на записи этого словаря.",
      ],
    ),
    workflow: localizedLines(
      [
        "Review the existing dictionary entries to confirm the language or locale is not already registered under a different ID.",
        "Choose a short, stable, lowercase ID (e.g. 'python', 'cpp', 'net') — this ID is permanent and used in index keys.",
        "Set a human-readable display name (e.g. 'Python', 'C++', '.NET') — this appears in the admin UI and reports.",
        "If a product repository uses a non-standard folder name for this language, create a per-product alias in the section below instead of adding a duplicate dictionary entry.",
      ],
      [
        "Проверьте существующие записи словаря — убедитесь, что язык или локаль ещё не зарегистрированы под другим ID.",
        "Выберите короткий, стабильный, строчный ID (например 'python', 'cpp', 'net') — этот ID постоянный и используется в ключах индекса.",
        "Задайте человекочитаемое display name (например 'Python', 'C++', '.NET') — оно отображается в админке и отчётах.",
        "Если репозиторий продукта использует нестандартное имя папки для этого языка, создайте per-product alias в разделе ниже вместо дублирования записи в словаре.",
      ],
    ),
    examples: [
      example(
        "language-dictionaries-example-1",
        "When to add a new language vs. an alias",
        "Когда добавлять новый язык vs. алиас",
        [
          "Add a new dictionary entry when the language is genuinely new to the platform (e.g. adding Rust support for the first time).",
          "Add an alias when the language already exists but a specific product uses a different folder name (e.g. product uses 'csharp' but canonical ID is 'net').",
          "Never add two dictionary entries for the same language — use aliases to handle naming variations.",
        ],
        [
          "Добавляйте новую запись в словарь, когда язык действительно новый для платформы (например, первое добавление Rust).",
          "Добавляйте алиас, когда язык уже существует, но конкретный продукт использует другое имя папки (например, продукт использует 'csharp', а canonical ID — 'net').",
          "Никогда не создавайте две записи в словаре для одного языка — используйте алиасы для вариаций именования.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-language-registries-dictionaries-main",
        "admin-language-registries-dictionaries",
        "Canonical language and locale dictionaries inside Language Registries.",
        "Словари canonical language и locale внутри Language Registries.",
        "The dictionaries panel shows all registered languages and locales. Use the form to add new entries.",
        "Панель словарей показывает все зарегистрированные языки и локали. Используйте форму для добавления новых записей.",
      ),
    ],
    relatedArticleIds: ["admin-language-registries", "onboarding-overview"],
    keywords: ["canonical languages", "locales", "registry", "dictionary", "SDK languages", "documentation locales"],
    adminSectionIds: ["language-registries"],
  },
  {
    id: "admin-language-registries-aliases",
    slug: "admin-language-registries-aliases",
    topic: "Admin Console",
    routePath: "/#language-registries",
    entryLabel: localizedText("Language Registries: Aliases", "Языковые реестры: алиасы"),
    title: localizedText(
      "Per-Product Language Aliases",
      "Алиасы языков для отдельных продуктов",
    ),
    summary: localizedText(
      "Aliases solve a common problem: different products use different folder names for the same programming language. For example, one product might call its .NET SDK folder 'csharp', another — 'dotnet', and a third — 'net'. Instead of creating separate dictionary entries for each variation, you create aliases that map all these names to a single canonical ID. Aliases are always scoped to a specific product, so they never affect other products.",
      "Алиасы решают типичную проблему: разные продукты используют разные имена папок для одного и того же языка программирования. Например, один продукт может назвать свою папку .NET SDK 'csharp', другой — 'dotnet', третий — 'net'. Вместо создания отдельных записей в словаре для каждого варианта, вы создаёте алиасы, которые маппят все эти имена на один канонический ID. Алиасы всегда привязаны к конкретному продукту и не влияют на другие продукты.",
    ),
    purpose: localizedLines(
      [
        "Map product-specific folder names to canonical language IDs without modifying source repositories.",
        "Keep the global dictionary clean — one entry per language, no duplicates for naming variations.",
        "Each alias is scoped to one product, so different products can have different aliases for the same canonical language.",
        "Aliases are used during ingestion to correctly classify documents by programming language.",
      ],
      [
        "Маппить имена папок конкретного продукта на канонические ID языков без изменения исходных репозиториев.",
        "Сохранять глобальный словарь чистым — одна запись на язык, без дубликатов для вариаций именования.",
        "Каждый алиас привязан к одному продукту, поэтому разные продукты могут иметь разные алиасы для одного канонического языка.",
        "Алиасы используются при ingestion для корректной классификации документов по языку программирования.",
      ],
    ),
    workflow: localizedLines(
      [
        "Select the product you want to configure from the dropdown.",
        "In the 'external_id' field, type the exact folder or identifier name as it appears in the product's source repository (e.g. 'csharp', 'py-dotnet').",
        "In the 'canonical_lang_id' dropdown, select the canonical language this external name should map to (e.g. 'net', 'python').",
        "Click 'Add Alias'. The mapping takes effect on the next ingestion run for this product.",
        "To remove an alias, click the Delete button next to it. Only remove aliases after confirming that no active ingestion depends on them.",
      ],
      [
        "Выберите продукт из выпадающего списка.",
        "В поле 'external_id' введите точное имя папки или идентификатора, как оно выглядит в исходном репозитории продукта (например 'csharp', 'py-dotnet').",
        "В выпадающем списке 'canonical_lang_id' выберите канонический язык, на который должно маппиться это внешнее имя (например 'net', 'python').",
        "Нажмите 'Add Alias'. Маппинг вступит в силу при следующем запуске ingestion для этого продукта.",
        "Для удаления алиаса нажмите кнопку Delete рядом с ним. Удаляйте алиасы только после подтверждения, что ни один активный ingestion от них не зависит.",
      ],
    ),
    examples: [
      example(
        "language-aliases-example-1",
        "Real-world alias scenario",
        "Реальный пример использования алиасов",
        [
          "Product Aspose.OCR has its Python SDK in a folder called 'python-net' in the repository, but the canonical language ID in ADCS is 'python'.",
          "You create an alias for product 'aspose.ocr': external_id = 'python-net' → canonical_lang_id = 'python'.",
          "Now when ingestion processes this repository, it correctly tags all documents from the 'python-net' folder as Python documentation.",
          "If the repository later renames the folder to 'python-dotnet', you simply update the alias — no dictionary changes needed.",
        ],
        [
          "У продукта Aspose.OCR его Python SDK находится в папке 'python-net' в репозитории, но канонический ID языка в ADCS — 'python'.",
          "Вы создаёте алиас для продукта 'aspose.ocr': external_id = 'python-net' → canonical_lang_id = 'python'.",
          "Теперь при ingestion этого репозитория система правильно тегирует все документы из папки 'python-net' как документацию Python.",
          "Если репозиторий позже переименует папку в 'python-dotnet', вы просто обновите алиас — изменения в словаре не нужны.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-language-registries-aliases-main",
        "admin-language-registries-aliases",
        "Per-product alias management panel with product selector, external ID input, and canonical language dropdown.",
        "Панель управления алиасами продукта с выбором продукта, вводом внешнего ID и выпадающим списком канонических языков.",
        "Select a product first, then create or delete aliases. Each alias maps one external name to one canonical language ID.",
        "Сначала выберите продукт, затем создавайте или удаляйте алиасы. Каждый алиас связывает одно внешнее имя с одним каноническим ID языка.",
      ),
    ],
    relatedArticleIds: ["admin-language-registries", "admin-language-registries-dictionaries", "admin-ingestion-jobs"],
    keywords: ["language aliases", "canonical mapping", "product-specific naming", "external id", "folder names"],
    adminSectionIds: ["language-registries"],
  },
  {
    id: "admin-api-keys-access",
    slug: "admin-api-keys-access",
    topic: "Admin Console",
    routePath: "/#api-keys-access",
    entryLabel: localizedText("API Keys & Access", "API-ключи и доступ"),
    title: localizedText(
      "Admin Console: API Keys, Scopes, and Access Boundaries",
      "Админка: API-ключи, scopes и границы доступа",
    ),
    summary: localizedText(
      "This page manages admin API keys, their scopes, product boundaries, owner email binding, key rotation, and import/export. It is the control point for safe delegation of product-owner access.",
      "На этой странице управляют API-ключами администратора, их разрешениями, продуктовыми границами, привязкой к email владельца, ротацией ключей и импортом/экспортом. Это центр безопасной делегации доступа.",
    ),
    purpose: localizedLines(
      [
        "Create, rotate, or disable admin API keys with mandatory owner email.",
        "Inspect effective roles, scope boundaries, and product isolation.",
        "Export keys for backup and import them on another instance.",
        "Ensure product-owner keys can change only the products they own while still seeing global diagnostics.",
      ],
      [
        "Создавать, ротировать или отключать API-ключи с обязательным email владельца.",
        "Просматривать роли, границы разрешений и продуктовую изоляцию.",
        "Экспортировать ключи для резервного копирования и импортировать на другую инсталляцию.",
        "Гарантировать, что продуктовые ключи могут менять только свои продукты, сохраняя видимость глобальной диагностики.",
      ],
    ),
    workflow: localizedLines(
      [
        "Review the current role and product scopes first.",
        "When creating a new key, specify the owner email and pick scopes from the visual selector.",
        "Use key rotation instead of manual create+disable when refreshing credentials.",
        "Use disable rather than delete to preserve audit continuity.",
        "Export keys before infrastructure migrations; import on the new instance.",
      ],
      [
        "Сначала просмотрите текущую роль и области продуктов.",
        "При создании нового ключа укажите email владельца и выберите разрешения через визуальный селектор.",
        "Используйте ротацию ключа вместо ручного создания+отключения при обновлении учётных данных.",
        "Используйте отключение вместо удаления, чтобы сохранить журнал аудита.",
        "Экспортируйте ключи перед миграцией инфраструктуры; импортируйте на новой инсталляции.",
      ],
    ),
    callouts: [
      callout(
        "api-keys-callout-email",
        "info",
        "Every key must have an owner email",
        "Каждый ключ должен иметь email владельца",
        [
          "Owner email is required and cannot be changed after creation. One email can own multiple keys. This ensures accountability for every delegated access.",
        ],
        [
          "Email владельца обязателен и не может быть изменён после создания. На один email может быть несколько ключей. Это обеспечивает ответственность за каждый делегированный доступ.",
        ],
      ),
      callout(
        "api-keys-callout-rotation",
        "warning",
        "Rotation disables the old key immediately",
        "Ротация немедленно отключает старый ключ",
        [
          "When you rotate a key, the old token stops working instantly. Share the new token before the old one is needed again.",
        ],
        [
          "При ротации ключа старый токен перестаёт работать мгновенно. Передайте новый токен до того, как понадобится старый.",
        ],
      ),
    ],
    commands: [],
    examples: [
      example(
        "keys-example-1",
        "Creating a product-owner key with email",
        "Создание ключа продуктового владельца с email",
        [
          "Enter the owner's email address — this is required and links the key to a person.",
          "Use the visual product selector to pick only the owned product ids.",
          "Use the scope selector to grant only the necessary permissions.",
          "Keep destructive scopes off unless explicitly justified.",
        ],
        [
          "Введите email владельца — это обязательное поле, привязывающее ключ к человеку.",
          "Используйте визуальный селектор продуктов для выбора только принадлежащих продуктов.",
          "Используйте селектор разрешений для выдачи только необходимых прав.",
          "Не давайте деструктивные разрешения без явного обоснования.",
        ],
      ),
      example(
        "keys-example-2",
        "Rotating a key before credential expiry",
        "Ротация ключа до истечения учётных данных",
        [
          "Click Rotate on the target key row.",
          "The system creates a new key with the same scopes and email, disables the old one.",
          "Copy the new token immediately — it is shown only once.",
          "Verify the new key works before discarding the old token from your secrets manager.",
        ],
        [
          "Нажмите «Ротировать» на строке нужного ключа.",
          "Система создаст новый ключ с теми же разрешениями и email, а старый отключит.",
          "Скопируйте новый токен сразу — он показывается только один раз.",
          "Убедитесь, что новый ключ работает, прежде чем удалять старый токен из менеджера секретов.",
        ],
      ),
      example(
        "keys-example-3",
        "Exporting and importing keys across environments",
        "Экспорт и импорт ключей между средами",
        [
          "Click Export to download all key metadata as JSON (tokens are never included).",
          "Transfer the JSON file to the target environment.",
          "Click Import and select the JSON file — new tokens will be generated for each key.",
          "Distribute the new tokens to key owners.",
        ],
        [
          "Нажмите «Экспорт» для скачивания метаданных всех ключей в JSON (токены не включаются).",
          "Перенесите JSON-файл в целевую среду.",
          "Нажмите «Импорт» и выберите JSON-файл — для каждого ключа будут сгенерированы новые токены.",
          "Раздайте новые токены владельцам ключей.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-api-keys-main",
        "admin-api-keys-access",
        "API Keys & Access section with email binding, rotation, export/import, and scope selectors.",
        "Раздел API-ключей и доступа с привязкой к email, ротацией, экспортом/импортом и визуальным выбором разрешений.",
        "Use this section for key lifecycle management: creation, rotation, scope updates, and credential export.",
        "Используйте этот раздел для управления жизненным циклом ключей: создание, ротация, обновление разрешений и экспорт.",
      ),
    ],
    relatedArticleIds: [
      "admin-api-keys-provisioning",
      "admin-api-keys-governance",
      "admin-config-history-rollback",
      "admin-critical-events",
    ],
    keywords: ["api keys", "access", "scopes", "product owner", "superuser"],
    adminSectionIds: ["api-keys-access"],
  },
  {
    id: "admin-api-keys-provisioning",
    slug: "admin-api-keys-provisioning",
    topic: "Admin Console",
    routePath: "/#api-keys-access",
    entryLabel: localizedText("API Keys: Provisioning", "API-ключи: выдача"),
    title: localizedText(
      "Admin Console: Creating Product and Superuser Keys",
      "Админка: создание product и superuser ключей",
    ),
    summary: localizedText(
      "This article documents the safe process for issuing new admin keys with mandatory email binding, choosing product scopes via visual selectors, and minimizing blast radius during delegation.",
      "Эта статья описывает безопасный процесс выдачи новых API-ключей с обязательной привязкой к email, выбора областей продуктов через визуальные селекторы и минимизации зоны поражения при делегировании доступа.",
    ),
    purpose: localizedLines(
      [
        "Explain the difference between product and superuser keys.",
        "Ensure every key has a traceable owner via email binding.",
        "Use the visual scope selector to keep the initial scope set minimal and explicit.",
        "Preserve operator understanding of why a new key was issued.",
      ],
      [
        "Объяснить разницу между продуктовыми и суперпользовательскими ключами.",
        "Гарантировать, что у каждого ключа есть отслеживаемый владелец через привязку к email.",
        "Использовать визуальный селектор разрешений для минимального и явного набора прав.",
        "Сохранять понимание оператором, зачем был выдан новый ключ.",
      ],
    ),
    workflow: localizedLines(
      [
        "Enter the owner email first — this is required and links every key to a responsible person.",
        "Choose key type (product or superuser).",
        "For product keys, click the product scope field to open the visual selector and check only the owned products.",
        "Click the scopes field to open the permission selector and grant only the required write scopes.",
        "Record a clear reason and store the previewed secret immediately because it is shown once.",
      ],
      [
        "Сначала введите email владельца — это обязательное поле, связывающее каждый ключ с ответственным лицом.",
        "Выберите тип ключа (продуктовый или суперпользовательский).",
        "Для продуктовых ключей нажмите на поле областей продуктов, чтобы открыть визуальный селектор, и отметьте только принадлежащие продукты.",
        "Нажмите на поле разрешений, чтобы открыть селектор прав и выдать только необходимые write-разрешения.",
        "Запишите понятную причину и сразу сохраните показанный секрет, потому что он отображается только один раз.",
      ],
    ),
    examples: [
      example(
        "api-keys-provisioning-example-1",
        "Delegating onboarding to a product owner",
        "Делегирование подключения продуктовому владельцу",
        [
          "Enter the product owner's email address.",
          "Click the product scope field and check only the owned product ids in the visual selector.",
          "Click the scopes field and check only `write:ingestion` and `write:settings` if the operator truly needs both.",
          "Do not issue a superuser key just because it is faster.",
        ],
        [
          "Введите email продуктового владельца.",
          "Нажмите на поле областей продуктов и отметьте в визуальном селекторе только принадлежащие продукты.",
          "Нажмите на поле разрешений и отметьте только `write:ingestion` и `write:settings`, если оператору действительно нужны оба.",
          "Не выдавайте суперпользовательский ключ только потому, что так быстрее.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-api-keys-provisioning-main",
        "admin-api-keys-provisioning",
        "API key creation form with email binding, visual product/scope selectors, and key type choice.",
        "Форма создания API-ключа с привязкой к email, визуальными селекторами продуктов/разрешений и выбором типа ключа.",
        "Use this form to issue a new key with email accountability and the smallest safe permission set.",
        "Используйте эту форму для выдачи нового ключа с привязкой к email и минимально безопасным набором разрешений.",
      ),
    ],
    relatedArticleIds: ["admin-api-keys-access", "admin-api-keys-governance"],
    keywords: ["api key creation", "product key", "superuser key", "scopes"],
    adminSectionIds: ["api-keys-access"],
  },
  {
    id: "admin-api-keys-governance",
    slug: "admin-api-keys-governance",
    topic: "Admin Console",
    routePath: "/#api-keys-access",
    entryLabel: localizedText("API Keys: Governance", "API-ключи: управление"),
    title: localizedText(
      "Admin Console: Key Registry and Audit Governance",
      "Админка: реестр ключей и аудит доступа",
    ),
    summary: localizedText(
      "Use this article when you need to update scopes, rotate or disable keys, inspect the audit history, or export/import keys across environments.",
      "Используйте эту статью, когда нужно обновить разрешения, ротировать или отключить ключи, проверить журнал аудита или экспортировать/импортировать ключи между средами.",
    ),
    purpose: localizedLines(
      [
        "Show how active keys should be reviewed and constrained over time.",
        "Use key rotation instead of manual recreate when refreshing credentials.",
        "Explain why disable is preferable to silent deletion.",
        "Export/import keys for environment migration and disaster recovery.",
        "Connect registry actions to the immutable audit trail.",
      ],
      [
        "Показать, как активные ключи должны проверяться и ограничиваться со временем.",
        "Использовать ротацию ключей вместо ручного пересоздания при обновлении учётных данных.",
        "Объяснить, почему отключение предпочтительнее удаления.",
        "Экспортировать/импортировать ключи для миграции сред и аварийного восстановления.",
        "Связать действия в реестре с неизменяемым журналом аудита.",
      ],
    ),
    workflow: localizedLines(
      [
        "Review the key registry row first — check owner email, product boundary, and active scopes.",
        "Use Rotate when credentials need refreshing — it creates a new key and disables the old one atomically.",
        "Update scopes only when you can explain the new need in one sentence.",
        "Disable keys that should no longer operate, then confirm the change in the audit trail.",
        "Use Export before migrations; Import on the new instance to recreate the key set with fresh tokens.",
      ],
      [
        "Сначала проверьте строку реестра ключей — email владельца, продуктовую границу и активные разрешения.",
        "Используйте ротацию, когда учётные данные нужно обновить — система создаст новый ключ и атомарно отключит старый.",
        "Обновляйте разрешения только если можете объяснить новую необходимость одним предложением.",
        "Отключайте ключи, которые больше не должны работать, и подтверждайте изменение в журнале аудита.",
        "Используйте экспорт перед миграцией; импорт на новой инсталляции для пересоздания набора ключей с новыми токенами.",
      ],
    ),
    examples: [
      example(
        "api-keys-governance-example-1",
        "Rotating a key and removing unnecessary scopes",
        "Ротация ключа и удаление ненужных разрешений",
        [
          "Click Rotate on the key row — old token stops working, new one is shown once.",
          "After rotation, update scopes on the new key to remove permissions no longer needed.",
          "Leave the key enabled if read-only diagnostics are still needed.",
          "Check the audit trail to confirm both the rotation and scope change are recorded.",
        ],
        [
          "Нажмите «Ротировать» на строке ключа — старый токен перестанет работать, новый покажется один раз.",
          "После ротации обновите разрешения нового ключа, убрав ненужные права.",
          "Оставьте ключ включённым, если по-прежнему нужна диагностика только для чтения.",
          "Проверьте журнал аудита, чтобы убедиться, что и ротация, и изменение разрешений записаны.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-api-keys-governance-main",
        "admin-api-keys-governance",
        "API key registry with rotation, scope updates, export/import, and audit trail.",
        "Реестр API-ключей с ротацией, обновлением разрешений, экспортом/импортом и журналом аудита.",
        "Use these panels to manage key lifecycle: rotate, update scopes, export for backup, and verify every change in the audit trail.",
        "Используйте эти панели для управления жизненным циклом ключей: ротация, обновление разрешений, экспорт для резервного копирования и проверка каждого изменения в журнале аудита.",
      ),
    ],
    relatedArticleIds: ["admin-api-keys-access", "admin-logs-traces"],
    keywords: ["api key registry", "audit trail", "disable key", "update scopes"],
    adminSectionIds: ["api-keys-access"],
  },
  {
    id: "admin-retrieval-settings",
    slug: "admin-retrieval-settings",
    topic: "Admin Console",
    routePath: "/#retrieval-settings",
    entryLabel: localizedText("Retrieval Settings", "Настройки поиска"),
    title: localizedText(
      "Admin Console: Retrieval Settings and Answer Shaping",
      "Админка: настройки поиска и формирование ответа",
    ),
    summary: localizedText(
      "This page controls per-product retrieval parameters: the number of returned chunks (top-k), the context token budget, the excerpt character limit, the low-confidence threshold, and the clarification policy that decides what happens when confidence is low.",
      "На этой странице настраиваются параметры поиска для каждого продукта: количество возвращаемых чанков (top-k), бюджет токенов контекста, лимит символов выдержки, порог низкой уверенности и политика уточнения, определяющая, что делать при низкой уверенности.",
    ),
    purpose: localizedLines(
      [
        "Tune retrieval quality without changing code or redeploying.",
        "Balance recall, latency, and answer compactness for a specific product.",
        "Adjust clarification behavior when confidence is low — ask, always return, or suppress.",
        "Review changes in the Config History section and roll back if needed.",
      ],
      [
        "Настраивать качество поиска без изменения кода и пересборки.",
        "Балансировать полноту, задержку и компактность ответа для конкретного продукта.",
        "Настраивать поведение при низкой уверенности — спросить, всегда возвращать или подавлять.",
        "Просматривать изменения в разделе «История конфигураций» и откатывать при необходимости.",
      ],
    ),
    workflow: localizedLines(
      [
        "Select the target product first and click Load to fetch current values.",
        "Click Update Settings to enter edit mode.",
        "Change one parameter at a time and observe its effect in Analytics before the next change.",
        "For the clarification policy, read the live description shown below the dropdown before saving.",
        "After saving, verify the change in Config History and monitor analytics feedback.",
      ],
      [
        "Сначала выберите целевой продукт и нажмите «Загрузить» для получения текущих значений.",
        "Нажмите «Обновить настройки», чтобы перейти в режим редактирования.",
        "Меняйте по одному параметру за раз и наблюдайте эффект в «Аналитике» перед следующим изменением.",
        "Для политики уточнения прочитайте описание, которое появляется под выпадающим списком, перед сохранением.",
        "После сохранения проверьте изменение в «Истории конфигураций» и отслеживайте обратную связь в аналитике.",
      ],
    ),
    callouts: [
      callout(
        "retrieval-settings-callout-policy",
        "info",
        "Clarification policy options",
        "Варианты политики уточнения",
        [
          "ask_when_low_confidence — suggests the user refine their query when confidence is low. Best for production accuracy.",
          "always_return — returns results regardless of confidence. Best for debugging and internal tools.",
          "suppress_low_confidence — returns empty when confidence is low. Use when wrong answers are worse than no answers.",
        ],
        [
          "ask_when_low_confidence — предлагает пользователю уточнить запрос при низкой уверенности. Лучший выбор для продакшн-точности.",
          "always_return — возвращает результаты независимо от уверенности. Лучший выбор для отладки и внутренних инструментов.",
          "suppress_low_confidence — возвращает пустой ответ при низкой уверенности. Используйте, когда ошибочные ответы хуже отсутствия ответа.",
        ],
      ),
      callout(
        "retrieval-settings-callout-ranges",
        "info",
        "Valid parameter ranges",
        "Допустимые диапазоны параметров",
        [
          "top_k: 1–50 chunks per query",
          "max_context_tokens: 512–65 536 tokens",
          "excerpt_char_limit: 120–5 000 characters",
          "low_confidence_threshold: 0.0–1.0 (score)",
        ],
        [
          "top_k: 1–50 чанков на запрос",
          "max_context_tokens: 512–65 536 токенов",
          "excerpt_char_limit: 120–5 000 символов",
          "low_confidence_threshold: 0.0–1.0 (оценка)",
        ],
      ),
    ],
    examples: [
      example(
        "retrieval-settings-example-1",
        "Reducing noisy answers",
        "Уменьшение шумных ответов",
        [
          "Lower `top_k` if too many weak chunks are returned.",
          "Reduce `excerpt_char_limit` if answers become too verbose.",
          "Raise `low_confidence_threshold` carefully to trigger clarification more often.",
        ],
        [
          "Уменьшите `top_k`, если возвращается слишком много слабых чанков.",
          "Снизьте `excerpt_char_limit`, если ответы становятся слишком многословными.",
          "Осторожно поднимите `low_confidence_threshold`, чтобы чаще срабатывало уточнение.",
        ],
      ),
      example(
        "retrieval-settings-example-2",
        "Switching clarification policy for debugging",
        "Переключение политики уточнения для отладки",
        [
          "Temporarily switch to `always_return` to see what results the retrieval engine actually produces.",
          "Collect debug data in Analytics for the affected scope.",
          "Switch back to `ask_when_low_confidence` before the change is visible to external users.",
          "Verify the switch-back in Config History.",
        ],
        [
          "Временно переключитесь на `always_return`, чтобы увидеть, какие результаты реально возвращает поиск.",
          "Соберите отладочные данные в «Аналитике» для затронутой области.",
          "Переключитесь обратно на `ask_when_low_confidence» до того, как изменение станет видимым внешним пользователям.",
          "Проверьте возврат в «Истории конфигураций».",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-retrieval-settings-main",
        "admin-retrieval-settings",
        "Retrieval Settings section with edit mode, clarification policy tooltip, and live policy description.",
        "Раздел настроек поиска с режимом редактирования, подсказкой политики уточнения и живым описанием выбранной политики.",
        "Tune retrieval behavior here after reviewing analytics and user feedback. All changes are tracked in Config History.",
        "Настраивайте поведение поиска здесь после проверки аналитики и обратной связи. Все изменения отслеживаются в «Истории конфигураций».",
      ),
    ],
    relatedArticleIds: ["admin-analytics", "admin-quality-reviews"],
    keywords: ["retrieval settings", "top_k", "context", "clarification", "thresholds"],
    adminSectionIds: ["retrieval-settings"],
  },
  {
    id: "admin-analytics",
    slug: "admin-analytics",
    topic: "Admin Console",
    routePath: "/#analytics",
    entryLabel: localizedText("Analytics", "Аналитика"),
    title: localizedText(
      "Admin Console: Analytics, Usefulness, Zero-Result Cockpit, and Capacity",
      "Админка: аналитика, usefulness, zero-result cockpit и capacity",
    ),
    summary: localizedText(
      "This page is the main evidence surface for usage, answer quality, zero-result pressure, usefulness feedback, and near-term capacity planning.",
      "Эта страница является основным evidence surface для usage, качества ответов, zero-result pressure, usefulness feedback и краткосрочного capacity planning.",
    ),
    purpose: localizedLines(
      [
        "Understand how the service is used across products, SDK languages, and locales.",
        "Investigate zero-result clusters and low-confidence traffic.",
        "Review direct usefulness feedback from users and prioritize improvements.",
        "Estimate short-horizon demand pressure and saturation risk.",
      ],
      [
        "Понимать, как сервис используется по продуктам, SDK языкам и локалям.",
        "Исследовать zero-result clusters и low-confidence traffic.",
        "Просматривать прямой usefulness feedback от пользователей и приоритизировать улучшения.",
        "Оценивать краткосрочное demand pressure и saturation risk.",
      ],
    ),
    workflow: localizedLines(
      [
        "Start with filters and the top summary counters.",
        "Inspect usefulness feedback and zero-result cockpit together; they complement each other.",
        "Use saved views for recurring analysis and export when you need offline reporting.",
        "Escalate into SQL Explorer only when the standard slices are not enough.",
      ],
      [
        "Начинайте с фильтров и верхних summary counters.",
        "Просматривайте usefulness feedback и zero-result cockpit вместе; они дополняют друг друга.",
        "Используйте saved views для повторяющегося анализа и export для offline reporting.",
        "Переходите в SQL Explorer только тогда, когда стандартных slices уже недостаточно.",
      ],
    ),
    examples: [
      example(
        "analytics-example-1",
        "Finding a hidden quality issue",
        "Поиск скрытой quality-проблемы",
        [
          "If zero-result counts are low but usefulness feedback is negative, the service is returning answers that technically work but still miss the operator goal.",
          "Look at negative reason codes such as `outdated_version` or `incomplete_answer`.",
          "Then tune retrieval settings or republish fresher content.",
        ],
        [
          "Если zero-result counts низкие, но usefulness feedback отрицательный, значит сервис формально возвращает ответы, но не решает задачу оператора.",
          "Смотрите на negative reason codes, например `outdated_version` или `incomplete_answer`.",
          "После этого настраивайте retrieval settings или публикуйте более свежий контент.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-analytics-main",
        "admin-analytics",
        "Analytics section with slices, usefulness, zero-result cockpit, and capacity forecast.",
        "Раздел Analytics с slices, usefulness, zero-result cockpit и capacity forecast.",
        "This is the main evidence page for product owners and operators.",
        "Это основная evidence-страница для product owners и операторов.",
      ),
    ],
    relatedArticleIds: [
      "admin-analytics-capacity-forecast",
      "admin-analytics-usefulness-feedback",
      "admin-analytics-zero-result-cockpit",
      "admin-retrieval-settings",
    ],
    keywords: ["analytics", "usefulness", "zero results", "capacity", "saved views"],
    adminSectionIds: ["analytics"],
  },
  {
    id: "admin-analytics-capacity-forecast",
    slug: "admin-analytics-capacity-forecast",
    topic: "Admin Console",
    routePath: "/#analytics",
    entryLabel: localizedText("Analytics: Capacity Forecast", "Analytics: прогноз нагрузки"),
    title: localizedText(
      "Admin Console: Capacity Forecast and Ops Planning",
      "Админка: Capacity Forecast и Ops Planning",
    ),
    summary: localizedText(
      "Use this deep-dive to interpret the short-horizon demand forecast and decide whether content gaps or infrastructure saturation needs action first.",
      "Используйте эту deep-dive статью, чтобы интерпретировать краткосрочный прогноз спроса и понять, что нужно исправлять в первую очередь: контентные пробелы или инфраструктурное насыщение.",
    ),
    purpose: localizedLines(
      [
        "Explain projected demand, growth ratio, and saturation risk in plain operational terms.",
        "Show how product-level hot rows should drive prioritization.",
        "Separate quality pressure from raw traffic growth.",
      ],
      [
        "Объяснить projected demand, growth ratio и saturation risk простыми операционными терминами.",
        "Показать, как product-level hot rows должны определять приоритеты.",
        "Отделить quality pressure от простого роста трафика.",
      ],
    ),
    workflow: localizedLines(
      [
        "Start with the top four cards to understand the global picture.",
        "Then inspect the hottest product rows and read the recommended action.",
        "Escalate to ingestion or infrastructure only after confirming whether the pressure is coverage-driven or traffic-driven.",
      ],
      [
        "Начните с четырех верхних карточек, чтобы понять глобальную картину.",
        "Затем проверьте самые горячие product rows и прочитайте recommended action.",
        "Переходите к ingestion или infrastructure только после подтверждения, вызвано ли давление coverage или чистым трафиком.",
      ],
    ),
    examples: [
      example(
        "analytics-capacity-example-1",
        "High growth with high zero-result pressure",
        "Высокий рост вместе с высоким zero-result pressure",
        [
          "Treat this as a content-quality scale problem first, not just an infra problem.",
          "Prioritize the hottest product row with the strongest recommendation.",
          "Only then check whether runtime capacity also needs attention.",
        ],
        [
          "Сначала воспринимайте это как content-quality scale problem, а не только как infra problem.",
          "Приоритизируйте самую горячую product row с наиболее сильной рекомендацией.",
          "И только потом проверяйте, нуждается ли runtime capacity в отдельном внимании.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-analytics-capacity-forecast-main",
        "admin-analytics-capacity-forecast",
        "Capacity forecast cards and hottest products table in Analytics.",
        "Карточки capacity forecast и таблица hottest products в Analytics.",
        "Use this panel to decide which product or system limit should be addressed next.",
        "Используйте эту панель, чтобы понять, какой продуктовый или системный лимит нужно адресовать следующим.",
      ),
    ],
    relatedArticleIds: ["admin-analytics", "admin-health-content-coverage"],
    keywords: ["capacity forecast", "ops planning", "demand growth", "saturation risk"],
    adminSectionIds: ["analytics"],
  },
  {
    id: "admin-analytics-usefulness-feedback",
    slug: "admin-analytics-usefulness-feedback",
    topic: "Admin Console",
    routePath: "/#analytics",
    entryLabel: localizedText("Analytics: Usefulness Feedback", "Аналитика: полезность ответов"),
    title: localizedText(
      "Admin Console: Usefulness Feedback Loop",
      "Админка: цикл обратной связи по полезности",
    ),
    summary: localizedText(
      "This article explains how to interpret explicit user feedback and use it to detect hidden answer-quality problems that zero-result metrics alone will miss.",
      "Эта статья объясняет, как интерпретировать явный user feedback и использовать его для обнаружения скрытых проблем качества ответов, которые не видны только по zero-result метрикам.",
    ),
    purpose: localizedLines(
      [
        "Explain useful, partially useful, and not useful signals.",
        "Show how reason codes reveal missing freshness, examples, or completeness.",
        "Tie request-level feedback to retrieval settings and content actions.",
      ],
      [
        "Объяснить сигналы useful, partially useful и not useful.",
        "Показать, как reason codes раскрывают нехватку freshness, examples или completeness.",
        "Связать request-level feedback с retrieval settings и контентными действиями.",
      ],
    ),
    workflow: localizedLines(
      [
        "Look at the negative share first.",
        "Then inspect the reason-code distribution and recent negative rows.",
        "Use request_id, product, sdk, and outcome to identify whether the issue belongs to retrieval, content freshness, or answer composition.",
      ],
      [
        "Сначала смотрите на negative share.",
        "Затем проверяйте распределение reason codes и последние негативные строки.",
        "Используйте request_id, product, sdk и outcome, чтобы понять, относится ли проблема к retrieval, свежести контента или композиции ответа.",
      ],
    ),
    examples: [
      example(
        "analytics-usefulness-example-1",
        "Negative feedback without zero-result spike",
        "Негативный feedback без роста zero-result",
        [
          "This usually means the system returned something, but not the right or complete thing.",
          "Inspect `outdated_version`, `missing_example`, or `incomplete_answer` reason codes.",
          "Adjust retrieval or republish fresher content before changing infra.",
        ],
        [
          "Обычно это значит, что система что-то вернула, но не то или не полностью.",
          "Проверьте reason codes `outdated_version`, `missing_example` или `incomplete_answer`.",
          "Сначала настройте retrieval или опубликуйте более свежий контент, а не меняйте infra.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-analytics-usefulness-feedback-main",
        "admin-analytics-usefulness-feedback",
        "Usefulness feedback summary and recent negative signals in Analytics.",
        "Сводка usefulness feedback и недавние негативные сигналы в Analytics.",
        "Use this panel to understand whether returned answers actually helped developers.",
        "Используйте эту панель, чтобы понять, действительно ли возвращенные ответы помогали разработчикам.",
      ),
    ],
    relatedArticleIds: ["admin-analytics", "admin-retrieval-settings"],
    keywords: ["usefulness feedback", "negative share", "reason codes", "request feedback"],
    adminSectionIds: ["analytics"],
  },
  {
    id: "admin-analytics-zero-result-cockpit",
    slug: "admin-analytics-zero-result-cockpit",
    topic: "Admin Console",
    routePath: "/#analytics",
    entryLabel: localizedText("Analytics: Zero-Result Cockpit", "Аналитика: запросы без результата"),
    title: localizedText(
      "Admin Console: Zero-Result Cockpit",
      "Админка: cockpit запросов без результата",
    ),
    summary: localizedText(
      "Use this deep-dive to understand grouped no-result and low-confidence clusters, why they happen, and which operator action is most appropriate for each cluster.",
      "Используйте эту deep-dive статью, чтобы понимать сгруппированные no-result и low-confidence кластеры, причины их появления и наиболее подходящее действие оператора для каждого кластера.",
    ),
    purpose: localizedLines(
      [
        "Translate raw no-result pressure into actionable clusters.",
        "Show which products, languages, and locales are impacted together.",
        "Connect each cluster to a concrete recommended action.",
      ],
      [
        "Преобразовать raw no-result pressure в actionable clusters.",
        "Показать, какие продукты, языки и локали затронуты вместе.",
        "Связать каждый cluster с конкретным recommended action.",
      ],
    ),
    workflow: localizedLines(
      [
        "Start with the top cluster and read its recommendation before drilling deeper.",
        "Inspect the scope columns to understand whether the issue is product-specific or systemic.",
        "Use sample queries to validate that the cluster description matches real user intent.",
      ],
      [
        "Начинайте с top cluster и сначала читайте его recommendation.",
        "Проверяйте scope columns, чтобы понять, локальна проблема для продукта или системная.",
        "Используйте sample queries, чтобы подтвердить, что описание cluster совпадает с реальным user intent.",
      ],
    ),
    examples: [
      example(
        "analytics-zero-result-example-1",
        "Translation fallback cluster",
        "Кластер translation fallback",
        [
          "If many queries share the same fallback and locale pattern, the issue may be translation coverage rather than missing documents.",
          "Validate the recommendation before launching a broad reindex.",
          "Escalate to language or translation policy only when the cluster evidence stays consistent.",
        ],
        [
          "Если многие запросы делят одну и ту же fallback и locale pattern, проблема может быть в translation coverage, а не в отсутствии документов.",
          "Подтвердите recommendation до запуска широкого reindex.",
          "Переходите к language или translation policy только когда evidence кластера остается устойчивым.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-analytics-zero-result-cockpit-main",
        "admin-analytics-zero-result-cockpit",
        "Zero-result cockpit cards and clusters table in Analytics.",
        "Карточки zero-result cockpit и таблица clusters в Analytics.",
        "Use this cockpit to find the highest-value missing-coverage problems first.",
        "Используйте этот cockpit, чтобы сначала находить самые ценные проблемы недостающего coverage.",
      ),
    ],
    relatedArticleIds: ["admin-analytics", "admin-ingestion-execution", "admin-health-content-coverage"],
    keywords: ["zero result", "clusters", "low confidence", "recommendation"],
    adminSectionIds: ["analytics"],
  },
  {
    id: "admin-sql-explorer",
    slug: "admin-sql-explorer",
    topic: "Admin Console",
    routePath: "/#sql-explorer-read-only",
    entryLabel: localizedText("SQL Explorer", "SQL Explorer"),
    title: localizedText(
      "Admin Console: Read-Only SQL Explorer",
      "Админка: read-only SQL Explorer",
    ),
    summary: localizedText(
      "Use this page to run controlled SELECT queries against analytics views when the standard dashboards are not enough.",
      "Эта страница используется для controlled SELECT-запросов к analytics views, когда стандартных дашбордов уже недостаточно.",
    ),
    purpose: localizedLines(
      [
        "Run ad-hoc analytics queries without database shell access.",
        "Export query results to CSV for offline analysis.",
        "Keep diagnostics safe through read-only guardrails and row limits.",
      ],
      [
        "Выполнять ad-hoc analytics queries без доступа к database shell.",
        "Экспортировать результаты в CSV для offline analysis.",
        "Сохранять диагностику безопасной благодаря read-only guardrails и row limits.",
      ],
    ),
    workflow: localizedLines(
      [
        "Write a single SELECT statement only.",
        "Use `analytics_queries` or `analytics_usefulness_feedback` views for exploratory queries.",
        "Start with low row limits and export only when the result shape is correct.",
      ],
      [
        "Пишите только один SELECT-запрос.",
        "Используйте `analytics_queries` или `analytics_usefulness_feedback` views для exploratory queries.",
        "Начинайте с небольших row limits и экспортируйте только после проверки результата.",
      ],
    ),
    examples: [
      example(
        "sql-example-1",
        "Investigating not-useful feedback by product",
        "Исследование not-useful feedback по продукту",
        [
          "Select from `analytics_usefulness_feedback` grouped by product_id and rating.",
          "Compare negative reason codes with zero-result clusters.",
          "Export the table if you need to share a weekly report.",
        ],
        [
          "Сделайте выборку из `analytics_usefulness_feedback` с группировкой по product_id и rating.",
          "Сравните negative reason codes с zero-result clusters.",
          "Экспортируйте таблицу, если нужно поделиться недельным отчетом.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-sql-explorer-main",
        "admin-sql-explorer",
        "SQL Explorer section with read-only query and CSV export controls.",
        "Раздел SQL Explorer с read-only query и CSV export controls.",
        "Use this page only when built-in analytics slices are not enough.",
        "Используйте эту страницу только тогда, когда встроенных analytics slices недостаточно.",
      ),
    ],
    relatedArticleIds: ["admin-sql-explorer-query-workflow", "admin-analytics", "admin-logs-traces"],
    keywords: ["sql", "analytics_queries", "csv export", "read only"],
    adminSectionIds: ["sql-explorer-read-only"],
  },
  {
    id: "admin-sql-explorer-query-workflow",
    slug: "admin-sql-explorer-query-workflow",
    topic: "Admin Console",
    routePath: "/#sql-explorer-read-only",
    entryLabel: localizedText("SQL Explorer: Query Workflow", "SQL Explorer: сценарий запросов"),
    title: localizedText(
      "Admin Console: SQL Query and CSV Export Workflow",
      "Админка: workflow SQL-запросов и CSV export",
    ),
    summary: localizedText(
      "This article explains how to use presets, saved views, preview runs, and CSV export safely when the standard analytics surfaces are not enough.",
      "Эта статья объясняет, как безопасно использовать presets, saved views, preview runs и CSV export, когда стандартных analytics surfaces уже недостаточно.",
    ),
    purpose: localizedLines(
      [
        "Reinforce the rule that this surface is for read-only diagnostics only.",
        "Show the correct order: preset or saved view, preview, then export.",
        "Prevent expensive or ambiguous queries when a simple slice would do.",
      ],
      [
        "Укрепить правило, что этот интерфейс предназначен только для read-only диагностики.",
        "Показать правильный порядок: preset или saved view, preview, затем export.",
        "Предотвращать дорогие или неоднозначные запросы там, где хватило бы простого slice.",
      ],
    ),
    workflow: localizedLines(
      [
        "Start from a quality preset or saved SQL view when possible.",
        "Run SELECT first and inspect row_count, truncation, and latency.",
        "Export CSV only after the preview proves the shape and volume are correct.",
      ],
      [
        "По возможности начинайте с quality preset или saved SQL view.",
        "Сначала запускайте SELECT и проверяйте row_count, truncation и latency.",
        "Экспортируйте CSV только после того, как preview подтвердил правильную форму и объем данных.",
      ],
    ),
    examples: [
      example(
        "sql-explorer-workflow-example-1",
        "Exporting a zero-result slice",
        "Экспорт zero-result slice",
        [
          "Apply a preset or saved view close to the target question.",
          "Preview the result with Run SELECT.",
          "Only then export CSV for offline analysis or sharing.",
        ],
        [
          "Примените preset или saved view, близкий к целевому вопросу.",
          "Предпросмотрите результат через Run SELECT.",
          "И только потом делайте CSV export для offline analysis или sharing.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-sql-explorer-query-workflow-main",
        "admin-sql-explorer-query-workflow",
        "SQL Explorer query editor, presets, and export controls.",
        "SQL Explorer query editor, presets и export controls.",
        "Use this panel for safe ad-hoc diagnostics when dashboards are not enough.",
        "Используйте эту панель для безопасной ad-hoc диагностики, когда дашбордов недостаточно.",
      ),
    ],
    relatedArticleIds: ["admin-sql-explorer", "admin-analytics"],
    keywords: ["sql workflow", "saved sql", "csv export", "select preview"],
    adminSectionIds: ["sql-explorer-read-only"],
  },
  {
    id: "admin-logs-traces",
    slug: "admin-logs-traces",
    topic: "Admin Console",
    routePath: "/#logs-traces",
    entryLabel: localizedText("Logs & Traces", "Логи и трассировка"),
    title: localizedText(
      "Admin Console: Logs, Traces, and Operational Audit Trail",
      "Админка: логи, трассировка и operational audit trail",
    ),
    summary: localizedText(
      "This page shows operational actions, observability links, and request identifiers needed to trace failures across the control plane.",
      "Эта страница показывает operational actions, observability links и request identifiers, которые нужны для трассировки проблем по control plane.",
    ),
    purpose: localizedLines(
      [
        "Correlate request_id with admin actions and observability surfaces.",
        "Jump into Grafana, Loki, or Tempo if those drill-down links are configured.",
        "Review recent operational actions for auditing and incident response.",
      ],
      [
        "Связывать request_id с admin actions и observability surfaces.",
        "Переходить в Grafana, Loki или Tempo, если настроены drill-down links.",
        "Просматривать recent operational actions для аудита и incident response.",
      ],
    ),
    workflow: localizedLines(
      [
        "Start with the request_id from the failing operation or event.",
        "Use the audit trail to see who changed what and when.",
        "Escalate into external observability tools only after you have identified the key request ids.",
      ],
      [
        "Начинайте с request_id проблемной операции или события.",
        "Используйте audit trail, чтобы понять кто, что и когда изменил.",
        "Переходите во внешние observability tools только после того, как определили ключевые request ids.",
      ],
    ),
    examples: [
      example(
        "logs-example-1",
        "Tracing a failed publish",
        "Трассировка failed publish",
        [
          "Open the related request_id from Critical Events or Ingestion Jobs.",
          "Review the action timeline in Logs & Traces.",
          "If external tracing is enabled, follow the drill-down link into Tempo or Loki.",
        ],
        [
          "Откройте связанный request_id из Critical Events или Ingestion Jobs.",
          "Просмотрите timeline действий в Logs & Traces.",
          "Если включена внешняя трассировка, перейдите по drill-down link в Tempo или Loki.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-logs-traces-main",
        "admin-logs-traces",
        "Logs & Traces section with audit trail and observability drill-down.",
        "Раздел Logs & Traces с audit trail и observability drill-down.",
        "Use this screen to connect UI actions to request ids and external traces.",
        "Используйте этот экран для связи UI-действий с request ids и внешними traces.",
      ),
    ],
    relatedArticleIds: ["admin-critical-events", "admin-health", "admin-sql-explorer"],
    keywords: ["logs", "traces", "audit trail", "request id", "tempo", "loki"],
    adminSectionIds: ["logs-traces"],
  },
  {
    id: "admin-config-history-rollback",
    slug: "admin-config-history-rollback",
    topic: "Admin Console",
    routePath: "/#config-history-rollback",
    entryLabel: localizedText("Config History & Rollback", "История конфигов и rollback"),
    title: localizedText(
      "Admin Console: Config History and Safe Rollback",
      "Админка: история конфигов и безопасный rollback",
    ),
    summary: localizedText(
      "This page keeps the configuration change ledger and allows safe rollback of product-scoped settings with preview and audit continuity.",
      "Эта страница хранит журнал изменений конфигурации и позволяет безопасно откатывать product-scoped settings с сохранением preview и audit continuity.",
    ),
    purpose: localizedLines(
      [
        "Review who changed a configuration, when, and why.",
        "Rollback a problematic change without editing raw config files by hand.",
        "Keep rollback evidence for future troubleshooting.",
      ],
      [
        "Понимать, кто изменил конфигурацию, когда и почему.",
        "Откатывать проблемные изменения без ручного редактирования raw config files.",
        "Сохранять rollback evidence для будущего troubleshooting.",
      ],
    ),
    workflow: localizedLines(
      [
        "Filter config history by product and config scope.",
        "Review before/after payloads before rolling back.",
        "Enter a rollback reason so the audit trail remains operationally useful.",
      ],
      [
        "Фильтруйте config history по product и config scope.",
        "Перед rollback просматривайте before/after payloads.",
        "Указывайте причину rollback, чтобы audit trail оставался операционно полезным.",
      ],
    ),
    examples: [
      example(
        "config-history-example-1",
        "Reverting an aggressive retrieval policy",
        "Откат слишком агрессивной retrieval policy",
        [
          "Open the latest change for the affected product.",
          "Compare the before and after thresholds.",
          "Rollback the change if usefulness and analytics degraded after the update.",
        ],
        [
          "Откройте последнее изменение для затронутого продукта.",
          "Сравните старые и новые thresholds.",
          "Выполните rollback, если после обновления ухудшились usefulness и analytics.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-config-history-main",
        "admin-config-history-rollback",
        "Config History & Rollback section with change ledger and rollback actions.",
        "Раздел Config History & Rollback с change ledger и rollback actions.",
        "Use this page to reverse a bad settings change without touching raw config files.",
        "Используйте эту страницу, чтобы отменить плохое изменение настроек без редактирования raw config files.",
      ),
    ],
    relatedArticleIds: ["admin-retrieval-settings", "admin-api-keys-access"],
    keywords: ["config history", "rollback", "audit", "before after"],
    adminSectionIds: ["config-history-rollback"],
  },
  {
    id: "admin-quality-reviews",
    slug: "admin-quality-reviews",
    topic: "Admin Console",
    routePath: "/#quality-reviews",
    entryLabel: localizedText("Quality Reviews", "Проверки качества"),
    title: localizedText(
      "Admin Console: Quality Reviews and Publish Governance",
      "Админка: проверки качества и publish-governance",
    ),
    summary: localizedText(
      "This page manages semantic review runs, approval policies, sampled items, and publish-governance decisions for converted content.",
      "Эта страница управляет semantic review runs, approval policies, sampled items и publish-governance решениями для преобразованного контента.",
    ),
    purpose: localizedLines(
      [
        "Inspect review scores before allowing publish for sensitive changes.",
        "Switch between human approval and auto-approve policies per product.",
        "Track blocking findings and approval history in one place.",
      ],
      [
        "Проверять review scores до разрешения publish для чувствительных изменений.",
        "Переключать human approval и auto-approve policies по продуктам.",
        "Отслеживать blocking findings и историю approvals в одном месте.",
      ],
    ),
    workflow: localizedLines(
      [
        "Select the target product and run a review when new content is ready.",
        "Inspect blocking findings and score matrix first.",
        "Approve or reject only after reading the artifact and policy context.",
      ],
      [
        "Выберите нужный продукт и запустите review, когда новый контент готов.",
        "Сначала изучите blocking findings и score matrix.",
        "Одобряйте или отклоняйте только после чтения artifact и policy context.",
      ],
    ),
    examples: [
      example(
        "quality-reviews-example-1",
        "Handling a borderline review run",
        "Обработка пограничного review run",
        [
          "If the score is close to the threshold, inspect sampled items manually.",
          "Check whether the issue is isolated or systemic.",
          "Keep approval mode conservative for products with frequent structural change.",
        ],
        [
          "Если score близок к threshold, вручную просмотрите sampled items.",
          "Определите, локальная это проблема или системная.",
          "Для продуктов с частыми структурными изменениями сохраняйте консервативный approval mode.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-quality-reviews-main",
        "admin-quality-reviews",
        "Quality Reviews section with run list, policies, and approval actions.",
        "Раздел Quality Reviews с run list, policies и approval actions.",
        "Use this page to decide whether conversion output is safe enough to publish.",
        "Используйте эту страницу, чтобы определить, достаточно ли безопасен conversion output для publish.",
      ),
    ],
    relatedArticleIds: [
      "admin-quality-reviews-policy",
      "admin-quality-reviews-runs",
      "admin-quality-reviews-run-diff",
      "admin-ingestion-jobs",
    ],
    keywords: ["quality reviews", "approval", "semantic review", "publish governance"],
    adminSectionIds: ["quality-reviews"],
  },
  {
    id: "admin-quality-reviews-policy",
    slug: "admin-quality-reviews-policy",
    topic: "Admin Console",
    routePath: "/#quality-reviews",
    entryLabel: localizedText("Quality Reviews: Policy", "Проверки качества: policy"),
    title: localizedText(
      "Admin Console: Review Policy and Presets",
      "Админка: review policy и presets",
    ),
    summary: localizedText(
      "This article explains how sampling, threshold score, and approval mode work together, and when presets should be applied instead of hand-editing every field.",
      "Эта статья объясняет, как sample size, threshold score и approval mode работают вместе и когда нужно применять presets вместо ручного редактирования каждого поля.",
    ),
    purpose: localizedLines(
      [
        "Explain the operational effect of sample size and threshold changes.",
        "Show when human approval should remain mandatory.",
        "Keep policy changes reviewable and consistent across products.",
      ],
      [
        "Объяснить операционный эффект изменений sample size и threshold.",
        "Показать, когда human approval должен оставаться обязательным.",
        "Сохранять policy changes проверяемыми и согласованными между продуктами.",
      ],
    ),
    workflow: localizedLines(
      [
        "Review the current product behavior first.",
        "Use a preset when it already matches the needed governance stance.",
        "If editing manually, change one variable at a time and watch subsequent runs before changing another.",
      ],
      [
        "Сначала проверьте текущее поведение продукта.",
        "Используйте preset, если он уже соответствует нужной governance stance.",
        "При ручном редактировании меняйте по одной переменной и смотрите на последующие runs до следующего изменения.",
      ],
    ),
    examples: [
      example(
        "quality-policy-example-1",
        "Tightening policy for a structurally unstable product",
        "Ужесточение policy для структурно нестабильного продукта",
        [
          "Increase the sample size before switching to auto-approve.",
          "Keep human approval if layout or conversion quality has been changing recently.",
          "Record the reason so later reviewers understand why the preset changed.",
        ],
        [
          "Увеличьте sample size до перехода на auto-approve.",
          "Сохраняйте human approval, если layout или conversion quality недавно менялись.",
          "Записывайте причину, чтобы последующие reviewers понимали, почему preset изменился.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-quality-reviews-policy-main",
        "admin-quality-reviews-policy",
        "Quality review policy and preset controls.",
        "Элементы quality review policy и presets.",
        "Use this panel to define how strict the semantic review gate should be.",
        "Используйте эту панель, чтобы определить строгость semantic review gate.",
      ),
    ],
    relatedArticleIds: ["admin-quality-reviews", "admin-quality-reviews-runs"],
    keywords: ["review policy", "sample size", "threshold", "approval mode", "preset"],
    adminSectionIds: ["quality-reviews"],
  },
  {
    id: "admin-quality-reviews-runs",
    slug: "admin-quality-reviews-runs",
    topic: "Admin Console",
    routePath: "/#quality-reviews",
    entryLabel: localizedText("Quality Reviews: Runs", "Проверки качества: runs"),
    title: localizedText(
      "Admin Console: Review Runs and Batch Decisions",
      "Админка: review runs и batch decisions",
    ),
    summary: localizedText(
      "Use this article to work with semantic review runs, select the correct run package, and apply approve or reject decisions without losing governance context.",
      "Используйте эту статью, чтобы работать с semantic review runs, выбирать нужный run package и применять approve или reject решения без потери governance context.",
    ),
    purpose: localizedLines(
      [
        "Explain which run should be opened first and how status affects next actions.",
        "Show safe usage of batch approve and batch reject.",
        "Keep reviewers from treating borderline runs as routine approvals.",
      ],
      [
        "Объяснить, какой run нужно открывать первым и как status влияет на следующие действия.",
        "Показать безопасное использование batch approve и batch reject.",
        "Не допускать превращения пограничных runs в рутинные approvals.",
      ],
    ),
    workflow: localizedLines(
      [
        "Open the most recent relevant run first.",
        "Read the score, threshold, and status before selecting multiple runs.",
        "Batch approve only homogeneous runs; reject with a reason when findings are still unresolved.",
      ],
      [
        "Сначала открывайте самый свежий релевантный run.",
        "Читайте score, threshold и status до выбора нескольких runs.",
        "Используйте batch approve только для однородных runs; отклоняйте с причиной, если findings еще не устранены.",
      ],
    ),
    examples: [
      example(
        "quality-runs-example-1",
        "Batch approve only clearly green runs",
        "Batch approve только явно зеленых runs",
        [
          "Select runs that share the same healthy score pattern and no blocking findings.",
          "Keep borderline runs out of the batch and inspect them one by one.",
          "Use reject reason text to preserve why a run stayed blocked.",
        ],
        [
          "Выбирайте runs с одинаково здоровым score pattern и без blocking findings.",
          "Не включайте пограничные runs в batch и проверяйте их по одному.",
          "Используйте reject reason text, чтобы сохранить причину, по которой run остался заблокированным.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-quality-reviews-runs-main",
        "admin-quality-reviews-runs",
        "Quality review runs list with selection and batch actions.",
        "Список quality review runs с selection и batch actions.",
        "Use this panel to triage review runs before approving or rejecting them.",
        "Используйте эту панель для triage review runs до approve или reject.",
      ),
    ],
    relatedArticleIds: ["admin-quality-reviews", "admin-quality-reviews-policy"],
    keywords: ["review runs", "batch approve", "batch reject", "semantic review"],
    adminSectionIds: ["quality-reviews"],
  },
  {
    id: "admin-quality-reviews-run-diff",
    slug: "admin-quality-reviews-run-diff",
    topic: "Admin Console",
    routePath: "/#quality-reviews",
    entryLabel: localizedText("Quality Reviews: Run Diff", "Проверки качества: run diff"),
    title: localizedText(
      "Admin Console: Review Run Diff and Evidence Comparison",
      "Админка: review run diff и сравнение evidence",
    ),
    summary: localizedText(
      "This article explains how to compare one review run against another to prove that quality really improved before publish or after a policy change.",
      "Эта статья объясняет, как сравнивать один review run с другим, чтобы доказать реальное улучшение качества до publish или после изменения policy.",
    ),
    purpose: localizedLines(
      [
        "Show how baseline and target runs should be selected.",
        "Use diff output as evidence when deciding whether a change helped or hurt.",
        "Prevent subjective approvals based on memory instead of comparison data.",
      ],
      [
        "Показать, как выбирать baseline и target runs.",
        "Использовать diff output как evidence при решении, улучшило ли изменение качество или ухудшило.",
        "Предотвращать субъективные approvals, основанные на памяти вместо comparison data.",
      ],
    ),
    workflow: localizedLines(
      [
        "Choose a known-good baseline run first.",
        "Compare it with the newest candidate run after a content or policy change.",
        "Use the diff result together with the current run status before approving publish.",
      ],
      [
        "Сначала выберите known-good baseline run.",
        "Сравните его с самым новым candidate run после изменения контента или policy.",
        "Используйте diff result вместе с текущим status run до approve publish.",
      ],
    ),
    examples: [
      example(
        "quality-run-diff-example-1",
        "Proving that a policy change improved reviews",
        "Доказательство, что изменение policy улучшило reviews",
        [
          "Compare the newest run against the last accepted baseline.",
          "Look for better score distribution and fewer blocking findings.",
          "Do not rely on a single headline score if the diff shows new regressions elsewhere.",
        ],
        [
          "Сравните новый run с последним принятым baseline.",
          "Ищите лучшее распределение score и меньше blocking findings.",
          "Не полагайтесь только на один headline score, если diff показывает новые regressions в других местах.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "admin-quality-reviews-run-diff-main",
        "admin-quality-reviews-run-diff",
        "Review run diff controls and comparison output.",
        "Элементы review run diff и comparison output.",
        "Use this panel to compare two review runs before changing publish decisions.",
        "Используйте эту панель для сравнения двух review runs до изменения publish decisions.",
      ),
    ],
    relatedArticleIds: ["admin-quality-reviews", "admin-quality-reviews-runs"],
    keywords: ["run diff", "baseline run", "comparison", "quality evidence"],
    adminSectionIds: ["quality-reviews"],
  },
  {
    id: "public-status",
    slug: "public-status",
    topic: "Public Pages",
    routePath: "/status",
    entryLabel: localizedText("Public Status", "Публичный статус"),
    title: localizedText(
      "Public Status Page",
      "Публичная страница статуса",
    ),
    summary: localizedText(
      "This page is for external developers who need to confirm public ADCS availability and MCP readiness before relying on it in an IDE or agent workflow.",
      "Эта страница предназначена для внешних разработчиков, которым нужно подтвердить доступность публичного ADCS и MCP readiness перед использованием в IDE или agent workflow.",
    ),
    purpose: localizedLines(
      [
        "Show overall public readiness without exposing private admin-only controls.",
        "Allow filtering by product_id and repo_id for large multi-product estates.",
        "Explain the currently active runtime topology and service mix at a public level.",
      ],
      [
        "Показывать общий public readiness без раскрытия приватных admin-only controls.",
        "Позволять фильтрацию по product_id и repo_id для больших multi-product estates.",
        "Объяснять текущую runtime topology и service mix на публичном уровне.",
      ],
    ),
    workflow: localizedLines(
      [
        "Open the page and check system readiness.",
        "Apply product/repo filters if you care about one service only.",
        "Use the coverage table to verify that the target docs/apiref service is ready for MCP.",
      ],
      [
        "Откройте страницу и проверьте system readiness.",
        "Примените product/repo filters, если вас интересует только один сервис.",
        "Используйте coverage table, чтобы подтвердить готовность нужного docs/apiref сервиса для MCP.",
      ],
    ),
    examples: [
      example(
        "public-status-example-1",
        "Before configuring a client IDE",
        "Перед настройкой клиентской IDE",
        [
          "Search for your product_id in the filter box.",
          "Confirm that the repo row is MCP-ready.",
          "Only then move to the integrations page to copy the config snippet.",
        ],
        [
          "Введите product_id в фильтр.",
          "Подтвердите, что строка нужного repo имеет MCP-ready статус.",
          "Только после этого переходите на страницу integrations за конфигом.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "public-status-main",
        "public-status",
        "Public status page with service readiness cards and coverage table.",
        "Публичная страница статуса с readiness cards и coverage table.",
        "External developers use this page before connecting an MCP client.",
        "Внешние разработчики используют эту страницу перед подключением MCP-клиента.",
      ),
    ],
    relatedArticleIds: ["public-integrations", "admin-health"],
    keywords: ["public status", "mcp ready", "coverage", "developers"],
  },
  {
    id: "public-integrations",
    slug: "public-integrations",
    topic: "Public Pages",
    routePath: "/integrations",
    entryLabel: localizedText("MCP Config Export", "Экспорт MCP-конфига"),
    title: localizedText(
      "Public Integrations and MCP Config Export",
      "Публичные интеграции и экспорт MCP-конфигов",
    ),
    summary: localizedText(
      "This page provides ready-to-paste client configuration snippets for Cursor, Claude Desktop, Qwen Code, and VS Code, plus a snippet explorer for integration examples.",
      "Эта страница предоставляет готовые к вставке конфиги для Cursor, Claude Desktop, Qwen Code и VS Code, а также snippet explorer с примерами интеграции.",
    ),
    purpose: localizedLines(
      [
        "Avoid handwritten MCP client JSON or command-line parameters.",
        "Keep transport choice explicit and visible.",
        "Show snippet examples that match the selected product, SDK language, version, and source kind.",
      ],
      [
        "Избегать ручного написания MCP client JSON или command-line параметров.",
        "Делать выбор transport явным и понятным.",
        "Показывать примеры snippets, соответствующие выбранному product, SDK language, version и source kind.",
      ],
    ),
    workflow: localizedLines(
      [
        "Enter product_id and optional language/version filters.",
        "Keep `streamable-http` unless your client explicitly needs SSE.",
        "Copy the generated snippet for the target IDE and test it against the public status page.",
      ],
      [
        "Введите product_id и при необходимости language/version filters.",
        "Сохраняйте `streamable-http`, если вашему клиенту явно не нужен SSE.",
        "Скопируйте сгенерированный snippet для нужной IDE и проверьте его через public status page.",
      ],
    ),
    examples: [
      example(
        "public-integrations-example-1",
        "Cursor setup",
        "Настройка Cursor",
        [
          "Generate config for the target product.",
          "Copy the Cursor snippet exactly as shown.",
          "Enable the MCP server in the IDE and test a product-specific query.",
        ],
        [
          "Сгенерируйте конфиг для нужного продукта.",
          "Скопируйте Cursor snippet без ручных изменений.",
          "Включите MCP server в IDE и протестируйте product-specific query.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "public-integrations-main",
        "public-integrations",
        "Integrations page with product filters and copy-ready MCP client snippets.",
        "Страница integrations с product filters и готовыми MCP client snippets.",
        "Use this page to generate and copy the exact client config for your AI IDE.",
        "Используйте эту страницу для генерации и копирования точного client config для вашей AI IDE.",
      ),
    ],
    relatedArticleIds: ["public-status", "onboarding-overview"],
    keywords: ["integrations", "cursor", "claude", "qwen", "vscode", "config export"],
  },
  {
    id: "onboarding-overview",
    slug: "onboarding-overview",
    topic: "Onboarding",
    routePath: "/onboarding",
    entryLabel: localizedText("Onboarding Knowledge Base", "База знаний по onboarding"),
    title: localizedText(
      "Onboarding Knowledge Base",
      "База знаний по onboarding",
    ),
    summary: localizedText(
      "This article explains how new product families are onboarded into ADCS, how repository layout is understood, and how validate-only plus publish should be staged.",
      "Эта статья объясняет, как новые product families подключаются к ADCS, как определяется структура repository layout и как нужно поэтапно выполнять validate-only и publish.",
    ),
    purpose: localizedLines(
      [
        "Explain the end-to-end onboarding flow for product owners and operators.",
        "Connect manual research, admin UI onboarding, layout detection, validate-only, and publish steps.",
        "Show where review artifacts and screenshot-driven documentation fit into the process.",
      ],
      [
        "Объяснить полный onboarding flow для product owners и операторов.",
        "Связать manual research, admin UI onboarding, layout detection, validate-only и publish steps.",
        "Показать, где в процессе находятся review artifacts и screenshot-driven документация.",
      ],
    ),
    workflow: localizedLines(
      [
        "Register the repositories and product metadata.",
        "Run layout detection and validate-only before any publish.",
        "Review artifacts, quality gates, and health state.",
        "Publish only after the target scope is operationally healthy.",
      ],
      [
        "Зарегистрируйте repositories и product metadata.",
        "Запустите layout detection и validate-only до любого publish.",
        "Проверьте artifacts, quality gates и состояние health.",
        "Публикуйте только после того, как target scope стал операционно здоровым.",
      ],
    ),
    examples: [
      example(
        "onboarding-overview-example-1",
        "Manual + UI workflow",
        "Комбинация manual + UI workflow",
        [
          "Research layout and conversion strategy first.",
          "Then use the admin UI to register the product and run bootstrap automation.",
          "Keep review, quality, and health evidence before go-live.",
        ],
        [
          "Сначала исследуйте layout и conversion strategy.",
          "Затем используйте admin UI для регистрации продукта и запуска bootstrap automation.",
          "Сохраняйте review, quality и health evidence до выхода в go-live.",
        ],
      ),
    ],
    screenshots: [
      screenshot(
        "onboarding-overview-main",
        "onboarding-overview",
        "Onboarding knowledge base page with left navigation and article content.",
        "Страница базы знаний onboarding с левым меню и содержимым статьи.",
        "Use this page when preparing a new product family or training a product owner.",
        "Используйте эту страницу при подготовке нового product family или обучении product owner.",
      ),
    ],
    relatedArticleIds: ["admin-ingestion-jobs", "admin-language-registries", "public-integrations"],
    keywords: ["onboarding", "layout detection", "validate only", "publish", "product family"],
  },
] as const;

export const HOW_TO_ARTICLE_BY_ID = new Map(
  HOW_TO_ARTICLES.map((article) => [article.id, article]),
);

export const HOW_TO_TOPICS: readonly HowToTopic[] = [
  "Admin Console",
  "Public Pages",
  "Onboarding",
] as const;

export const ADMIN_SECTION_HOW_TO_MAP: Readonly<Record<string, HowToArticleId>> = {
  health: "admin-health",
  "runtime-guard": "admin-health-runtime-guard",
  "indexes-topology": "admin-health-dependencies-topology",
  "content-coverage": "admin-health-content-coverage",
  "ingestion-jobs": "admin-ingestion-jobs",
  snapshots: "admin-snapshots",
  "critical-events": "admin-critical-events",
  "language-registries": "admin-language-registries",
  "api-keys-access": "admin-api-keys-access",
  "retrieval-settings": "admin-retrieval-settings",
  analytics: "admin-analytics",
  "sql-explorer-read-only": "admin-sql-explorer",
  "logs-traces": "admin-logs-traces",
  "config-history-rollback": "admin-config-history-rollback",
  "quality-reviews": "admin-quality-reviews",
} as const;

export const ADMIN_SUBSECTION_HOW_TO_MAP = {
  health: {
    runtimeGuard: "admin-health-runtime-guard",
    dependenciesTopology: "admin-health-dependencies-topology",
    contentCoverage: "admin-health-content-coverage",
  },
  ingestionJobs: {
    onboarding: "admin-ingestion-onboarding",
    execution: "admin-ingestion-execution",
    reviewWorkspace: "admin-ingestion-review-workspace",
  },
  snapshots: {
    rollback: "admin-snapshots-rollback",
    cleanup: "admin-snapshots-cleanup",
  },
  criticalEvents: {
    lifecycle: "admin-critical-events-lifecycle",
    history: "admin-critical-events-history",
  },
  languageRegistries: {
    dictionaries: "admin-language-registries-dictionaries",
    aliases: "admin-language-registries-aliases",
  },
  apiKeysAccess: {
    provisioning: "admin-api-keys-provisioning",
    governance: "admin-api-keys-governance",
  },
  analytics: {
    capacityForecast: "admin-analytics-capacity-forecast",
    usefulnessFeedback: "admin-analytics-usefulness-feedback",
    zeroResultCockpit: "admin-analytics-zero-result-cockpit",
  },
  sqlExplorer: {
    queryWorkflow: "admin-sql-explorer-query-workflow",
  },
  qualityReviews: {
    policy: "admin-quality-reviews-policy",
    runs: "admin-quality-reviews-runs",
    runDiff: "admin-quality-reviews-run-diff",
  },
} as const satisfies Record<string, Record<string, HowToArticleId>>;

export const STANDALONE_PAGE_HOW_TO_MAP: Readonly<Record<string, HowToArticleId>> = {
  status: "public-status",
  integrations: "public-integrations",
  onboarding: "onboarding-overview",
} as const;

export function resolveHowToArticle(articleId: string | null | undefined): HowToArticle | null {
  if (!articleId) {
    return null;
  }
  return HOW_TO_ARTICLE_BY_ID.get(articleId as HowToArticleId) ?? null;
}

export function buildHowToHref(
  articleId: HowToArticleId,
  localeOrOptions?: HowToLocale | BuildHowToHrefOptions,
  maybeOptions?: BuildHowToHrefOptions,
): string {
  const options =
    typeof localeOrOptions === "string"
      ? { ...(maybeOptions ?? {}), locale: localeOrOptions }
      : (localeOrOptions ?? {});
  const params = new URLSearchParams({
    article: articleId,
  });
  if (options.locale) {
    params.set("lang", options.locale);
  }
  if (options.sourceSectionId) {
    params.set("from", options.sourceSectionId);
  }
  if (options.sourceLabel) {
    params.set("source_label", options.sourceLabel);
  }
  if (options.returnTo) {
    params.set("return_to", options.returnTo);
  }
  return `/howto?${params.toString()}`;
}

export function listHowToArticlesByTopic(topic: HowToTopic): HowToArticle[] {
  return HOW_TO_ARTICLES.filter((article) => article.topic === topic);
}

export function listHowToArticlesByRoutePath(routePath: string): HowToArticle[] {
  return HOW_TO_ARTICLES.filter((article) => article.routePath === routePath);
}

export function articleHasLocaleGaps(article: HowToArticle, locale: HowToLocale): boolean {
  if (locale === "en") {
    return false;
  }

  const localizedTextMissing = (value: LocalizedText): boolean => !value[locale].trim();
  const localizedLinesMissing = (value: LocalizedLines): boolean =>
    value[locale].length === 0 || value[locale].some((line) => !line.trim());

  return (
    localizedTextMissing(article.entryLabel) ||
    localizedTextMissing(article.title) ||
    localizedTextMissing(article.summary) ||
    localizedLinesMissing(article.purpose) ||
    localizedLinesMissing(article.workflow) ||
    (article.callouts ?? []).some(
      (item) => localizedTextMissing(item.title) || localizedLinesMissing(item.body),
    ) ||
    (article.commands ?? []).some(
      (item) =>
        localizedTextMissing(item.label) || localizedTextMissing(item.description),
    ) ||
    article.examples.some(
      (item) => localizedTextMissing(item.title) || localizedLinesMissing(item.bullets),
    ) ||
    article.screenshots.some(
      (item) => localizedTextMissing(item.alt) || localizedTextMissing(item.caption),
    )
  );
}

export function searchHowToArticles(
  query: string,
  articles: readonly HowToArticle[] = HOW_TO_ARTICLES,
): HowToArticle[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return [...articles];
  }
  return articles.filter((article) => {
    const haystack = [
      article.slug,
      article.title.en,
      article.title.ru,
      article.summary.en,
      article.summary.ru,
      article.keywords.join(" "),
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(normalizedQuery);
  });
}

function mergeLocalizedText(
  baseValue: LocalizedText,
  overrideValue: LocalizedText | undefined,
): LocalizedText {
  if (!overrideValue) {
    return baseValue;
  }
  return {
    en: overrideValue.en.trim() || baseValue.en,
    ru: overrideValue.ru.trim() || baseValue.ru,
  };
}

function mergeLocalizedLines(
  baseValue: LocalizedLines,
  overrideValue: LocalizedLines | undefined,
): LocalizedLines {
  if (!overrideValue) {
    return baseValue;
  }
  return {
    en: overrideValue.en.length > 0 ? overrideValue.en : baseValue.en,
    ru: overrideValue.ru.length > 0 ? overrideValue.ru : baseValue.ru,
  };
}

function normalizeCollectionOverride<T>(
  overrideItems: readonly T[] | undefined,
): readonly T[] | null {
  if (!overrideItems || overrideItems.length === 0) {
    return null;
  }
  return overrideItems;
}

function mergeCallouts(
  baseItems: readonly HowToCallout[] | undefined,
  overrideItems: readonly HowToCallout[] | undefined,
): HowToCallout[] | undefined {
  const resolvedOverride = normalizeCollectionOverride(overrideItems);
  if (!resolvedOverride) {
    return baseItems ? [...baseItems] : undefined;
  }
  return resolvedOverride.map((item, index) => {
    const baseItem = baseItems?.[index];
    return {
      id: item.id,
      level: item.level,
      title: mergeLocalizedText(baseItem?.title ?? localizedText("", ""), item.title),
      body: mergeLocalizedLines(baseItem?.body ?? localizedLines([], []), item.body),
    };
  });
}

function mergeCommands(
  baseItems: readonly HowToCommand[] | undefined,
  overrideItems: readonly HowToCommand[] | undefined,
): HowToCommand[] | undefined {
  const resolvedOverride = normalizeCollectionOverride(overrideItems);
  if (!resolvedOverride) {
    return baseItems ? [...baseItems] : undefined;
  }
  return resolvedOverride.map((item, index) => {
    const baseItem = baseItems?.[index];
    return {
      id: item.id,
      command: item.command.trim() || baseItem?.command || "",
      label: mergeLocalizedText(baseItem?.label ?? localizedText("", ""), item.label),
      description: mergeLocalizedText(
        baseItem?.description ?? localizedText("", ""),
        item.description,
      ),
    };
  });
}

function mergeExamples(
  baseItems: readonly HowToExample[],
  overrideItems: readonly HowToExample[] | undefined,
): HowToExample[] {
  const resolvedOverride = normalizeCollectionOverride(overrideItems);
  if (!resolvedOverride) {
    return [...baseItems];
  }
  return resolvedOverride.map((item, index) => {
    const baseItem = baseItems[index];
    return {
      id: item.id,
      title: mergeLocalizedText(baseItem?.title ?? localizedText("", ""), item.title),
      bullets: mergeLocalizedLines(baseItem?.bullets ?? localizedLines([], []), item.bullets),
    };
  });
}

function mergeScreenshots(
  baseItems: readonly HowToScreenshot[],
  overrideItems: readonly HowToScreenshot[] | undefined,
): HowToScreenshot[] {
  const resolvedOverride = normalizeCollectionOverride(overrideItems);
  if (!resolvedOverride) {
    return [...baseItems];
  }
  return resolvedOverride.map((item, index) => {
    const baseItem = baseItems[index];
    return {
      id: item.id,
      src: item.src.trim() || baseItem?.src || "",
      alt: mergeLocalizedText(baseItem?.alt ?? localizedText("", ""), item.alt),
      caption: mergeLocalizedText(baseItem?.caption ?? localizedText("", ""), item.caption),
    };
  });
}

export function buildHowToOverridePayload(
  article: HowToArticle,
): HowToArticleOverridePayload {
  return {
    entry_label: { ...article.entryLabel },
    title: { ...article.title },
    summary: { ...article.summary },
    purpose: {
      en: [...article.purpose.en],
      ru: [...article.purpose.ru],
    },
    workflow: {
      en: [...article.workflow.en],
      ru: [...article.workflow.ru],
    },
    callouts: [...(article.callouts ?? [])].map((item) => ({
      id: item.id,
      level: item.level,
      title: { ...item.title },
      body: {
        en: [...item.body.en],
        ru: [...item.body.ru],
      },
    })),
    commands: [...(article.commands ?? [])].map((item) => ({
      id: item.id,
      command: item.command,
      label: { ...item.label },
      description: { ...item.description },
    })),
    examples: article.examples.map((item) => ({
      id: item.id,
      title: { ...item.title },
      bullets: {
        en: [...item.bullets.en],
        ru: [...item.bullets.ru],
      },
    })),
    screenshots: article.screenshots.map((item) => ({
      id: item.id,
      src: item.src,
      alt: { ...item.alt },
      caption: { ...item.caption },
    })),
  };
}

export function applyHowToOverride(
  article: HowToArticle,
  overridePayload: HowToArticleOverridePayload | null | undefined,
): HowToArticle {
  if (!overridePayload) {
    return article;
  }
  return {
    ...article,
    entryLabel: mergeLocalizedText(article.entryLabel, overridePayload.entry_label),
    title: mergeLocalizedText(article.title, overridePayload.title),
    summary: mergeLocalizedText(article.summary, overridePayload.summary),
    purpose: mergeLocalizedLines(article.purpose, overridePayload.purpose),
    workflow: mergeLocalizedLines(article.workflow, overridePayload.workflow),
    callouts: mergeCallouts(article.callouts, overridePayload.callouts),
    commands: mergeCommands(article.commands, overridePayload.commands),
    examples: mergeExamples(article.examples, overridePayload.examples),
    screenshots: mergeScreenshots(article.screenshots, overridePayload.screenshots),
  };
}
