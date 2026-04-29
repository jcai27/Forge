"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ActionLink, Surface } from "@/components/ui";
import { apiSend } from "@/lib/api";

type MagicLinkResponse = {
  ok: boolean;
  attempt_id: string;
  token?: string;
};

export function CandidateAccessPanel() {
  const router = useRouter();
  const [inviteToken, setInviteToken] = useState("invite_candidate_demo");
  const [email, setEmail] = useState("candidate@example.com");
  const [busy, setBusy] = useState<"request" | "redeem" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [magicToken, setMagicToken] = useState<string | null>(null);

  async function requestAccess() {
    setBusy("request");
    setError(null);
    setMessage(null);
    try {
      const payload = await apiSend<MagicLinkResponse>("/auth/candidate/magic-link/request", {
        method: "POST",
        body: JSON.stringify({ invite_token: inviteToken, email }),
      });
      if (payload.token) {
        setMagicToken(payload.token);
        setMessage("Local development token issued. Continue to open the candidate session.");
      } else {
        setMessage("Magic link requested. Check the configured delivery channel.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to request candidate access.");
    } finally {
      setBusy(null);
    }
  }

  async function redeemAccess() {
    if (!magicToken) return;
    setBusy("redeem");
    setError(null);
    try {
      await apiSend("/auth/candidate/magic-link/redeem", {
        method: "POST",
        body: JSON.stringify({ token: magicToken }),
      });
      router.push("/candidate/assignments/warehouse-ops-api-v1");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to open candidate access.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Surface className="p-8">
      <div className="grid gap-8 lg:grid-cols-[1.05fr_0.95fr]">
        <div className="space-y-4">
          <p className="page-eyebrow">Candidate entry</p>
          <h1 className="regal-title text-5xl font-semibold text-white">Open the managed assessment as the candidate.</h1>
          <p className="text-base leading-7 text-slate-400">
            Candidates now enter through invite-based access instead of typing raw user IDs into the product. In local development, the seeded invite returns a dev token immediately so you can complete the end-to-end flow in one browser.
          </p>
          <div className="rounded-[22px] border border-white/10 bg-white/[0.03] p-5 text-sm leading-7 text-slate-400">
            Default local candidate:
            <div className="mt-2 font-mono text-xs text-slate-200">invite_candidate_demo / candidate@example.com</div>
          </div>
        </div>

        <div className="space-y-4 rounded-[24px] border border-white/10 bg-white/[0.02] p-5">
          <div>
            <label className="page-eyebrow">Invite token</label>
            <input
              className="mt-2 w-full rounded-[16px] border border-white/10 bg-[#0b0e15] px-4 py-3 text-sm text-white outline-none"
              data-testid="candidate-invite-token"
              onChange={(event) => setInviteToken(event.target.value)}
              value={inviteToken}
            />
          </div>
          <div>
            <label className="page-eyebrow">Email</label>
            <input
              className="mt-2 w-full rounded-[16px] border border-white/10 bg-[#0b0e15] px-4 py-3 text-sm text-white outline-none"
              data-testid="candidate-email"
              onChange={(event) => setEmail(event.target.value)}
              value={email}
            />
          </div>
          <button className="site-cta w-full justify-center" data-testid="candidate-request-access" disabled={busy !== null} onClick={() => void requestAccess()} type="button">
            {busy === "request" ? "Requesting access…" : "Request candidate access"}
          </button>

          {magicToken ? (
            <div className="space-y-3 rounded-[22px] border border-emerald-500/20 bg-emerald-500/10 p-4">
              <div className="text-sm font-medium text-emerald-100">Development magic link token</div>
              <code className="block overflow-hidden text-ellipsis whitespace-nowrap rounded-xl border border-white/10 bg-black/10 px-3 py-2 text-xs text-emerald-50">
                {magicToken}
              </code>
              <button
                className="rounded-full bg-white px-4 py-2 text-sm font-medium text-slate-950"
                data-testid="candidate-redeem-access"
                disabled={busy !== null}
                onClick={() => void redeemAccess()}
                type="button"
              >
                {busy === "redeem" ? "Opening candidate session…" : "Continue as candidate"}
              </button>
            </div>
          ) : null}

          {message ? <div className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-slate-300">{message}</div> : null}
          {error ? <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{error}</div> : null}

          <div className="flex gap-3 text-sm">
            <ActionLink href="/login" tone="secondary">
              Internal sign in
            </ActionLink>
          </div>
        </div>
      </div>
    </Surface>
  );
}
