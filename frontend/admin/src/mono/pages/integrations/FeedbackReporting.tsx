"use client";

import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Banner } from "@/mono/components/Banner";
import { Button } from "@/mono/components/Button";
import { Icon } from "@/mono/lib/icons";
import {
  AdminApiError,
  submitPublicQueryFeedback,
  submitPublicQueryIssue,
  type PublicQueryFeedbackResponse,
  type PublicQueryIssueResponse,
} from "@/lib/admin-api";

/* ----------------------------------------------------------------------------
 * Feedback and Issue Reporting
 *
 * Two-lane public reporting surface tied to a query `request_id`:
 *   • LEFT  — usefulness feedback (rating + reason)  → submitPublicQueryFeedback
 *   • RIGHT — documentation issue (issue_type + notes) → submitPublicQueryIssue
 *
 * Both lanes are REAL public POSTs (no auth). There is no fixture fallback for a
 * mutation: a submission either succeeds against the backend or it does not, and
 * the result is surfaced honestly (success line or error banner with the server
 * message). Offline, the form is fully reviewable and interactive — pressing a
 * Submit simply reports the failure honestly rather than faking a confirmation.
 *
 * The `request_id` comes from the public Query Playground output line; the form
 * is shared evidence-linking scaffolding, so it does not invent results.
 * -------------------------------------------------------------------------- */

const ISSUE_TYPES: { value: string; label: string }[] = [
  { value: "missing_docs", label: "Missing content" },
  { value: "wrong_docs", label: "Wrong / outdated answer" },
  { value: "outdated_docs", label: "Outdated docs" },
  { value: "bad_example", label: "Bad example" },
  { value: "other", label: "Other" },
];

const RATINGS: { value: string; label: string }[] = [
  { value: "useful", label: "Useful — answered my question" },
  { value: "partially_useful", label: "Partially useful" },
  { value: "not_useful", label: "Not useful" },
];

const REASON_CODES: { value: string; label: string }[] = [
  { value: "accurate_citation", label: "Accurate, cited answer" },
  { value: "wrong_version", label: "Wrong API version" },
  { value: "missing_example", label: "Missing example" },
  { value: "hallucinated_symbol", label: "Hallucinated symbol" },
  { value: "low_relevance", label: "Low relevance" },
];

/** Visually-hidden style for labels and live-region announcements. */
const SR_ONLY = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0,0,0,0)",
  whiteSpace: "nowrap",
  border: 0,
} as const;

export default function FeedbackReporting() {
  // Shared request_id (links both lanes to stored query evidence).
  const [requestId, setRequestId] = useState("");
  const trimmedRequest = requestId.trim();

  // --- Feedback lane state ---
  const [rating, setRating] = useState(RATINGS[0].value);
  const [reasonCode, setReasonCode] = useState("");
  const [feedbackText, setFeedbackText] = useState("");
  const feedbackMutation = useMutation<
    PublicQueryFeedbackResponse,
    unknown,
    { request_id: string; rating: string; reason_codes?: string[] }
  >({
    mutationFn: (payload) => submitPublicQueryFeedback(payload),
  });

  // --- Issue lane state ---
  const [issueType, setIssueType] = useState(ISSUE_TYPES[0].value);
  const [notes, setNotes] = useState("");
  const issueMutation = useMutation<
    PublicQueryIssueResponse,
    unknown,
    { request_id: string; issue_type: string; notes?: string }
  >({
    mutationFn: (payload) => submitPublicQueryIssue(payload),
  });

  const requestIdId = useId();
  const ratingId = useId();
  const reasonId = useId();
  const feedbackTextId = useId();
  const issueTypeId = useId();
  const notesId = useId();

  const submitFeedback = () => {
    if (!trimmedRequest) return;
    // reason_codes is a string[]; carry the structured reason and any free-text
    // detail together so the operator's note persists with the feedback signal.
    const codes = [reasonCode, feedbackText.trim()].filter(Boolean);
    feedbackMutation.mutate({
      request_id: trimmedRequest,
      rating,
      reason_codes: codes.length ? codes : undefined,
    });
  };

  const submitIssue = () => {
    if (!trimmedRequest) return;
    issueMutation.mutate({
      request_id: trimmedRequest,
      issue_type: issueType,
      notes: notes.trim() || undefined,
    });
  };

  const feedbackError =
    feedbackMutation.error instanceof AdminApiError
      ? feedbackMutation.error.message
      : feedbackMutation.error
        ? "Failed to submit feedback."
        : null;
  const issueError =
    issueMutation.error instanceof AdminApiError
      ? issueMutation.error.message
      : issueMutation.error
        ? "Failed to submit issue report."
        : null;

  const feedbackResult = feedbackMutation.data;
  const issueResult = issueMutation.data;

  return (
    <div className="pub t-mono">
      <section className="pub-card" aria-label="Feedback and issue reporting">
        <div className="pub-card-head">
          <span className="pub-card-title">Feedback &amp; issue reporting</span>
          <span className="right muted-note">links to your query request_id</span>
        </div>

        <div style={{ padding: "16px 20px" }}>
          {/* Shared request_id */}
          <label className="muted-note" htmlFor={requestIdId} style={{ display: "block", marginBottom: 6 }}>
            Request ID
          </label>
          <span className="input" style={{ display: "block", maxWidth: 340 }}>
            <input
              id={requestIdId}
              className="inputctl"
              value={requestId}
              onChange={(e) => setRequestId(e.target.value)}
              placeholder="request_id (from the query playground)"
              aria-label="request_id from the query playground"
            />
          </span>
          {!trimmedRequest && (
            <div className="muted-note" style={{ marginTop: 8, display: "inline-flex", alignItems: "center", gap: 6 }}>
              <Icon name="info" />
              Enter the request_id from a public query to link your report to stored evidence.
            </div>
          )}

          {/* Two-lane layout */}
          <div className="intro-grid" style={{ marginTop: 18 }}>
            {/* LEFT — usefulness feedback */}
            <div className="pub-card" style={{ margin: 0 }}>
              <div className="pub-card-head">
                <span className="pub-card-title" style={{ fontSize: 14 }}>
                  Rate this answer
                </span>
              </div>
              <form
                style={{ padding: "14px 18px" }}
                onSubmit={(e) => {
                  e.preventDefault();
                  submitFeedback();
                }}
              >
                <label style={SR_ONLY} htmlFor={ratingId}>
                  Rating
                </label>
                <span className="select" style={{ display: "block", marginBottom: 10 }}>
                  <select
                    id={ratingId}
                    className="selectctl"
                    value={rating}
                    onChange={(e) => setRating(e.target.value)}
                    aria-label="Rating"
                  >
                    {RATINGS.map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                </span>
                <label style={SR_ONLY} htmlFor={reasonId}>
                  Reason
                </label>
                <span className="select" style={{ display: "block", marginBottom: 12 }}>
                  <select
                    id={reasonId}
                    className="selectctl"
                    value={reasonCode}
                    onChange={(e) => setReasonCode(e.target.value)}
                    aria-label="Reason"
                  >
                    <option value="">No specific reason</option>
                    {REASON_CODES.map((r) => (
                      <option key={r.value} value={r.value}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                </span>
                <label style={SR_ONLY} htmlFor={feedbackTextId}>
                  Feedback detail
                </label>
                <textarea
                  id={feedbackTextId}
                  value={feedbackText}
                  onChange={(e) => setFeedbackText(e.target.value)}
                  placeholder="Optional — what made this answer useful or not?"
                  aria-label="Feedback detail"
                  rows={3}
                  spellCheck
                  style={{
                    display: "block",
                    width: "100%",
                    marginBottom: 12,
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    background: "var(--surface)",
                    padding: "8px 10px",
                    fontFamily: "var(--font-sans)",
                    fontSize: 12.5,
                    color: "var(--fg)",
                    outline: "none",
                    resize: "vertical",
                  }}
                />
                <Button
                  type="submit"
                  variant="btn-primary"
                  icon="check"
                  disabled={feedbackMutation.isPending || !trimmedRequest}
                >
                  {feedbackMutation.isPending ? "Submitting…" : "Submit feedback"}
                </Button>
                <div style={{ marginTop: 12 }} role="status" aria-live="polite">
                  {feedbackError ? (
                    <div
                      className="pub-status-led"
                      style={{ background: "var(--crit-bg)", color: "var(--crit)" }}
                      role="alert"
                    >
                      <span className="led" style={{ background: "var(--crit)", animation: "none" }} />
                      {feedbackError}
                    </div>
                  ) : feedbackResult ? (
                    <Banner
                      variant="ok"
                      icon="check"
                      title={feedbackResult.updated_existing ? "Feedback updated" : "Feedback recorded"}
                      text={`Thanks — usefulness feedback for ${feedbackResult.request_id} was saved.`}
                    />
                  ) : null}
                </div>
              </form>
            </div>

            {/* RIGHT — documentation issue */}
            <div className="pub-card" style={{ margin: 0 }}>
              <div className="pub-card-head">
                <span className="pub-card-title" style={{ fontSize: 14 }}>
                  Report a documentation issue
                </span>
              </div>
              <form
                style={{ padding: "14px 18px" }}
                onSubmit={(e) => {
                  e.preventDefault();
                  submitIssue();
                }}
              >
                <label style={SR_ONLY} htmlFor={issueTypeId}>
                  Issue type
                </label>
                <span className="select" style={{ display: "block", marginBottom: 10 }}>
                  <select
                    id={issueTypeId}
                    className="selectctl"
                    value={issueType}
                    onChange={(e) => setIssueType(e.target.value)}
                    aria-label="Issue type"
                  >
                    {ISSUE_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                </span>
                <label style={SR_ONLY} htmlFor={notesId}>
                  Notes
                </label>
                <textarea
                  id={notesId}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Optional notes — what was wrong or missing"
                  aria-label="Optional notes"
                  rows={3}
                  spellCheck
                  style={{
                    display: "block",
                    width: "100%",
                    marginBottom: 12,
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    background: "var(--surface)",
                    padding: "8px 10px",
                    fontFamily: "var(--font-sans)",
                    fontSize: 12.5,
                    color: "var(--fg)",
                    outline: "none",
                    resize: "vertical",
                  }}
                />
                <Button
                  type="submit"
                  variant="btn-primary"
                  icon="alert"
                  disabled={issueMutation.isPending || !trimmedRequest}
                >
                  {issueMutation.isPending ? "Reporting…" : "Report issue"}
                </Button>
                <div style={{ marginTop: 12 }} role="status" aria-live="polite">
                  {issueError ? (
                    <div
                      className="pub-status-led"
                      style={{ background: "var(--crit-bg)", color: "var(--crit)" }}
                      role="alert"
                    >
                      <span className="led" style={{ background: "var(--crit)", animation: "none" }} />
                      {issueError}
                    </div>
                  ) : issueResult ? (
                    <Banner
                      variant="ok"
                      icon="check"
                      title={issueResult.updated_existing ? "Issue updated" : "Issue recorded"}
                      text={`The content team will triage report ${issueResult.request_id}.`}
                    />
                  ) : null}
                </div>
              </form>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
