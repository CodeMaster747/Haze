import { Laptop, Plug } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Badge } from '@/components/ui/Badge';
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
      title="paired machines"
      right={self?.short_id ? <Badge>this node · {self.short_id}</Badge> : undefined}
    >
      {peers.length === 0 ? (
        <p className="py-6 text-center text-sm text-text-muted">
          {enabled
            ? 'No paired machines yet. Use “add a machine” above on both computers.'
            : 'The demo cluster is pre-paired.'}
        </p>
      ) : (
        <ul className="divide-y divide-border-subtle">
          {peers.map((peer) => (
            <li key={peer.node_id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
              <Laptop size={16} className="shrink-0 text-text-muted" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-text-primary">{peer.name}</p>
                <p className="truncate font-mono text-[11px] text-text-dim">
                  {peer.short_id} · {peer.last_host}:{peer.last_port} · {peer.platform || 'unknown'}
                </p>
              </div>
              {results[peer.node_id] && (
                <span
                  className={`font-mono text-[11px] ${
                    results[peer.node_id] === 'reachable' ? 'text-state-online' : 'text-state-error'
                  }`}
                >
                  {results[peer.node_id]}
                </span>
              )}
              <button
                type="button"
                disabled={pinging === peer.node_id}
                onClick={() => void ping(peer)}
                title="Open an authenticated connection and check it responds"
                className="rounded border border-border px-2 py-1 text-xs text-text-secondary transition hover:border-accent-primary/50 hover:text-accent-primary disabled:opacity-40"
              >
                <Plug size={12} className="inline" /> {pinging === peer.node_id ? '…' : 'check'}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
