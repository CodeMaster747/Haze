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
import { Code, CodeBlock } from '@/components/ui/Code';
import { Panel } from '@/components/ui/Panel';
import { Skeleton } from '@/components/ui/Skeleton';
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
    <div className="flex min-h-dvh flex-col bg-bg-primary text-text-primary">
      <Header link={link} isLive={isLive} />

      <main className="shell animate-fade-in flex-1 py-6 sm:py-8">
        {simulation && <Hero />}

        {link === 'unauthorised' ? (
          <Unauthorised />
        ) : nodes.length === 0 ? (
          <ConnectingSkeleton />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-2">
              {nodes.map((node) => (
                <NodeCard key={node.name} node={node} />
              ))}
            </div>

            {simulation ? (
              <div className="grid items-start gap-4 lg:grid-cols-2">
                <DemoControls cluster={simulation} />
                <DecisionTrace decision={simulation.snapshot().lastDecision} />
              </div>
            ) : (
              <div className="grid items-start gap-4 lg:grid-cols-2">
                <NetworkPanel discovery={discovery} disabled={!isLive} />
                <PeerList enabled={isLive} />
              </div>
            )}

            <JobsPanel jobs={jobs} peers={peers} disabled={!isLive} />

            {!simulation && <PairingPanel pairing={pairing} disabled={!isLive} />}
          </div>
        )}

        {simulation && link !== 'unauthorised' && <DemoFooter />}
      </main>

      {awaiting && <SasDialog pending={awaiting} />}
    </div>
  );
}

/** What someone needs on arriving at the cluster itself.
 *
 *  This used to repeat the product pitch, which is now the landing page's job
 *  and which most visitors have just finished reading. Repeating it here made
 *  the click feel like it had gone nowhere. What is left is orientation: what
 *  you are looking at, what is fabricated about it, and what to do with it —
 *  which is also what someone arriving on a direct link to /cluster needs,
 *  having never seen the landing page.
 */
function Hero() {
  return (
    <section className="mb-6 max-w-2xl sm:mb-8">
      <h1 className="text-2xl font-semibold tracking-tight text-text-primary sm:text-3xl">
        Simulated cluster
      </h1>
      <p className="mt-3 text-base leading-relaxed text-text-secondary">
        The hardware and the passage of time are fabricated. The scheduling is not — every
        placement below runs through the same function a real agent uses.
      </p>
      <p className="mt-2 text-sm leading-relaxed text-text-muted">
        Submit a job, drag the link between machines from LAN to slow, or take one offline
        mid-render and watch the work move.
      </p>
    </section>
  );
}

/** First connect. The layout that is arriving, at the size it will arrive at,
 *  so the page does not jump when the first telemetry frame lands. */
function ConnectingSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-label="Connecting to the agent on this machine">
      <div className="grid gap-4 lg:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} className="rounded-lg border border-border-subtle bg-bg-panel">
            <div className="flex h-11 items-center border-b border-border-subtle px-4">
              <Skeleton className="h-3.5 w-32" />
            </div>
            <div className="space-y-4 p-4">
              <div className="grid gap-4 sm:grid-cols-2">
                {[0, 1, 2, 3].map((j) => (
                  <div key={j} className="space-y-2">
                    <Skeleton className="h-3 w-20" />
                    <Skeleton className="h-1.5 w-full rounded-full" />
                  </div>
                ))}
              </div>
              <Skeleton className="h-6 w-full" />
            </div>
          </div>
        ))}
      </div>
      <p className="text-center text-sm text-text-muted">Connecting to the agent on this machine…</p>
    </div>
  );
}

/** The demo's closing pitch: what this is, and how to run it for real.
 *
 *  A footer band rather than a panel. It is not a peer of the cluster panels
 *  above it, and giving it the same border would say that it is. */
function DemoFooter() {
  return (
    <footer className="mt-10 border-t border-border-subtle pt-6">
      <div className="grid gap-6 sm:grid-cols-2 sm:gap-10">
        <div className="space-y-3 text-sm leading-relaxed text-text-secondary">
          <h2 className="text-sm font-medium text-text-primary">This is a simulation</h2>
          <p>
            There is no backend here. The hardware and the passage of time are simulated in your
            browser — but the placement decisions are made by the{' '}
            <strong className="font-medium text-text-primary">
              same scheduler the real agent runs
            </strong>
            , held to the Python implementation by a conformance corpus in CI.
          </p>
          <a
            href="https://github.com/CodeMaster747/Haze"
            className="inline-flex items-center gap-1 rounded text-accent-primary underline-offset-4 transition-colors hover:text-accent-hover hover:underline"
          >
            Source, architecture notes and threat model →
          </a>
        </div>

        <div className="space-y-3">
          <h2 className="text-sm font-medium text-text-primary">Pool your own machines</h2>
          <CodeBlock>
            uv tool install haze-agent{'\n'}haze up
          </CodeBlock>
          <p className="text-xs leading-relaxed text-text-muted">
            Then <Code>haze pair --serve</Code> on one machine and{' '}
            <Code>haze pair --host &lt;address&gt;</Code> on the other.
          </p>
        </div>
      </div>
    </footer>
  );
}

/** The most likely first-run confusion: the page was opened by hand at
 *  127.0.0.1:7433 rather than via the tokenised URL the agent prints. Say
 *  exactly that, with the fix, instead of showing a generic error. */
function Unauthorised() {
  return (
    <Panel title="Not authorised" className="mx-auto max-w-xl">
      <div className="space-y-3 text-sm leading-relaxed text-text-secondary">
        <p>
          This page needs the access token the agent prints when it starts. Open the console using
          the full URL from your terminal:
        </p>
        <CodeBlock>haze open</CodeBlock>
        <p className="text-xs text-text-muted">
          The token lives in <Code>~/.haze/config.json</Code> and gates an API that can run
          processes on this machine, which is why the dashboard will not load without it.
        </p>
      </div>
    </Panel>
  );
}
