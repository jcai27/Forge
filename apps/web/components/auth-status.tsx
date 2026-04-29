"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch, apiSend } from "@/lib/api";
import { DEV_AUTH_HEADER, inferDevAuthRole } from "@/lib/dev-auth";

type SessionResponse = {
  user: {
    id: string;
    email: string;
    full_name: string;
    user_type: string;
    organization_id: string | null;
  };
  session: {
    mfa_required: boolean;
    mfa_verified: boolean;
    mfa_enrolled: boolean;
  };
};

export function AuthStatus() {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const role = inferDevAuthRole(pathname);
    void apiFetch<SessionResponse>("/auth/session", role ? { headers: { [DEV_AUTH_HEADER]: role } } : undefined).then((payload) => {
      if (cancelled) return;
      setSession(payload);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  async function logout() {
    setBusy(true);
    try {
      await apiSend("/auth/logout", { method: "POST" });
      setSession(null);
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  if (!loaded) {
    return <div className="text-xs text-slate-500">Checking session…</div>;
  }

  if (!session) {
    return (
      <div className="flex items-center gap-3">
        <Link className="site-nav-link" href="/admin/review-queue">
          Reviewer view
        </Link>
        <Link className="site-cta" href="/candidate/assignments/warehouse-ops-api-v1">
          Candidate view
        </Link>
      </div>
    );
  }

  const roleLabel = session.user.user_type === "candidate" ? "Candidate" : session.user.user_type === "admin" ? "Admin" : "Reviewer";
  const destination =
    session.user.user_type === "candidate"
      ? "/candidate/assignments/warehouse-ops-api-v1"
      : session.user.user_type === "admin"
        ? "/admin/review-queue"
        : "/admin/review-queue";

  return (
    <div className="flex items-center gap-3">
      <Link className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs font-medium text-slate-200" href={destination}>
        {session.user.full_name} • {roleLabel}
      </Link>
      {!session.session.mfa_verified && session.session.mfa_required ? (
        <Link className="site-nav-link text-amber-300" href="/login">
          Verify MFA
        </Link>
      ) : null}
      <button
        className="site-nav-link"
        disabled={busy}
        onClick={() => void logout()}
        type="button"
      >
        {busy ? "Resetting…" : "Reset demo view"}
      </button>
    </div>
  );
}
