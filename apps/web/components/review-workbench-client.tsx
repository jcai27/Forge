"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiSend } from "@/lib/api";
import { cn } from "@/lib/utils";

type AccessToken = {
  token: string;
  access_type: string;
  status: string;
  expires_at: string | null;
};

type Assignment = {
  id: string;
  reviewer_id: string;
  status: string;
  due_at: string | null;
} | null;

type Review = {
  id: string;
  reviewer_id: string;
  decision: string;
  confidence: number;
  notes: string;
  reviewer_annotations?: {
    strongest_signal?: string;
    biggest_concern?: string;
    recommended_interview_focus?: string;
    publish_or_restrict_reason?: string;
  };
  state: string;
  escalation_state: string;
} | null;

function toneForStatus(value: string | null | undefined) {
  if (!value) return "border-white/10 bg-white/[0.03] text-slate-400";
  if (value.includes("published") || value.includes("portable") || value.includes("human_reviewed")) return "border-emerald-500/25 bg-emerald-500/12 text-emerald-300";
  if (value.includes("review") || value.includes("claimed")) return "border-sky-500/25 bg-sky-500/12 text-sky-300";
  if (value.includes("flagged") || value.includes("second")) return "border-amber-500/25 bg-amber-500/12 text-amber-300";
  if (value.includes("revoked") || value.includes("failed")) return "border-rose-500/25 bg-rose-500/12 text-rose-300";
  return "border-white/10 bg-white/[0.03] text-slate-300";
}

const rubricAnchors = [
  {
    label: "Strong",
    detail: "Core behavior is correct, evidence is fresh, and the candidate explains tradeoffs clearly enough that an interview can build from the artifact.",
  },
  {
    label: "Mixed",
    detail: "Important signal is present, but there is still meaningful ambiguity around correctness, completeness, or judgment under pressure.",
  },
  {
    label: "Weak",
    detail: "The artifact does not yet support a confident hiring read because the implementation, evidence, or explanation is too incomplete.",
  },
] as const;

export function ReviewWorkbenchClient({
  reportId,
  submissionId,
  reviewState,
  publicationState,
  assignment,
  review,
  accessTokens,
}: {
  reportId: string;
  submissionId: string;
  reviewState: string;
  publicationState: string | null;
  assignment: Assignment;
  review: Review;
  accessTokens: AccessToken[];
}) {
  const router = useRouter();
  const [decision, setDecision] = useState(review?.decision ?? "interview");
  const [notes, setNotes] = useState(review?.notes ?? "");
  const [strongestSignal, setStrongestSignal] = useState(review?.reviewer_annotations?.strongest_signal ?? "");
  const [biggestConcern, setBiggestConcern] = useState(review?.reviewer_annotations?.biggest_concern ?? "");
  const [recommendedInterviewFocus, setRecommendedInterviewFocus] = useState(review?.reviewer_annotations?.recommended_interview_focus ?? "");
  const [publishReason, setPublishReason] = useState(review?.reviewer_annotations?.publish_or_restrict_reason ?? "");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function claim() {
    setBusyKey("claim");
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

  async function release() {
    setBusyKey("release");
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

  async function saveDraft() {
    setBusyKey("draft");
    setError(null);
    try {
      await apiSend("/employer/reviews", {
        method: "POST",
        body: JSON.stringify({
          submission_id: submissionId,
          decision,
          confidence: review?.confidence ?? 0.75,
          rubric_scores: [],
          notes,
          reviewer_annotations: {
            strongest_signal: strongestSignal,
            biggest_concern: biggestConcern,
            recommended_interview_focus: recommendedInterviewFocus,
            publish_or_restrict_reason: publishReason,
          },
        }),
      });
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save draft review.");
    } finally {
      setBusyKey(null);
    }
  }

  async function publish() {
    if (!review?.id) return;
    setBusyKey("publish");
    setError(null);
    try {
      await apiSend("/internal/reviews/publish", {
        method: "POST",
        body: JSON.stringify({
          review_id: review.id,
          visibility: "unlisted",
        }),
      });
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to publish review.");
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

  const reportToken = accessTokens.find((token) => token.access_type === "report" && token.status === "active");
  const previewToken = accessTokens.find((token) => token.access_type === "preview" && token.status === "active");

  return (
    <div className="space-y-5">
      <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Reviewer session</div>
        <div className="mt-3 rounded-2xl border border-white/10 bg-[#0b0e15] px-4 py-3 text-sm text-slate-300">
          Authenticated reviewer context
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <span className={cn("inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium", toneForStatus(reviewState))}>{reviewState}</span>
          <span className={cn("inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium", toneForStatus(publicationState ?? "draft"))}>
            {publicationState ?? "draft"}
          </span>
          <span className={cn("inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium", toneForStatus(assignment?.status ?? "unassigned"))}>
            {assignment ? `${assignment.reviewer_id} / ${assignment.status}` : "unassigned"}
          </span>
        </div>
      </div>

      {error ? <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{error}</div> : null}

      <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Decision</div>
        <select
          className="mt-3 w-full rounded-2xl border border-white/10 bg-[#0b0e15] px-4 py-3 text-sm text-white outline-none transition focus:border-indigo-400/40"
          onChange={(event) => setDecision(event.target.value)}
          value={decision}
        >
          <option value="advance">advance</option>
          <option value="interview">interview</option>
          <option value="reject">reject</option>
          <option value="offer">offer</option>
        </select>
        <div className="mt-4 rounded-[24px] border border-white/10 bg-[#0b0e15] p-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Rubric anchors</div>
          <div className="mt-3 grid gap-3">
            {rubricAnchors.map((anchor) => (
              <div className="rounded-[18px] border border-white/10 bg-white/[0.03] p-3" key={anchor.label}>
                <div className="text-xs font-semibold text-white">{anchor.label}</div>
                <p className="mt-2 text-xs leading-5 text-slate-400">{anchor.detail}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-4 rounded-[24px] border border-white/10 bg-[#0b0e15] p-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Fast review loop</div>
          <div className="mt-3 space-y-2 text-xs text-slate-400">
            <div className="rounded-[18px] border border-white/10 bg-white/[0.03] px-3 py-2">1. Decide whether the candidate should advance.</div>
            <div className="rounded-[18px] border border-white/10 bg-white/[0.03] px-3 py-2">2. Capture the strongest signal and biggest concern in concrete language.</div>
            <div className="rounded-[18px] border border-white/10 bg-white/[0.03] px-3 py-2">3. Tell the hiring team what to probe next before you publish.</div>
          </div>
        </div>
        <label className="mt-4 block text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Reviewer notes</label>
        <textarea
          className="mt-2 min-h-[180px] w-full rounded-[24px] border border-white/10 bg-[#0b0e15] px-4 py-4 text-sm text-white outline-none transition focus:border-indigo-400/40"
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Summarize product judgment, quality, risk, and what should happen next."
          rows={7}
          value={notes}
        />
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Strongest signal</label>
            <textarea
              className="mt-2 min-h-[110px] w-full rounded-[24px] border border-white/10 bg-[#0b0e15] px-4 py-4 text-sm text-white outline-none transition focus:border-indigo-400/40"
              data-testid={`review-workbench-strongest-signal-${reportId}`}
              onChange={(event) => setStrongestSignal(event.target.value)}
              placeholder="What is the clearest positive signal in this project?"
              rows={4}
              value={strongestSignal}
            />
          </div>
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Biggest concern</label>
            <textarea
              className="mt-2 min-h-[110px] w-full rounded-[24px] border border-white/10 bg-[#0b0e15] px-4 py-4 text-sm text-white outline-none transition focus:border-indigo-400/40"
              data-testid={`review-workbench-biggest-concern-${reportId}`}
              onChange={(event) => setBiggestConcern(event.target.value)}
              placeholder="What risk or weakness matters most?"
              rows={4}
              value={biggestConcern}
            />
          </div>
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Interview focus</label>
            <textarea
              className="mt-2 min-h-[110px] w-full rounded-[24px] border border-white/10 bg-[#0b0e15] px-4 py-4 text-sm text-white outline-none transition focus:border-indigo-400/40"
              data-testid={`review-workbench-interview-focus-${reportId}`}
              onChange={(event) => setRecommendedInterviewFocus(event.target.value)}
              placeholder="What should the hiring team probe next?"
              rows={4}
              value={recommendedInterviewFocus}
            />
          </div>
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Publish or restrict reason</label>
            <textarea
              className="mt-2 min-h-[110px] w-full rounded-[24px] border border-white/10 bg-[#0b0e15] px-4 py-4 text-sm text-white outline-none transition focus:border-indigo-400/40"
              data-testid={`review-workbench-publish-reason-${reportId}`}
              onChange={(event) => setPublishReason(event.target.value)}
              placeholder="Why should this artifact be portable, restricted, or escalated?"
              rows={4}
              value={publishReason}
            />
          </div>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <button
            className="rounded-full bg-[linear-gradient(135deg,#2563eb,#06b6d4)] px-4 py-3 text-sm font-medium text-white shadow-[0_18px_42px_rgba(37,99,235,0.24)] transition hover:-translate-y-0.5 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busyKey !== null}
            onClick={() => void claim()}
            type="button"
          >
            {busyKey === "claim" ? "Claiming..." : "Claim"}
          </button>
          <button
            className="rounded-full border border-white/10 bg-white/[0.03] px-4 py-3 text-sm font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.07] disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busyKey !== null || !assignment}
            onClick={() => void release()}
            type="button"
          >
            {busyKey === "release" ? "Releasing..." : "Release"}
          </button>
          <button
            className="rounded-full border border-white/10 bg-white/[0.03] px-4 py-3 text-sm font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.07] disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busyKey !== null}
            onClick={() => void saveDraft()}
            type="button"
          >
            {busyKey === "draft" ? "Saving..." : "Save draft"}
          </button>
          <button
            className="rounded-full bg-[linear-gradient(135deg,#4338ca,#0ea5e9)] px-4 py-3 text-sm font-medium text-white transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={busyKey !== null || !review?.id}
            onClick={() => void publish()}
            type="button"
          >
            {busyKey === "publish" ? "Publishing..." : "Publish"}
          </button>
        </div>
      </div>

      <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Issued access</div>
        {accessTokens.length ? (
          <div className="mt-4 space-y-3">
            {accessTokens.map((access) => (
              <div className="rounded-3xl border border-white/10 bg-[#0b0e15] p-4" key={access.token}>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium capitalize text-white">{access.access_type}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {access.status} {access.expires_at ? `until ${access.expires_at}` : ""}
                    </div>
                  </div>
                  <span className={cn("inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium", toneForStatus(access.status))}>{access.status}</span>
                </div>
                <code className="mt-3 block overflow-hidden text-ellipsis whitespace-nowrap rounded-2xl border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-slate-500">
                  {access.token}
                </code>
                <button
                  className="mt-3 rounded-full border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.07] disabled:cursor-not-allowed disabled:opacity-60"
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
          <p className="mt-3 text-sm leading-6 text-slate-400">No employer-facing links have been issued yet. Publish the review to create them.</p>
        )}

        {(reportToken || previewToken) && (
          <div className="mt-4 flex flex-wrap gap-3">
            {reportToken ? (
              <Link className="inline-flex items-center rounded-full bg-[linear-gradient(135deg,#8795ff,#9aa7ff)] px-4 py-2.5 text-sm font-medium text-slate-950 transition hover:-translate-y-0.5" href={`/employer/report/${reportToken.token}`}>
                Open employer report
              </Link>
            ) : null}
            {previewToken ? (
              <Link className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.07]" href={`/employer/preview/${previewToken.token}`}>
                Open employer preview
              </Link>
            ) : null}
          </div>
        )}
      </div>

      <Link className="inline-flex text-sm font-medium text-indigo-300 hover:text-indigo-200" href="/admin/review-queue">
        Back to reviewer queue
      </Link>
    </div>
  );
}
