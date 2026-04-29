import { SectionCard } from "@/components/section-card";
import { DataTable, EmptyState, MetricCard, PageSection, StatusPill, Surface } from "@/components/ui";
import { serverApiFetch } from "@/lib/server-api";

type RuntimeStatusResponse = {
  runtime: {
    configured_backend: string;
    active_backend: string;
    preferred_backend?: string;
    fallback_backend?: string;
    docker?: {
      binary: string;
      available: boolean;
    };
    paths: {
      root: string;
      templates: string;
    };
    limits: {
      cpu: string;
      memory: string;
      timeout_seconds: number;
    };
    workspace_counts: {
      total: number;
      by_status: Record<string, number>;
      by_backend: Record<string, number>;
    };
    preview: {
      configured: boolean;
      active_backend: string;
      host: string;
      port_range: [number, number];
      idle_timeout_seconds: number;
      preview_counts: {
        total: number;
        by_status: Record<string, number>;
        by_scope: Record<string, number>;
      };
    };
    worker?: {
      enabled: boolean;
      embedded: boolean;
      poll_interval_seconds: number;
      batch_size: number;
      loop_running: boolean;
      last_result?: {
        job_id?: string | null;
        job_type?: string | null;
        status: string;
        error?: string;
      } | null;
    };
  };
  maintenance: {
    cleanup_on_startup: boolean;
    cleanup_interval_seconds: number;
    cleanup_loop_running: boolean;
    last_cleanup: {
      trigger: string;
      started_at: string;
      completed_at: string;
      error: string | null;
      result: {
        backend: string;
        cleaned_workspaces: string[];
        cleaned_count: number;
      } | null;
    } | null;
  };
};

type RuntimeWorkspaceResponse = {
  items: Array<{
    workspace_id: string;
    session_id: string;
    backend: string;
    status: string;
    created_at?: string;
    last_event_at?: string;
    expires_at?: number;
    container_name?: string;
    container_id?: string;
  }>;
};

type RuntimePreviewResponse = {
  items: Array<{
    scope: string;
    subject_id: string;
    status: string;
    backend: string;
    port?: number;
    default_path?: string;
    last_accessed_at?: string;
  }>;
};

function renderStatusMap(map: Record<string, number>) {
  return Object.entries(map).map(([key, value]) => (
    <div className="rounded-3xl border border-white/10 bg-white/[0.03] px-4 py-4" key={key}>
      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{key}</div>
      <div className="mt-2 text-xl font-semibold text-white">{value}</div>
    </div>
  ));
}

export default async function RuntimePage() {
  const [statusData, workspaceData, previewData] = await Promise.all([
    serverApiFetch<RuntimeStatusResponse>("/internal/runtime/status", { devAuthRole: "admin" }),
    serverApiFetch<RuntimeWorkspaceResponse>("/internal/runtime/workspaces?limit=8", { devAuthRole: "admin" }),
    serverApiFetch<RuntimePreviewResponse>("/internal/runtime/previews?limit=8", { devAuthRole: "admin" }),
  ]);

  if (!statusData) {
    return (
      <main className="page-stack">
        <PageSection>
          <EmptyState
            description="Runtime operations require an authenticated admin session."
            eyebrow="Runtime"
            title="Runtime status unavailable"
          />
        </PageSection>
      </main>
    );
  }

  const runtime = statusData?.runtime;
  const maintenance = statusData?.maintenance;
  const workspaces = workspaceData?.items ?? [];
  const previews = previewData?.items ?? [];

  return (
    <main className="page-stack">
      <PageSection>
        <Surface className="hero-gradient p-8">
          <div className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-3">
                <StatusPill tone="accent">Runtime operations</StatusPill>
                <StatusPill>{runtime?.active_backend ?? "unavailable"}</StatusPill>
              </div>
              <div className="space-y-4">
                <h1 className="text-5xl font-semibold tracking-tight text-white">Operate the controlled runtime like serious hiring infrastructure.</h1>
                <p className="max-w-3xl text-base leading-7 text-slate-400">
                  Session isolation, preview health, worker state, cleanup behavior, and workspace inventory all need to stay legible if this product is
                  going to support real hiring decisions.
                </p>
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-1">
              <MetricCard label="Workspaces" supporting="Tracked runtime sessions" value={runtime?.workspace_counts.total ?? 0} />
              <MetricCard label="Previews" supporting="Active preview records" value={runtime?.preview.preview_counts.total ?? 0} />
              <MetricCard label="Worker" supporting={runtime?.worker?.embedded ? "embedded mode" : "external mode"} value={runtime?.worker?.loop_running ? "running" : "stopped"} />
            </div>
          </div>
        </Surface>
      </PageSection>

      <PageSection>
        <div className="grid gap-6 lg:grid-cols-2">
          <SectionCard eyebrow="Isolation" title="Backend state">
            {runtime ? (
              <div className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <MetricCard label="Configured backend" supporting="Target runtime mode" value={runtime.configured_backend} className="shadow-none" />
                  <MetricCard label="Active backend" supporting="Live execution backend" value={runtime.active_backend} className="shadow-none" />
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  {[
                    ["CPU", runtime.limits.cpu],
                    ["Memory", runtime.limits.memory],
                    ["Timeout", `${runtime.limits.timeout_seconds}s`],
                  ].map(([label, value]) => (
                    <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-4" key={label}>
                      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</div>
                      <div className="mt-2 font-mono text-sm text-slate-300">{value}</div>
                    </div>
                  ))}
                </div>
                {runtime.docker ? (
                  <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-4">
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.18em] text-slate-400">Docker</div>
                        <div className="mt-2 text-sm text-slate-600">{runtime.docker.binary}</div>
                      </div>
                      <StatusPill tone={runtime.docker.available ? "success" : "danger"}>
                        {runtime.docker.available ? "available" : "unavailable"}
                      </StatusPill>
                    </div>
                  </div>
                ) : null}
                <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-4 text-sm leading-6 text-slate-400">
                  Runtime root: <span className="font-mono text-xs text-slate-300">{runtime.paths.root}</span>
                </div>
              </div>
            ) : (
              <EmptyState description="Confirm the API process is running and the internal runtime endpoints are reachable." eyebrow="Isolation" title="Runtime status unavailable" />
            )}
          </SectionCard>

          <SectionCard eyebrow="Maintenance" title="Cleanup and worker loop">
            {maintenance ? (
              <div className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <MetricCard label="Cleanup loop" supporting="Automatic stale session cleanup" value={maintenance.cleanup_loop_running ? "running" : "stopped"} className="shadow-none" />
                  <MetricCard label="Interval" supporting="Automatic cleanup cadence" value={`${maintenance.cleanup_interval_seconds}s`} className="shadow-none" />
                </div>
                <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Last cleanup</div>
                  {maintenance.last_cleanup ? (
                    <div className="mt-3 space-y-2 text-sm text-slate-400">
                      <div>Trigger: {maintenance.last_cleanup.trigger}</div>
                      <div>Completed: {maintenance.last_cleanup.completed_at}</div>
                      <div>Cleaned count: {maintenance.last_cleanup.result?.cleaned_count ?? 0}</div>
                      {maintenance.last_cleanup.error ? <div className="text-rose-600">Error: {maintenance.last_cleanup.error}</div> : null}
                    </div>
                  ) : (
                    <div className="mt-3 text-sm text-slate-500">No cleanup run completed yet.</div>
                  )}
                </div>
                {runtime?.worker ? (
                <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-400">
                  Worker mode: {runtime.worker.embedded ? "embedded" : "external"} • poll {runtime.worker.poll_interval_seconds}s • batch{" "}
                  {runtime.worker.batch_size}
                    {runtime.worker.last_result ? (
                      <div className="mt-2 text-slate-500">
                        Last result: {runtime.worker.last_result.job_type ?? "unknown"} / {runtime.worker.last_result.status}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : (
              <EmptyState description="Confirm the API process is running and the cleanup loop has exposed status." eyebrow="Maintenance" title="Cleanup status unavailable" />
            )}
          </SectionCard>
        </div>
      </PageSection>

      <PageSection>
        <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
          <SectionCard eyebrow="Workspace counts" title="By status">
            {runtime ? <div className="grid gap-3 sm:grid-cols-2">{renderStatusMap(runtime.workspace_counts.by_status)}</div> : <EmptyState description="No workspace count data is available yet." title="No workspace data" />}
          </SectionCard>

          <SectionCard eyebrow="Preview counts" title="By status">
            {runtime ? <div className="grid gap-3 sm:grid-cols-2">{renderStatusMap(runtime.preview.preview_counts.by_status)}</div> : <EmptyState description="No preview count data is available yet." title="No preview data" />}
          </SectionCard>
        </div>
      </PageSection>

      <PageSection>
        <div className="grid gap-6 lg:grid-cols-2">
          <SectionCard eyebrow="Recent sessions" title="Workspace inventory">
            <DataTable
              headers={["Workspace", "Session", "Backend", "Status", "Last activity"]}
              rows={workspaces.map((workspace) => [
                workspace.workspace_id,
                workspace.session_id,
                workspace.backend,
                <StatusPill key={`${workspace.workspace_id}-status`} tone={workspace.status === "running" ? "success" : "neutral"}>
                  {workspace.status}
                </StatusPill>,
                workspace.last_event_at ?? workspace.created_at ?? "—",
              ])}
            />
          </SectionCard>

          <SectionCard eyebrow="Recent previews" title="Preview inventory">
            <DataTable
              headers={["Scope", "Subject", "Status", "Backend", "Last accessed"]}
              rows={previews.map((preview) => [
                preview.scope,
                preview.subject_id,
                <StatusPill key={`${preview.subject_id}-status`} tone={preview.status === "ready" ? "success" : preview.status === "failed" ? "danger" : "neutral"}>
                  {preview.status}
                </StatusPill>,
                preview.backend,
                preview.last_accessed_at ?? "—",
              ])}
            />
          </SectionCard>
        </div>
      </PageSection>
    </main>
  );
}
