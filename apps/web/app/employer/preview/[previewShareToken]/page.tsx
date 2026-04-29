import Link from "next/link";

import { EmptyState, PageSection, StatusPill, Surface } from "@/components/ui";
import { apiFetch, apiOrigin } from "@/lib/api";

type EmployerPreviewResponse = {
  preview: {
    status: string;
    default_url?: string | null;
    error?: string | null;
  };
  submission: {
    id: string;
  };
  report: {
    id: string;
  };
};

export default async function EmployerPreviewPage({
  params,
}: {
  params: Promise<{ previewShareToken: string }>;
}) {
  const { previewShareToken } = await params;
  const data = await apiFetch<EmployerPreviewResponse>(`/employer/previews/${previewShareToken}`);

  if (!data) {
    return (
      <main className="page-stack">
        <PageSection>
          <EmptyState
            description="Published previews unlock only when the portable artifact includes a reproducible project surface."
            eyebrow="Project preview"
            title="Preview unavailable"
          />
        </PageSection>
      </main>
    );
  }

  const previewUrl = data.preview.default_url ? `${apiOrigin}${data.preview.default_url}` : null;

  return (
    <main className="page-stack">
      <PageSection>
        <Surface className="hero-gradient p-8">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-4">
              <div className="flex flex-wrap gap-3">
                <StatusPill tone="accent">Project preview</StatusPill>
                <StatusPill tone={data.preview.status === "ready" ? "success" : "warning"}>{data.preview.status}</StatusPill>
              </div>
              <div>
                <h1 className="text-5xl font-semibold tracking-tight text-white">Published project preview</h1>
                <p className="mt-4 max-w-3xl text-base leading-7 text-slate-400">
                  This preview is reproduced from the published artifact, not from a mutable live workspace. It anchors the hiring conversation to one
                  stable build that both sides can trust.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-3">
              <Link className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.03] px-4 py-2.5 text-sm font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.07]" href="/">
                Back to discovery
              </Link>
              {previewUrl ? (
                <a className="inline-flex items-center rounded-full bg-[linear-gradient(135deg,#8795ff,#9aa7ff)] px-4 py-2.5 text-sm font-medium text-slate-950 shadow-[0_18px_42px_rgba(135,149,255,0.24)] transition hover:-translate-y-0.5 hover:brightness-110" href={previewUrl} rel="noreferrer" target="_blank">
                  Open full tab
                </a>
              ) : null}
            </div>
          </div>
        </Surface>
      </PageSection>

      <PageSection>
        {previewUrl ? (
          <div className="overflow-hidden rounded-[32px] border border-slate-200 bg-slate-950 p-4 shadow-[0_24px_80px_rgba(15,23,42,0.35)]" data-testid="employer-preview-frame-container">
            <div className="mb-4 flex items-center gap-3 rounded-full border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-300">
              <span className="font-medium text-white">Published preview</span>
              <span className="truncate text-slate-400">{previewUrl}</span>
            </div>
            <iframe
              className="h-[78vh] w-full rounded-[24px] border border-white/10 bg-white"
              data-testid="employer-preview-iframe"
              src={previewUrl}
              title="Published project preview"
            />
          </div>
        ) : (
          <EmptyState description={data.preview.error ?? "Preview did not start."} eyebrow="Project preview" title="Preview unavailable" />
        )}
      </PageSection>
    </main>
  );
}
