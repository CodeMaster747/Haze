import { Radio, RadioTower } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { api } from '@/lib/api';
import type { PairingState } from '@/types';

/** Both halves of starting a pairing, side by side.
 *
 *  Deliberately shows the two directions together rather than behind a
 *  wizard: the user has to do one of these on *each* machine, and seeing both
 *  options makes that obvious in a way a single "Add a device" button does not.
 */
export function PairingPanel({ pairing, disabled }: { pairing: PairingState | null; disabled: boolean }) {
  const [host, setHost] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const armed = pairing?.armed ?? false;

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'request failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="add a machine"
      right={armed ? <Badge tone="busy">open · {Math.round(pairing?.arm_remaining_s ?? 0)}s</Badge> : undefined}
    >
      {disabled ? (
        <p className="text-sm text-text-muted">
          Pairing is disabled in this demo — there is no agent behind it. Install Haze on two
          machines to pair them for real.
        </p>
      ) : (
        <div className="grid gap-5 sm:grid-cols-2">
          <section>
            <h3 className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-text-primary">
              <RadioTower size={14} className="text-accent-primary" />
              Wait for a machine
            </h3>
            <p className="mb-3 text-xs leading-relaxed text-text-muted">
              Opens a window on this machine. Do this on one of the two, then use the other
              column over there.
            </p>
            <button
              type="button"
              disabled={busy}
              onClick={() => void run(armed ? api.disarmPairing : () => api.armPairing(180))}
              className="w-full rounded border border-border px-3 py-2 text-sm text-text-secondary transition hover:border-accent-primary/50 hover:text-accent-primary disabled:opacity-40"
            >
              {armed ? 'Close the window' : 'Open for 3 minutes'}
            </button>
          </section>

          <section>
            <h3 className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-text-primary">
              <Radio size={14} className="text-accent-primary" />
              Connect to a machine
            </h3>
            <p className="mb-3 text-xs leading-relaxed text-text-muted">
              Its address on your network, e.g.{' '}
              <code className="font-mono text-text-secondary">192.168.1.42</code>.
            </p>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (host.trim()) void run(() => api.initiatePairing(host.trim()));
              }}
            >
              <input
                value={host}
                onChange={(e) => setHost(e.target.value)}
                placeholder="192.168.1.42"
                spellCheck={false}
                autoComplete="off"
                className="min-w-0 flex-1 rounded border border-border bg-bg-tertiary px-2.5 py-2 font-mono text-sm text-text-primary outline-none transition placeholder:text-text-dim focus:border-accent-primary/60"
              />
              <button
                type="submit"
                disabled={busy || !host.trim()}
                className="rounded border border-accent-primary/50 bg-accent-subtle px-3 py-2 text-sm text-accent-primary transition hover:bg-accent-primary/20 disabled:opacity-40"
              >
                Connect
              </button>
            </form>
          </section>
        </div>
      )}

      {(error || pairing?.last_error) && (
        <p className="mt-4 rounded border border-state-error/30 bg-state-error/5 px-3 py-2 text-xs text-state-error">
          {error ?? pairing?.last_error}
        </p>
      )}
    </Panel>
  );
}
