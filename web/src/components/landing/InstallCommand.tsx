import { Check, Copy } from 'lucide-react';
import { useEffect, useState } from 'react';

import { CONTROL_HEIGHT, type Size } from '@/components/ui/controlSize';

const COMMAND = 'uv tool install haze-agent';

/** The install line, as something you take text out of rather than read.
 *
 *  It sits next to the primary call to action because for this audience it is
 *  a second, equally valid entry point: the demo needs nothing installed, and
 *  the real thing needs exactly this.
 */
/** Matched to the Button it sits beside by sharing that component's height
 *  scale, so the two cannot drift apart. */
export function InstallCommand({ size = 'md' }: { size?: Size }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copy = () => {
    navigator.clipboard?.writeText(COMMAND).then(
      () => setCopied(true),
      () => undefined,
    );
  };

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={copied ? 'Install command copied' : `Copy install command: ${COMMAND}`}
      className={`group inline-flex max-w-full items-center gap-2.5 rounded-md border border-border-subtle bg-bg-tertiary px-3 text-left transition-colors ease-out-quart hover:border-border hover:bg-bg-elevated ${CONTROL_HEIGHT[size]}`}
    >
      <span aria-hidden className="shrink-0 font-mono text-xs text-text-dim">
        $
      </span>
      <span className="min-w-0 truncate font-mono text-xs text-text-secondary">{COMMAND}</span>
      {copied ? (
        <Check size={14} strokeWidth={2} aria-hidden className="shrink-0 text-state-online" />
      ) : (
        <Copy
          size={14}
          strokeWidth={2}
          aria-hidden
          className="shrink-0 text-text-dim transition-colors ease-out-quart group-hover:text-text-secondary"
        />
      )}
    </button>
  );
}
