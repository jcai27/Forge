"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch, apiSend } from "@/lib/api";
import { DEV_AUTH_HEADER } from "@/lib/dev-auth";
import { canonicalAssignmentBrief } from "@/lib/mock-platform";

type SessionCreateResponse = {
  session: {
    id: string;
  };
};

type SessionState = {
  user: {
    id: string;
    email: string;
    full_name: string;
    user_type: string;
  };
  session: {
    mfa_required: boolean;
    mfa_verified: boolean;
  };
};

export function LaunchAssessmentCard() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<SessionState | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void apiFetch<SessionState>("/auth/session", { headers: { [DEV_AUTH_HEADER]: "candidate" } }).then((payload) => {
      if (cancelled) return;
      setSession(payload);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function launchAssessment() {
    setBusy(true);
    setError(null);

    try {
      const response = await apiSend<SessionCreateResponse>("/candidate/sessions", {
        headers: { [DEV_AUTH_HEADER]: "candidate" },
        method: "POST",
        body: JSON.stringify({
          track_version_id: "track_backend_api_v1",
        }),
      });
      router.push(`/candidate/session/${response.session.id}`);
    } catch (launchError) {
      setError(launchError instanceof Error ? launchError.message : "Unable to start project.");
      setBusy(false);
    }
  }

  const readyCandidate = session?.user.user_type === "candidate";

  return (
    <div className="rounded-[24px] border border-white/10 bg-[linear-gradient(180deg,#131823,#10141d)] p-7 text-slate-300 shadow-[0_18px_56px_rgba(0,0,0,0.22)]" data-testid="assignment-launch-panel">
      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-4">
          <div className="space-y-2">
            <p className="page-eyebrow">Final step before coding</p>
            <h3 className="regal-title text-3xl font-semibold text-white">Launch the managed workspace for this project credential.</h3>
            <p className="text-sm leading-7 text-slate-400">{canonicalAssignmentBrief.overview}</p>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            {[
              ["Project", canonicalAssignmentBrief.title],
              ["Environment", canonicalAssignmentBrief.environmentFacts[0][1]],
              ["Included", "Editor, terminal, tests, reflection gate"],
            ].map(([label, value]) => (
              <div className="rounded-[18px] border border-white/10 bg-white/[0.02] p-4" key={label}>
                <div className="page-eyebrow">{label}</div>
                <div className="mt-2 text-sm font-medium text-white">{value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-[20px] border border-white/10 bg-white/[0.02] p-5">
          {loaded && readyCandidate ? (
            <div className="grid gap-4">
              <div className="rounded-[18px] border border-white/10 bg-[#0b0e15] p-4">
                <div className="page-eyebrow">Signed in as</div>
                <div className="mt-2 text-sm font-medium text-white">{session.user.full_name}</div>
                <div className="mt-1 text-xs text-slate-500">{session.user.email}</div>
              </div>
              <button
                className="inline-flex items-center justify-center rounded-full border border-[rgba(199,174,106,0.24)] bg-[linear-gradient(180deg,rgba(199,174,106,0.16),rgba(199,174,106,0.08))] px-5 py-3 text-sm font-medium text-white shadow-[0_16px_36px_rgba(0,0,0,0.2)] transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60"
                data-testid="launch-managed-session-button"
                disabled={busy}
                onClick={() => void launchAssessment()}
                type="button"
              >
                {busy ? "Opening workspace..." : "Launch workspace"}
              </button>
              <p className="text-sm leading-6 text-slate-500">
                The local test flow launches directly into the seeded candidate workspace.
              </p>
            </div>
          ) : loaded ? (
            <div className="grid gap-4">
              <div className="rounded-[18px] border border-white/10 bg-[#0b0e15] p-4 text-sm leading-7 text-slate-400">
                Candidate access did not initialize. Reload the page and try again.
              </div>
              <Link className="site-cta justify-center" href="/candidate/assignments/warehouse-ops-api-v1">
                Reload candidate flow
              </Link>
            </div>
          ) : (
            <div className="text-sm text-slate-500">Checking candidate session…</div>
          )}

          {error ? <div className="mt-4 rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{error}</div> : null}
        </div>
      </div>
    </div>
  );
}
