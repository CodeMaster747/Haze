import { Pause, Play, Plus, RotateCcw } from 'lucide-react';
import type { ReactNode } from 'react';
import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Panel } from '@/components/ui/Panel';
import type { SimulatedCluster } from '@/sim/cluster';

/** The demo's controls.
 *
 *  The point of these is that the scheduler's behaviour is something you can
 *  *provoke*, not just read about. Drag the link slider and the encode job
 *  moves home; kill the workstation mid-render and watch the work reappear
 *  somewhere else.
 */
export function DemoControls({ cluster }: { cluster: SimulatedCluster }) {
  const snapshot = cluster.snapshot();
  const [, force] = useState(0);
  const refresh = () => force((n) => n + 1);

  const act = (fn: () => void) => {
    fn();
    refresh();
  };

  const linkLabel =
    snapshot.latencyMultiplier <= 1.2
      ? 'fast LAN'
      : snapshot.latencyMultiplier <= 6
        ? 'ordinary WiFi'
        : 'slow link';

  return (
    <Panel
      title="Try it"
      right={
        <span className="font-mono text-2xs tabular-nums text-text-dim">
          t+{snapshot.clock.seconds.toFixed(0)}s
        </span>
      }
    >
      <div className="space-y-5">
        <Group label="Submit a job" hint="The scheduler decides where it runs.">
          <div className="flex flex-wrap gap-2">
            {(['render', 'encode', 'benchmark'] as const).map((kind) => (
              <Button
                key={kind}
                size="sm"
                icon={Plus}
                onClick={() => act(() => cluster.submit(kind))}
              >
                {kind}
              </Button>
            ))}
          </div>
        </Group>

        <div>
          <label
            htmlFor="latency"
            className="flex items-baseline justify-between gap-2 text-xs font-medium text-text-secondary"
          >
            <span>Network between machines</span>
            <span className="font-mono text-2xs font-normal text-text-muted">{linkLabel}</span>
          </label>
          <input
            id="latency"
            type="range"
            min={1}
            max={30}
            step={1}
            value={snapshot.latencyMultiplier}
            aria-valuetext={linkLabel}
            onChange={(e) => act(() => cluster.setLatencyMultiplier(Number(e.target.value)))}
            className="mt-3 w-full cursor-pointer accent-accent-primary"
          />
          <p className="mt-2 text-2xs leading-relaxed text-text-dim">
            Drag this while an encode is queued. Past a point, shipping 700 MiB costs more than
            the faster machine saves — and the scheduler brings the work home.
          </p>
        </div>

        <Group
          label="Take a machine offline"
          hint="Anything running there is rescheduled onto what is left."
        >
          <div className="flex flex-wrap gap-2">
            {snapshot.nodes.map((node) => (
              <Button
                key={node.nodeId}
                size="sm"
                disabled={node.isSelf}
                title={
                  node.isSelf
                    ? 'This is the machine you are “on”'
                    : node.online
                      ? `Take ${node.profile.name} offline`
                      : `Bring ${node.profile.name} back online`
                }
                onClick={() => act(() => cluster.setNodeOnline(node.nodeId, !node.online))}
              >
                <span
                  aria-hidden
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    node.online ? 'bg-state-online' : 'bg-state-error'
                  }`}
                />
                <span className="font-mono">{node.profile.name}</span>
                {!node.online && <span className="text-text-dim">down</span>}
              </Button>
            ))}
          </div>
        </Group>

        <div className="flex items-center gap-2 border-t border-border-subtle pt-4">
          <Button
            size="sm"
            icon={snapshot.clock.paused ? Play : Pause}
            onClick={() => act(() => cluster.clock.setPaused(!snapshot.clock.paused))}
          >
            {snapshot.clock.paused ? 'Resume' : 'Pause'}
          </Button>

          <div className="flex gap-1" role="group" aria-label="Simulation speed">
            {[1, 3, 10].map((speed) => (
              <Button
                key={speed}
                size="sm"
                variant="ghost"
                active={snapshot.clock.speed === speed}
                aria-pressed={snapshot.clock.speed === speed}
                onClick={() => act(() => cluster.clock.setSpeed(speed))}
                className="font-mono"
              >
                {speed}×
              </Button>
            ))}
          </div>

          <Button
            size="sm"
            variant="ghost"
            icon={RotateCcw}
            className="ml-auto"
            onClick={() => act(() => cluster.reset())}
          >
            Reset
          </Button>
        </div>
      </div>
    </Panel>
  );
}

/** A labelled block of controls. The label carries the hierarchy, so the
 *  controls themselves do not need borders around them to look grouped. */
function Group({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <div>
      <p className="text-xs font-medium text-text-secondary">{label}</p>
      <p className="mt-1 text-2xs text-text-muted">{hint}</p>
      <div className="mt-3">{children}</div>
    </div>
  );
}
