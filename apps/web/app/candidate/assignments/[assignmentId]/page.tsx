import { LaunchAssessmentCard } from "@/components/launch-assessment-card";
import { SectionCard } from "@/components/section-card";
import { PageSection, StatusPill, Surface } from "@/components/ui";
import {
  assignmentChecklist,
  assignmentDeliverables,
  assignmentGuardrails,
  assignmentRequirements,
  assignmentWorkflow,
  canonicalAssignmentBrief,
  rubricDimensions,
} from "@/lib/mock-platform";

export default async function AssignmentDetailPage({
  params,
}: {
  params: Promise<{ assignmentId: string }>;
}) {
  const { assignmentId } = await params;

  return (
    <main className="page-stack">
      <PageSection>
        <div className="grid gap-8 xl:grid-cols-[1fr_320px]">
          <div className="space-y-6">
            <Surface className="hero-gradient p-8">
              <div className="space-y-5">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusPill tone="accent">{assignmentId}</StatusPill>
                  <StatusPill>{canonicalAssignmentBrief.roleFocus}</StatusPill>
                  <StatusPill>{canonicalAssignmentBrief.expectedTime}</StatusPill>
                </div>
                <div className="space-y-4">
                  <p className="page-eyebrow">Candidate assignment</p>
                  <h1 className="regal-title text-5xl font-semibold text-white">{canonicalAssignmentBrief.title} take-home assignment.</h1>
                  <p className="max-w-3xl text-base leading-7 text-slate-400">{canonicalAssignmentBrief.overview}</p>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  {[
                    ["Primary goal", canonicalAssignmentBrief.primaryGoal],
                    ["Success bar", canonicalAssignmentBrief.successBar],
                    ["What matters most", canonicalAssignmentBrief.whatMattersMost],
                  ].map(([label, value]) => (
                    <div className="rounded-[18px] border border-white/10 bg-white/[0.03] p-4" key={label}>
                      <div className="page-eyebrow">{label}</div>
                      <div className="mt-2 text-sm leading-6 text-slate-300">{value}</div>
                    </div>
                  ))}
                </div>
              </div>
            </Surface>

            <SectionCard eyebrow="Brief" title="What you need to do">
              <p>{canonicalAssignmentBrief.framing}</p>
              <div className="grid gap-3">
                {assignmentRequirements.map((requirement) => (
                  <div className="rounded-[18px] border border-white/10 bg-white/[0.02] px-4 py-4 text-sm text-slate-400" key={requirement}>
                    {requirement}
                  </div>
                ))}
              </div>
            </SectionCard>

            <div className="grid gap-6 lg:grid-cols-2">
              <SectionCard eyebrow="Submission" title="What to hand back">
                <div className="space-y-3">
                  {assignmentDeliverables.map((deliverable) => (
                    <div className="rounded-[18px] border border-white/10 bg-white/[0.02] px-4 py-4" key={deliverable}>
                      {deliverable}
                    </div>
                  ))}
                </div>
              </SectionCard>

              <SectionCard eyebrow="Evaluation" title="How the review will read">
                <div className="space-y-3">
                  {rubricDimensions.map((dimension) => (
                    <div className="rounded-[18px] border border-white/10 bg-white/[0.02] p-4" key={dimension.label}>
                      <div className="flex items-center justify-between gap-4">
                        <h3 className="text-sm font-semibold text-white">{dimension.label}</h3>
                        <StatusPill>{dimension.weight}</StatusPill>
                      </div>
                      <p className="mt-2 text-sm leading-6 text-slate-400">{dimension.description}</p>
                    </div>
                  ))}
                </div>
              </SectionCard>
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <SectionCard eyebrow="Guardrails" title="Constraints">
                <div className="space-y-3">
                  {assignmentGuardrails.map((item) => (
                    <div className="rounded-[18px] border border-white/10 bg-white/[0.02] px-4 py-4" key={item}>
                      {item}
                    </div>
                  ))}
                </div>
              </SectionCard>

              <SectionCard eyebrow="Workflow" title="Recommended path">
                <div className="space-y-3">
                  {assignmentWorkflow.map((step, index) => (
                    <div className="rounded-[18px] border border-white/10 bg-white/[0.02] p-4" key={step.title}>
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-full border border-[rgba(199,174,106,0.24)] bg-[rgba(199,174,106,0.1)] text-sm font-semibold text-[#e7d8ab]">
                          {index + 1}
                        </div>
                        <div className="text-sm font-semibold text-white">{step.title}</div>
                      </div>
                      <p className="mt-3 text-sm leading-6 text-slate-400">{step.detail}</p>
                    </div>
                  ))}
                </div>
              </SectionCard>
            </div>
          </div>

          <div className="space-y-6 xl:sticky xl:top-28 xl:self-start">
            <Surface className="p-6">
              <div className="space-y-5">
                <div>
                  <p className="page-eyebrow">Launch</p>
                  <div className="mt-2 text-3xl font-semibold text-white">{canonicalAssignmentBrief.expectedTime}</div>
                </div>
                <div className="rounded-[18px] border border-white/10 bg-white/[0.02] p-4">
                  <p className="page-eyebrow">Environment</p>
                  <div className="mt-3 space-y-3">
                    {canonicalAssignmentBrief.environmentFacts.map(([label, value]) => (
                      <div key={label}>
                        <div className="page-eyebrow text-slate-400">{label}</div>
                        <div className="mt-1 text-sm font-medium text-slate-200">{value}</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="space-y-3">
                  <p className="page-eyebrow">Checklist</p>
                  {assignmentChecklist.map((item, index) => (
                    <div className="flex items-start gap-3 rounded-[18px] border border-white/10 bg-white/[0.02] px-4 py-3 text-sm text-slate-400" key={item}>
                      <div className="mt-0.5 flex h-5 w-5 items-center justify-center rounded-full border border-white/10 bg-white/[0.03] text-[11px] font-semibold text-slate-500">
                        {index + 1}
                      </div>
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
                <div className="text-sm text-slate-500">
                  Reviewers will see your code, checks, timeline, AI usage summary, and short reflection.
                </div>
              </div>
            </Surface>

            <LaunchAssessmentCard />
          </div>
        </div>
      </PageSection>
    </main>
  );
}
