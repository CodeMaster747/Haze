/** A deterministic cluster, simulated in the browser.
 *
 *  This is what the deployed demo runs. There is no backend: no server to pay
 *  for, nothing to cold-start, and nothing that can rot when a free tier
 *  changes its terms. It is also why the public URL shows something moving
 *  within a second of landing.
 *
 *  The important property is that it is **not a mock**. Placement goes through
 *  `decide()` — the same function, checked against the Python implementation by
 *  the conformance corpus. What is simulated is the hardware and the passage of
 *  time; the decisions are real.
 */

import { decide, type Decision, type JobRequirement, type NodeCandidate } from '@/sim/scheduler';
import { VirtualClock } from '@/sim/clock';
import { mulberry32, ouStep } from '@/sim/rng';
import { PROFILES, type Profile } from '@/sim/profiles';

export type SimJobState = 'queued' | 'running' | 'succeeded' | 'failed';

export interface SimJob {
  id: string;
  label: string;
  runtime: string;
  requirement: JobRequirement;
  state: SimJobState;
  nodeId: string | null;
  /** 0-1. Work completed, not time elapsed — a job moved to a slower node
   *  keeps its progress rather than restarting the bar. */
  progress: number;
  decision: Decision | null;
  startedAt: number | null;
  finishedAt: number | null;
  error: string;
  attempts: number;
  transferRemaining: number;
  /** Seconds of compute still owed, at speed_factor 1.0. */
  workRemaining: number;
}

export interface SimNode {
  profile: Profile;
  nodeId: string;
  online: boolean;
  cpu: number;
  ramPercent: number;
  gpuUtil: number;
  isSelf: boolean;
}

const SELF_PROFILE = 'laptop';
const DEFAULT_SEED = 0x48415a45; // "HAZE"
const GiB = 1024 ** 3;
const MiB = 1024 ** 2;

/** Load a running job adds to its node, in CPU percent. Enough that a busy
 *  node visibly becomes a worse choice, which is the behaviour worth showing. */
const LOAD_PER_JOB = 45;

export interface ClusterSnapshot {
  nodes: SimNode[];
  jobs: SimJob[];
  clock: { seconds: number; paused: boolean; speed: number };
  latencyMultiplier: number;
  lastDecision: Decision | null;
}

export class SimulatedCluster {
  readonly clock = new VirtualClock();

  private rand: () => number;
  private nodes: SimNode[] = [];
  private jobs: SimJob[] = [];
  private latencyMultiplier = 1;
  private lastDecision: Decision | null = null;
  private jobCounter = 0;
  private seed: number;

  constructor(seed: number = DEFAULT_SEED) {
    this.seed = seed;
    this.rand = mulberry32(seed);
    this.reset();
  }

  reset(): void {
    this.rand = mulberry32(this.seed);
    this.clock.reset();
    this.jobs = [];
    this.jobCounter = 0;
    this.lastDecision = null;
    this.latencyMultiplier = 1;
    this.nodes = PROFILES.map((profile) => this.makeNode(profile));
  }

  private makeNode(profile: Profile): SimNode {
    return {
      profile,
      // Shaped like a real node id so the UI needs no special case, but
      // unmistakably a demo value on inspection.
      nodeId: `DEMO${profile.name.slice(0, 3).toUpperCase()}`,
      online: true,
      cpu: profile.cpuMean,
      ramPercent: 30 + this.rand() * 25,
      gpuUtil: profile.gpu?.utilisation ?? 0,
      isSelf: profile.name === SELF_PROFILE,
    };
  }

  // --- controls ----------------------------------------------------------

  setLatencyMultiplier(value: number): void {
    this.latencyMultiplier = Math.max(0.1, Math.min(50, value));
  }

  getLatencyMultiplier(): number {
    return this.latencyMultiplier;
  }

  setNodeOnline(nodeId: string, online: boolean): void {
    const node = this.nodes.find((n) => n.nodeId === nodeId);
    if (!node || node.online === online) return;
    node.online = online;

    if (!online) {
      // Anything running there is lost and must be placed again. This is the
      // fault-injection demo: kill a node mid-job and watch the work move.
      for (const job of this.jobs) {
        if (job.nodeId === nodeId && (job.state === 'running' || job.state === 'queued')) {
          job.state = 'queued';
          job.nodeId = null;
          job.attempts += 1;
          job.error = `${node.profile.name} went offline — rescheduling`;
        }
      }
    }
  }

  addNode(profileName: string): void {
    const profile = PROFILES.find((p) => p.name === profileName);
    if (!profile) return;
    const copy: Profile = { ...profile, name: `${profile.name}-${this.nodes.length}` };
    this.nodes.push({ ...this.makeNode(copy), isSelf: false });
  }

  removeNode(nodeId: string): void {
    const node = this.nodes.find((n) => n.nodeId === nodeId);
    if (!node || node.isSelf) return; // never remove the machine you are "on"
    this.setNodeOnline(nodeId, false);
    this.nodes = this.nodes.filter((n) => n.nodeId !== nodeId);
  }

  submit(kind: 'render' | 'encode' | 'benchmark'): SimJob {
    this.jobCounter += 1;
    const requirement = REQUIREMENTS[kind];
    const job: SimJob = {
      id: `demo-${this.jobCounter.toString().padStart(4, '0')}`,
      label: LABELS[kind],
      runtime: requirement.runtime,
      requirement,
      state: 'queued',
      nodeId: null,
      progress: 0,
      decision: null,
      startedAt: null,
      finishedAt: null,
      error: '',
      attempts: 0,
      transferRemaining: 0,
      workRemaining: requirement.work_units,
    };
    this.jobs = [job, ...this.jobs].slice(0, 12);
    return job;
  }

  // --- the loop ----------------------------------------------------------

  tick(realDeltaMs: number): void {
    const deltaMs = this.clock.advance(realDeltaMs);
    if (deltaMs === 0) return;
    const deltaS = deltaMs / 1000;

    this.driftTelemetry(deltaS);
    this.placeQueuedJobs();
    this.advanceRunningJobs(deltaS);
  }

  private driftTelemetry(deltaS: number): void {
    // Scaled by the timestep so the drift looks the same at any clock speed.
    const scale = Math.min(1, deltaS);
    for (const node of this.nodes) {
      if (!node.online) {
        node.cpu = 0;
        node.gpuUtil = 0;
        continue;
      }
      const busy = this.jobs.filter(
        (j) => j.nodeId === node.nodeId && j.state === 'running',
      ).length;
      const target = Math.min(98, node.profile.cpuMean + busy * LOAD_PER_JOB);
      node.cpu = ouStep(node.cpu, target, 0.25 * scale, 6 * scale, this.rand);
      node.ramPercent = ouStep(node.ramPercent, 45 + busy * 12, 0.1 * scale, 2 * scale, this.rand);
      if (node.profile.gpu) {
        const gpuTarget = (node.profile.gpu.utilisation ?? 10) + busy * 30;
        node.gpuUtil = ouStep(node.gpuUtil, Math.min(98, gpuTarget), 0.2 * scale, 8 * scale, this.rand);
      }
    }
  }

  private placeQueuedJobs(): void {
    for (const job of this.jobs) {
      if (job.state !== 'queued') continue;

      const decision = decide(this.candidates(), job.requirement);
      job.decision = decision;
      this.lastDecision = decision;

      if (decision.chosen === null) {
        job.state = 'failed';
        job.error = decision.summary;
        job.finishedAt = this.clock.seconds;
        continue;
      }

      const chosen = decision.assessments.find((a) => a.node_id === decision.chosen);
      job.nodeId = decision.chosen;
      job.state = 'running';
      job.startedAt ??= this.clock.seconds;
      job.error = '';
      // The transfer the scheduler predicted, so what the bar shows and what
      // the decision said agree.
      job.transferRemaining = Math.max(
        0,
        (chosen?.estimated_seconds ?? 0) - job.workRemaining / this.speedOf(decision.chosen),
      );
    }
  }

  private advanceRunningJobs(deltaS: number): void {
    for (const job of this.jobs) {
      if (job.state !== 'running' || job.nodeId === null) continue;

      const node = this.nodes.find((n) => n.nodeId === job.nodeId);
      if (!node || !node.online) {
        job.state = 'queued';
        job.nodeId = null;
        continue;
      }

      let remaining = deltaS;
      if (job.transferRemaining > 0) {
        const spent = Math.min(job.transferRemaining, remaining);
        job.transferRemaining -= spent;
        remaining -= spent;
      }
      if (remaining <= 0) continue;

      const contention = 1 + Math.min(100, Math.max(0, node.cpu)) / 100;
      job.workRemaining -= (remaining * node.profile.speedFactor) / contention;

      const total = job.requirement.work_units;
      job.progress = Math.min(1, Math.max(0, 1 - job.workRemaining / total));

      if (job.workRemaining <= 0) {
        job.state = 'succeeded';
        job.progress = 1;
        job.finishedAt = this.clock.seconds;
      }
    }
  }

  private speedOf(nodeId: string): number {
    return this.nodes.find((n) => n.nodeId === nodeId)?.profile.speedFactor ?? 1;
  }

  /** The scheduler's view of this cluster. */
  candidates(): NodeCandidate[] {
    return this.nodes.map((node) => ({
      node_id: node.nodeId,
      name: node.profile.name,
      cores: node.profile.cores,
      ram_total: node.profile.ramBytes,
      ram_available: Math.round((1 - node.ramPercent / 100) * node.profile.ramBytes),
      cpu_percent: Math.round(node.cpu * 10) / 10,
      speed_factor: node.profile.speedFactor,
      runtimes: node.profile.gpu ? ['hashbench', 'blender', 'ffmpeg'] : ['hashbench', 'blender'],
      encoders: node.profile.gpu?.encoders ?? [],
      has_gpu: node.profile.gpu !== null,
      gpu_name: node.profile.gpu?.name ?? '',
      // The slider. Multiplying latency and dividing throughput is what makes
      // "drag this and watch the scheduler change its mind" work.
      latency_ms: node.isSelf ? 0 : 3 * this.latencyMultiplier,
      throughput_mbps: node.isSelf ? 0 : 940 / this.latencyMultiplier,
      is_self: node.isSelf,
      simulated: true,
      online: node.online,
    }));
  }

  snapshot(): ClusterSnapshot {
    return {
      nodes: [...this.nodes],
      jobs: [...this.jobs],
      clock: {
        seconds: this.clock.seconds,
        paused: this.clock.isPaused,
        speed: this.clock.speed,
      },
      latencyMultiplier: this.latencyMultiplier,
      lastDecision: this.lastDecision,
    };
  }
}

const REQUIREMENTS: Record<'render' | 'encode' | 'benchmark', JobRequirement> = {
  render: {
    runtime: 'blender',
    cpu_cores: 4,
    ram_bytes: 2 * GiB,
    needs_gpu: true,
    preferred_encoders: [],
    input_bytes: 40 * MiB,
    work_units: 24,
  },
  encode: {
    runtime: 'ffmpeg',
    cpu_cores: 2,
    ram_bytes: GiB,
    needs_gpu: false,
    preferred_encoders: ['hevc_nvenc'],
    input_bytes: 700 * MiB,
    work_units: 14,
  },
  benchmark: {
    runtime: 'hashbench',
    cpu_cores: 1,
    ram_bytes: 512 * MiB,
    needs_gpu: false,
    preferred_encoders: [],
    input_bytes: 0,
    work_units: 10,
  },
};

const LABELS: Record<'render' | 'encode' | 'benchmark', string> = {
  render: 'Blender render · 40 MiB in',
  encode: 'HEVC encode · 700 MiB in',
  benchmark: 'CPU benchmark · no inputs',
};
