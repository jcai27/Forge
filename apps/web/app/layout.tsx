import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { AuthStatus } from "@/components/auth-status";

import "./globals.css";

export const metadata: Metadata = {
  title: "Forge | Candidate Workspace and Reviewer Ops",
  description: "Controlled candidate workspace, reviewer queue, and employer-ready reports.",
};

const navLinks = [
  { href: "/", label: "Home" },
  { href: "/candidate/assignments/warehouse-ops-api-v1", label: "Candidate" },
  { href: "/admin/review-queue", label: "Review Queue" },
  { href: "/admin/runtime", label: "Runtime" },
];

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <div className="app-background">
          <div className="shell-frame">
            <header className="site-header">
              <Link className="brand-lockup" href="/">
                <div className="brand-mark">FG</div>
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.26em] text-slate-500">Forge</p>
                  <div className="regal-title text-sm font-semibold text-white">Candidate workspace and reviewer ops</div>
                </div>
              </Link>

              <nav className="hidden items-center gap-1 md:flex">
                {navLinks.map((link) => (
                  <Link className="site-nav-link" href={link.href} key={link.href}>
                    {link.label}
                  </Link>
                ))}
              </nav>

              <div className="hidden items-center gap-3 lg:flex">
                <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs font-medium text-slate-300">
                  Local pilot
                </span>
                <AuthStatus />
              </div>
            </header>
            {children}
          </div>
        </div>
      </body>
    </html>
  );
}
