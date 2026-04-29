type ScoreBarProps = {
  label: string;
  score: number;
  evidence?: string;
};

export function ScoreBar({ label, score, evidence }: ScoreBarProps) {
  const clamped = Math.max(0, Math.min(score, 100));

  return (
    <div className="space-y-3 rounded-[28px] border border-white/10 bg-white/[0.03] p-5">
      <div className="flex items-center justify-between gap-4">
        <span className="text-sm font-medium text-slate-200">{label}</span>
        <strong className="font-mono text-sm font-semibold text-white">{clamped.toFixed(0)}</strong>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-white/10">
        <div className="h-full rounded-full bg-[linear-gradient(90deg,#8795ff,#d946ef)]" style={{ width: `${clamped}%` }} />
      </div>
      {evidence ? <p className="text-sm leading-6 text-slate-400">{evidence}</p> : null}
    </div>
  );
}
