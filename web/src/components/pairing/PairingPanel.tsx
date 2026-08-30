import { Radio, RadioTower } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Callout } from '@/components/ui/Callout';
import { Code } from '@/components/ui/Code';
import { Field, Input } from '@/components/ui/Field';
import { Panel } from '@/components/ui/Panel';
import { api } from '@/lib/api';
import type { PairingState } from '@/types';

/** Both halves of starting a pairing, side by side.
 *
 *  Deliberately shows the two directions together rather than behind a
 *  wizard: the user has to do one of these on *each* machine, and seeing both
 *  options makes that obvious in a way a single "Add a device" button does not.
 */
export function PairingPanel({
  pairing,
  disabled,
}: {
  pairing: PairingState | null;
  disabled: boolean;
}) {
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
      title="Add a machine"
      right={
        armed ? (
          <Badge tone="busy" dot>
            open · {Math.round(pairing?.arm_remaining_s ?? 0)}s
          </Badge>
        ) : undefined
      }
    >
      {disabled ? (
        <p className="text-sm leading-relaxed text-text-muted">
          Pairing is disabled in this demo — there is no agent behind it. Install Haze on two
          machines to pair them for real.
        </p>
      ) : (
        // Two equal halves separated by a hairline rather than two cards: they
        // are one instruction with two ends, not two features.
        <div className="grid gap-6 sm:grid-cols-2 sm:gap-0">
          <section className="sm:pr-6">
            <Step icon={RadioTower} title="Wait for a machine">
              Opens a window on this machine. Do this on one of the two, then use the other
              column over there.
            </Step>
            <Button
              className="mt-4 w-full"
              disabled={busy}
              onClick={() => void run(armed ? api.disarmPairing : () => api.armPairing(180))}
            >
              {armed ? 'Close the window' : 'Open for 3 minutes'}
            </Button>
          </section>

          <section className="border-t border-border-subtle pt-6 sm:border-l sm:border-t-0 sm:pl-6 sm:pt-0">
            <Step icon={Radio} title="Connect to a machine">
              Its address on your network, e.g. <Code>192.168.1.42</Code>.
            </Step>
            <form
              className="mt-4 flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (host.trim()) void run(() => api.initiatePairing(host.trim()));
              }}
            >
              <Field label="Address" hideLabel className="flex-1">
                {(id) => (
                  <Input
                    id={id}
                    value={host}
                    onChange={(e) => setHost(e.target.value)}
                    placeholder="192.168.1.42"
                    mono
                    spellCheck={false}
                    autoComplete="off"
                  />
                )}
              </Field>
              <Button type="submit" variant="primary" disabled={busy || !host.trim()}>
                Connect
              </Button>
            </form>
          </section>
        </div>
      )}

      {(error || pairing?.last_error) && (
        <Callout tone="error" className="mt-4">
          {error ?? pairing?.last_error}
        </Callout>
      )}
    </Panel>
  );
}

function Step({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof Radio;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <h3 className="flex items-center gap-2 text-sm font-medium text-text-primary">
        <Icon size={14} strokeWidth={2} aria-hidden className="text-accent-primary" />
        {title}
      </h3>
      <p className="mt-1.5 text-xs leading-relaxed text-text-muted">{children}</p>
    </>
  );
}
