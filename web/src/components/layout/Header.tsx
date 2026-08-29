import { Activity, CloudOff, Loader2, ShieldAlert, Waves } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import type { LinkState } from '@/types';

const LINK: Record<LinkState, { label: string; tone: 'online' | 'busy' | 'error' | 'offline'; icon: typeof Activity }> = {
  live: { label: 'live', tone: 'online', icon: Activity },
  connecting: { label: 'connecting', tone: 'busy', icon: Loader2 },
  retrying: { label: 'reconnecting', tone: 'busy', icon: Loader2 },
  unauthorised: { label: 'not authorised', tone: 'error', icon: ShieldAlert },
  closed: { label: 'disconnected', tone: 'offline', icon: CloudOff },
};

export function Header({ link, isLive }: { link: LinkState; isLive: boolean }) {
  const state = LINK[link];
  const Icon = state.icon;
  const spinning = link === 'connecting' || link === 'retrying';

  return (
    <header className="sticky top-0 z-10 border-b border-border-subtle bg-bg-primary/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-5 py-3">
        <Waves size={18} className="text-accent-primary" />
        <span className="font-mono text-sm font-medium tracking-tight text-text-primary">haze</span>

        {/* The hosted demo must never be mistakable for a live cluster. */}
        {!isLive && <Badge tone="simulated">demo · simulated cluster</Badge>}

        <div className="ml-auto">
          <Badge tone={state.tone}>
            <Icon size={10} className={spinning ? 'animate-spin' : undefined} />
            {state.label}
          </Badge>
        </div>
      </div>
    </header>
  );
}
