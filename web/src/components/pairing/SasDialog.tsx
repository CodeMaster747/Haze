import { ShieldAlert } from 'lucide-react';
import { useState } from 'react';

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="sas-heading"
        className="w-full max-w-lg animate-fade-in rounded-lg border border-border bg-bg-panel shadow-2xl"
      >
        <header className="border-b border-border-subtle px-6 py-4">
          <h2 id="sas-heading" className="text-base font-medium text-text-primary">
            {heading}
          </h2>
          <p className="mt-1 font-mono text-xs text-text-muted">
            {pending.short_id} · {pending.platform || 'unknown platform'}
            {pending.version && ` · haze ${pending.version}`}
          </p>
        </header>

        <div className="px-6 py-7 text-center">
          <p className="mb-5 text-sm text-text-secondary">
            Check that <strong className="text-text-primary">both machines</strong> are showing
            exactly this:
          </p>

          <div
            className="font-mono text-5xl font-semibold tracking-[0.3em] text-accent-primary"
            aria-label={`Confirmation code ${pending.sas_digits.split('').join(' ')}`}
          >
            {pending.sas_digits}
          </div>

          <div className="mt-4 flex flex-wrap justify-center gap-x-3 gap-y-1 font-mono text-sm text-accent-secondary">
            {pending.sas_words.map((word, i) => (
              <span key={i}>{word}</span>
            ))}
          </div>

          <div className="mt-6 flex items-start gap-2.5 rounded border border-state-error/30 bg-state-error/5 px-3.5 py-3 text-left">
            <ShieldAlert size={15} className="mt-0.5 shrink-0 text-state-error" />
            <p className="text-xs leading-relaxed text-text-secondary">
              If the two screens show <strong className="text-text-primary">different</strong>{' '}
              codes, something is intercepting the connection. Choose{' '}
              <span className="font-medium text-text-primary">They don&apos;t match</span>.
            </p>
          </div>

          {error && <p className="mt-3 text-xs text-state-error">{error}</p>}
        </div>

        <footer className="flex flex-col-reverse gap-2 border-t border-border-subtle px-6 py-4 sm:flex-row sm:justify-between">
          <button
            type="button"
            disabled={busy}
            onClick={() => void decide(false)}
            className="rounded border border-border px-4 py-2 text-sm text-text-secondary transition hover:border-state-error/50 hover:text-state-error disabled:opacity-40"
          >
            They don&apos;t match
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void decide(true)}
            className="rounded border border-accent-primary/50 bg-accent-subtle px-4 py-2 text-sm font-medium text-accent-primary transition hover:bg-accent-primary/20 disabled:opacity-40"
          >
            {busy ? 'Confirming…' : 'They match — pair'}
          </button>
        </footer>

        <p className="pb-4 text-center font-mono text-[11px] text-text-dim">
          expires in {Math.round(pending.expires_in_s)}s
        </p>
      </div>
    </div>
  );
}
