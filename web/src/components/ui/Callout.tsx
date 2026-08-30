import { CircleAlert, Info, TriangleAlert, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

type Tone = 'warn' | 'error' | 'info';

/** An inline notice attached to the thing it is about.
 *
 *  There were three of these written by hand with three different paddings,
 *  three border opacities and two text sizes. Same notice, same shape.
 */
const TONES: Record<Tone, { box: string; icon: string; fallback: LucideIcon }> = {
  warn: {
    box: 'border-state-busy/25 bg-state-busy/[0.06]',
    icon: 'text-state-busy',
    fallback: TriangleAlert,
  },
  error: {
    box: 'border-state-error/30 bg-state-error/[0.06]',
    icon: 'text-state-error',
    fallback: CircleAlert,
  },
  info: { box: 'border-border bg-bg-tertiary', icon: 'text-text-muted', fallback: Info },
};

export function Callout({
  tone = 'info',
  icon,
  children,
  className = '',
}: {
  tone?: Tone;
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
}) {
  const t = TONES[tone];
  const Icon = icon ?? t.fallback;

  return (
    <div
      role={tone === 'error' ? 'alert' : undefined}
      className={`flex items-start gap-2.5 rounded-md border px-3 py-2.5 ${t.box} ${className}`}
    >
      <Icon size={14} strokeWidth={2} aria-hidden className={`mt-px shrink-0 ${t.icon}`} />
      <div className="min-w-0 text-xs leading-relaxed text-text-secondary">{children}</div>
    </div>
  );
}
