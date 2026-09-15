"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { getAdminErrorMessage } from "@/components/admin-console.utils";
import { useAdminKeys } from "@/hooks/useAdminKeys";
import type { AdminKeyAuditRecord, AdminKeyRecord } from "@/lib/admin-api";

import { Button } from "../components/Button";
import { Card } from "../components/Card";
import { Input, Segmented, Select } from "../components/Field";
import { PageHead } from "../components/PageHead";
import { Pill } from "../components/Pill";
import { ScopeChip } from "../components/ScopeChip";
import { EmptyState, ErrorState, PermissionDenied, Skeleton, StaleBadge } from "../components/states";
import { ShowMoreRow, Table, TableCard } from "../components/Table";
import { Tag } from "../components/Tag";
import { Icon } from "../lib/icons";
import { useAdminData } from "../shell/data";
import { useToast } from "../shell/overlays";
import { useConfirm } from "../shell/overlays";

type AdminKeysHook = ReturnType<typeof useAdminKeys>;

// ───────────────────────────────────────────────────────────────── Fixtures ──

interface KeyDatum {
  id: string;
  owner: string;
  role: "superuser" | "product";
  scopes: string;
  products: string;
  enabled: boolean;
  /** The currently authenticated key — self-guard disables rotate/disable. */
  self: boolean;
  /** Human created-at label. */
  created: string;
  /** Sort key — higher = more recently created (registry default = recency). */
  createdRank: number;
  /** Creating actor. */
  createdBy: string;
  /** Live record (when bound from the API) so rows can call key-scoped mutations. */
  record?: AdminKeyRecord;
}

const KEYS: KeyDatum[] = [
  { id: "adcs_live_a17c", owner: "system@local", role: "superuser", scopes: "*", products: "global", enabled: true, self: true, created: "2026-01-04 08:12", createdRank: 1, createdBy: "bootstrap" },
  { id: "adcs_prod_4f2b", owner: "ingest-bot@example.com", role: "product", scopes: "write:ingestion", products: "aspose.ocr, aspose.cells", enabled: true, self: false, created: "2026-05-30 14:03", createdRank: 4, createdBy: "system@local" },
  { id: "adcs_ro_9d10c", owner: "analyst@example.com", role: "product", scopes: "read:analytics, read:events", products: "aspose.words", enabled: true, self: false, created: "2026-06-01 09:41", createdRank: 3, createdBy: "system@local" },
  { id: "adcs_tmp_22ae", owner: "contractor@example.com", role: "product", scopes: "read:analytics", products: "aspose.barcode", enabled: false, self: false, created: "2026-06-03 11:20", createdRank: 2, createdBy: "system@local" },
];

const KEY_TYPES = ["product", "superuser"];

type AuditRow = [action: string, key: string, who: string, reason: string, when: string];

const KAUDIT: AuditRow[] = [
  ["create", "adcs_tmp_22ae", "system@local", "Contractor onboarding 2026-06", "3 days ago"],
  ["scope-change", "adcs_ro_9d10c", "system@local", "Added read:events", "2 days ago"],
  ["rotate", "adcs_prod_4f2b", "system@local", "Weekly key hygiene", "yesterday"],
  ["disable", "adcs_tmp_22ae", "system@local", "Engagement ended", "today 09:10"],
];

// A second page of audit rows — exercises the "show more" pager (API caps at 50).
const KAUDIT_MORE: AuditRow[] = [
  ["enable", "adcs_ro_9d10c", "system@local", "Investigation cleared", "4 days ago"],
  ["scope-change", "adcs_prod_4f2b", "system@local", "Narrowed to write:ingestion", "5 days ago"],
  ["create", "adcs_prod_4f2b", "system@local", "Ingestion service account", "6 days ago"],
];

// Audit pager page size (20; the API caps at 50).
const AUDIT_PAGE = 20;

// Minimum length for the rollback/scope-change reason captured before a mutation.
const REASON_MIN = 10;
// Audit-trail reason cap (max 500 chars).
const REASON_MAX = 500;

// Per-row disabled-reason caption/tooltip when the operator cannot manage a key
// (requires write:settings AND superuser-or-matching-product-scope).
const MANAGE_TIP = "Disabled: requires write:settings and matching product scope.";

// Scope-combination guard: write:destructive
// is meaningless without write:ingestion, so it is blocked at create AND scope-update
// time. Returns the validation message, or null when the set is valid.
function scopeComboError(scopeList: string[]): string | null {
  if (scopeList.includes("write:destructive") && !scopeList.includes("write:ingestion")) {
    return "write:destructive requires write:ingestion.";
  }
  return null;
}

// ───────────────────────────────────────────── Live → fixture-shape mappers ──

// Map a live AdminKeyRecord onto the fixture render shape. The self-key guard uses
// the check `key.key_id === session.key_id` —
// the backend key_prefix is the first 12 chars of the raw token, so prefix-vs-token
// slices never match; an `apiKey.startsWith(key_prefix)` fallback covers header-auth
// sessions. `createdBy` is resolved from the audit trail's matching "create" entry —
// the key record itself carries no creating-actor field (API limitation: actor from audit).
function toKeyDatum(
  rec: AdminKeyRecord,
  selfKeyId: string,
  apiKey: string,
  createdByForKeyId: Map<string, string>,
): KeyDatum {
  const createdMs = Date.parse(rec.created_at);
  const isSelf =
    (selfKeyId.length > 0 && rec.key_id === selfKeyId) ||
    (apiKey.length > 0 && rec.key_prefix.length > 0 && apiKey.startsWith(rec.key_prefix));
  return {
    id: rec.key_prefix,
    owner: rec.owner_email ?? "—",
    role: rec.is_superuser ? "superuser" : "product",
    scopes: rec.scopes.length ? rec.scopes.join(", ") : "—",
    products: rec.product_scopes.length ? rec.product_scopes.join(", ") : "global",
    enabled: rec.enabled,
    self: isSelf,
    created: Number.isNaN(createdMs) ? rec.created_at : new Date(createdMs).toLocaleString(),
    createdRank: Number.isNaN(createdMs) ? 0 : createdMs,
    // Audit rows store target_key_id = record.key_id (admin_auth.py), not the prefix —
    // join on key_id so the creating actor resolves for live rows.
    createdBy: createdByForKeyId.get(rec.key_id) ?? "—",
    record: rec,
  };
}

// Live audit record → the section's AuditRow tuple shape.
function toAuditRow(rec: AdminKeyAuditRecord): AuditRow {
  return [
    rec.action,
    rec.target_key_id,
    rec.actor_key_id,
    rec.reason ?? "—",
    new Date(rec.created_at).toLocaleString(),
  ];
}

// ────────────────────────────────────────────────── One-time secret reveal ──

function SecretReveal({
  secret,
  rotated,
  onDismiss,
}: {
  secret: string;
  /** Rotation replacement secret vs. a freshly created key (drives the reveal copy). */
  rotated?: boolean;
  onDismiss: () => void;
}) {
  const { toast } = useToast();
  return (
    <div
      className="recovery"
      role="status"
      style={{
        borderColor: "color-mix(in srgb, var(--ok) 30%, var(--border))",
        background: "var(--ok-bg)",
        marginTop: 12,
      }}
    >
      <div
        className="rec-ico"
        style={{ background: "color-mix(in srgb, var(--ok) 16%, transparent)", color: "var(--ok)" }}
      >
        <Icon name="key" />
      </div>
      <div className="rec-body">
        <div className="rec-title">
          {rotated ? "Rotated key — shown once" : "New key created — shown once"}
        </div>
        <div className="rec-text">
          {rotated
            ? "The previous secret is now invalid. Copy the new one before navigating away — it cannot be retrieved later."
            : "Copy it now before navigating away. It cannot be retrieved later."}
        </div>
        <div
          className="kvline"
          style={{
            marginTop: 8,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
            padding: "8px 10px",
          }}
        >
          <b>{secret}</b>
        </div>
        <div className="rec-actions">
          <Button
            variant="btn-primary"
            size="sm"
            icon="download"
            onClick={() => {
              void navigator.clipboard?.writeText(secret).catch(() => {});
              toast("Secret copied to clipboard");
            }}
          >
            Copy secret
          </Button>
          <Button variant="btn-ghost" size="sm" icon="x" onClick={onDismiss}>
            Dismiss
          </Button>
        </div>
      </div>
    </div>
  );
}

function newSecret(): string {
  return (
    "adcs_live_" +
    Math.random().toString(36).slice(2, 10) +
    Math.random().toString(36).slice(2, 10)
  );
}

// ───────────────────────────────────── Inline reason-capture / preview modal ──
// Reuses the ConfirmModal CSS contract exactly (modal-overlay › modal › modal-head/
// body/foot, .sum, .modal-field) so it matches the system; traps focus + Esc-closes
// like the shell overlay. Drives the "Update Scopes" confirmation preview:
// the operator edits scopes/products, sees the resulting scope set in a .sum preview,
// and must enter a ≥REASON_MIN-char reason before the change is applied + audited.

interface ScopeEditState {
  scopes: string;
  products: string;
}

function ScopeUpdateModal({
  keyId,
  isSuperuser,
  initial,
  onCancel,
  onApply,
}: {
  keyId: string;
  isSuperuser: boolean;
  initial: ScopeEditState;
  onCancel: () => void;
  onApply: (next: ScopeEditState, reason: string) => void;
}) {
  const [scopes, setScopes] = useState(initial.scopes);
  const [products, setProducts] = useState(initial.products);
  const [reason, setReason] = useState("");
  const modalRef = useRef<HTMLDivElement>(null);
  const firstRef = useRef<HTMLInputElement>(null);

  const scopeList = scopes.split(",").map((s) => s.trim()).filter(Boolean);
  const productList = products.split(",").map((s) => s.trim()).filter(Boolean);
  // Non-superuser keys must keep at least one product scope (mirrors the hook guard).
  const productsOk = isSuperuser || productList.length > 0;
  // write:destructive requires write:ingestion (scope validation).
  const scopeComboMsg = scopeComboError(scopeList);
  const reasonOk = reason.trim().length >= REASON_MIN;
  const canApply = productsOk && scopeComboMsg == null && reasonOk;

  useEffect(() => {
    firstRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      const root = modalRef.current;
      if (!root) return;
      const focusable = root.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
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
  }, [onCancel]);

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="su-title" ref={modalRef}>
        <div className="modal-head">
          <div className="mi" style={{ background: "var(--warn-bg)", color: "var(--warn)" }}>
            <Icon name="sliders" />
          </div>
          <div className="modal-title" id="su-title">
            Update scopes
          </div>
          <button type="button" className="x" aria-label="Close" onClick={onCancel}>
            <Icon name="x" />
          </button>
        </div>
        <div className="modal-body">
          <div>
            Review the new permission set for <b>{keyId}</b> before applying. Changes take effect
            immediately and are recorded in the audit trail.
          </div>
          <div className="modal-field" style={{ marginBottom: 12 }}>
            <label htmlFor="su-scopes">Scopes (comma-separated)</label>
            <input
              id="su-scopes"
              ref={firstRef}
              value={scopes}
              onChange={(e) => setScopes(e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
            {scopeComboMsg && (
              <div className="confirm-hint" style={{ color: "var(--crit)" }}>
                {scopeComboMsg}
              </div>
            )}
          </div>
          <div className="modal-field" style={{ marginBottom: 12 }}>
            <label htmlFor="su-products">Product scopes (comma-separated)</label>
            <input
              id="su-products"
              value={products}
              onChange={(e) => setProducts(e.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
            {!productsOk && (
              <div className="confirm-hint" style={{ color: "var(--crit)" }}>
                A product key must keep at least one product scope.
              </div>
            )}
          </div>
          <div className="sum" aria-label="Resulting access preview">
            scopes → <b>{scopeList.length ? scopeList.join(", ") : "—"}</b>
            <br />
            products → <b>{productList.length ? productList.join(", ") : "global (all products)"}</b>
          </div>
          <div className="modal-field">
            <label htmlFor="su-reason">Reason (for the audit trail)</label>
            <textarea
              id="su-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              maxLength={REASON_MAX}
              autoComplete="off"
              spellCheck={false}
              style={{
                width: "100%",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                background: "var(--surface)",
                padding: "8px 12px",
                fontFamily: "var(--font-mono)",
                fontSize: "13px",
                color: "var(--fg)",
                outline: "none",
                resize: "vertical",
              }}
            />
            <div className="confirm-hint">
              Minimum {REASON_MIN} characters. {reason.trim().length}/{REASON_MIN}
            </div>
          </div>
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-amber"
            disabled={!canApply}
            onClick={() => onApply({ scopes, products }, reason.trim())}
          >
            Apply scopes
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────── Provisioning ──

function ProvisioningCard({
  canWrite,
  canCreateSuperuser,
  h,
}: {
  canWrite: boolean;
  canCreateSuperuser: boolean;
  h: AdminKeysHook;
}) {
  // Local secret used only in fixtures-mode (no backend → no issued preview).
  const [fixtureSecret, setFixtureSecret] = useState<string | null>(null);
  // Live one-time secret from create/rotate; falls back to the fixture demo secret.
  const liveSecret = h.issuedKeyPreview ?? h.rotatedKeyPreview;
  const secret = liveSecret ?? fixtureSecret;
  // A rotation replacement (vs. a freshly created key) drives the reveal copy —
  // "Rotated key (shown once)" instead of the create text.
  const isRotated = h.issuedKeyPreview == null && h.rotatedKeyPreview != null;
  const creating = h.createAdminKeyMutation.isPending;
  // Scope-combination guard on the create path: write:destructive without
  // write:ingestion blocks Create and surfaces the validation message as the tooltip.
  const newScopeList = h.newKeyScopes.split(",").map((s) => s.trim()).filter(Boolean);
  const createScopeComboMsg = scopeComboError(newScopeList);
  // The create button's disabled reason: the hook's own reason (owner/scope/pending)
  // first, then the scope-combination message.
  const createDisabledReason = h.keyCreateDisabledReason ?? createScopeComboMsg;
  const createDisabled = !canWrite || createDisabledReason != null;
  // Key-type options are gated on session role: only a superuser may issue a
  // superuser key (the key-type select disables "superuser" if !session.is_superuser).
  // A non-superuser sees the "product" option only, so the choice can
  // never be made client-side (the backend 403 stays a last-resort guard).
  const keyTypeOptions = canCreateSuperuser ? KEY_TYPES : ["product"];
  // Safety-critical: the Key Provisioning form is frozen while a key
  // creation request is in flight — fields are frozen mid-flight so values cannot
  // drift between click and response (the button already flips to "Creating…").
  const fieldsDisabled = !canWrite || creating;
  // Effective key type (mirrors the Key type Select value). When "superuser" is
  // chosen the Product scopes field is disabled/greyed — superuser keys grant access
  // to ALL products, so a product-scope set is meaningless. The
  // entered value is retained but read-only, and re-selecting "product" re-enables it.
  const isSuperuserType = canCreateSuperuser && h.newKeyIsSuperuser;
  const productScopesDisabled = fieldsDisabled || isSuperuserType;

  return (
    <Card
      title="Key provisioning"
      sub="One email can hold multiple keys. Empty product scope = assigned products only. Mutations are scope-gated."
    >
      {!canWrite && (
        <PermissionDenied
          scope="write:settings"
          extra="Only superusers can provision or manage superuser keys."
        />
      )}
      <div className="toolbar">
        <Input
          label="Owner email"
          width={190}
          placeholder="owner@example.com"
          value={h.newKeyOwnerEmail}
          onChange={(e) => h.setNewKeyOwnerEmail(e.target.value)}
          disabled={fieldsDisabled}
        />
        <Input
          label="Product scopes"
          width={140}
          placeholder={isSuperuserType ? "all products" : "aspose.ocr"}
          value={h.newKeyProductScopes}
          onChange={(e) => h.setNewKeyProductScopes(e.target.value)}
          disabled={productScopesDisabled}
          title={isSuperuserType ? "Superuser keys grant access to all products — product scopes do not apply." : undefined}
        />
        <Input
          label="Scopes"
          width={190}
          placeholder="read:analytics, read:events"
          value={h.newKeyScopes}
          onChange={(e) => h.setNewKeyScopes(e.target.value)}
          disabled={fieldsDisabled}
        />
        <Input
          label="Reason (optional)"
          width={190}
          placeholder="Contractor onboarding 2026-06"
          value={h.newKeyReason}
          onChange={(e) => h.setNewKeyReason(e.target.value)}
          maxLength={REASON_MAX}
          disabled={fieldsDisabled}
        />
        <Select
          label="Key type"
          width={120}
          options={keyTypeOptions}
          value={canCreateSuperuser && h.newKeyIsSuperuser ? "superuser" : "product"}
          onChange={(e) => h.setNewKeyIsSuperuser(e.target.value === "superuser")}
          disabled={fieldsDisabled}
        />
        <div className="toolbar-right">
          <Button
            variant="btn-primary"
            size="sm"
            icon={creating ? "refresh" : "plus"}
            disabled={createDisabled}
            title={canWrite ? (createDisabledReason ?? undefined) : "Requires scope: write:settings"}
            onClick={() => {
              // Live create when a backend is reachable; otherwise reveal a fixture
              // demo secret so the one-time-reveal panel stays reviewable offline.
              if (h.adminKeysQuery.isSuccess) {
                h.createAdminKeyMutation.mutate();
              } else {
                setFixtureSecret(newSecret());
              }
            }}
          >
            {creating ? "Creating…" : "Create key"}
          </Button>
        </div>
      </div>
      <div className="muted-note" data-guidance="">
        Define the narrowest viable access. The reason is recorded in the audit trail. The secret is
        shown once — copy it before navigating away.
      </div>
      <div id="key-secret">
        {secret && (
          <SecretReveal
            secret={secret}
            rotated={isRotated}
            onDismiss={() => {
              // Clear the fixture demo secret AND the live issued/rotated previews —
              // Dismiss is how the operator removes the raw secret after vaulting it.
              setFixtureSecret(null);
              h.dismissKeyPreviews();
            }}
          />
        )}
      </div>
      {h.createAdminKeyMutation.isError && (
        <div className="recovery" role="alert" style={{ marginTop: 12 }}>
          <div className="rec-ico">
            <Icon name="alert" />
          </div>
          <div className="rec-body">
            <div className="rec-title">Key creation failed</div>
            <div className="rec-text">
              {getAdminErrorMessage(h.createAdminKeyMutation.error, "Failed to create admin key.")}{" "}
              Check the owner email, scopes, and product scopes, then retry — the form keeps your
              input.
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

// ───────────────────────────────────────────────────────────── Key row ──────

function KeyRow({ k, canManage, h }: { k: KeyDatum; canManage: boolean; h: AdminKeysHook }) {
  const { confirm } = useConfirm();
  const { toast } = useToast();
  // Offline (fixture) rows keep optimistic local toggle; live rows reflect the query.
  const [fixtureEnabled, setFixtureEnabled] = useState(k.enabled);
  const [scopeEditOpen, setScopeEditOpen] = useState(false);
  const rec = k.record;
  const enabled = rec ? k.enabled : fixtureEnabled;
  const guarded = k.self; // self-key: cannot rotate/disable the authenticated key
  const selfTip = guarded ? "Cannot disable/rotate the currently authenticated key" : undefined;
  // Disabled-reason tooltip: self-guard wins on rotate/disable, then manageability.
  const manageTip = canManage ? undefined : MANAGE_TIP;

  // Per-row in-flight affordance: only the row whose key_id is mutating shows "…".
  const rotating = !!rec && h.rotateAdminKeyMutation.isPending && h.rotateAdminKeyMutation.variables === rec.key_id;
  const disabling = !!rec && h.disableAdminKeyMutation.isPending && h.disableAdminKeyMutation.variables === rec.key_id;
  const enabling = !!rec && h.enableAdminKeyMutation.isPending && h.enableAdminKeyMutation.variables === rec.key_id;
  const updating =
    !!rec &&
    h.updateAdminKeyScopesMutation.isPending &&
    h.updateAdminKeyScopesMutation.variables?.keyId === rec.key_id;

  return (
    <div className="snap-row">
      <div>
        <div className="snap-id">
          {k.id} · {k.role}{" "}
          {enabled ? <Pill variant="ok">enabled</Pill> : <Pill variant="neutral">disabled</Pill>}
          {k.self && <Tag>this key</Tag>}
        </div>
        <div className="snap-meta mono">
          owner: {k.owner} · scopes: {k.scopes} · products: {k.products}
        </div>
        <div className="snap-meta">
          created {k.created} · by <span className="mono">{k.createdBy}</span>
        </div>
      </div>
      <div
        className="snap-right"
        style={canManage ? undefined : { flexDirection: "column", alignItems: "flex-end", gap: 6 }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <Button
            variant="btn-ghost"
            size="sm"
            disabled={!canManage || updating}
            title={manageTip}
            onClick={() => {
              // Confirmation preview + reason capture before the scope change
              // (safety-critical). Offline this is a no-op apply + toast.
              setScopeEditOpen(true);
            }}
          >
            {updating ? "Updating…" : "Update scopes"}
          </Button>
          {enabled ? (
            <>
              <Button
                variant="btn-ghost"
                size="sm"
                disabled={!canManage || guarded || rotating}
                title={selfTip ?? manageTip}
                onClick={() =>
                  confirm({
                    title: "Rotate API key",
                    icon: "refresh",
                    tone: "amber",
                    body: (
                      <>
                        Issues a new secret for <b>{k.id}</b> and invalidates the old one{" "}
                        <b>immediately</b>. Update your integrations with the new value.
                      </>
                    ),
                    summary: (
                      <>
                        key <b>{k.id}</b> · new secret generated
                      </>
                    ),
                    confirmLabel: "Rotate key",
                    // Live rows toast from the hook's onSuccess only — never before
                    // the request settles. Fixture rows resolve synchronously.
                    successToast: rec ? undefined : `Key ${k.id} rotated — new secret issued`,
                    onConfirm: () => {
                      if (rec) h.rotateAdminKeyMutation.mutate(rec.key_id);
                    },
                  })
                }
              >
                {rotating ? "Rotating…" : "Rotate"}
              </Button>
              <Button
                variant="btn-ghost"
                size="sm"
                disabled={!canManage || guarded || disabling}
                title={selfTip ?? manageTip}
                onClick={() =>
                  confirm({
                    title: "Disable API key",
                    icon: "key",
                    tone: "amber",
                    body: (
                      <>
                        Disables key <b>{k.id}</b>. Requests using it will be rejected until it is
                        re-enabled. Existing sessions are unaffected.
                      </>
                    ),
                    summary: (
                      <>
                        key <b>{k.id}</b> · {k.role} · {k.products}
                      </>
                    ),
                    confirmLabel: "Disable key",
                    // Live success toasts fire in the hook's onSuccess; failures
                    // surface via the onError toast + the registry's red alert.
                    successToast: rec ? undefined : `Key ${k.id} disabled`,
                    onConfirm: () => {
                      if (rec) h.disableAdminKeyMutation.mutate(rec.key_id);
                      else setFixtureEnabled(false);
                    },
                  })
                }
              >
                {disabling ? "Disabling…" : "Disable"}
              </Button>
            </>
          ) : (
            <Button
              variant="btn-ghost"
              size="sm"
              disabled={!canManage || enabling}
              title={manageTip}
              onClick={() => {
                if (rec) {
                  h.enableAdminKeyMutation.mutate(rec.key_id);
                } else {
                  setFixtureEnabled(true);
                  toast(`Key ${k.id} enabled`);
                }
              }}
            >
              {enabling ? "Enabling…" : "Enable"}
            </Button>
          )}
        </div>
        {!canManage && (
          <div className="snap-meta" style={{ color: "var(--warn)" }}>
            {MANAGE_TIP}
          </div>
        )}
      </div>
      {scopeEditOpen && (
        <ScopeUpdateModal
          keyId={k.id}
          isSuperuser={k.role === "superuser"}
          initial={{ scopes: k.scopes === "*" || k.scopes === "—" ? "" : k.scopes, products: k.products === "global" ? "" : k.products }}
          onCancel={() => setScopeEditOpen(false)}
          onApply={(next, reason) => {
            setScopeEditOpen(false);
            const scopeList = next.scopes.split(",").map((s) => s.trim()).filter(Boolean);
            const productList = next.products.split(",").map((s) => s.trim()).filter(Boolean);
            if (rec) {
              // The operator-typed reason is sent verbatim so the audit trail's
              // Reason column records it (every action is logged with the
              // operator-provided reason), instead of a hardcoded generic string.
              h.updateAdminKeyScopesMutation.mutate({
                keyId: rec.key_id,
                scopes: scopeList,
                productScopes: productList,
                reason,
              });
            } else {
              toast(`Scopes updated for ${k.id} — ${reason}`);
            }
          }}
        />
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────── Section ──────

type RoleFilter = "All roles" | "superuser" | "product";
type SortMode = "Recent first" | "Owner A–Z";
const STATUS_SEG = ["All", "Enabled", "Disabled"];

export function ApiKeysSection() {
  const { toast } = useToast();
  const data = useAdminData();
  const h = useAdminKeys({
    apiKey: data.apiKey,
    sessionIsSuccess: data.sessionIsSuccess,
    // Mono section key is "apikeys"; the hook's 60s auto-refresh gate keys off the
    // SidebarSectionId "api-keys-access" — pass that so the refetch fires.
    activeSectionId: "api-keys-access",
    canManageKeys: data.can("write:settings"),
    showAlert: data.showAlert,
    // The Mono Update-Scopes flow uses its own ScopeUpdateModal (preview + reason),
    // so the hook's two-prompt bridge is unused; keep it inert for type-compat.
    showPrompt: (_title, _label, defaultValue, action) => action(defaultValue),
  });

  // Operator's effective access — gates provisioning + all key mutations.
  const canWrite = data.can("write:settings");
  // Only a superuser session may issue superuser keys. Permissive until
  // a real session loads so offline every key-type choice stays reviewable.
  const canCreateSuperuser = data.session ? data.session.is_superuser : true;

  // Creating-actor lookup: derive from the audit trail's "create" entries keyed by
  // target_key_id (= record.key_id; the key record carries no actor of its own).
  // API limitation: the key record exposes no creating actor; sourced from the audit trail.
  const liveAudit = h.adminKeyAuditQuery.data ?? [];
  const createdByForKeyId = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of liveAudit) {
      if (a.action === "create" && !m.has(a.target_key_id)) m.set(a.target_key_id, a.actor_key_id);
    }
    return m;
  }, [liveAudit]);

  // Live key registry (mapped to the fixture render shape); fixtures ONLY when the
  // session is offline — online empty/error states must show the real states,
  // never substitute fixture rows (or fixture-derived header counts).
  const offline = !data.sessionIsSuccess;
  const liveKeys = h.adminKeysQuery.data ?? [];
  // Self-key guard: the check is key.key_id === session.key_id (an apiKey slice
  // cannot match the backend's 12-char key_prefix).
  const selfKeyId = data.session?.key_id ?? "";
  const allRows: KeyDatum[] = liveKeys.length
    ? liveKeys.map((r) => toKeyDatum(r, selfKeyId, data.apiKey, createdByForKeyId))
    : offline
      ? KEYS
      : [];

  // Per-key manageability (canManageThisKey = write:settings AND
  // (operator is_superuser OR (!key.is_superuser AND key products ⊆ operator
  // products))). Superuser keys and global keys (empty product_scopes) are not
  // manageable by non-superusers. Fixture rows / no session stay permissive so the
  // offline section keeps every action reviewable.
  const session = data.session;
  const canManageRow = (k: KeyDatum): boolean => {
    if (!canWrite) return false;
    const rec = k.record;
    if (!rec || !session) return true;
    if (session.is_superuser) return true;
    if (rec.is_superuser) return false;
    return (
      rec.product_scopes.length > 0 &&
      rec.product_scopes.every((p) => session.product_scopes.includes(p))
    );
  };

  // ── Registry filters + sort (information density / scannability) ──
  // Applied to the DISPLAY source client-side so they respond fully offline.
  const [query, setQuery] = useState("");
  const [statusSeg, setStatusSeg] = useState(0); // 0=All 1=Enabled 2=Disabled
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("All roles");
  const [sortMode, setSortMode] = useState<SortMode>("Recent first");

  const q = query.trim().toLowerCase();
  const shown: KeyDatum[] = allRows
    .filter((k) => {
      if (statusSeg === 1 && !k.enabled) return false;
      if (statusSeg === 2 && k.enabled) return false;
      if (roleFilter !== "All roles" && k.role !== roleFilter) return false;
      if (!q) return true;
      // Free-text matches owner email, key-ID prefix, role, and scope names.
      return (
        k.id.toLowerCase().includes(q) ||
        k.owner.toLowerCase().includes(q) ||
        k.role.toLowerCase().includes(q) ||
        k.scopes.toLowerCase().includes(q) ||
        k.products.toLowerCase().includes(q)
      );
    })
    .slice()
    .sort((a, b) =>
      sortMode === "Owner A–Z"
        ? a.owner.localeCompare(b.owner)
        : b.createdRank - a.createdRank,
    );

  const filtersActive = q !== "" || statusSeg !== 0 || roleFilter !== "All roles";

  // Live audit trail → AuditRow tuples; fixtures (incl. the second pager page) only
  // when offline — an empty live audit table must never show fixture governance rows.
  // Live data pages at AUDIT_PAGE (20 of max 50): the
  // first 20 render inline and rows 21..50 fold into the "+N more" reveal, instead of
  // dumping every fetched row at once. The offline fixtures keep their own KAUDIT /
  // KAUDIT_MORE split so the pager stays demonstrable with no backend.
  const liveAuditRows = liveAudit.map(toAuditRow);
  const auditRows: AuditRow[] = liveAudit.length
    ? liveAuditRows.slice(0, AUDIT_PAGE)
    : offline
      ? KAUDIT
      : [];
  const auditMore: AuditRow[] = liveAudit.length
    ? liveAuditRows.slice(AUDIT_PAGE)
    : offline
      ? KAUDIT_MORE
      : [];

  // Real query-driven state: loading/error only
  // when there is no data yet; empty when the API returns an empty registry.
  const liveView: "ready" | "loading" | "error" | "empty" = h.adminKeysQuery.isLoading && !liveKeys.length
    ? "loading"
    : h.adminKeysQuery.isError && !liveKeys.length
      ? "error"
      : h.adminKeysQuery.isSuccess && !liveKeys.length
        ? "empty"
        : "ready";
  // The registry-state preview Select stays interactive so each state remains
  // reviewable; once a backend drives data it reflects the live query instead.
  const [previewOverride, setPreviewOverride] = useState<"ready" | "loading" | "error" | "empty">("ready");
  // Display-set gate (mirror Health): the rows always carry a fixture fallback, so a
  // Skeleton/Error/Empty card must NEVER hide them while a fixture exists. Offline the
  // override drives the body only when it would NOT hide a fixture — i.e. "ready" keeps the
  // rows, and the non-ready previews still surface (Skeleton/Error/Empty) ONLY when the
  // DISPLAY set (post-filter) is genuinely empty. With fixtures present the rows win.
  const offlineView = previewOverride !== "ready" && !shown.length ? previewOverride : "ready";
  const view = data.sessionIsSuccess ? liveView : offlineView;
  // The Select reflects the operator's own selection so the control visibly responds even
  // when fixtures keep the body in the "ready" presentation.
  const selectedView = data.sessionIsSuccess ? liveView : previewOverride;

  // Mutation in-flight ("Mutation in progress" / "Refreshing…").
  const anyMutating =
    h.createAdminKeyMutation.isPending ||
    h.disableAdminKeyMutation.isPending ||
    h.enableAdminKeyMutation.isPending ||
    h.rotateAdminKeyMutation.isPending ||
    h.updateAdminKeyScopesMutation.isPending;

  // Per-mutation error surface: any failed key action
  // renders the red alert in the registry card; the hook additionally
  // fires an error toast from each mutation's onError.
  const keyActionFailed =
    h.disableAdminKeyMutation.isError ||
    h.enableAdminKeyMutation.isError ||
    h.updateAdminKeyScopesMutation.isError ||
    h.rotateAdminKeyMutation.isError;
  const keyActionError =
    h.disableAdminKeyMutation.error ??
    h.enableAdminKeyMutation.error ??
    h.updateAdminKeyScopesMutation.error ??
    h.rotateAdminKeyMutation.error;

  // Mutation succeeded but the background refetch errored → registry may diverge from
  // the toast feedback ("Mutation success, but refetch fails").
  const refetchDiverged =
    !h.createAdminKeyMutation.isPending &&
    (h.createAdminKeyMutation.isSuccess ||
      h.disableAdminKeyMutation.isSuccess ||
      h.enableAdminKeyMutation.isSuccess ||
      h.rotateAdminKeyMutation.isSuccess ||
      h.updateAdminKeyScopesMutation.isSuccess) &&
    h.adminKeysQuery.isError;

  const superuserCount = allRows.filter((k) => k.role === "superuser").length;
  const disabledCount = allRows.filter((k) => !k.enabled).length;

  const AUDIT_COLS = 5;

  return (
    <>
      <PageHead
        title="API Keys & Access"
        sub="Provision and manage admin API keys, scopes, and product-level access."
        onHelp={() => {
          window.location.href = "/howto";
        }}
        actions={
          <>
            <ScopeChip label="scope" value="write:settings" dot />
            {anyMutating && <StaleBadge>Refreshing…</StaleBadge>}
            <Button
              variant="btn-ghost"
              size="sm"
              icon="download"
              disabled={!canWrite}
              title={canWrite ? undefined : "Requires scope: write:settings"}
              onClick={() => {
                // Live export/import success copy is owned by the hook
                // (runExportKeys/runImportKeys → "Keys exported." / "Imported N
                // key(s)."). Mirror that exact wording offline so the fixture path
                // matches the live success strings.
                if (h.adminKeysQuery.isSuccess) void h.runExportKeys();
                else toast("Keys exported.");
              }}
            >
              Export
            </Button>
            <Button
              variant="btn-ghost"
              size="sm"
              icon="upload"
              disabled={!canWrite}
              title={canWrite ? undefined : "Requires scope: write:settings"}
              onClick={() => {
                if (h.adminKeysQuery.isSuccess) void h.runImportKeys();
                else toast(`Imported ${allRows.length} key(s).`);
              }}
            >
              Import
            </Button>
          </>
        }
      />

      <ProvisioningCard canWrite={canWrite} canCreateSuperuser={canCreateSuperuser} h={h} />

      {refetchDiverged && (
        <div className="recovery warn" role="alert" style={{ marginBottom: 14 }}>
          <div className="rec-ico">
            <Icon name="alert" />
          </div>
          <div className="rec-body">
            <div className="rec-title">Registry may be out of date</div>
            <div className="rec-text">
              The mutation succeeded, but the background refresh failed — the change may not appear in
              the list yet. It will reconcile on the next 60-second refetch.
            </div>
            <div className="rec-actions">
              <Button
                variant="btn-ghost"
                size="sm"
                icon="refresh"
                onClick={() => void h.adminKeysQuery.refetch()}
              >
                Refresh now
              </Button>
            </div>
          </div>
        </div>
      )}

      <Card
        title="Key registry"
        sub={`${allRows.length} keys · ${superuserCount} superuser · ${disabledCount} disabled`}
        flush
        right={
          <Select
            width={150}
            options={["Live", "Loading", "Refetch error", "Empty"]}
            value={
              selectedView === "ready"
                ? "Live"
                : selectedView === "loading"
                  ? "Loading"
                  : selectedView === "error"
                    ? "Refetch error"
                    : "Empty"
            }
            onChange={(e) => {
              const v = e.target.value;
              setPreviewOverride(
                v === "Loading" ? "loading" : v === "Refetch error" ? "error" : v === "Empty" ? "empty" : "ready",
              );
            }}
            aria-label="Registry state preview"
          />
        }
      >
        <div className="toolbar" style={{ padding: "12px 16px 0" }}>
          <Input
            label="Search keys"
            width={230}
            placeholder="owner, key id, role, or scope"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search keys by owner, id, role, or scope"
          />
          <div className="field">
            <span className="flabel">Status</span>
            <Segmented
              options={STATUS_SEG}
              active={statusSeg}
              onChange={setStatusSeg}
              ariaLabel="Filter by enabled status"
            />
          </div>
          <Select
            label="Role"
            width={140}
            options={["All roles", "superuser", "product"]}
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value as RoleFilter)}
          />
          <Select
            label="Sort"
            width={150}
            options={["Recent first", "Owner A–Z"]}
            value={sortMode}
            onChange={(e) => setSortMode(e.target.value as SortMode)}
          />
          {filtersActive && (
            <div className="toolbar-right">
              <span className="muted-note">
                {shown.length} of {allRows.length}
              </span>
              <Button
                variant="btn-ghost"
                size="sm"
                icon="x"
                onClick={() => {
                  setQuery("");
                  setStatusSeg(0);
                  setRoleFilter("All roles");
                }}
              >
                Clear
              </Button>
            </div>
          )}
        </div>
        {view === "loading" ? (
          <div style={{ padding: 16 }}>
            <Skeleton rows={4} />
          </div>
        ) : view === "error" ? (
          <div style={{ padding: 16 }}>
            <ErrorState
              title="Failed to load keys"
              text="The registry is showing the last cached data. It will retry on the next 60-second refetch."
              cause="admin API unreachable or database in read-only mode"
              actions={
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="refresh"
                  onClick={() => {
                    setPreviewOverride("ready");
                    void h.adminKeysQuery.refetch();
                  }}
                >
                  Retry now
                </Button>
              }
            />
          </div>
        ) : view === "empty" ? (
          <div style={{ padding: 16 }}>
            <EmptyState
              title="No admin keys yet"
              text="No API keys have been provisioned. Create one using the Key provisioning form above to delegate scoped access."
            />
          </div>
        ) : !shown.length ? (
          <div style={{ padding: 16 }}>
            <EmptyState
              title="No keys match these filters"
              text="No keys match the current search, status, or role filter. Clear the filters to see the full registry."
              action={
                <Button
                  variant="btn-ghost"
                  size="sm"
                  icon="x"
                  onClick={() => {
                    setQuery("");
                    setStatusSeg(0);
                    setRoleFilter("All roles");
                  }}
                >
                  Clear filters
                </Button>
              }
            />
          </div>
        ) : (
          <div className="snap-list">
            {shown.map((k) => (
              <KeyRow key={k.id} k={k} canManage={canManageRow(k)} h={h} />
            ))}
          </div>
        )}
        {keyActionFailed && (
          <div style={{ padding: "12px 16px 16px" }}>
            <div className="recovery" role="alert">
              <div className="rec-ico">
                <Icon name="alert" />
              </div>
              <div className="rec-body">
                <div className="rec-title">Key action failed</div>
                <div className="rec-text">
                  {getAdminErrorMessage(keyActionError, "Failed to update key settings.")} The
                  registry is unchanged — the action buttons stay enabled so you can retry.
                </div>
              </div>
            </div>
          </div>
        )}
      </Card>

      <Card
        title="Key audit trail"
        sub="Append-only governance log — every create / rotate / disable / scope-change."
        flush
        right={<StaleBadge>showing 50 recent</StaleBadge>}
      >
        <TableCard>
          <Table>
            <thead>
              <tr>
                <th style={{ width: 140 }}>Action</th>
                <th style={{ width: 160 }}>Key</th>
                <th style={{ width: 150 }}>Actor</th>
                <th>Reason</th>
                <th className="num" style={{ width: 110 }}>
                  When
                </th>
              </tr>
            </thead>
            <tbody>
              {auditRows.length === 0 ? (
                <tr>
                  <td colSpan={AUDIT_COLS} style={{ padding: 16 }}>
                    <EmptyState
                      title="No audit entries yet"
                      text="No key mutations have been recorded. Create, rotate, disable, or re-scope a key and the governance log will populate here."
                    />
                  </td>
                </tr>
              ) : (
                auditRows.map((row, i) => (
                  <AuditTr key={`${row[0]}-${row[1]}-${row[4]}-${i}`} row={row} />
                ))
              )}
              {auditMore.length > 0 && (
                <ShowMoreRow
                  colSpan={AUDIT_COLS}
                  count={auditMore.length}
                  extra={auditMore.map((row, i) => (
                    <AuditTr key={`${row[0]}-${row[1]}-${row[4]}-more-${i}`} row={row} />
                  ))}
                />
              )}
            </tbody>
          </Table>
        </TableCard>
      </Card>
    </>
  );
}

function AuditTr({ row }: { row: AuditRow }) {
  const [action, key, who, reason, when] = row;
  return (
    <tr className="data">
      <td>
        <Tag>{action}</Tag>
      </td>
      <td>
        <span className="repo-id">{key}</span>
      </td>
      <td>
        <span className="mono" style={{ fontSize: "11.5px", color: "var(--fg-muted)" }}>
          {who}
        </span>
      </td>
      <td>{reason}</td>
      <td className="num">{when}</td>
    </tr>
  );
}
