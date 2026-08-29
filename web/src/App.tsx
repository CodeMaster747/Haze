import { useEffect } from 'react';

import { NodeCard } from '@/components/cluster/NodeCard';
import { NetworkPanel } from '@/components/discovery/NetworkPanel';
import { Header } from '@/components/layout/Header';
import { PairingPanel } from '@/components/pairing/PairingPanel';
import { PeerList } from '@/components/pairing/PeerList';
import { SasDialog } from '@/components/pairing/SasDialog';
import { Panel } from '@/components/ui/Panel';
import { useCluster } from '@/stores/cluster';

export default function App() {
  const { nodes, link, pairing, discovery, isLive, connect } = useCluster();

  useEffect(() => connect(), [connect]);

  // At most one dialog at a time. The agent allows only one outstanding
  // request per peer, and stacking modals would make "compare these digits"
  // ambiguous about which pair of screens is being compared.
  const awaiting = pairing?.pending.find((p) => p.decision === 'pending');

  return (
    <div className="min-h-dvh bg-bg-primary text-text-primary">
      <Header link={link} isLive={isLive} />

      <main className="mx-auto max-w-6xl animate-fade-in space-y-4 px-5 py-6">
        {link === 'unauthorised' ? (
          <Unauthorised />
        ) : nodes.length === 0 ? (
          <Panel>
            <p className="py-10 text-center text-sm text-text-muted">
              Connecting to the agent on this machine…
            </p>
          </Panel>
        ) : (
          <>
            <div className="grid gap-4 lg:grid-cols-2">
              {nodes.map((node) => (
                <NodeCard key={node.name} node={node} />
              ))}
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <NetworkPanel discovery={discovery} disabled={!isLive} />
              <PeerList enabled={isLive} />
            </div>

            <PairingPanel pairing={pairing} disabled={!isLive} />
          </>
        )}
      </main>

      {awaiting && <SasDialog pending={awaiting} />}
    </div>
  );
}

/** The most likely first-run confusion: the page was opened by hand at
 *  127.0.0.1:7433 rather than via the tokenised URL the agent prints. Say
 *  exactly that, with the fix, instead of showing a generic error. */
function Unauthorised() {
  return (
    <Panel title="not authorised">
      <div className="space-y-3 text-sm text-text-secondary">
        <p>
          This page needs the access token the agent prints when it starts. Open the console
          using the full URL from your terminal:
        </p>
        <pre className="overflow-x-auto rounded border border-border-subtle bg-bg-tertiary px-3 py-2 font-mono text-xs text-text-primary">
          haze open
        </pre>
        <p className="text-text-muted">
          The token lives in{' '}
          <code className="font-mono text-text-secondary">~/.haze/config.json</code> and gates an
          API that can run processes on this machine, which is why the dashboard will not load
          without it.
        </p>
      </div>
    </Panel>
  );
}
