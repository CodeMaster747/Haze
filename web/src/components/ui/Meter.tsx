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
  const clamped = Math.min(100, Math.max(0, value));

  return (
    <div className="min-w-0">
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="min-w-0 truncate text-xs text-text-secondary">{label}</span>
        <span className="shrink-0 font-mono text-xs tabular-nums text-text-primary">
          {unknown ? '—' : percent(value)}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={unknown ? undefined : Math.round(clamped)}
        aria-valuetext={unknown ? 'not reported' : percent(value)}
        className="h-1.5 overflow-hidden rounded-full bg-bg-tertiary"
      >
        {!unknown && (
          <div
            className={`h-full rounded-full transition-[width] duration-500 ease-out-quart ${tone}`}
            style={{ width: `${clamped}%` }}
          />
        )}
      </div>
      {detail && <p className="mt-1.5 truncate text-2xs text-text-dim">{detail}</p>}
    </div>
  );
}
