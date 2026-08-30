import { Activity, CloudOff, Loader2, ShieldAlert } from 'lucide-react';

import { Badge } from '@/components/ui/Badge';
import { Wordmark } from '@/components/ui/Wordmark';
import type { LinkState } from '@/types';

const LINK: Record<
  LinkState,
  { label: string; tone: 'online' | 'busy' | 'error' | 'offline'; icon: typeof Activity }
> = {
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
    <header className="sticky top-0 z-20 border-b border-border-subtle bg-bg-primary/90 backdrop-blur-md">
      {/* Fixed height rather than padding around variable-height children:
          the header must not resize when the connection badge changes text. */}
      <div className="shell flex h-14 items-center gap-3">
        <Wordmark />

        {/* The hosted demo must never be mistakable for a live cluster. */}
        {!isLive && (
          <Badge tone="simulated" dot>
            <span className="sm:hidden">simulated</span>
            <span className="hidden sm:inline">demo · simulated cluster</span>
          </Badge>
        )}

        {/* Only meaningful when there is a real connection to report. In the
            demo the link is a constant, and a green "live" chip beside the
            "simulated cluster" chip says two opposite things at once. */}
        {isLive && (
          <div className="ml-auto">
            <Badge tone={state.tone}>
              <Icon
                size={11}
                strokeWidth={2.25}
                aria-hidden
                className={spinning ? 'animate-spin' : undefined}
              />
              {state.label}
            </Badge>
          </div>
        )}
      </div>
    </header>
  );
}
