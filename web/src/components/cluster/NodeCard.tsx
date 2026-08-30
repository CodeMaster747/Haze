import { Cpu, HardDrive, MemoryStick, MonitorCog } from 'lucide-react';
import type { ReactNode } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Meter } from '@/components/ui/Meter';
import { Panel } from '@/components/ui/Panel';
import { bytes, duration } from '@/lib/format';
import type { NodeInfo } from '@/types';

export function NodeCard({ node }: { node: NodeInfo }) {
  const t = node.telemetry;

  return (
    <Panel
      title={node.name}
      right={
        <>
          {/* A simulated node is badged on every surface that renders it. An
              unbadged synthetic "RTX 4090" is the fastest way to turn this
              project's best demo asset into a credibility problem. */}
          {node.simulated && <Badge tone="simulated">simulated</Badge>}
          {node.is_self && <Badge>this machine</Badge>}
          <Badge tone={node.status} dot>
            {node.status}
          </Badge>
        </>
      }
    >
      {!t ? (
        <p className="py-8 text-center text-sm text-text-muted">Waiting for telemetry…</p>
      ) : (
        <div className="space-y-5">
          <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
            <Meter
              label="CPU"
              value={t.cpu.percent}
              detail={`${t.cpu.cores} threads · ${t.cpu.physical_cores} cores`}
            />
            <Meter
              label="Memory"
              value={t.ram.percent}
              detail={`${bytes(t.ram.used)} of ${bytes(t.ram.total)}`}
            />
            <Meter
              label="Disk"
              value={t.disk.percent}
              detail={`${bytes(t.disk.free)} free of ${bytes(t.disk.total)}`}
            />
            <Meter
              label={t.gpu ? `GPU · ${t.gpu.name}` : 'GPU'}
              value={t.gpu?.utilisation ?? 0}
              unknown={t.gpu?.utilisation == null}
              detail={
                t.gpu
                  ? t.gpu.vram_total != null
                    ? `${bytes(t.gpu.vram_used)} of ${bytes(t.gpu.vram_total)} VRAM`
                    : 'unified memory · no separate VRAM figure'
                  : 'none detected'
              }
            />
          </div>

          <CoreGrid cores={t.cpu.per_core} />

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border-subtle pt-3 font-mono text-2xs text-text-dim">
            <Spec icon={<Cpu size={12} aria-hidden />} label={`${t.cpu.cores}c`} />
            <Spec icon={<MemoryStick size={12} aria-hidden />} label={bytes(t.ram.total, 0)} />
            <Spec icon={<HardDrive size={12} aria-hidden />} label={bytes(t.disk.total, 0)} />
            {t.gpu && (
              <Spec
                icon={<MonitorCog size={12} aria-hidden />}
                label={t.gpu.encoders[0] ?? 'no encoder'}
              />
            )}
            <span className="ml-auto tabular-nums">up {duration(t.uptime_s)}</span>
          </div>
        </div>
      )}
    </Panel>
  );
}

function Spec({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      {icon}
      {label}
    </span>
  );
}

/** Per-core load. The point of showing it is that a job pinned to 4 cores looks
 *  visibly different from one saturating all 16 — which is the whole argument
 *  for having per-node resource caps. */
function CoreGrid({ cores }: { cores: number[] }) {
  if (cores.length === 0) return null;
  return (
    <div
      className="flex gap-0.5 overflow-x-auto"
      role="img"
      aria-label={`Per-core utilisation across ${cores.length} cores`}
    >
      {cores.map((load, i) => {
        const height = Math.min(100, Math.max(0, load));
        return (
          <div
            key={i}
            className="h-6 min-w-1 flex-1 overflow-hidden rounded-sm bg-bg-tertiary"
            title={`core ${i}: ${load.toFixed(0)}%`}
          >
            <div
              className="w-full bg-accent-primary/70 transition-[height,margin] duration-500 ease-out-quart"
              style={{ height: `${height}%`, marginTop: `${100 - height}%` }}
            />
          </div>
        );
      })}
    </div>
  );
}
