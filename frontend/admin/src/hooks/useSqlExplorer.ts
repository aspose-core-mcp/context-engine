"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import type { SqlSavedView } from "@/components/admin-console.types";
import { SQL_VIEWS_STORAGE_KEY, SQL_QUALITY_PRESETS } from "@/components/admin-console.types";
import {
  queryAnalyticsSql,
  exportAnalyticsSql,
  fetchAnalyticsSqlSchema,
} from "@/lib/admin-api";
import { downloadCsv } from "@/components/admin-console.utils";

/**
 * Frontend SELECT-only validator. Mirrors the backend validator in
 * src/adcs/admin/analytics.py::_validate_read_only_select. The frontend
 * check provides immediate feedback; the backend remains the source of
 * truth and rejects anything the frontend lets through.
 */
export function validateSelectOnlySql(sql: string): { ok: boolean; error?: string } {
  const stripped = sql.trim();
  if (!stripped) return { ok: false, error: "SQL cannot be empty." };

  const lowered = stripped.toLowerCase().replace(/\s+/g, " ");
  if (!lowered.startsWith("select") && !lowered.startsWith("with")) {
    return { ok: false, error: "Only SELECT (or WITH ... SELECT) statements are allowed." };
  }

  // Block multi-statement queries (any ; that isn't trailing)
  if (stripped.replace(/;+\s*$/, "").includes(";")) {
    return { ok: false, error: "Only a single SELECT statement is allowed." };
  }

  const tokens = ` ${lowered} `;
  const blockedKeywords = [
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "grant",
    "revoke",
    "comment",
    "vacuum",
    "analyze",
    "copy",
    "lock",
    "reindex",
    "merge",
    "call",
    "do",
    "execute",
  ];
  for (const kw of blockedKeywords) {
    if (tokens.includes(` ${kw} `)) {
      return { ok: false, error: `Forbidden keyword: ${kw.toUpperCase()}` };
    }
  }

  const blockedTables = [
    "admin_api_keys",
    "admin_sessions",
    "pg_authid",
    "pg_shadow",
    "pg_user",
    "pg_roles",
  ];
  for (const t of blockedTables) {
    if (tokens.includes(` ${t}`) || tokens.includes(`.${t}`) || tokens.includes(`(${t}`)) {
      return {
        ok: false,
        error: `Access to table \`${t}\` is not allowed (contains credentials).`,
      };
    }
  }

  const blockedColumns = [
    "token_hash",
    "api_key",
    "password",
    "secret",
    "private_key",
    "credentials",
    "session_token",
  ];
  for (const c of blockedColumns) {
    if (lowered.includes(c)) {
      return {
        ok: false,
        error: `Access to sensitive column \`${c}\` is not allowed.`,
      };
    }
  }

  return { ok: true };
}

export type UseSqlExplorerArgs = {
  apiKey: string;
  showAlert: (message: string, title?: string) => void;
  /** Email of the current logged-in user, used as author when saving queries. */
  currentUserEmail?: string | null;
};

/**
 * Initial editor query. Multi-line so the editor renders it formatted;
 * the trailing semicolon is accepted by both the frontend validator and the
 * backend `_validate_read_only_select` (which strips trailing `;`).
 */
const DEFAULT_SQL_TEXT =
  "SELECT endpoint, COUNT(*) AS requests\nFROM analytics_queries\nGROUP BY endpoint;";

export function useSqlExplorer(args: UseSqlExplorerArgs) {
  const { apiKey, showAlert, currentUserEmail } = args;

  const [sqlText, setSqlText] = useState(DEFAULT_SQL_TEXT);
  const [sqlViewName, setSqlViewName] = useState("");
  const [sqlViewDescription, setSqlViewDescription] = useState("");
  const [sqlViewComment, setSqlViewComment] = useState("");
  const [savedSqlViews, setSavedSqlViews] = useState<SqlSavedView[]>([]);
  const [sqlLastQueryDurationMs, setSqlLastQueryDurationMs] = useState<number | null>(null);
  const [sqlLastExportDurationMs, setSqlLastExportDurationMs] = useState<number | null>(null);

  // Load saved views from localStorage
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const raw = window.localStorage.getItem(SQL_VIEWS_STORAGE_KEY);
    if (!raw) {
      return;
    }
    try {
      const parsed = JSON.parse(raw) as SqlSavedView[];
      if (Array.isArray(parsed)) {
        setSavedSqlViews(parsed);
      }
    } catch {
      setSavedSqlViews([]);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(SQL_VIEWS_STORAGE_KEY, JSON.stringify(savedSqlViews));
  }, [savedSqlViews]);

  // Both mutations accept an optional SQL override. When omitted they execute the
  // current `sqlText` (backward-compatible behavior); callers that just updated
  // `sqlText` in the same tick (e.g. "load saved query & run") pass the string
  // explicitly so the executed SQL can never trail the displayed SQL by a render.
  const sqlQueryMutation = useMutation({
    mutationFn: (overrideSql?: string) => {
      const statement = overrideSql ?? sqlText;
      const validation = validateSelectOnlySql(statement);
      if (!validation.ok) {
        return Promise.reject(new Error(validation.error ?? "Invalid SQL"));
      }
      return queryAnalyticsSql(apiKey, { sql: statement, max_rows: 1000 });
    },
  });

  const sqlExportMutation = useMutation({
    mutationFn: (overrideSql?: string) => {
      const statement = overrideSql ?? sqlText;
      const validation = validateSelectOnlySql(statement);
      if (!validation.ok) {
        return Promise.reject(new Error(validation.error ?? "Invalid SQL"));
      }
      return exportAnalyticsSql(apiKey, { sql: statement, max_rows: 1000 });
    },
    onSuccess: (response) => {
      downloadCsv(response.filename, response.csv_payload);
    },
  });

  const sqlSchemaQuery = useQuery({
    queryKey: ["admin-sql-schema", apiKey],
    queryFn: () => fetchAnalyticsSqlSchema(apiKey),
    enabled: apiKey.length > 0,
    staleTime: 1000 * 60 * 10, // 10 minutes — schema rarely changes
  });

  function saveSqlView() {
    const name = sqlViewName.trim();
    if (!name) {
      showAlert("Set SQL view name.", "Validation Error");
      return;
    }
    const now = new Date().toISOString();
    const view: SqlSavedView = {
      view_id: `${Date.now()}`,
      name,
      sql: sqlText,
      created_at: now,
      updated_at: now,
      author_email: currentUserEmail ?? undefined,
      description: sqlViewDescription.trim() || undefined,
      comment: sqlViewComment.trim() || undefined,
    };
    setSavedSqlViews((previous) => [view, ...previous].slice(0, 100));
    setSqlViewName("");
    setSqlViewDescription("");
    setSqlViewComment("");
  }

  /** Update an existing saved query — bumps updated_at, preserves author/created_at. */
  function updateSqlView(
    viewId: string,
    patch: Partial<Pick<SqlSavedView, "name" | "sql" | "description" | "comment">>,
  ) {
    setSavedSqlViews((previous) =>
      previous.map((item) =>
        item.view_id === viewId
          ? { ...item, ...patch, updated_at: new Date().toISOString() }
          : item,
      ),
    );
  }

  function applySqlView(view: SqlSavedView) {
    setSqlText(view.sql);
  }

  function applySqlPreset(presetId: string) {
    const preset = SQL_QUALITY_PRESETS.find((item) => item.id === presetId);
    if (!preset) {
      return;
    }
    setSqlText(preset.sql);
  }

  function deleteSqlView(viewId: string) {
    setSavedSqlViews((previous) => previous.filter((item) => item.view_id !== viewId));
  }

  /**
   * Run the query (optionally overriding the executed SQL — see the mutation
   * comment) and record wall-clock duration. Resolves with the live result so
   * callers can chain success/error feedback off the settled request.
   */
  async function runSqlQueryWithTiming(overrideSql?: string) {
    const startedAt = Date.now();
    setSqlLastQueryDurationMs(null);
    try {
      return await sqlQueryMutation.mutateAsync(overrideSql);
    } finally {
      setSqlLastQueryDurationMs(Date.now() - startedAt);
    }
  }

  /** Export counterpart of `runSqlQueryWithTiming`; resolves with the CSV payload. */
  async function runSqlExportWithTiming(overrideSql?: string) {
    const startedAt = Date.now();
    setSqlLastExportDurationMs(null);
    try {
      return await sqlExportMutation.mutateAsync(overrideSql);
    } finally {
      setSqlLastExportDurationMs(Date.now() - startedAt);
    }
  }

  return {
    sqlText,
    setSqlText,
    sqlViewName,
    setSqlViewName,
    sqlViewDescription,
    setSqlViewDescription,
    sqlViewComment,
    setSqlViewComment,
    savedSqlViews,
    sqlLastQueryDurationMs,
    sqlLastExportDurationMs,
    sqlQueryMutation,
    sqlExportMutation,
    sqlSchemaQuery,
    saveSqlView,
    updateSqlView,
    applySqlView,
    applySqlPreset,
    deleteSqlView,
    runSqlQueryWithTiming,
    runSqlExportWithTiming,
  };
}
