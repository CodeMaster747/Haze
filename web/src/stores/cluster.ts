import { create } from 'zustand';

import { createDataSource, type DataSource } from '@/data';
import type { LinkState, NodeInfo, PairingState } from '@/types';

interface ClusterState {
  nodes: NodeInfo[];
  link: LinkState;
  pairing: PairingState | null;
  source: DataSource | null;
  /** True when this build talks to a real agent; false in the hosted demo. */
  isLive: boolean;
  connect: () => () => void;
}

export const useCluster = create<ClusterState>((set) => ({
  nodes: [],
  link: 'connecting',
  pairing: null,
  source: null,
  isLive: !__HAZE_DEMO__,

  connect: () => {
    const source = createDataSource();
    set({ source });
    return source.subscribe(({ nodes, link, pairing }) =>
      // `pairing` is omitted on telemetry-only ticks; keep the last value
      // rather than blanking the dialog every second.
      set((state) => ({ nodes, link, pairing: pairing ?? state.pairing })),
    );
  },
}));

export const selectSelf = (s: ClusterState): NodeInfo | undefined =>
  s.nodes.find((n) => n.is_self) ?? s.nodes[0];
