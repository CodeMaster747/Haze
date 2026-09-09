import { Laptop, Plug, Server } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { Panel } from '@/components/ui/Panel';
import { api } from '@/lib/api';
import type { PeerRow, SelfNode } from '@/types';

/** Paired machines.
 *
 *  Polled rather than streamed: the peer list changes only when someone pairs
 *  or unpairs, so a 5-second poll costs nothing and avoids adding another
 *  message type to the socket for an event that happens twice a year.
 */
export function PeerList({ enabled }: { enabled: boolean }) {
  const [self, setSelf] = useState<SelfNode | null>(null);
  const [peers, setPeers] = useState<PeerRow[]>([]);
  const [pinging, setPinging] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!enabled) return;
    let alive = true;

    const load = async () => {
      try {
        const data = await api.listPeers();
        if (alive) {
          setSelf(data.self);
          setPeers(data.peers);
        }
      } catch {
        // Transient (agent restarting, socket blip); the next tick retries.
      }
    };

    void load();
    const timer = window.setInterval(() => void load(), 5_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [enabled]);

  const ping = async (peer: PeerRow) => {
    setPinging(peer.node_id);
    try {
      const result = await api.pingPeer(peer.node_id);
      setResults((r) => ({ ...r, [peer.node_id]: result.ok ? 'reachable' : result.detail }));
    } catch (e) {
      setResults((r) => ({ ...r, [peer.node_id]: e instanceof Error ? e.message : 'failed' }));
    } finally {
      setPinging(null);
    }
  };

  return (
    <Panel
      title="Paired machines"
      right={
        self?.short_id ? (
          <Badge mono>
            <Server size={11} aria-hidden /> {self.short_id}
          </Badge>
        ) : undefined
      }
    >
      {peers.length === 0 ? (
        <EmptyState
          icon={Laptop}
          title={enabled ? 'No paired machines yet' : 'The demo cluster is pre-paired'}
          hint={
            enabled
              ? 'Use “Add a machine” below on both computers — one waits, the other connects.'
              : undefined
          }
        />
      ) : (
        <ul className="divide-y divide-border-subtle">
          {peers.map((peer) => {
            const result = results[peer.node_id];
            return (
              <li key={peer.node_id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                <Laptop size={16} strokeWidth={2} aria-hidden className="shrink-0 text-text-muted" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-text-primary">{peer.name}</p>
                  <p className="truncate font-mono text-2xs text-text-dim">
                    {peer.short_id} · {peer.last_host}:{peer.last_port} ·{' '}
                    {peer.platform || 'unknown'}
                  </p>
                  {peer.pinned_host && (
                    /* A pinned address is dialled ahead of the last-seen one,
                       so showing only the latter would have the dashboard
                       naming an address the agent is not using. */
                    <p className="truncate font-mono text-2xs text-text-muted">
                      pinned {peer.pinned_host}:{peer.pinned_port}
                    </p>
                  )}
                </div>
                {result && (
                  <span
                    role="status"
                    className={`hidden shrink-0 font-mono text-2xs sm:inline ${
                      result === 'reachable' ? 'text-state-online' : 'text-state-error'
                    }`}
                  >
                    {result}
                  </span>
                )}
                <Button
                  size="sm"
                  icon={Plug}
                  loading={pinging === peer.node_id}
                  onClick={() => void ping(peer)}
                  title="Open an authenticated connection and check it responds"
                >
                  Check
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
