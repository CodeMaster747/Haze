import { Antenna, Link2, Plus, Radar, TriangleAlert } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { api } from '@/lib/api';
import type { DiscoveredNode, DiscoveryState } from '@/types';

/** Machines on this network.
 *
 *  Shows *which mechanism* found each node, because that is diagnostic. A node
 *  seen only by broadcast means multicast is being filtered — common on mesh
 *  access points, and the single most confusing failure in this whole system if
 *  it is not surfaced.
 */
export function NetworkPanel({
  discovery,
  disabled,
}: {
  discovery: DiscoveryState | null;
  disabled: boolean;
}) {
  const [host, setHost] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nodes = discovery?.nodes ?? [];
  const isolated = nodes.filter((n) => n.reachable === false && n.sources.length > 0);

  const addManual = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!host.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.addManualNode(host.trim());
      setHost('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="on this network"
      right={
        discovery && (
          <div className="flex gap-1.5">
            <Badge tone={discovery.mdns ? 'online' : 'offline'}>
              <Radar size={10} /> mdns
            </Badge>
            <Badge tone={discovery.broadcast ? 'online' : 'offline'}>
              <Antenna size={10} /> beacon
            </Badge>
          </div>
        )
      }
    >
      {nodes.length === 0 ? (
        <p className="py-5 text-center text-sm text-text-muted">
          {discovery && !discovery.mdns && !discovery.broadcast
            ? 'Automatic discovery is unavailable on this machine — add a node by address below.'
            : 'No other Haze nodes seen yet.'}
        </p>
      ) : (
        <ul className="divide-y divide-border-subtle">
          {nodes.map((node) => (
            <NodeRow key={node.node_id} node={node} />
          ))}
        </ul>
      )}

      {isolated.length > 0 && (
        <div className="mt-4 flex items-start gap-2.5 rounded border border-state-busy/30 bg-state-busy/5 px-3 py-2.5">
          <TriangleAlert size={14} className="mt-0.5 shrink-0 text-state-busy" />
          <p className="text-xs leading-relaxed text-text-secondary">
            <strong className="text-text-primary">
              {isolated.map((n) => n.name).join(', ')}
            </strong>{' '}
            {isolated.length === 1 ? 'is advertising' : 'are advertising'} but cannot be
            connected to. Your access point is probably isolating clients from each other —
            common on guest networks. No discovery setting can work around it; the machines
            need a network that permits device-to-device traffic.
          </p>
        </div>
      )}

      {!disabled && (
        <form onSubmit={(e) => void addManual(e)} className="mt-4 flex gap-2 border-t border-border-subtle pt-4">
          <input
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="add by address — 192.168.1.42"
            spellCheck={false}
            autoComplete="off"
            className="min-w-0 flex-1 rounded border border-border bg-bg-tertiary px-2.5 py-1.5 font-mono text-xs text-text-primary outline-none transition placeholder:text-text-dim focus:border-accent-primary/60"
          />
          <button
            type="submit"
            disabled={busy || !host.trim()}
            className="rounded border border-border px-2.5 py-1.5 text-xs text-text-secondary transition hover:border-accent-primary/50 hover:text-accent-primary disabled:opacity-40"
          >
            <Plus size={12} className="inline" /> add
          </button>
        </form>
      )}

      {error && <p className="mt-2 text-xs text-state-error">{error}</p>}
    </Panel>
  );
}

function NodeRow({ node }: { node: DiscoveredNode }) {
  const tone =
    node.reachable === false ? 'error' : node.paired ? 'online' : 'offline';

  return (
    <li className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
      <Link2 size={15} className="shrink-0 text-text-muted" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-text-primary">{node.name}</p>
        <p className="truncate font-mono text-[11px] text-text-dim">
          {node.short_id} · {node.host}
          {node.port ? `:${node.port}` : ''} · via {node.sources.join(' + ')}
        </p>
      </div>
      {node.paired ? (
        <Badge tone="online">paired</Badge>
      ) : (
        <Badge tone={tone}>{node.reachable === false ? 'unreachable' : 'not paired'}</Badge>
      )}
    </li>
  );
}
