/** A cluster that exists entirely in the visitor's browser.
 *
 *  This is what the Firebase-hosted demo runs. It makes no network calls, so
 *  the deployed site has no backend to pay for, nothing to cold-start, and
 *  nothing that can rot when a free tier changes. It is also the reason the
 *  public URL shows something moving within a second of landing.
 *
 *  M5 extends this into the interactive sandbox (add/kill nodes, latency
 *  slider, scheduler re-placement on a virtual clock). M0 establishes the seam
 *  and the telemetry shape so the UI is built against both sources from the
 *  first commit.
 */

import type { ClusterUpdate, DataSource } from '@/data/DataSource';
import { PROFILES, type Profile } from '@/sim/profiles';
import { mulberry32, ouStep } from '@/sim/rng';
import type { NodeInfo, Telemetry } from '@/types';

const TICK_MS = 1_000;
const DEFAULT_SEED = 0x48415a45; // "HAZE"

interface SimNode {
  profile: Profile;
  cpu: number;
  ramPercent: number;
  diskPercent: number;
  gpuUtil: number;
}

export class SimSource implements DataSource {
  readonly kind = 'simulation' as const;

  private readonly rand: () => number;
  private readonly nodes: SimNode[];
  private timer: number | null = null;
  private startedAt = Date.now();

  constructor(seed: number = DEFAULT_SEED) {
    this.rand = mulberry32(seed);
    this.nodes = PROFILES.map((profile) => ({
      profile,
      cpu: profile.cpuMean,
      ramPercent: 30 + this.rand() * 25,
      diskPercent: 20 + this.rand() * 40,
      gpuUtil: profile.gpu?.utilisation ?? 0,
    }));
  }

  subscribe(onUpdate: (update: ClusterUpdate) => void): () => void {
    const emit = () => onUpdate({ nodes: this.nodes.map((n) => this.toNodeInfo(n)), link: 'live' });

    emit();
    this.timer = window.setInterval(() => {
      for (const node of this.nodes) {
        node.cpu = ouStep(node.cpu, node.profile.cpuMean, 0.18, 9, this.rand);
        node.ramPercent = ouStep(node.ramPercent, 45, 0.06, 2.5, this.rand);
        if (node.profile.gpu) {
          node.gpuUtil = ouStep(node.gpuUtil, node.profile.gpu.utilisation ?? 10, 0.12, 11, this.rand);
        }
      }
      emit();
    }, TICK_MS);

    return () => {
      if (this.timer !== null) window.clearInterval(this.timer);
      this.timer = null;
    };
  }

  private toNodeInfo(node: SimNode): NodeInfo {
    const { profile } = node;
    const ramUsed = Math.round((node.ramPercent / 100) * profile.ramBytes);
    const diskUsed = Math.round((node.diskPercent / 100) * profile.diskBytes);

    const telemetry: Telemetry = {
      node_name: profile.name,
      ts: Date.now() / 1000,
      uptime_s: Math.round((Date.now() - this.startedAt) / 1000),
      cpu: {
        percent: Math.round(node.cpu * 10) / 10,
        // Per-core spread around the aggregate, so the core grid looks like a
        // real machine rather than N identical bars.
        per_core: Array.from({ length: profile.cores }, (_, i) =>
          Math.round(Math.min(100, Math.max(0, node.cpu + ((i * 37) % 23) - 11)) * 10) / 10,
        ),
        cores: profile.cores,
        physical_cores: profile.physicalCores,
      },
      ram: {
        total: profile.ramBytes,
        used: ramUsed,
        available: profile.ramBytes - ramUsed,
        percent: Math.round(node.ramPercent * 10) / 10,
      },
      disk: {
        total: profile.diskBytes,
        used: diskUsed,
        free: profile.diskBytes - diskUsed,
        percent: Math.round(node.diskPercent * 10) / 10,
      },
      gpu: profile.gpu
        ? { ...profile.gpu, utilisation: Math.round(node.gpuUtil * 10) / 10 }
        : null,
      net: null,
    };

    return {
      name: profile.name,
      node_id: null,
      status: 'online',
      simulated: true,
      is_self: profile.name === 'laptop',
      telemetry,
    };
  }
}
