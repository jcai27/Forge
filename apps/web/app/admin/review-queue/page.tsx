import Link from "next/link";

import { ReviewQueueClient } from "@/components/review-queue-client";
import { EmptyState, PageSection } from "@/components/ui";
import { serverApiFetch } from "@/lib/server-api";

type ReviewQueueResponse = {
  items: Array<{
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
  }>;
};

function averageScore(items: ReviewQueueResponse["items"]) {
  if (!items.length) return "0";
  const total = items.reduce((sum, item) => sum + item.automated_total_score, 0);
  return Math.round(total / items.length).toString();
}

export default async function ReviewQueuePage() {
  const data = await serverApiFetch<ReviewQueueResponse>("/internal/review-queue", { devAuthRole: "admin" });
  if (!data) {
    return (
      <main className="page-stack">
        <PageSection>
          <EmptyState
            action={
              <Link className="site-cta" href="/login">
                Sign in to review
              </Link>
            }
            description="Reviewer and admin pages now require an authenticated internal session."
            eyebrow="Review queue"
            title="Review queue unavailable"
          />
        </PageSection>
      </main>
    );
  }

  const items = data?.items ?? [];
  const claimed = items.filter((item) => item.assignment?.status === "claimed").length;
  const published = items.filter((item) => item.publication_state?.includes("published")).length;
  const escalated = items.filter((item) => item.escalation_state && item.escalation_state !== "none").length;
  const navItems = [
    { label: "Dashboard", active: true, href: "/admin/review-queue" },
    { label: "Assignments", active: false, href: "/admin/review-queue" },
    { label: "Candidates", active: false, href: "/candidate/dashboard" },
    { label: "Templates", active: false, href: "/candidate/assignments/warehouse-ops-api-v1" },
    { label: "Runtime", active: false, href: "/admin/runtime" },
    { label: "Settings", active: false, href: "/admin/review-queue" },
  ];

  return (
    <main className="relative left-1/2 min-h-screen w-screen -translate-x-1/2 bg-[#090b11] text-slate-100">
      <section className="mx-auto grid min-h-screen max-w-[1980px] border-x border-white/10 bg-[#0b0e15] xl:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="border-r border-white/10 bg-[#0d1018]">
          <div className="border-b border-white/10 px-5 py-5">
            <div className="rounded-[22px] border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Project preview</div>
              <div className="mt-2 flex items-center justify-between gap-3 text-xl font-medium text-white">
                <span>Acme Corp</span>
                <span className="text-slate-500">v</span>
              </div>
            </div>
          </div>

          <div className="px-5 py-8">
            <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Workspace</div>
            <nav className="mt-5 space-y-2">
              {navItems.map((item) => (
                <Link
                  className={
                    item.active
                      ? "flex items-center rounded-2xl border border-white/10 bg-white/10 px-4 py-4 text-lg font-medium text-white"
                      : "flex items-center rounded-2xl px-4 py-4 text-lg text-slate-400 transition hover:bg-white/5 hover:text-slate-200"
                  }
                  href={item.href}
                  key={item.label}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </aside>

        <section className="min-h-screen">
          <header className="border-b border-white/10 bg-[#0e1118] px-6 py-4">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex min-w-0 flex-1 items-center gap-4">
                <div className="flex h-14 min-w-0 flex-1 items-center rounded-[20px] border border-white/10 bg-white/[0.03] px-5 text-lg text-slate-400">
                  Search assignments, candidates...
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-300">K</div>
                <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-300">Alerts</div>
                <Link
                  className="inline-flex items-center rounded-2xl bg-[linear-gradient(135deg,#8795ff,#9aa7ff)] px-6 py-3 text-base font-semibold text-slate-950 transition hover:brightness-110"
                  href="/candidate/assignments/warehouse-ops-api-v1"
                >
                  + New assignment
                </Link>
              </div>
            </div>
          </header>

          <div className="space-y-8 px-6 py-8">
            <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
              <div>
                <h1 className="text-5xl font-semibold tracking-tight text-white">Welcome back, Maya</h1>
                <p className="mt-3 max-w-3xl text-base leading-7 text-slate-400">
                  Reviewer ownership, candidate progress, publication state, and employer access all sit in one operational dashboard.
                </p>
              </div>
              <div className="flex items-center gap-3 text-slate-400">
                <span className="text-sm">Last 30 days</span>
                <span className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm">v1.4.2</span>
              </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-4">
              {[
                ["Active assignments", String(items.length), `+${Math.max(items.length - claimed, 0)}`],
                ["Candidates in progress", String(claimed), `+${claimed}`],
                ["Published reports", String(published), `+${published}`],
                ["Avg. score", averageScore(items), escalated ? `+${escalated} escalated` : "stable"],
              ].map(([label, value, delta]) => (
                <div className="rounded-[28px] border border-white/10 bg-white/[0.04] px-6 py-6 shadow-[0_20px_50px_rgba(0,0,0,0.18)]" key={label}>
                  <div className="text-[15px] text-slate-400">{label}</div>
                  <div className="mt-6 flex items-end justify-between gap-4">
                    <div className="text-6xl font-semibold tracking-tight text-white">{value}</div>
                    <div className="rounded-xl border border-emerald-400/15 bg-emerald-500/12 px-3 py-2 text-sm font-medium text-emerald-300">{delta}</div>
                  </div>
                </div>
              ))}
            </div>

            <div className="space-y-4">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <h2 className="text-2xl font-semibold text-white">Active assignments</h2>
                <div className="flex flex-wrap items-center gap-3">
                  <button className="rounded-2xl border border-white/10 bg-white/[0.03] px-5 py-3 text-lg text-slate-300 transition hover:bg-white/8" type="button">
                    Filter
                  </button>
                  <Link
                    className="rounded-2xl border border-white/10 bg-transparent px-5 py-3 text-lg text-white transition hover:bg-white/5"
                    href="/admin/runtime"
                  >
                    View all
                  </Link>
                </div>
              </div>

              <ReviewQueueClient items={items} />
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}
