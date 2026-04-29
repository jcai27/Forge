import Link from "next/link";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { cn } from "@/lib/utils";

export function PageSection({
  className,
  children,
  ...props
}: {
  className?: string;
  children: ReactNode;
} & ComponentPropsWithoutRef<"section">) {
  return (
    <section className={cn("mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8", className)} {...props}>
      {children}
    </section>
  );
}

export function Surface({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <div className={cn("rounded-[24px] border border-white/10 bg-[linear-gradient(180deg,#131823,#0f131d)] text-slate-100 shadow-[0_18px_56px_rgba(0,0,0,0.24)]", className)}>{children}</div>;
}

export function DarkSurface({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-[24px] border border-white/10 bg-[linear-gradient(180deg,#171c28,#0f141d)] text-slate-100 shadow-[0_18px_56px_rgba(2,6,23,0.36)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500", className)}>{children}</p>;
}

export function StatusPill({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "success" | "warning" | "danger" | "dark";
  className?: string;
}) {
  const tones = {
    neutral: "border-white/10 bg-white/[0.04] text-slate-300",
    accent: "border-[rgba(199,174,106,0.24)] bg-[rgba(199,174,106,0.1)] text-[#e7d8ab]",
    success: "border-emerald-400/25 bg-emerald-500/12 text-emerald-200",
    warning: "border-amber-400/25 bg-amber-500/12 text-amber-200",
    danger: "border-rose-400/25 bg-rose-500/12 text-rose-200",
    dark: "border-white/12 bg-white/8 text-slate-100",
  };
  return <span className={cn("inline-flex items-center rounded-full border px-3 py-1 text-[11px] font-medium", tones[tone], className)}>{children}</span>;
}

export function MetricCard({
  label,
  value,
  supporting,
  className,
}: {
  label: string;
  value: ReactNode;
  supporting?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-[22px] border border-white/10 bg-white/[0.03] p-5", className)}>
      <div className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">{label}</p>
        <div className="text-2xl font-semibold tracking-tight text-white">{value}</div>
        {supporting ? <div className="text-sm leading-6 text-slate-400">{supporting}</div> : null}
      </div>
    </div>
  );
}

export function ActionLink({
  href,
  children,
  tone = "primary",
  className,
}: {
  href: string;
  children: ReactNode;
  tone?: "primary" | "secondary";
  className?: string;
}) {
  return (
    <Link
      className={cn(
        "inline-flex items-center justify-center rounded-full px-4 py-2.5 text-sm font-medium transition duration-150 ease-out",
        tone === "primary"
          ? "border border-[rgba(199,174,106,0.24)] bg-[linear-gradient(180deg,rgba(199,174,106,0.16),rgba(199,174,106,0.08))] text-white shadow-[0_16px_36px_rgba(0,0,0,0.2)] hover:-translate-y-0.5"
          : "border border-white/10 bg-white/[0.03] text-slate-200 hover:-translate-y-0.5 hover:border-[rgba(199,174,106,0.16)] hover:bg-white/[0.06]",
        className,
      )}
      href={href}
    >
      {children}
    </Link>
  );
}

export function DataTable({
  headers,
  rows,
}: {
  headers: string[];
  rows: Array<Array<ReactNode>>;
}) {
  return (
    <div className="overflow-hidden rounded-[22px] border border-white/10 bg-[#121620]">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-white/8 text-left text-sm">
          <thead className="bg-white/[0.03]">
            <tr>
              {headers.map((header) => (
                <th key={header} className="px-4 py-3 font-medium text-slate-500">
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/8">
            {rows.map((row, index) => (
              <tr key={index} className="hover:bg-white/[0.03]">
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex} className="px-4 py-3 align-top text-slate-300">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function EmptyState({
  eyebrow,
  title,
  description,
  action,
  className,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("rounded-[24px] border border-dashed border-white/10 bg-white/[0.03] p-10 text-center", className)}>
      {eyebrow ? <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">{eyebrow}</div> : null}
      <div className="mx-auto mt-3 max-w-2xl">
        <h3 className="text-2xl font-semibold tracking-tight text-white">{title}</h3>
        <p className="mt-3 text-sm leading-7 text-slate-400">{description}</p>
      </div>
      {action ? <div className="mt-5 flex justify-center">{action}</div> : null}
    </div>
  );
}
