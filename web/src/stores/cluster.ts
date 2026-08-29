import { create } from 'zustand';

import { createDataSource, type DataSource } from '@/data';
import { SimSource } from '@/data/SimSource';
import type { SimulatedCluster } from '@/sim/cluster';
import type {
  DiscoveryState,
  JobsState,
  LinkState,
  NodeInfo,
  PairingState,
} from '@/types';

interface ClusterState {
  nodes: NodeInfo[];
  link: LinkState;
  pairing: PairingState | null;
  discovery: DiscoveryState | null;
  jobs: JobsState | null;
  source: DataSource | null;
  /** Present only in the demo build. The live source has no equivalent,
   *  which is why the demo controls render conditionally on it. */
  simulation: SimulatedCluster | null;
  /** True when this build talks to a real agent; false in the hosted demo. */
  isLive: boolean;
  connect: () => () => void;
}

export const useCluster = create<ClusterState>((set) => ({
  nodes: [],
  link: 'connecting',
  pairing: null,
  discovery: null,
  jobs: null,
  source: null,
  simulation: null,
  isLive: !__HAZE_DEMO__,

  connect: () => {
    const source = createDataSource();
    set({ source, simulation: source instanceof SimSource ? source.cluster : null });
    return source.subscribe(({ nodes, link, pairing, discovery, jobs }) =>
      // `pairing` and `discovery` are omitted on telemetry-only ticks; keep the
      // last value rather than blanking the dialog and node list every second.
      set((state) => ({
        nodes,
        link,
        pairing: pairing ?? state.pairing,
        discovery: discovery ?? state.discovery,
        jobs: jobs ?? state.jobs,
      })),
    );
  },
}));

export const selectSelf = (s: ClusterState): NodeInfo | undefined =>
  s.nodes.find((n) => n.is_self) ?? s.nodes[0];
