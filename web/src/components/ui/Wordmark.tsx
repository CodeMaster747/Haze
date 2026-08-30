import { Waves } from 'lucide-react';

import { RouteLink } from '@/components/ui/RouteLink';

/** The Haze wordmark.
 *
 *  There were three copies of this — the dashboard header, the landing nav and
 *  the footer — at two different icon sizes, which is exactly the drift a
 *  shared component exists to prevent.
 *
 *  It is a link home only in the hosted build, and that is a real gap it
 *  closes rather than a decoration: the public site sends you to /cluster and
 *  the dashboard header had nothing on it that went back. In the agent's own
 *  build there is nowhere to go — `/` *is* the dashboard — so it stays inert
 *  text, and `__HAZE_DEMO__` is a compile-time constant, so the agent bundle
 *  contains no router code at all.
 */
export function Wordmark({ className = '' }: { className?: string }) {
  const mark = (
    <>
      <Waves size={16} strokeWidth={2} aria-hidden className="text-accent-primary" />
      <span className="font-mono text-sm font-medium tracking-tight">haze</span>
    </>
  );

  const shared = `inline-flex shrink-0 items-center gap-2 text-text-primary ${className}`;

  if (!__HAZE_DEMO__) return <div className={shared}>{mark}</div>;

  return (
    <RouteLink
      to="/"
      aria-label="Haze — home"
      className={`${shared} rounded-md transition-colors ease-out-quart hover:text-accent-primary`}
    >
      {mark}
    </RouteLink>
  );
}
