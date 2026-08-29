/** The seam that lets one build serve two very different situations.
 *
 *  `HttpAgentSource` talks to a real Node Agent over same-origin HTTP and
 *  WebSocket. `SimSource` runs a deterministic cluster entirely in the browser
 *  and makes no network calls at all, which is what the Firebase-hosted demo
 *  uses — that is why the deployed site costs nothing to run and cannot break.
 *
 *  Every component consumes this interface, never `fetch` directly, so the demo
 *  exercises the same rendering path as the real dashboard.
 */

import type { DiscoveryState, LinkState, NodeInfo, PairingState } from '@/types';

export interface ClusterUpdate {
  nodes: NodeInfo[];
  link: LinkState;
  /** Undefined means "unchanged" — telemetry ticks far more often than
   *  pairing or discovery, so most updates carry neither payload. */
  pairing?: PairingState;
  discovery?: DiscoveryState;
}

export interface DataSource {
  /** Human label for the source, shown in the UI so it is never ambiguous
   *  whether you are looking at real hardware or a simulation. */
  readonly kind: 'agent' | 'simulation';

  /** Begin streaming. Returns a teardown function. The callback fires on every
   *  state change, including link-state transitions with unchanged nodes. */
  subscribe(onUpdate: (update: ClusterUpdate) => void): () => void;
}
