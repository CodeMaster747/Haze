import { create } from 'zustand';

import { createDataSource, type DataSource } from '@/data';
import type { LinkState, NodeInfo } from '@/types';

interface ClusterState {
  nodes: NodeInfo[];
  link: LinkState;
  source: DataSource | null;
  /** True when this build talks to a real agent; false in the hosted demo. */
  isLive: boolean;
  connect: () => () => void;
}

export const useCluster = create<ClusterState>((set) => ({
  nodes: [],
  link: 'connecting',
  source: null,
  isLive: !__HAZE_DEMO__,

  connect: () => {
    const source = createDataSource();
    set({ source });
    return source.subscribe(({ nodes, link }) => set({ nodes, link }));
  },
}));

export const selectSelf = (s: ClusterState): NodeInfo | undefined =>
  s.nodes.find((n) => n.is_self) ?? s.nodes[0];
