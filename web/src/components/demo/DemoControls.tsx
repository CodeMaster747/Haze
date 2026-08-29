import { Pause, Play, Plus, RotateCcw, Zap } from 'lucide-react';
import { useState } from 'react';

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

  return (
    <Panel
      title="try it"
      right={
        <span className="font-mono text-[10px] text-text-dim">
          t+{snapshot.clock.seconds.toFixed(0)}s
        </span>
      }
    >
      <div className="space-y-4">
        <div>
          <p className="mb-2 text-xs text-text-muted">Submit a job — the scheduler places it.</p>
          <div className="flex flex-wrap gap-2">
            {(['render', 'encode', 'benchmark'] as const).map((kind) => (
              <button
                key={kind}
                type="button"
                onClick={() => act(() => cluster.submit(kind))}
                className="rounded border border-accent-primary/50 bg-accent-subtle px-3 py-1.5 text-xs text-accent-primary transition hover:bg-accent-primary/20"
              >
                <Plus size={11} className="inline" /> {kind}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label
            htmlFor="latency"
            className="mb-1.5 flex items-baseline justify-between text-xs text-text-muted"
          >
            <span>Network between machines</span>
            <span className="font-mono text-text-secondary">
              {snapshot.latencyMultiplier <= 1.2
                ? 'fast LAN'
                : snapshot.latencyMultiplier <= 6
                  ? 'ordinary WiFi'
                  : 'slow link'}
            </span>
          </label>
          <input
            id="latency"
            type="range"
            min={1}
            max={30}
            step={1}
            value={snapshot.latencyMultiplier}
            onChange={(e) => act(() => cluster.setLatencyMultiplier(Number(e.target.value)))}
            className="w-full accent-[#38bdc9]"
          />
          <p className="mt-1 text-[11px] leading-relaxed text-text-dim">
            Drag this while an encode is queued. Past a point, shipping 700 MiB costs more
            than the faster machine saves — and the scheduler brings the work home.
          </p>
        </div>

        <div>
          <p className="mb-2 text-xs text-text-muted">
            Take a machine offline. Anything running there is rescheduled.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {snapshot.nodes.map((node) => (
              <button
                key={node.nodeId}
                type="button"
                disabled={node.isSelf}
                title={node.isSelf ? 'This is the machine you are “on”' : undefined}
                onClick={() => act(() => cluster.setNodeOnline(node.nodeId, !node.online))}
                className={`rounded border px-2 py-1 font-mono text-[11px] transition disabled:opacity-30 ${
                  node.online
                    ? 'border-state-online/40 text-state-online hover:border-state-error/60 hover:text-state-error'
                    : 'border-state-error/40 text-state-error hover:border-state-online/60 hover:text-state-online'
                }`}
              >
                <Zap size={10} className="inline" /> {node.profile.name}
                {node.online ? '' : ' (down)'}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2 border-t border-border-subtle pt-3">
          <button
            type="button"
            onClick={() => act(() => cluster.clock.setPaused(!snapshot.clock.paused))}
            className="rounded border border-border px-2.5 py-1 text-xs text-text-secondary transition hover:border-accent-primary/50 hover:text-accent-primary"
          >
            {snapshot.clock.paused ? (
              <>
                <Play size={11} className="inline" /> resume
              </>
            ) : (
              <>
                <Pause size={11} className="inline" /> pause
              </>
            )}
          </button>
          {[1, 3, 10].map((speed) => (
            <button
              key={speed}
              type="button"
              onClick={() => act(() => cluster.clock.setSpeed(speed))}
              className={`rounded border px-2 py-1 font-mono text-xs transition ${
                snapshot.clock.speed === speed
                  ? 'border-accent-primary/50 bg-accent-subtle text-accent-primary'
                  : 'border-border text-text-muted hover:text-text-secondary'
              }`}
            >
              {speed}×
            </button>
          ))}
          <button
            type="button"
            onClick={() => act(() => cluster.reset())}
            className="ml-auto rounded border border-border px-2.5 py-1 text-xs text-text-muted transition hover:text-text-secondary"
          >
            <RotateCcw size={11} className="inline" /> reset
          </button>
        </div>
      </div>
    </Panel>
  );
}
