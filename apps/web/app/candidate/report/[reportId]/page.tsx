import Link from "next/link";

import { ScoreBar } from "@/components/score-bar";
import { SectionCard } from "@/components/section-card";
import { ActionLink, EmptyState, MetricCard, PageSection, StatusPill, Surface } from "@/components/ui";
import { serverApiFetch } from "@/lib/server-api";

type CandidateReportResponse = {
  report: {
    id: string;
    status: string;
    is_portable: boolean;
    candidate_summary: {
      track: {
        title: string;
        version: string;
        duration_minutes: number;
      };
      submission: {
        automated_score: {
          total_score: number;
          correctness_score: number;
          quality_score: number;
        };
        benchmark_summary: {
          overall_percentile: number | null;
          cohort_size: number;
          benchmark_state?: string | null;
        };
      };
      timeline_summary: {
        work_pattern_summary: string;
        integrity: {
          flags: string[];
          confidence_score: number;
          ai_usage_summary: string;
          review_signals?: Array<{
            key: string;
            label: string;
            severity: string;
          }>;
        };
        timeline: Array<{
          at: string;
          label: string;
          type: string;
        }>;
      };
      review_status: {
        state: string;
        portable: boolean;
      };
      candidate_reflection?: {
        summary_note?: string;
        tradeoff_note?: string;
        unfinished_work_note?: string;
        submission_checklist?: Record<string, boolean>;
      };
      next_steps: string[];
    };
  };
};

export default async function CandidateReportPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;
  const data = await serverApiFetch<CandidateReportResponse>(`/candidate/reports/${reportId}`, { devAuthRole: "candidate" });

  if (!data) {
    return (
      <main className="page-stack">
        <PageSection>
          <EmptyState
            action={<ActionLink href="/candidate/access">Access your assignment</ActionLink>}
            description="Candidate reports now load from your authenticated session rather than a typed-in demo identity."
            eyebrow="Published artifact"
            title="Artifact unavailable"
          />
        </PageSection>
      </main>
    );
  }

  const { report } = data;
  const summary = report.candidate_summary;
  const integrity = summary.timeline_summary.integrity;
  const percentileLabel = summary.submission.benchmark_summary.overall_percentile ?? "Building benchmark context";
  const reviewStateLabel = summary.review_status.state.replaceAll("_", " ");
  const candidateReadout = report.is_portable
    ? "This report is portable now. Companies can read the artifact as a reviewed piece of engineering evidence."
    : "This report is still controlled. The code is submitted, but employer-facing portability depends on review and publication.";
  const signalLabels =
    integrity.review_signals?.length
      ? integrity.review_signals.map((signal) => `${signal.label} (${signal.severity})`)
      : integrity.flags.length
        ? integrity.flags
        : ["No active trust concerns"];
  const reflection = summary.candidate_reflection;

  return (
    <main className="page-stack">
      <PageSection>
        <Surface className="hero-gradient p-8">
          <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-3">
                <StatusPill tone="accent">Published artifact</StatusPill>
                <StatusPill tone={report.is_portable ? "success" : "warning"}>{report.is_portable ? "Portable" : "Awaiting publication"}</StatusPill>
                <StatusPill tone="neutral">Review state: {reviewStateLabel}</StatusPill>
              </div>
              <div className="space-y-4">
                <h1 className="text-5xl font-semibold tracking-tight text-white">{summary.track.title}</h1>
                <p className="max-w-3xl text-base leading-8 text-slate-400">
                  This report should answer two questions quickly: what did you build, and how will an employer read it? Everything else is supporting
                  evidence.
                </p>
              </div>
              <div className="flex flex-wrap gap-3 text-sm text-slate-500">
                <span>{summary.track.version}</span>
                <span>•</span>
                <span>{summary.track.duration_minutes} minute target</span>
                <span>•</span>
                <strong data-testid="candidate-report-review-state" className="font-medium text-slate-100">
                  {summary.review_status.state}
                </strong>
              </div>
              <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Current read</div>
                <p className="mt-3 text-base leading-7 text-slate-300">{candidateReadout}</p>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-1">
              <MetricCard label="Review state" supporting="Where the report currently sits in the publication flow" value={reviewStateLabel} />
              <MetricCard label="Portable status" supporting="Whether employers can use this as a shareable hiring artifact yet" value={report.is_portable ? "shareable" : "held for review"} />
              <MetricCard label="Signal score" supporting={`${summary.submission.benchmark_summary.cohort_size} reports currently in this cohort`} value={summary.submission.automated_score.total_score} />
            </div>
          </div>
        </Surface>
      </PageSection>

      <PageSection>
        <div className="grid gap-6 lg:grid-cols-[1fr_0.92fr]">
          <SectionCard eyebrow="Interpretation" title="What this report says right now">
            <p className="text-base leading-7 text-slate-300">
              The top-level judgment is intentionally plainspoken. A strong report should tell you where you stand before anyone dives into benchmarks or
              trace detail.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">How employers are likely to read it</div>
                <div className="mt-2 text-sm font-medium text-slate-100">{summary.timeline_summary.work_pattern_summary}</div>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Benchmark context</div>
                <div className="mt-2 text-sm font-medium text-slate-100">{percentileLabel}</div>
              </div>
            </div>
            <div className="space-y-3">
              {summary.next_steps.map((step) => (
                <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-400" key={step}>
                  {step}
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard eyebrow="Strengths" title="Signals visible in the work">
            <ScoreBar label="Correctness and reliability" score={summary.submission.automated_score.correctness_score} />
            <ScoreBar label="Project polish" score={summary.submission.automated_score.quality_score} />
            <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
              <div className="text-sm font-medium text-slate-100">Why this helps you</div>
              <p className="mt-3 text-sm leading-7 text-slate-400">
                Strong reports reward legibility. They make it easy for a hiring team to understand your decisions, not just your raw output.
              </p>
            </div>
          </SectionCard>
        </div>
      </PageSection>

      {reflection && (reflection.summary_note || reflection.tradeoff_note || reflection.unfinished_work_note) ? (
        <PageSection>
          <SectionCard eyebrow="Candidate reflection" title="What you said about the work">
            <div className="grid gap-4 lg:grid-cols-3">
              <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">What changed</div>
                <p className="mt-3 text-sm leading-7 text-slate-300">{reflection.summary_note || "No summary provided."}</p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Tradeoff made</div>
                <p className="mt-3 text-sm leading-7 text-slate-300">{reflection.tradeoff_note || "No tradeoff provided."}</p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Still unfinished</div>
                <p className="mt-3 text-sm leading-7 text-slate-300">{reflection.unfinished_work_note || "No follow-up provided."}</p>
              </div>
            </div>
          </SectionCard>
        </PageSection>
      ) : null}

      <PageSection>
        <div className="grid gap-6 lg:grid-cols-[1fr_0.88fr]">
          <SectionCard eyebrow="Trust" title="Publication signals">
            <p className="text-sm leading-7 text-slate-400">{integrity.ai_usage_summary}</p>
            <div className="flex flex-wrap gap-2">
              {signalLabels.map((flag) => (
                <StatusPill key={flag} tone={flag === "No active trust concerns" ? "neutral" : "warning"}>
                  {flag}
                </StatusPill>
              ))}
            </div>
            <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
              <div className="text-sm font-medium text-slate-100">Why this matters</div>
              <p className="mt-3 text-sm leading-7 text-slate-400">
                Trust signals exist to protect the artifact, not to turn it into surveillance. The goal is to make your published work legible and credible.
              </p>
            </div>
          </SectionCard>

          <SectionCard eyebrow="Share" title="What happens next">
            <p className="text-sm leading-7 text-slate-400">
              The report is meant to travel with context. Review state, portability, and trust posture matter more than inflated marketing language.
            </p>
            <div className="flex flex-wrap gap-3">
              <ActionLink href="/candidate/dashboard">Back to portfolio</ActionLink>
              <Link className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.07]" href="/candidate/assignments/warehouse-ops-api-v1">
                View project brief
              </Link>
            </div>
          </SectionCard>
        </div>
      </PageSection>

      <PageSection>
        <SectionCard eyebrow="Build timeline" title="Visible build history">
          <div className="grid gap-3">
            {summary.timeline_summary.timeline.map((item) => (
              <div className="rounded-[28px] border border-white/10 bg-white/[0.03] p-4" key={`${item.at}-${item.type}`}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-100">{item.type}</div>
                    <div className="mt-1 text-sm text-slate-400">{item.label}</div>
                  </div>
                  <div className="font-mono text-xs text-slate-500">{item.at}</div>
                </div>
              </div>
            ))}
          </div>
        </SectionCard>
      </PageSection>
    </main>
  );
}
