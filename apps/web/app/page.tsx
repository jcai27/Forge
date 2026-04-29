import { ActionLink, PageSection, StatusPill, Surface } from "@/components/ui";

export default function HomePage() {
  return (
    <main className="page-stack">
      <PageSection>
        <div className="space-y-8">
          <Surface className="hero-gradient p-8">
            <div className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr]">
              <div className="space-y-5">
                <div className="flex flex-wrap gap-2">
                  <StatusPill tone="accent">Core flows only</StatusPill>
                  <StatusPill>Candidate workspace</StatusPill>
                  <StatusPill>Reviewer queue</StatusPill>
                </div>
                <div className="space-y-4">
                  <p className="page-eyebrow">Forge pilot</p>
                  <h1 className="regal-title text-balance text-5xl font-semibold text-white sm:text-6xl">
                    Candidate workspace in. Reviewer decision out.
                  </h1>
                  <p className="max-w-3xl text-base leading-8 text-slate-400">
                    This build is intentionally narrow. It keeps the candidate assignment flow, the reviewer decision flow, and the employer-facing report
                    flow, while removing the speculative marketplace surfaces around them.
                  </p>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
                {[
                  ["Candidate", "Read the brief, launch a workspace, run checks, and submit."],
                  ["Reviewer", "Claim work, inspect evidence, and publish or restrict access."],
                  ["Runtime", "Check worker state, workspace inventory, and preview health."],
                ].map(([label, detail]) => (
                  <div className="rounded-[22px] border border-white/10 bg-white/[0.03] p-5" key={label}>
                    <div className="text-xl font-semibold text-white">{label}</div>
                    <p className="mt-2 text-sm leading-6 text-slate-400">{detail}</p>
                  </div>
                ))}
              </div>
            </div>
          </Surface>

          <div className="grid gap-4 lg:grid-cols-3">
            {[
              {
                title: "Start candidate flow",
                detail: "Open the assignment and move directly into the managed workspace.",
                href: "/candidate/assignments/warehouse-ops-api-v1",
                cta: "Open assignment",
              },
              {
                title: "Open reviewer queue",
                detail: "Review submitted work, publish reports, and manage employer access.",
                href: "/admin/review-queue",
                cta: "Open queue",
              },
              {
                title: "Check runtime",
                detail: "Inspect active workspaces, previews, and worker loop status.",
                href: "/admin/runtime",
                cta: "Open runtime",
              },
            ].map((item) => (
              <div className="rounded-[22px] border border-white/10 bg-[linear-gradient(180deg,#121722,#0e121b)] p-6" key={item.title}>
                <div className="page-eyebrow">Core surface</div>
                <h2 className="regal-title mt-3 text-3xl font-semibold text-white">{item.title}</h2>
                <p className="mt-3 text-sm leading-7 text-slate-400">{item.detail}</p>
                <div className="mt-6">
                  <ActionLink href={item.href}>{item.cta}</ActionLink>
                </div>
              </div>
            ))}
          </div>

          <div className="rounded-[22px] border border-white/10 bg-white/[0.02] p-6">
            <div className="page-eyebrow">What remains in scope</div>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {[
                "Candidate assignment, workspace, preview, and submission.",
                "Reviewer queue, review detail, publication, and access revocation.",
                "Employer report and frozen preview links after publication.",
              ].map((item) => (
                <div className="rounded-[18px] border border-white/10 bg-white/[0.03] px-4 py-4 text-sm text-slate-300" key={item}>
                  {item}
                </div>
              ))}
            </div>
          </div>
        </div>
      </PageSection>
    </main>
  );
}
