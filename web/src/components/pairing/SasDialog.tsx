import { ShieldAlert } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Callout } from '@/components/ui/Callout';
import { api } from '@/lib/api';
import type { PendingPairing } from '@/types';

/** The confirmation dialog.
 *
 *  The design constraints here are security requirements, not aesthetics:
 *
 *  - The digits are the largest thing on screen, because the user has to
 *    compare them against another machine several feet away.
 *  - The words are shown too: "breakup blockade slingshot clamshell" is much
 *    harder to misread as matching than "143031" is.
 *  - Confirm is not the default action and is not the only styled button. A
 *    dialog that is easy to click through is security theatre — the whole
 *    mechanism rests on the user actually looking at the other screen.
 *    Keyboard focus lands on the *reject* button for the same reason.
 */
export function SasDialog({ pending }: { pending: PendingPairing }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const decide = async (confirmed: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await (confirmed ? api.confirmPairing : api.rejectPairing)(pending.session_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'request failed');
      setBusy(false);
    }
  };

  const heading =
    pending.direction === 'incoming'
      ? `${pending.name} wants to pair with this machine`
      : `Pairing with ${pending.name}`;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/70 p-4 backdrop-blur-sm">
      <div className="flex min-h-full items-center justify-center">
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="sas-heading"
          className="w-full max-w-lg animate-dialog-in rounded-xl border border-border bg-bg-panel shadow-modal"
        >
          <header className="border-b border-border-subtle px-6 py-4">
            <h2 id="sas-heading" className="text-lg font-medium tracking-tight text-text-primary">
              {heading}
            </h2>
            <p className="mt-1 font-mono text-2xs text-text-muted">
              {pending.short_id} · {pending.platform || 'unknown platform'}
              {pending.version && ` · haze ${pending.version}`}
            </p>
          </header>

          <div className="px-6 py-8 text-center">
            <p className="text-sm text-text-secondary">
              Check that <strong className="font-medium text-text-primary">both machines</strong>{' '}
              are showing exactly this:
            </p>

            <div
              className="mt-6 font-mono text-4xl font-semibold tabular-nums tracking-digits text-accent-primary sm:text-5xl"
              aria-label={`Confirmation code ${pending.sas_digits.split('').join(' ')}`}
            >
              {pending.sas_digits}
            </div>

            <div className="mt-5 flex flex-wrap justify-center gap-1.5">
              {pending.sas_words.map((word, i) => (
                <span
                  key={i}
                  className="rounded border border-border-subtle bg-bg-tertiary px-2 py-1 font-mono text-xs text-accent-secondary"
                >
                  {word}
                </span>
              ))}
            </div>

            <Callout tone="error" icon={ShieldAlert} className="mt-7 text-left">
              If the two screens show{' '}
              <strong className="font-medium text-text-primary">different</strong> codes, something
              is intercepting the connection. Choose{' '}
              <span className="font-medium text-text-primary">They don&apos;t match</span>.
            </Callout>

            {error && (
              <p role="alert" className="mt-3 text-xs text-state-error">
                {error}
              </p>
            )}
          </div>

          <footer className="flex flex-col-reverse gap-2 border-t border-border-subtle px-6 py-4 sm:flex-row sm:justify-between">
            <Button
              size="lg"
              variant="danger"
              autoFocus
              disabled={busy}
              onClick={() => void decide(false)}
            >
              They don&apos;t match
            </Button>
            <Button
              size="lg"
              variant="primary"
              loading={busy}
              onClick={() => void decide(true)}
            >
              {busy ? 'Confirming…' : 'They match — pair'}
            </Button>
          </footer>

          <p className="pb-4 text-center font-mono text-2xs tabular-nums text-text-dim">
            expires in {Math.round(pending.expires_in_s)}s
          </p>
        </div>
      </div>
    </div>
  );
}
