import { ReactNode } from "react";

import { cn } from "@/lib/utils";

type SectionCardProps = {
  eyebrow?: string;
  title: string;
  children: ReactNode;
  className?: string;
};

export function SectionCard({ eyebrow, title, children, className }: SectionCardProps) {
  return (
    <section className={cn("rounded-[24px] border border-white/10 bg-[linear-gradient(180deg,#131823,#10141d)] p-7 text-slate-300 shadow-[0_18px_56px_rgba(0,0,0,0.22)]", className)}>
      {eyebrow ? <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">{eyebrow}</p> : null}
      <h2 className="regal-title text-[clamp(1.35rem,2vw,2rem)] font-semibold text-white">{title}</h2>
      <div className="mt-5 space-y-4 text-sm leading-6 text-slate-400">{children}</div>
    </section>
  );
}
