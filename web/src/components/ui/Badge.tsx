import type { ReactNode } from 'react';

type Tone = 'online' | 'busy' | 'offline' | 'error' | 'simulated' | 'accent' | 'neutral';

/** Status chips.
 *
 *  These were 10px uppercase mono with 0.1em tracking — texture rather than
 *  text, and below the size at which a status is readable at a glance. Now
 *  11px sans at normal tracking, with an optional dot so state can be read
 *  from the colour without relying on colour alone for meaning.
 */
const TONES: Record<Tone, { chip: string; dot: string }> = {
  online: { chip: 'border-state-online/30 text-state-online bg-state-online/10', dot: 'bg-state-online' },
  busy: { chip: 'border-state-busy/30 text-state-busy bg-state-busy/10', dot: 'bg-state-busy' },
  offline: { chip: 'border-border text-text-muted bg-bg-elevated', dot: 'bg-state-offline' },
  error: { chip: 'border-state-error/30 text-state-error bg-state-error/10', dot: 'bg-state-error' },
  simulated: {
    chip: 'border-state-simulated/35 text-state-simulated bg-state-simulated/10',
    dot: 'bg-state-simulated',
  },
  accent: { chip: 'border-accent-primary/35 text-accent-primary bg-accent-subtle', dot: 'bg-accent-primary' },
  neutral: { chip: 'border-border text-text-muted bg-bg-elevated', dot: 'bg-text-muted' },
};

interface BadgeProps {
  tone?: Tone;
  /** Leading status dot. For live state, not for labels. */
  dot?: boolean;
  mono?: boolean;
  children: ReactNode;
}

export function Badge({ tone = 'neutral', dot = false, mono = false, children }: BadgeProps) {
  const t = TONES[tone];
  return (
    <span
      className={`inline-flex h-5 shrink-0 items-center gap-1.5 rounded border px-1.5 text-2xs font-medium leading-none ${
        mono ? 'font-mono' : ''
      } ${t.chip}`}
    >
      {dot && <span aria-hidden className={`h-1.5 w-1.5 shrink-0 rounded-full ${t.dot}`} />}
      {children}
    </span>
  );
}
