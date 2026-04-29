import Link from "next/link";

import { ScoreBar } from "@/components/score-bar";
import { SectionCard } from "@/components/section-card";
import { ActionLink, EmptyState, PageSection, StatusPill, Surface } from "@/components/ui";
import { apiFetch } from "@/lib/api";

type EmployerReportResponse = {
  report: {
    id: string;
    status: string;
    employer_summary: {
      track: {
        title: string;
        version: string;
        role_family: string;
      };
      artifact_summary: {
        workspace_id: string;
        artifact_uri: string | null;
        artifact_sha: string | null;
        artifact_manifest_uri?: string | null;
      };
      dimension_breakdown: Array<{
        dimension: string;
        score: number;
        evidence: string;
      }>;
      integrity_summary: {
        confidence_score: number;
        flags: string[];
        ai_usage_summary: string;
      };
      benchmark_summary: {
        overall_percentile: number | null;
        cohort_size: number;
        benchmark_state?: string | null;
      };
      candidate_reflection?: {
        summary_note?: string;
        tradeoff_note?: string;
        unfinished_work_note?: string;
      };
      preview_available?: boolean;
      preview_access_token?: string | null;
      preview_share_token?: string | null;
      preview_default_path?: string | null;
      report_access_token?: string | null;
      human_review?: {
        decision: string;
        confidence: number;
        notes: string;
        reviewer_annotations?: {
          strongest_signal?: string;
          biggest_concern?: string;
          recommended_interview_focus?: string;
          publish_or_restrict_reason?: string;
        };
        publication_state?: string;
      };
      recommended_question: string;
    };
  };
  submission: {
    review_state: string;
    share_token: string;
  };
};

export default async function EmployerReportPage({
  params,
}: {
  params: Promise<{ shareToken: string }>;
}) {
  const { shareToken } = await params;
  const data = await apiFetch<EmployerReportResponse>(`/employer/reports/${shareToken}`);

  if (!data) {
    return (
      <main className="page-stack">
        <PageSection>
          <EmptyState
            description="Employer access opens only after publication. Until then, this profile stays private to preserve trust."
            eyebrow="Talent profile"
            title="Profile not discoverable yet"
          />
        </PageSection>
      </main>
    );
  }

  const { report, submission } = data;
  const summary = report.employer_summary;
  const previewToken = summary.preview_access_token ?? summary.preview_share_token;
  const percentileLabel = summary.benchmark_summary.overall_percentile ?? "Growing benchmark cohort";
  const decisionLabel = summary.human_review?.decision ?? "review pending";
  const decisionSummary = summary.human_review
    ? `Reviewer recommendation: ${summary.human_review.decision}. This is the fastest way to understand whether the project should move forward.`
    : "The artifact exists, but a reviewer has not attached a hiring recommendation yet.";
  const reviewerAnnotations = summary.human_review?.reviewer_annotations;

  return (
    <main className="page-stack">
      <PageSection>
        <Surface className="hero-gradient p-8">
          <div className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-3">
                <StatusPill tone="accent">Discoverable talent profile</StatusPill>
                <StatusPill tone="success">Published</StatusPill>
                <StatusPill tone="neutral">Decision: {decisionLabel}</StatusPill>
              </div>
              <div className="space-y-4">
                <h1 className="text-5xl font-semibold tracking-tight text-white">{summary.track.title}</h1>
                <p className="max-w-3xl text-base leading-8 text-slate-400">
                  This report is a hiring memo first. It should answer whether the candidate should advance, what signal matters most, where the risk sits, and what the interview should probe next.
                </p>
              </div>
              <div className="flex flex-wrap gap-3 text-sm text-slate-500">
                <span>{summary.track.role_family}</span>
                <span>•</span>
                <span>{summary.track.version}</span>
                <span>•</span>
                <strong data-testid="employer-report-review-state" className="font-medium text-slate-100">
                  {submission.review_state}
                </strong>
              </div>
              <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Hiring memo</div>
                <p className="mt-3 text-base leading-7 text-slate-300">{decisionSummary}</p>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
              {[
                ["Recommendation", decisionLabel, "The top-line hiring call on this artifact."],
                ["Strongest signal", reviewerAnnotations?.strongest_signal || "Reviewer signal not attached yet.", "What the team should believe fastest."],
                ["Biggest concern", reviewerAnnotations?.biggest_concern || "Reviewer concern not attached yet.", "The main reason to slow down or probe deeper."],
                ["Interview focus", reviewerAnnotations?.recommended_interview_focus || summary.recommended_question, "The next thing the interviewer should pressure-test."],
              ].map(([label, value, supporting]) => (
                <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5" key={label}>
                  <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                  <div className="mt-2 text-lg font-semibold text-white" data-testid={label === "Strongest signal" ? "employer-report-strongest-signal" : undefined}>{value}</div>
                  <p className="mt-2 text-sm leading-6 text-slate-400">{supporting}</p>
                </div>
              ))}
            </div>
          </div>
        </Surface>
      </PageSection>

      <PageSection>
        <div className="grid gap-6 lg:grid-cols-[1.02fr_0.98fr]">
          <SectionCard eyebrow="Reviewer perspective" title="What the hiring team should know">
            {summary.human_review ? (
              <div className="space-y-4">
                    <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
                      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Decision signal</div>
                      <div className="mt-2 text-2xl font-semibold text-white" data-testid="employer-report-decision">
                    {summary.human_review.decision}
                  </div>
                      <p className="mt-3 text-sm leading-6 text-slate-400">
                    Use this as the headline interpretation, then validate it against the evidence and the follow-up question below.
                  </p>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                    <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
                      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Confidence</div>
                      <div className="mt-2 text-lg font-semibold text-white">{summary.human_review.confidence}</div>
                    </div>
                    <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
                      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Publication</div>
                      <div className="mt-2 text-sm font-medium text-slate-100" data-testid="employer-report-publication">
                      {summary.human_review.publication_state ?? "restricted"}
                    </div>
                  </div>
                </div>
                <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Reviewer notes</div>
                  <p className="mt-3 text-sm leading-7 text-slate-400" data-testid="employer-report-notes">
                    {summary.human_review.notes}
                  </p>
                </div>
                {reviewerAnnotations ? (
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
                      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Strongest signal</div>
                      <p className="mt-3 text-sm leading-7 text-slate-400">{reviewerAnnotations.strongest_signal || "Not provided."}</p>
                    </div>
                    <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
                      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Biggest concern</div>
                      <p className="mt-3 text-sm leading-7 text-slate-400">{reviewerAnnotations.biggest_concern || "Not provided."}</p>
                    </div>
                    <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
                      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Interview focus</div>
                      <p className="mt-3 text-sm leading-7 text-slate-400">{reviewerAnnotations.recommended_interview_focus || "Not provided."}</p>
                    </div>
                    <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
                      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Publication reason</div>
                      <p className="mt-3 text-sm leading-7 text-slate-400">{reviewerAnnotations.publish_or_restrict_reason || "Not provided."}</p>
                    </div>
                  </div>
                ) : null}
                <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5 text-sm leading-7 text-slate-400">
                  Suggested follow-up: <strong className="text-slate-100">{summary.recommended_question}</strong>
                </div>
              </div>
            ) : (
              <div className="rounded-[28px] border border-dashed border-white/10 bg-white/[0.03] p-8 text-sm text-slate-500">
                Reviewer interpretation has not been attached yet.
              </div>
            )}
          </SectionCard>

          <SectionCard eyebrow="Evidence" title="Why this candidate stands out">
            <p className="text-base leading-7 text-slate-300">
              The strongest employer read is not “interesting project.” It is “clear evidence under realistic constraints.” This section should make that
              evidence easy to scan.
            </p>
            <div className="space-y-3">
              {summary.dimension_breakdown.map((item) => (
                <ScoreBar key={item.dimension} label={item.dimension.replaceAll("_", " ")} score={item.score} evidence={item.evidence} />
              ))}
            </div>
          </SectionCard>
        </div>
      </PageSection>

      <PageSection>
        <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
          <SectionCard eyebrow="Project proof" title="Artifact identity">
            <div className="space-y-3">
              {[
                ["Workspace", summary.artifact_summary.workspace_id],
                ["Artifact URI", summary.artifact_summary.artifact_uri ?? "not attached"],
                ["Artifact SHA", summary.artifact_summary.artifact_sha ?? "not attached"],
                ["Manifest", summary.artifact_summary.artifact_manifest_uri ?? "not attached"],
              ].map(([label, value]) => (
                <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4" key={label}>
                  <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                  <div className="mt-2 break-all font-mono text-xs text-slate-400">{value}</div>
                </div>
              ))}
            </div>
            <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5 text-sm leading-7 text-slate-400">
              Share token: <span className="font-mono text-xs text-slate-300">{submission.share_token}</span>
            </div>
          </SectionCard>

          <SectionCard eyebrow="Trust and access" title="How to use this report">
            <p className="text-sm leading-7 text-slate-400">{summary.integrity_summary.ai_usage_summary}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {[
                ["Trust confidence", String(summary.integrity_summary.confidence_score)],
                ["Benchmark context", String(percentileLabel)],
              ].map(([label, value]) => (
                <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4" key={label}>
                  <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                  <div className="mt-2 text-sm font-medium text-slate-200">{value}</div>
                </div>
              ))}
            </div>
            {summary.candidate_reflection ? (
              <div className="grid gap-3">
                {[
                  ["Candidate summary", summary.candidate_reflection.summary_note || "Not provided."],
                  ["Tradeoff note", summary.candidate_reflection.tradeoff_note || "Not provided."],
                  ["Unfinished follow-up", summary.candidate_reflection.unfinished_work_note || "Not provided."],
                ].map(([label, value]) => (
                  <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4" key={label}>
                    <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                    <p className="mt-2 text-sm leading-7 text-slate-400">{value}</p>
                  </div>
                ))}
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              {(summary.integrity_summary.flags.length ? summary.integrity_summary.flags : ["No active trust concerns"]).map((flag) => (
                <StatusPill key={flag} tone={flag === "No active trust concerns" ? "neutral" : "warning"}>
                  {flag}
                </StatusPill>
              ))}
            </div>
            <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5 text-sm leading-7 text-slate-400">
              Use the report for fast screening, then go deeper with the preview, artifact metadata, and the reviewer’s recommended follow-up question.
            </div>
            <div className="flex flex-wrap gap-3">
              {summary.preview_available && previewToken ? <ActionLink href={`/employer/preview/${previewToken}`}>Open project preview</ActionLink> : null}
              <ActionLink href="/discover" tone="secondary">
                Back to discovery
              </ActionLink>
            </div>
          </SectionCard>
        </div>
      </PageSection>
    </main>
  );
}
