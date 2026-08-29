import type { ReactNode } from 'react';

type Tone = 'online' | 'busy' | 'offline' | 'error' | 'simulated' | 'neutral';

const TONES: Record<Tone, string> = {
  online: 'border-state-online/35 text-state-online bg-state-online/10',
  busy: 'border-state-busy/35 text-state-busy bg-state-busy/10',
  offline: 'border-state-offline/35 text-state-offline bg-state-offline/10',
  error: 'border-state-error/35 text-state-error bg-state-error/10',
  simulated: 'border-state-simulated/40 text-state-simulated bg-state-simulated/10',
  neutral: 'border-border text-text-muted bg-bg-tertiary',
};

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.1em] ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}
