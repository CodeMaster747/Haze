/** A cluster that exists entirely in the visitor's browser.
 *
 *  This is what the deployed demo runs. No backend: nothing to pay for,
 *  nothing to cold-start, nothing that rots when a free tier changes terms —
 *  and something moving within a second of landing on the page.
 *
 *  It is not a mock. Placement goes through the same `decide()` the agent uses,
 *  held to the Python implementation by a conformance corpus in CI. The
 *  hardware and the passage of time are simulated; the scheduling is real.
 */

import type { ClusterUpdate, DataSource } from '@/data/DataSource';
import { SimulatedCluster, type SimJob, type SimNode } from '@/sim/cluster';
import type {
  DiscoveredNode,
  DiscoveryState,
  Job,
  JobsState,
  NodeInfo,
  Telemetry,
} from '@/types';

const FRAME_MS = 250;

export class SimSource implements DataSource {
  readonly kind = 'simulation' as const;

  /** Exposed so the demo controls can drive it. The live source has no
   *  equivalent, which is why the controls only render in demo builds. */
  readonly cluster: SimulatedCluster;

  private timer: number | null = null;
  private lastTick = 0;

  constructor(seed?: number) {
    this.cluster = new SimulatedCluster(seed);
  }

  subscribe(onUpdate: (update: ClusterUpdate) => void): () => void {
    const emit = () => {
      const snapshot = this.cluster.snapshot();
      onUpdate({
        nodes: snapshot.nodes.map((n) => this.toNodeInfo(n)),
        link: 'live',
        pairing: { armed: false, arm_remaining_s: 0, pending: [], last_error: null },
        discovery: this.toDiscovery(snapshot.nodes),
        jobs: this.toJobs(snapshot.jobs),
      });
    };

    this.lastTick = performance.now();
    emit();

    this.timer = window.setInterval(() => {
      const now = performance.now();
      this.cluster.tick(now - this.lastTick);
      this.lastTick = now;
      emit();
    }, FRAME_MS);

    return () => {
      if (this.timer !== null) window.clearInterval(this.timer);
      this.timer = null;
    };
  }

  // --- shaping into the same types the live agent produces -----------------

  private toNodeInfo(node: SimNode): NodeInfo {
    const { profile } = node;
    const ramUsed = Math.round((node.ramPercent / 100) * profile.ramBytes);

    const telemetry: Telemetry = {
      node_name: profile.name,
      simulated: true,
      ts: this.cluster.clock.seconds,
      uptime_s: Math.round(this.cluster.clock.seconds),
      cpu: {
        percent: Math.round(node.cpu * 10) / 10,
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
      disk: { total: profile.diskBytes, used: 0, free: profile.diskBytes, percent: 22 },
      gpu: profile.gpu
        ? { ...profile.gpu, utilisation: Math.round(node.gpuUtil * 10) / 10 }
        : null,
      net: null,
    };

    return {
      name: profile.name,
      node_id: node.nodeId,
      status: node.online ? 'online' : 'offline',
      simulated: true,
      is_self: node.isSelf,
      telemetry: node.online ? telemetry : null,
    };
  }

  private toDiscovery(nodes: SimNode[]): DiscoveryState {
    return {
      mdns: true,
      broadcast: true,
      nodes: nodes
        .filter((n) => !n.isSelf)
        .map(
          (n, i): DiscoveredNode => ({
            node_id: n.nodeId,
            short_id: n.nodeId,
            name: n.profile.name,
            host: `192.168.1.${20 + i}`,
            port: 8443,
            sources: ['mdns', 'broadcast'],
            platform: 'demo',
            version: '0.1.0',
            paired: true,
            reachable: n.online,
            age_s: 1,
          }),
        ),
    };
  }

  private toJobs(jobs: SimJob[]): JobsState {
    return {
      caps: {
        max_cores: 8,
        max_ram_bytes: 32 * 1024 ** 3,
        max_wall_seconds: 7200,
        allow_gpu: true,
        enforcement: 'simulated — nothing actually executes in the demo',
      },
      runtimes: [
        { name: 'hashbench', available: true, description: 'CPU benchmark' },
        { name: 'blender', available: true, description: 'Render frames from a .blend file' },
        { name: 'ffmpeg', available: true, description: 'Transcode a video file' },
      ],
      jobs: jobs.map((job): Job => this.toJob(job)),
    };
  }

  private toJob(job: SimJob): Job {
    const chosen = job.decision?.assessments.find((a) => a.node_id === job.nodeId);
    const stage =
      job.transferRemaining > 0 ? 'transferring' : job.state === 'running' ? 'computing' : job.state;

    return {
      job_id: job.id,
      runtime: job.runtime,
      label: job.label,
      submitted_by: '',
      args: {},
      resources: {
        cpu_cores: job.requirement.cpu_cores,
        ram_bytes: job.requirement.ram_bytes,
        wall_seconds: 900,
        needs_gpu: job.requirement.needs_gpu,
        preferred_encoders: job.requirement.preferred_encoders,
      },
      state:
        job.state === 'succeeded' ? 'succeeded' : job.state === 'failed' ? 'failed' : job.state,
      progress: {
        fraction: job.progress,
        stage,
        detail: job.decision?.summary ?? '',
        frames_done: null,
        frames_total: null,
        rate: chosen ? `~${chosen.estimated_seconds}s predicted` : '',
        eta_seconds: null,
      },
      created_at: new Date(0).toISOString(),
      started_at: job.startedAt === null ? null : new Date(job.startedAt * 1000).toISOString(),
      finished_at: job.finishedAt === null ? null : new Date(job.finishedAt * 1000).toISOString(),
      duration_s:
        job.startedAt !== null && job.finishedAt !== null
          ? Math.round((job.finishedAt - job.startedAt) * 100) / 100
          : null,
      exit_code: job.state === 'succeeded' ? 0 : null,
      error: job.error,
      log_tail: [],
      outputs: [],
      peak_ram_bytes: 0,
    };
  }
}
