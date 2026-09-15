"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { SidebarSectionId } from "@/components/admin-console.types";
import {
  fetchCriticalEvents,
  fetchCriticalEventActions,
  postCriticalEventAction,
} from "@/lib/admin-api";
import { buildDisabledReason, getAdminErrorMessage } from "@/components/admin-console.utils";

export type UseCriticalEventsArgs = {
  apiKey: string;
  sessionIsSuccess: boolean;
  activeSectionId: SidebarSectionId;
  canMutateIngestion: boolean;
  showAlert: (message: string, title?: string) => void;
  showPrompt: (title: string, label: string, defaultValue: string, action: (value: string) => void) => void;
};

export function useCriticalEvents(args: UseCriticalEventsArgs) {
  const {
    apiKey,
    sessionIsSuccess,
    activeSectionId,
    canMutateIngestion,
    showAlert,
    showPrompt,
  } = args;

  const queryClient = useQueryClient();

  const criticalEventsQuery = useQuery({
    queryKey: ["admin-critical-events", apiKey],
    queryFn: () => fetchCriticalEvents(apiKey, 50),
    enabled: sessionIsSuccess,
    refetchInterval: activeSectionId === "critical-events" ? 60_000 : false,
  });

  const criticalActionsQuery = useQuery({
    queryKey: ["admin-critical-event-actions", apiKey],
    queryFn: () => fetchCriticalEventActions(apiKey, 50),
    enabled: sessionIsSuccess,
    refetchInterval: activeSectionId === "critical-events" ? 60_000 : false,
  });

  // Full fetched queue (limit=50). Consumers paginate client-side (10 per page).
  const criticalIncidents = criticalEventsQuery.data ?? [];

  const eventActionMutation = useMutation({
    mutationFn: ({
      eventId,
      action,
      payload,
    }: {
      eventId: string;
      action:
        | "acknowledge"
        | "mute"
        | "snooze"
        | "assign"
        | "severity-override"
        | "escalate"
        | "resolve";
      payload: Record<string, unknown>;
    }) => postCriticalEventAction(apiKey, eventId, action, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin-critical-events", apiKey] });
      await queryClient.invalidateQueries({ queryKey: ["admin-critical-event-actions", apiKey] });
    },
    // Every lifecycle mutation surfaces its failure (Mono toast via showAlert) —
    // callers must never toast success optimistically before settle.
    onError: (error: unknown) => {
      showAlert(
        getAdminErrorMessage(error, "The critical-event action failed. Retry or check backend logs."),
        "Action Failed",
      );
    },
  });

  const criticalEventActionDisabledReason = buildDisabledReason({
    missingScope: !canMutateIngestion ? "write:ingestion" : null,
    pending: eventActionMutation.isPending,
    pendingMessage: "Another critical-event action is in progress.",
  });

  function runCriticalEventAction(
    eventId: string,
    action:
      | "acknowledge"
      | "mute"
      | "snooze"
      | "assign"
      | "severity-override"
      | "escalate"
      | "resolve",
  ) {
    // Mute and snooze are capped at 30 days (43200 minutes).
    if (action === "mute" || action === "snooze") {
      const label = action === "mute" ? "Mute" : "Snooze";
      showPrompt(`${label} Duration`, "Minutes (max 43200 = 30 days)", "60", (rawDuration) => {
        const duration = Number.parseInt(rawDuration, 10);
        if (Number.isNaN(duration) || duration < 1 || duration > 43_200) {
          showAlert("Invalid duration. Allowed range: 1 to 43200 minutes (30 days max).", "Validation Error");
          return;
        }
        eventActionMutation.mutate({ eventId, action, payload: { duration_minutes: duration } });
      });
      return;
    }

    if (action === "assign") {
      showPrompt("Assign Owner", "Owner (SLA timer max 30 days)", "product-owner", (owner) => {
        if (!owner.trim()) {
          showAlert("Owner is required for assignment.", "Validation Error");
          return;
        }
        eventActionMutation.mutate({ eventId, action, payload: { owner: owner.trim() } });
      });
      return;
    }

    if (action === "severity-override") {
      showPrompt("Override Severity", "critical | high | warning", "high", (severity) => {
        const normalizedSeverity = severity.trim().toLowerCase();
        if (!["critical", "high", "warning"].includes(normalizedSeverity)) {
          showAlert("Invalid severity value.", "Validation Error");
          return;
        }
        eventActionMutation.mutate({ eventId, action, payload: { severity: normalizedSeverity } });
      });
      return;
    }

    // Escalate requires a reason for the audit trail.
    if (action === "escalate") {
      showPrompt("Escalate Incident", "Escalation reason", "Requires immediate attention", (reason) => {
        if (!reason.trim()) {
          showAlert("Escalation reason is required.", "Validation Error");
          return;
        }
        eventActionMutation.mutate({ eventId, action, payload: { reason: reason.trim() } });
      });
      return;
    }

    // Resolve requires a reason for the audit trail.
    if (action === "resolve") {
      showPrompt("Resolve Incident", "Resolution summary", "Incident resolved", (reason) => {
        if (!reason.trim()) {
          showAlert("Resolution reason is required.", "Validation Error");
          return;
        }
        eventActionMutation.mutate({ eventId, action, payload: { reason: reason.trim() } });
      });
      return;
    }

    eventActionMutation.mutate({ eventId, action, payload: {} });
  }

  return {
    criticalEventsQuery,
    criticalActionsQuery,
    criticalIncidents,
    eventActionMutation,
    criticalEventActionDisabledReason,
    runCriticalEventAction,
  };
}
