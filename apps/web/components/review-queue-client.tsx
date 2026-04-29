"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { apiSend } from "@/lib/api";
import { cn } from "@/lib/utils";

type QueueItem = {
  report_id: string;
  submission_id: string;
  review_id: string | null;
  review_state: string;
  report_status: string;
  automated_total_score: number;
  integrity_flags: string[];
  review_signals: Array<{ label: string }>;
  benchmark_percentile: number | null;
  benchmark_state: string | null;
  assignment: {
    id: string;
    reviewer_id: string;
    status: string;
    due_at: string | null;
  } | null;
  sla_state: string;
  escalation_state: string | null;
  publication_state: string | null;
  portable: boolean;
  access_tokens: Array<{
    token: string;
    access_type: string;
    status: string;
    expires_at: string | null;
  }>;
};

function toneForStatus(value: string | null | undefined) {
  if (!value) return "border-white/10 bg-white/[0.03] text-slate-400";
  if (value.includes("published") || value.includes("portable") || value.includes("human_reviewed")) return "border-emerald-500/25 bg-emerald-500/12 text-emerald-300";
  if (value.includes("review") || value.includes("claimed") || value.includes("active")) return "border-sky-500/25 bg-sky-500/12 text-sky-300";
  if (value.includes("flagged") || value.includes("second") || value.includes("pending")) return "border-amber-500/25 bg-amber-500/12 text-amber-300";
  if (value.includes("revoked") || value.includes("failed") || value.includes("draft")) return "border-white/10 bg-white/[0.03] text-slate-400";
  return "border-white/10 bg-white/[0.03] text-slate-300";
}

function compactTime(value: string | null) {
  if (!value) return "now";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diffMs = Date.now() - date.getTime();
  const diffMinutes = Math.max(0, Math.floor(diffMs / 60000));
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.floor(diffHours / 24)}d ago`;
}

export function ReviewQueueClient({ items }: { items: QueueItem[] }) {
  const router = useRouter();
  const [notesBySubmission, setNotesBySubmission] = useState<Record<string, string>>({});
  const [decisionBySubmission, setDecisionBySubmission] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const initialSelection = items[0]?.report_id ?? null;
  const [selectedReportId, setSelectedReportId] = useState<string | null>(initialSelection);
  const selectedItem = useMemo(() => items.find((item) => item.report_id === selectedReportId) ?? items[0] ?? null, [items, selectedReportId]);

  async function claim(submissionId: string) {
    setBusyKey(`claim:${submissionId}`);
    setError(null);
    try {
      await apiSend("/internal/reviewer/assignments/claim", {
        method: "POST",
        body: JSON.stringify({ submission_id: submissionId }),
      });
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to claim review.");
    } finally {
      setBusyKey(null);
    }
  }

  async function release(submissionId: string) {
    setBusyKey(`release:${submissionId}`);
    setError(null);
    try {
      await apiSend(`/internal/reviewer/assignments/${submissionId}/release`, {
        method: "POST",
      });
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to release review.");
    } finally {
      setBusyKey(null);
    }
  }

  async function saveDraft(submissionId: string) {
    setBusyKey(`draft:${submissionId}`);
    setError(null);
    try {
      await apiSend("/employer/reviews", {
        method: "POST",
        body: JSON.stringify({
          submission_id: submissionId,
          decision: decisionBySubmission[submissionId] ?? "interview",
          confidence: 0.75,
          rubric_scores: [],
          notes: notesBySubmission[submissionId] ?? "",
          reviewer_annotations: {},
        }),
      });
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save draft review.");
    } finally {
      setBusyKey(null);
    }
  }

  async function publish(reviewId: string) {
    setBusyKey(`publish:${reviewId}`);
    setError(null);
    try {
      await apiSend("/internal/reviews/publish", {
        method: "POST",
        body: JSON.stringify({
          review_id: reviewId,
          visibility: "unlisted",
        }),
      });
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to publish report.");
    } finally {
      setBusyKey(null);
    }
  }

  async function revoke(token: string) {
    setBusyKey(`revoke:${token}`);
    setError(null);
    try {
      await apiSend(`/internal/report-access/${token}/revoke`, {
        method: "POST",
        body: JSON.stringify({ reason: "manual revoke" }),
      });
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to revoke access.");
    } finally {
      setBusyKey(null);
    }
  }

  if (!items.length) {
    return (
      <div className="rounded-[32px] border border-dashed border-white/10 bg-white/[0.03] px-8 py-12 text-center text-slate-400">
        No pending submissions yet. Launch a candidate flow, submit work, and return once finalization completes.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 rounded-[28px] border border-white/10 bg-white/[0.03] p-5 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Reviewer session</div>
          <p className="mt-2 text-sm leading-6 text-slate-400">Queue actions now run as the signed-in reviewer. Claim, draft, publish, and revoke all derive ownership from your session.</p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-[#0b0e15] px-4 py-3 text-sm text-slate-300 xl:max-w-xs">
          Authenticated reviewer context
        </div>
      </div>

      {error ? <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{error}</div> : null}

      <div className="overflow-hidden rounded-[32px] border border-white/10 bg-[#12151d] shadow-[0_20px_60px_rgba(0,0,0,0.22)]">
        <div className="hidden grid-cols-[2.2fr_1.6fr_0.9fr_1fr_1fr_1fr] gap-4 border-b border-white/10 px-8 py-6 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500 lg:grid">
          <div>Assignment</div>
          <div>Owner</div>
          <div>Score</div>
          <div>Status</div>
          <div>Last activity</div>
          <div className="text-right">Open</div>
        </div>

        <div className="divide-y divide-white/8">
          {items.map((item) => {
            const signals = item.review_signals.length ? item.review_signals.map((signal) => signal.label) : item.integrity_flags.length ? item.integrity_flags : ["no active signals"];
            const isSelected = selectedItem?.report_id === item.report_id;

            return (
              <section data-testid={`review-queue-item-${item.report_id}`} key={item.report_id}>
                <button
                  className={cn(
                    "w-full px-6 py-6 text-left transition hover:bg-white/[0.03] lg:px-8",
                    isSelected ? "bg-white/[0.025]" : "bg-transparent",
                  )}
                  onClick={() => setSelectedReportId(item.report_id)}
                  type="button"
                >
                  <div className="grid gap-4 lg:grid-cols-[2.2fr_1.6fr_0.9fr_1fr_1fr_1fr] lg:items-center">
                    <div className="min-w-0">
                      <div className="text-2xl font-medium text-white">{item.submission_id}</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {signals.slice(0, 2).map((signal) => (
                          <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[11px] text-slate-400" key={signal}>
                            {signal}
                          </span>
                        ))}
                      </div>
                      <div className="mt-3 font-mono text-xs text-slate-500">report {item.report_id}</div>
                    </div>

                    <div>
                      <div
                        className="text-lg text-slate-300"
                        data-testid={`queue-assignment-state-${item.report_id}`}
                      >
                        {item.assignment ? `${item.assignment.reviewer_id} / ${item.assignment.status}` : "unassigned"}
                      </div>
                      <div className="mt-1 text-sm text-slate-500">{item.sla_state}</div>
                    </div>

                    <div className="text-4xl font-semibold tracking-tight text-white">{item.automated_total_score}</div>

                    <div className="flex flex-wrap gap-2">
                      <span
                        className={cn("inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium", toneForStatus(item.review_state))}
                        data-testid={`queue-review-state-${item.report_id}`}
                      >
                        {item.review_state}
                      </span>
                      <span
                        className={cn("inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium", toneForStatus(item.publication_state ?? "draft"))}
                        data-testid={`queue-publication-state-${item.report_id}`}
                      >
                        {item.publication_state ?? "draft"}
                      </span>
                    </div>

                    <div className="text-lg text-slate-400">{compactTime(item.assignment?.due_at ?? null)}</div>

                    <div className="text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-white transition hover:bg-white/7 disabled:cursor-not-allowed disabled:opacity-60"
                          data-testid={`claim-review-${item.report_id}`}
                          disabled={busyKey !== null}
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedReportId(item.report_id);
                            void claim(item.submission_id);
                          }}
                          type="button"
                        >
                          {busyKey === `claim:${item.submission_id}` ? "Claiming..." : "Claim"}
                        </button>
                        <span className="inline-flex items-center text-lg text-slate-300">Open</span>
                      </div>
                    </div>
                  </div>
                </button>

                {isSelected ? (
                  <div className="border-t border-white/8 bg-[#0d1018] px-6 py-6 lg:px-8">
                    <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
                      <div className="space-y-5">
                        <div className="grid gap-4 sm:grid-cols-3">
                          {[
                            ["Benchmark", item.benchmark_percentile ?? item.benchmark_state ?? "pending"],
                            ["Escalation", item.escalation_state ?? "none"],
                            ["Portability", item.portable ? "portable" : "controlled"],
                          ].map(([label, value]) => (
                            <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4" key={label}>
                              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                              <div className="mt-2 text-sm font-medium text-slate-200">{value}</div>
                            </div>
                          ))}
                        </div>

                        <div className="grid gap-4 sm:grid-cols-4">
                          {[
                            ["Automated score", String(item.automated_total_score)],
                            ["Trust signals", String(signals.length)],
                            ["Active links", String(item.access_tokens.filter((access) => access.status === "active").length)],
                            ["Review state", item.review_state.replaceAll("_", " ")],
                          ].map(([label, value]) => (
                            <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4" key={label}>
                              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                              <div className="mt-2 text-sm font-medium text-slate-200">{value}</div>
                            </div>
                          ))}
                        </div>

                        <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Queue evidence snapshot</div>
                          <p className="mt-2 text-sm leading-6 text-slate-400">
                            Use the queue for triage, ownership, and a quick draft note. Use the full review page for the structured decision memo, candidate reflection, and final publish judgment.
                          </p>
                          <div className="mt-3 flex flex-wrap gap-2">
                            {signals.map((signal) => (
                              <span className="rounded-full border border-white/10 bg-[#0b0e15] px-3 py-1 text-xs text-slate-300" key={signal}>
                                {signal}
                              </span>
                            ))}
                          </div>
                        </div>

                        <div className="grid gap-4 sm:grid-cols-2">
                          <div>
                            <label className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Decision</label>
                            <select
                              className="mt-2 w-full rounded-2xl border border-white/10 bg-[#0b0e15] px-4 py-3 text-sm text-white outline-none transition focus:border-indigo-400/40"
                              data-testid={`review-decision-${item.report_id}`}
                              onChange={(event) => setDecisionBySubmission((current) => ({ ...current, [item.submission_id]: event.target.value }))}
                              value={decisionBySubmission[item.submission_id] ?? "interview"}
                            >
                              <option value="advance">advance</option>
                              <option value="interview">interview</option>
                              <option value="reject">reject</option>
                              <option value="offer">offer</option>
                            </select>
                          </div>
                          <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                            <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Queue summary</div>
                            <div className="mt-2 text-sm font-medium text-slate-200">{item.review_state.replaceAll("_", " ")}</div>
                            <div className="mt-1 text-sm text-slate-500">report status {item.report_status}</div>
                          </div>
                        </div>

                        <div>
                          <label className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Reviewer notes</label>
                          <textarea
                            className="mt-2 min-h-[150px] w-full rounded-[24px] border border-white/10 bg-[#0b0e15] px-4 py-4 text-sm text-white outline-none transition focus:border-indigo-400/40"
                            data-testid={`review-notes-${item.report_id}`}
                            onChange={(event) => setNotesBySubmission((current) => ({ ...current, [item.submission_id]: event.target.value }))}
                            placeholder="Quick triage note. Use the full review page for the structured recommendation."
                            rows={5}
                            value={notesBySubmission[item.submission_id] ?? ""}
                          />
                        </div>

                        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                          <button
                            className="rounded-2xl bg-[linear-gradient(135deg,#2563eb,#06b6d4)] px-4 py-3 text-sm font-medium text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
                            disabled={busyKey !== null}
                            onClick={() => void claim(item.submission_id)}
                            type="button"
                          >
                            {busyKey === `claim:${item.submission_id}` ? "Claiming..." : "Claim"}
                          </button>
                          <button
                            className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm font-medium text-slate-200 transition hover:bg-white/7 disabled:cursor-not-allowed disabled:opacity-60"
                            data-testid={`release-review-${item.report_id}`}
                            disabled={busyKey !== null || !item.assignment}
                            onClick={() => void release(item.submission_id)}
                            type="button"
                          >
                            {busyKey === `release:${item.submission_id}` ? "Releasing..." : "Release"}
                          </button>
                          <button
                            className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm font-medium text-slate-200 transition hover:bg-white/7 disabled:cursor-not-allowed disabled:opacity-60"
                            data-testid={`save-draft-${item.report_id}`}
                            disabled={busyKey !== null}
                            onClick={() => void saveDraft(item.submission_id)}
                            type="button"
                          >
                            {busyKey === `draft:${item.submission_id}` ? "Saving..." : "Save draft"}
                          </button>
                          <button
                            className="rounded-2xl bg-[linear-gradient(135deg,#8795ff,#9aa7ff)] px-4 py-3 text-sm font-medium text-slate-950 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
                            data-testid={`publish-review-${item.report_id}`}
                            disabled={busyKey !== null || !item.review_id}
                            onClick={() => (item.review_id ? void publish(item.review_id) : undefined)}
                            type="button"
                          >
                            {busyKey === `publish:${item.review_id}` ? "Publishing..." : "Publish"}
                          </button>
                        </div>
                      </div>

                      <div className="space-y-4">
                        <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Report detail</div>
                              <div className="mt-2 text-sm text-slate-300">Open the full evaluation surface for deeper rubric evidence and timeline context.</div>
                            </div>
                            <Link className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-sm text-white transition hover:bg-white/7" href={`/admin/reviews/${item.report_id}`}>
                              Open review
                            </Link>
                          </div>
                        </div>

                        {item.access_tokens.length ? (
                          <div className="space-y-3 rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                            <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Issued access</div>
                            {item.access_tokens.map((access) => (
                              <div
                                className="rounded-[22px] border border-white/10 bg-[#0b0e15] p-4"
                                data-testid={`report-access-${item.report_id}-${access.access_type}`}
                                key={access.token}
                              >
                                <div className="flex items-center justify-between gap-3">
                                  <div>
                                    <div className="text-sm font-medium capitalize text-white">{access.access_type}</div>
                                    <div className="mt-1 text-xs text-slate-500">
                                      {access.status} {access.expires_at ? `until ${access.expires_at}` : ""}
                                    </div>
                                  </div>
                                  <span className={cn("inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium", toneForStatus(access.status))}>
                                    {access.status}
                                  </span>
                                </div>
                                <code className="mt-3 block overflow-hidden text-ellipsis whitespace-nowrap rounded-2xl border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-slate-400" data-testid={`report-access-token-${item.report_id}-${access.access_type}`}>
                                  {access.token}
                                </code>
                                <button
                                  className="mt-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm font-medium text-slate-200 transition hover:bg-white/7 disabled:cursor-not-allowed disabled:opacity-60"
                                  data-testid={`revoke-access-${item.report_id}-${access.access_type}`}
                                  disabled={busyKey !== null || access.status !== "active"}
                                  onClick={() => void revoke(access.token)}
                                  type="button"
                                >
                                  {busyKey === `revoke:${access.token}` ? "Revoking..." : "Revoke"}
                                </button>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="rounded-[24px] border border-dashed border-white/10 bg-white/[0.03] p-5 text-sm text-slate-500">
                            No employer-facing access has been issued yet. Publish the review to create report and preview links.
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ) : null}
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}
