import Link from "next/link";

import { ReviewWorkbenchClient } from "@/components/review-workbench-client";
import { ScoreBar } from "@/components/score-bar";
import { SectionCard } from "@/components/section-card";
import { ActionLink, EmptyState, PageSection, StatusPill, Surface } from "@/components/ui";
import { serverApiFetch } from "@/lib/server-api";

type InternalReportDetailResponse = {
  report: {
    id: string;
    status: string;
    is_portable: boolean;
    review_summary: {
      publication_state?: string | null;
      escalation_state?: string | null;
      review_id?: string | null;
    };
    candidate_summary: {
      track: {
        title: string;
        version: string;
        duration_minutes: number;
      };
      candidate_reflection?: {
        summary_note?: string;
        tradeoff_note?: string;
        unfinished_work_note?: string;
      };
      timeline_summary: {
        work_pattern_summary: string;
        timeline: Array<{
          at: string;
          type: string;
          label: string;
        }>;
      };
    };
    employer_summary: {
      dimension_breakdown: Array<{
        dimension: string;
        score: number;
        evidence: string;
      }>;
      recommended_question: string;
      integrity_summary?: {
        ai_usage_summary?: string;
      };
      artifact_summary: {
        workspace_id: string;
        artifact_uri: string | null;
        artifact_sha: string | null;
        artifact_manifest_uri?: string | null;
      };
      human_review?: {
        decision?: string;
        confidence?: number;
        notes?: string;
        reviewer_annotations?: {
          strongest_signal?: string;
          biggest_concern?: string;
          recommended_interview_focus?: string;
          publish_or_restrict_reason?: string;
        };
        publication_state?: string;
      };
    };
  };
  submission: {
    id: string;
    review_state: string;
    benchmark_summary: {
      overall_percentile: number | null;
      benchmark_state?: string | null;
      cohort_size?: number;
    };
    evidence_summary: Record<string, string>;
    provenance_summary: {
      integrity?: {
        confidence_score?: number;
        flags?: string[];
        review_signals?: Array<{ label: string; severity?: string }>;
        ai_usage_summary?: string;
      };
    };
  };
  session: {
    id: string;
    workspace_id: string;
    status: string;
    preview_summary?: {
      status?: string;
      default_url?: string | null;
    } | null;
  };
  review: {
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
  assignment: {
    id: string;
    reviewer_id: string;
    status: string;
    due_at: string | null;
  } | null;
  access_tokens: Array<{
    token: string;
    access_type: string;
    status: string;
    expires_at: string | null;
  }>;
};

export default async function ReviewEvaluationPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;
  const data = await serverApiFetch<InternalReportDetailResponse>(`/internal/reports/${reportId}`, { devAuthRole: "admin" });

  if (!data) {
    return (
      <main className="page-stack">
        <PageSection>
          <EmptyState
            action={<ActionLink href="/login">Sign in to review</ActionLink>}
            description="Open this page from an authenticated reviewer session after a submission finishes finalization."
            eyebrow="Review detail"
            title="Review detail unavailable"
          />
        </PageSection>
      </main>
    );
  }

  const { report, submission, session, review, assignment, access_tokens } = data;
  const reviewSignals =
    submission.provenance_summary?.integrity?.review_signals?.length
      ? submission.provenance_summary.integrity.review_signals.map((signal) => `${signal.label}${signal.severity ? ` (${signal.severity})` : ""}`)
      : submission.provenance_summary?.integrity?.flags?.length
        ? submission.provenance_summary.integrity.flags
        : ["No active review signals"];
  const benchmarkLabel = submission.benchmark_summary.overall_percentile ?? submission.benchmark_summary.benchmark_state ?? "Benchmark pending";
  const evidenceEntries = Object.entries(submission.evidence_summary ?? {});
  const reviewerMemo = review?.reviewer_annotations ?? report.employer_summary.human_review?.reviewer_annotations ?? {};
  const candidateReflection = report.candidate_summary.candidate_reflection;
  const candidateReflectionPresent = Boolean(candidateReflection?.summary_note || candidateReflection?.tradeoff_note || candidateReflection?.unfinished_work_note);
  const previewStatus = session.preview_summary?.status ?? "not available";
  const trustSignalCount = reviewSignals.length === 1 && reviewSignals[0] === "No active review signals" ? 0 : reviewSignals.length;
  const activeEvidenceCount = evidenceEntries.length;

  return (
    <main className="page-stack">
      <PageSection>
        <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
          <div className="space-y-6">
            <Surface className="hero-gradient p-8">
              <div className="space-y-5">
                <div className="flex flex-wrap items-center gap-3">
                  <StatusPill tone="accent">Live review workstation</StatusPill>
                  <StatusPill tone={report.is_portable ? "success" : "warning"}>{report.is_portable ? "portable" : "controlled"}</StatusPill>
                  <StatusPill>{submission.review_state.replaceAll("_", " ")}</StatusPill>
                </div>
                <div className="space-y-4">
                  <h1 className="text-5xl font-semibold tracking-tight text-white">{report.candidate_summary.track.title}</h1>
                  <p className="max-w-3xl text-base leading-7 text-slate-400">
                    This page is the actual decision surface: interpret the work, compare it against the evidence, and decide whether this report should
                    become shareable.
                  </p>
                </div>
                <div className="grid gap-4 sm:grid-cols-4">
                  {[
                    ["Report", report.id],
                    ["Submission", submission.id],
                    ["Workspace", session.workspace_id],
                    ["Benchmark", String(benchmarkLabel)],
                  ].map(([label, value]) => (
                    <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4" key={label}>
                      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                      <div className="mt-2 break-all text-sm font-medium text-slate-100">{value}</div>
                    </div>
                  ))}
                </div>
              </div>
            </Surface>

            <div className="grid gap-6 lg:grid-cols-[1.08fr_0.92fr]">
              <SectionCard eyebrow="Decision memo" title="What should happen with this candidate">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Recommendation</div>
                    <div className="mt-2 text-xl font-semibold text-white">{review?.decision ?? "not set"}</div>
                  </div>
                  <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Publish state</div>
                    <div className="mt-2 text-xl font-semibold text-white">{report.review_summary.publication_state ?? "draft"}</div>
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {[
                    ["Strongest signal", reviewerMemo.strongest_signal || "Capture this in the structured review before publishing."],
                    ["Biggest concern", reviewerMemo.biggest_concern || "Call out the risk that should shape the interview."],
                    ["Interview focus", reviewerMemo.recommended_interview_focus || report.employer_summary.recommended_question],
                    ["Publish or restrict reason", reviewerMemo.publish_or_restrict_reason || "Explain why this artifact should or should not become portable."],
                  ].map(([label, value]) => (
                    <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4" key={label}>
                      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                      <p className="mt-2 text-sm leading-6 text-slate-300">{value}</p>
                    </div>
                  ))}
                </div>
              </SectionCard>

              <SectionCard eyebrow="Evidence summary" title="What the reviewer can trust quickly">
                <div className="grid gap-3 sm:grid-cols-2">
                  {[
                    ["Checks evidence", activeEvidenceCount ? `${activeEvidenceCount} frozen URI${activeEvidenceCount === 1 ? "" : "s"}` : "No frozen URIs attached"],
                    ["Preview state", previewStatus],
                    ["Candidate reflection", candidateReflectionPresent ? "present" : "missing"],
                    ["Trust signals", trustSignalCount ? `${trustSignalCount} active` : "none active"],
                  ].map(([label, value]) => (
                    <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4" key={label}>
                      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                      <div className="mt-2 text-sm font-medium text-slate-200">{value}</div>
                    </div>
                  ))}
                </div>
                <p className="text-sm leading-7 text-slate-400">
                  Use this summary for speed. The deeper sections below exist to defend the judgment, not to replace the judgment.
                </p>
              </SectionCard>
            </div>

            <div className="grid gap-6 lg:grid-cols-[1.02fr_0.98fr]">
              <SectionCard eyebrow="Summary" title="What the work currently says">
                <p className="text-base leading-7 text-slate-300">{report.candidate_summary.timeline_summary.work_pattern_summary}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Session status</div>
                    <div className="mt-2 text-sm font-medium text-slate-100">{session.status}</div>
                  </div>
                  <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Preview status</div>
                    <div className="mt-2 text-sm font-medium text-slate-100">{session.preview_summary?.status ?? "not available"}</div>
                  </div>
                </div>
                <div className="space-y-3">
                  {reviewSignals.map((signal) => (
                    <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-400" key={signal}>
                      {signal}
                    </div>
                  ))}
                </div>
              </SectionCard>

              <SectionCard eyebrow="Evidence" title="Dimension readout">
                <div className="space-y-3">
                  {report.employer_summary.dimension_breakdown.map((item) => (
                    <ScoreBar key={item.dimension} label={item.dimension.replaceAll("_", " ")} score={item.score} evidence={item.evidence} />
                  ))}
                </div>
              </SectionCard>
            </div>

            <div className="grid gap-6 lg:grid-cols-[1fr_0.92fr]">
              <SectionCard eyebrow="Artifact proof" title="Submission evidence">
                <div className="space-y-3">
                  {[
                    ["Artifact URI", report.employer_summary.artifact_summary.artifact_uri ?? "not attached"],
                    ["Artifact SHA", report.employer_summary.artifact_summary.artifact_sha ?? "not attached"],
                    ["Manifest", report.employer_summary.artifact_summary.artifact_manifest_uri ?? "not attached"],
                  ].map(([label, value]) => (
                    <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4" key={label}>
                      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                      <div className="mt-2 break-all font-mono text-xs text-slate-400">{value}</div>
                    </div>
                  ))}
                </div>
                {evidenceEntries.length ? (
                  <div className="space-y-3">
                    {evidenceEntries.map(([label, value]) => (
                      <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4" key={label}>
                        <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                        <div className="mt-2 break-all font-mono text-xs text-slate-400">{value}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-[24px] border border-dashed border-white/10 bg-white/[0.03] p-4 text-sm text-slate-500">
                    No frozen evidence URIs were attached to this submission.
                  </div>
                )}
              </SectionCard>

              <SectionCard eyebrow="Timeline" title="Visible build trail">
                <div className="space-y-3">
                  {report.candidate_summary.timeline_summary.timeline.length ? (
                    report.candidate_summary.timeline_summary.timeline.map((item) => (
                      <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4" key={`${item.at}-${item.type}`}>
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold text-slate-100">{item.type}</div>
                            <div className="mt-1 text-sm text-slate-400">{item.label}</div>
                          </div>
                          <div className="font-mono text-xs text-slate-500">{item.at}</div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-[24px] border border-dashed border-white/10 bg-white/[0.03] p-4 text-sm text-slate-500">
                      No timeline events were attached to this submission.
                    </div>
                  )}
                </div>
                <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4 text-sm leading-7 text-slate-400">
                  Suggested follow-up: <strong className="text-slate-100">{report.employer_summary.recommended_question}</strong>
                </div>
                {report.employer_summary.integrity_summary?.ai_usage_summary ? (
                  <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-400">
                    {report.employer_summary.integrity_summary.ai_usage_summary}
                  </div>
                ) : null}
              </SectionCard>
            </div>
          </div>

          <div className="space-y-6 xl:sticky xl:top-28 xl:self-start">
            <ReviewWorkbenchClient
              accessTokens={access_tokens}
              assignment={assignment}
              publicationState={report.review_summary.publication_state ?? null}
              reportId={report.id}
              review={review}
              reviewState={submission.review_state}
              submissionId={submission.id}
            />
            {report.candidate_summary.candidate_reflection ? (
              <SectionCard eyebrow="Candidate reflection" title="Submission context">
                <div className="space-y-3 text-sm leading-7 text-slate-400">
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">What changed</div>
                    <p className="mt-2">{report.candidate_summary.candidate_reflection.summary_note || "Not provided."}</p>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Tradeoff note</div>
                    <p className="mt-2">{report.candidate_summary.candidate_reflection.tradeoff_note || "Not provided."}</p>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Unfinished follow-up</div>
                    <p className="mt-2">{report.candidate_summary.candidate_reflection.unfinished_work_note || "Not provided."}</p>
                  </div>
                </div>
              </SectionCard>
            ) : null}
            {review?.notes ? (
              <SectionCard eyebrow="Latest draft" title="Current reviewer summary">
                <div className="space-y-3 text-sm leading-7 text-slate-400">
                  <p>{review.notes}</p>
                  {review.reviewer_annotations ? (
                    <>
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Strongest signal</div>
                        <p className="mt-2">{review.reviewer_annotations.strongest_signal || "Not provided."}</p>
                      </div>
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Biggest concern</div>
                        <p className="mt-2">{review.reviewer_annotations.biggest_concern || "Not provided."}</p>
                      </div>
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Interview focus</div>
                        <p className="mt-2">{review.reviewer_annotations.recommended_interview_focus || "Not provided."}</p>
                      </div>
                    </>
                  ) : null}
                </div>
              </SectionCard>
            ) : null}
            <SectionCard eyebrow="Navigation" title="Related surfaces">
              <div className="space-y-3">
                <Link className="block rounded-3xl border border-white/10 bg-white/[0.03] px-4 py-4 text-sm font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.07]" href="/admin/review-queue">
                  Back to reviewer queue
                </Link>
                <Link className="block rounded-3xl border border-white/10 bg-white/[0.03] px-4 py-4 text-sm font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.07]" href="/admin/runtime">
                  Inspect runtime health
                </Link>
              </div>
            </SectionCard>
          </div>
        </div>
      </PageSection>
    </main>
  );
}
