import { Antenna, Link2, Plus, Radar, TriangleAlert, WifiOff } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Callout } from '@/components/ui/Callout';
import { EmptyState } from '@/components/ui/EmptyState';
import { Field, Input } from '@/components/ui/Field';
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
  const noMechanism = discovery != null && !discovery.mdns && !discovery.broadcast;

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
      title="On this network"
      right={
        discovery && (
          <>
            <Badge tone={discovery.mdns ? 'online' : 'offline'} >
              <Radar size={11} aria-hidden /> mdns
            </Badge>
            <Badge tone={discovery.broadcast ? 'online' : 'offline'}>
              <Antenna size={11} aria-hidden /> beacon
            </Badge>
          </>
        )
      }
    >
      {nodes.length === 0 ? (
        <EmptyState
          icon={WifiOff}
          title={noMechanism ? 'Automatic discovery is unavailable here' : 'No other Haze nodes seen yet'}
          hint={
            noMechanism
              ? 'Neither mDNS nor the broadcast beacon could start on this machine. Add a node by address below.'
              : 'Nodes announce themselves every few seconds once the agent is running on them.'
          }
        />
      ) : (
        <ul className="divide-y divide-border-subtle">
          {nodes.map((node) => (
            <NodeRow key={node.node_id} node={node} />
          ))}
        </ul>
      )}

      {isolated.length > 0 && (
        <Callout tone="warn" icon={TriangleAlert} className="mt-4">
          <strong className="font-medium text-text-primary">
            {isolated.map((n) => n.name).join(', ')}
          </strong>{' '}
          {isolated.length === 1 ? 'is advertising' : 'are advertising'} but cannot be connected
          to. Your access point is probably isolating clients from each other — common on guest
          networks. No discovery setting can work around it; the machines need a network that
          permits device-to-device traffic.
        </Callout>
      )}

      {!disabled && (
        <form
          onSubmit={(e) => void addManual(e)}
          className="mt-4 flex items-end gap-2 border-t border-border-subtle pt-4"
        >
          <Field label="Add a node by address" className="flex-1">
            {(id) => (
              <Input
                id={id}
                aria-describedby={error ? 'add-node-error' : undefined}
                value={host}
                onChange={(e) => setHost(e.target.value)}
                placeholder="192.168.1.42"
                mono
                invalid={Boolean(error)}
                spellCheck={false}
                autoComplete="off"
              />
            )}
          </Field>
          <Button type="submit" icon={Plus} disabled={!host.trim()} loading={busy}>
            Add
          </Button>
        </form>
      )}

      {error && (
        <Callout tone="error" className="mt-3">
          <span id="add-node-error">{error}</span>
        </Callout>
      )}
    </Panel>
  );
}

function NodeRow({ node }: { node: DiscoveredNode }) {
  const tone = node.reachable === false ? 'error' : node.paired ? 'online' : 'offline';

  return (
    <li className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
      <Link2 size={16} strokeWidth={2} aria-hidden className="shrink-0 text-text-muted" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-text-primary">{node.name}</p>
        <p className="truncate font-mono text-2xs text-text-dim">
          {node.short_id} · {node.host}
          {node.port ? `:${node.port}` : ''} · via {node.sources.join(' + ')}
        </p>
      </div>
      {node.paired ? (
        <Badge tone="online" dot>
          paired
        </Badge>
      ) : (
        <Badge tone={tone} dot>
          {node.reachable === false ? 'unreachable' : 'not paired'}
        </Badge>
      )}
    </li>
  );
}
