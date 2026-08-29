import { create } from 'zustand';

import { createDataSource, type DataSource } from '@/data';
import type { DiscoveryState, LinkState, NodeInfo, PairingState } from '@/types';

interface ClusterState {
  nodes: NodeInfo[];
  link: LinkState;
  pairing: PairingState | null;
  discovery: DiscoveryState | null;
  source: DataSource | null;
  /** True when this build talks to a real agent; false in the hosted demo. */
  isLive: boolean;
  connect: () => () => void;
}

export const useCluster = create<ClusterState>((set) => ({
  nodes: [],
  link: 'connecting',
  pairing: null,
  discovery: null,
  source: null,
  isLive: !__HAZE_DEMO__,

  connect: () => {
    const source = createDataSource();
    set({ source });
    return source.subscribe(({ nodes, link, pairing, discovery }) =>
      // `pairing` and `discovery` are omitted on telemetry-only ticks; keep the
      // last value rather than blanking the dialog and node list every second.
      set((state) => ({
        nodes,
        link,
        pairing: pairing ?? state.pairing,
        discovery: discovery ?? state.discovery,
      })),
    );
  },
}));

export const selectSelf = (s: ClusterState): NodeInfo | undefined =>
  s.nodes.find((n) => n.is_self) ?? s.nodes[0];
