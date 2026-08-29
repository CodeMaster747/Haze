import { loadTone, percent } from '@/lib/format';

interface MeterProps {
  label: string;
  value: number;
  detail?: string;
  /** Rendered muted, for values the OS will not report (e.g. VRAM on Apple
   *  Silicon without root). Distinguishes "0%" from "unknown". */
  unknown?: boolean;
}

const TONE = {
  ok: 'bg-accent-primary',
  warn: 'bg-state-busy',
  high: 'bg-state-error',
} as const;

export function Meter({ label, value, detail, unknown = false }: MeterProps) {
  const tone = TONE[loadTone(value)];
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-xs text-text-secondary">{label}</span>
        <span className="font-mono text-xs tabular-nums text-text-primary">
          {unknown ? '—' : percent(value)}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-bg-tertiary">
        {!unknown && (
          <div
            className={`h-full rounded-full transition-[width] duration-500 ease-out-quart ${tone}`}
            style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
          />
        )}
      </div>
      {detail && <p className="mt-1 font-mono text-[11px] text-text-dim">{detail}</p>}
    </div>
  );
}
