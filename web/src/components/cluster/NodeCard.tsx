import { Cpu, HardDrive, MemoryStick, MonitorCog } from 'lucide-react';

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
        <div className="flex items-center gap-1.5">
          {/* A simulated node is badged on every surface that renders it. An
              unbadged synthetic "RTX 4090" is the fastest way to turn this
              project's best demo asset into a credibility problem. */}
          {node.simulated && <Badge tone="simulated">simulated</Badge>}
          {node.is_self && <Badge>this machine</Badge>}
          <Badge tone={node.status}>{node.status}</Badge>
        </div>
      }
    >
      {!t ? (
        <p className="py-6 text-center text-sm text-text-muted">waiting for telemetry…</p>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
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

          <dl className="flex flex-wrap gap-x-5 gap-y-1 border-t border-border-subtle pt-3 font-mono text-[11px] text-text-dim">
            <Stat icon={<Cpu size={11} />} label={`${t.cpu.cores}c`} />
            <Stat icon={<MemoryStick size={11} />} label={bytes(t.ram.total, 0)} />
            <Stat icon={<HardDrive size={11} />} label={bytes(t.disk.total, 0)} />
            {t.gpu && <Stat icon={<MonitorCog size={11} />} label={t.gpu.encoders[0] ?? 'no encoder'} />}
            <span className="ml-auto">up {duration(t.uptime_s)}</span>
          </dl>
        </div>
      )}
    </Panel>
  );
}

function Stat({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
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
    <div className="flex gap-[3px]" aria-label="per-core utilisation">
      {cores.map((load, i) => (
        <div
          key={i}
          className="h-6 flex-1 overflow-hidden rounded-sm bg-bg-tertiary"
          title={`core ${i}: ${load.toFixed(0)}%`}
        >
          <div
            className="w-full bg-accent-primary/70 transition-[height] duration-500 ease-out-quart"
            style={{ height: `${Math.min(100, Math.max(0, load))}%`, marginTop: `${100 - Math.min(100, Math.max(0, load))}%` }}
          />
        </div>
      ))}
    </div>
  );
}
