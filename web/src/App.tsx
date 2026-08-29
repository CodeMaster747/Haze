import { useEffect, useState } from 'react';

import { NodeCard } from '@/components/cluster/NodeCard';
import { NetworkPanel } from '@/components/discovery/NetworkPanel';
import { DecisionTrace } from '@/components/demo/DecisionTrace';
import { DemoControls } from '@/components/demo/DemoControls';
import { JobsPanel } from '@/components/jobs/JobsPanel';
import { Header } from '@/components/layout/Header';
import { PairingPanel } from '@/components/pairing/PairingPanel';
import { PeerList } from '@/components/pairing/PeerList';
import { SasDialog } from '@/components/pairing/SasDialog';
import { Panel } from '@/components/ui/Panel';
import { api } from '@/lib/api';
import { useCluster } from '@/stores/cluster';
import type { PeerRow } from '@/types';

export default function App() {
  const { nodes, link, pairing, discovery, jobs, simulation, isLive, connect } = useCluster();
  const [peers, setPeers] = useState<PeerRow[]>([]);

  // Only for the "run on" picker. Polled, because pairing changes twice a year
  // and does not deserve a place on the telemetry socket.
  useEffect(() => {
    if (!isLive) return;
    let alive = true;
    const load = () =>
      api
        .listPeers()
        .then((d) => alive && setPeers(d.peers))
        .catch(() => undefined);
    void load();
    const timer = window.setInterval(load, 5_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [isLive]);

  useEffect(() => connect(), [connect]);

  // At most one dialog at a time. The agent allows only one outstanding
  // request per peer, and stacking modals would make "compare these digits"
  // ambiguous about which pair of screens is being compared.
  const awaiting = pairing?.pending.find((p) => p.decision === 'pending');

  return (
    <div className="min-h-dvh bg-bg-primary text-text-primary">
      <Header link={link} isLive={isLive} />

      <main className="mx-auto max-w-6xl animate-fade-in space-y-4 px-5 py-6">
        {simulation && <Hero />}
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

            {simulation ? (
              <div className="grid gap-4 lg:grid-cols-2">
                <DemoControls cluster={simulation} />
                <DecisionTrace decision={simulation.snapshot().lastDecision} />
              </div>
            ) : (
              <div className="grid gap-4 lg:grid-cols-2">
                <NetworkPanel discovery={discovery} disabled={!isLive} />
                <PeerList enabled={isLive} />
              </div>
            )}

            <JobsPanel jobs={jobs} peers={peers} disabled={!isLive} />

            {!simulation && <PairingPanel pairing={pairing} disabled={!isLive} />}
            {simulation && <DemoFooter />}
          </>
        )}
      </main>

      {awaiting && <SasDialog pending={awaiting} />}
    </div>
  );
}

/** What a first-time visitor needs in the first two seconds.
 *
 *  Deliberately above the cluster, and deliberately short: the moving nodes
 *  below are doing the persuading, and this only has to say what they are.
 */
function Hero() {
  return (
    <section className="pb-2">
      <h1 className="text-2xl font-medium tracking-tight text-text-primary sm:text-3xl">
        Pool your own machines into a private compute network.
      </h1>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
        A weak laptop borrows a desktop's GPU. A NAS lends its disks. You own every node, so
        there is no cloud bill and no third party in the data path.{' '}
        <span className="text-text-muted">
          Below is a live simulated cluster — submit a job, slow the network, kill a machine.
        </span>
      </p>
    </section>
  );
}

/** The demo's closing pitch: what this is, and how to run it for real. */
function DemoFooter() {
  return (
    <Panel title="this is a simulation">
      <div className="space-y-3 text-sm leading-relaxed text-text-secondary">
        <p>
          There is no backend here. The hardware and the passage of time are simulated in
          your browser — but the placement decisions are made by the{' '}
          <strong className="text-text-primary">same scheduler the real agent runs</strong>,
          held to the Python implementation by a conformance corpus in CI.
        </p>
        <p>To pool your own machines for real:</p>
        <pre className="overflow-x-auto rounded border border-border-subtle bg-bg-tertiary px-3 py-2 font-mono text-xs text-text-primary">
          uv tool install haze-agent{'\n'}haze up
        </pre>
        <p className="text-text-muted">
          Then <code className="font-mono text-text-secondary">haze pair --serve</code> on one
          machine and{' '}
          <code className="font-mono text-text-secondary">haze pair --host &lt;address&gt;</code>{' '}
          on the other.
        </p>
        <a
          href="https://github.com/CodeMaster747/Haze"
          className="inline-block text-accent-primary underline-offset-2 hover:underline"
        >
          Source, architecture notes and threat model →
        </a>
      </div>
    </Panel>
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
