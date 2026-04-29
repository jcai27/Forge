"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { apiSend } from "@/lib/api";
import { ActionLink, Surface } from "@/components/ui";

type LoginResponse = {
  user: {
    user_type: string;
    full_name: string;
  };
  session: {
    mfa_required: boolean;
    mfa_verified: boolean;
    mfa_enrolled: boolean;
  };
};

type EnrollResponse = {
  enrollment: {
    secret: string;
    provisioning_uri: string;
    recovery_codes: string[];
  };
};

export function InternalLoginPanel() {
  const router = useRouter();
  const [email, setEmail] = useState("reviewer@verified.dev");
  const [password, setPassword] = useState("demo-password");
  const [mfaCode, setMfaCode] = useState("");
  const [busy, setBusy] = useState<"login" | "enroll" | "verify" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loginState, setLoginState] = useState<LoginResponse | null>(null);
  const [enrollment, setEnrollment] = useState<EnrollResponse["enrollment"] | null>(null);

  const firstRecoveryCode = useMemo(() => enrollment?.recovery_codes?.[0] ?? "", [enrollment]);

  async function login() {
    setBusy("login");
    setError(null);
    try {
      const payload = await apiSend<LoginResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setLoginState(payload);
      if (!payload.session.mfa_required || payload.session.mfa_verified) {
        router.push("/admin/review-queue");
        router.refresh();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to sign in.");
    } finally {
      setBusy(null);
    }
  }

  async function enrollMfa() {
    setBusy("enroll");
    setError(null);
    try {
      const payload = await apiSend<EnrollResponse>("/auth/mfa/enroll", {
        method: "POST",
      });
      setEnrollment(payload.enrollment);
      setMfaCode(payload.enrollment.recovery_codes[0] ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to start MFA enrollment.");
    } finally {
      setBusy(null);
    }
  }

  async function verifyMfa() {
    setBusy("verify");
    setError(null);
    try {
      await apiSend("/auth/mfa/verify", {
        method: "POST",
        body: JSON.stringify({ code: mfaCode }),
      });
      router.push("/admin/review-queue");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to verify MFA.");
    } finally {
      setBusy(null);
    }
  }

  const needsMfa = loginState?.session.mfa_required && !loginState.session.mfa_verified;

  return (
    <Surface className="p-8">
      <div className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-4">
          <p className="page-eyebrow">Internal access</p>
          <h1 className="regal-title text-5xl font-semibold text-white">Sign in to reviewer and runtime operations.</h1>
          <p className="text-base leading-7 text-slate-400">
            The internal surface now runs through a real authenticated session. In local development, the seeded reviewer account is preloaded for testing and MFA can be completed with a recovery code.
          </p>
          <div className="rounded-[22px] border border-white/10 bg-white/[0.03] p-5 text-sm leading-7 text-slate-400">
            Default local reviewer:
            <div className="mt-2 font-mono text-xs text-slate-200">reviewer@verified.dev / demo-password</div>
          </div>
        </div>

        <div className="space-y-4 rounded-[24px] border border-white/10 bg-white/[0.02] p-5">
          <div>
            <label className="page-eyebrow">Email</label>
            <input
              className="mt-2 w-full rounded-[16px] border border-white/10 bg-[#0b0e15] px-4 py-3 text-sm text-white outline-none"
              data-testid="internal-login-email"
              onChange={(event) => setEmail(event.target.value)}
              value={email}
            />
          </div>
          <div>
            <label className="page-eyebrow">Password</label>
            <input
              className="mt-2 w-full rounded-[16px] border border-white/10 bg-[#0b0e15] px-4 py-3 text-sm text-white outline-none"
              data-testid="internal-login-password"
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              value={password}
            />
          </div>
          <button className="site-cta w-full justify-center" data-testid="internal-login-submit" disabled={busy !== null} onClick={() => void login()} type="button">
            {busy === "login" ? "Signing in…" : "Sign in"}
          </button>

          {needsMfa ? (
            <div className="space-y-4 rounded-[22px] border border-amber-500/20 bg-amber-500/10 p-4">
              <div className="text-sm font-medium text-amber-100">MFA verification required</div>
              {!loginState?.session.mfa_enrolled ? (
                <>
                  <p className="text-sm leading-6 text-amber-100/80">This account does not have MFA enrolled yet. Start enrollment, then verify with a recovery code for local testing.</p>
                  <button
                    className="rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm font-medium text-white"
                    data-testid="internal-mfa-enroll"
                    disabled={busy !== null}
                    onClick={() => void enrollMfa()}
                    type="button"
                  >
                    {busy === "enroll" ? "Preparing MFA…" : "Start MFA enrollment"}
                  </button>
                </>
              ) : null}

              {enrollment ? (
                <div className="space-y-3 rounded-[18px] border border-white/10 bg-black/10 p-4 text-sm text-amber-50">
                  <div>Recovery code</div>
                  <code className="block rounded-xl border border-white/10 bg-black/10 px-3 py-2 text-xs">{firstRecoveryCode}</code>
                  <div className="text-xs text-amber-50/80">Provisioning URI: {enrollment.provisioning_uri}</div>
                </div>
              ) : null}

              <div>
                <label className="page-eyebrow text-amber-50/80">MFA code or recovery code</label>
                <input className="mt-2 w-full rounded-[16px] border border-white/10 bg-[#0b0e15] px-4 py-3 text-sm text-white outline-none" onChange={(event) => setMfaCode(event.target.value)} value={mfaCode} />
              </div>
              <button
                className="site-cta w-full justify-center"
                data-testid="internal-mfa-verify"
                disabled={busy !== null || !mfaCode.trim()}
                onClick={() => void verifyMfa()}
                type="button"
              >
                {busy === "verify" ? "Verifying…" : "Verify MFA"}
              </button>
            </div>
          ) : null}

          {error ? <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{error}</div> : null}

          <div className="flex gap-3 text-sm">
            <ActionLink href="/candidate/access" tone="secondary">
              Candidate access
            </ActionLink>
          </div>
        </div>
      </div>
    </Surface>
  );
}
