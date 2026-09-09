/** Domain types shared by the live agent view and the simulated demo.
 *
 *  These mirror the payloads in agent/src/haze/api/ws.py. They are hand-written
 *  rather than generated because the agent's API is small and private (loopback
 *  only, one consumer); a codegen step would cost more than it saves. If the
 *  API grows, generate from OpenAPI the way Frugal does.
 */

import type { Decision } from '@/sim/scheduler';

export interface CpuStats {
  percent: number;
  per_core: number[];
  cores: number;
  physical_cores: number;
}

export interface MemStats {
  total: number;
  used: number;
  available: number;
  percent: number;
}

export interface DiskStats {
  total: number;
  used: number;
  free: number;
  percent: number;
}

/** Populated in M2. `null` on nodes where the OS will not report GPU telemetry
 *  without elevated privileges — notably Apple Silicon, where the sudoless path
 *  (`ioreg -r -c AGXAccelerator`) gives utilisation but not VRAM breakdown. */
export interface GpuStats {
  vendor: 'nvidia' | 'apple' | 'amd' | 'intel';
  name: string;
  utilisation: number | null;
  vram_total: number | null;
  vram_used: number | null;
  encoders: string[];
}

export interface NetStats {
  latency_ms: number | null;
  throughput_mbps: number | null;
}

export interface Telemetry {
  node_name: string;
  /** True when this node's hardware is fabricated from a devnet profile.
   *  Travels with every sample so nothing can render a node without knowing. */
  simulated?: boolean;
  ts: number;
  uptime_s: number;
  cpu: CpuStats;
  ram: MemStats;
  disk: DiskStats;
  gpu: GpuStats | null;
  net: NetStats | null;
}

export type NodeStatus = 'online' | 'busy' | 'offline' | 'error';

export interface NodeInfo {
  name: string;
  /** Ed25519-derived, set from M1. `null` before identity exists. */
  node_id: string | null;
  status: NodeStatus;
  /** True for devnet/demo nodes with synthetic hardware profiles.
   *  Every surface that renders a node MUST show this — an unbadged fake
   *  "RTX 4090" on a machine with no NVIDIA GPU turns the project's best demo
   *  asset into its worst credibility problem. */
  simulated: boolean;
  is_self: boolean;
  telemetry: Telemetry | null;
}

/** What the socket is doing, for the connection indicator. */
export type LinkState = 'connecting' | 'live' | 'retrying' | 'unauthorised' | 'closed';

// --- pairing ---------------------------------------------------------------

export type PairDirection = 'incoming' | 'outgoing';
export type PairDecision = 'pending' | 'confirmed' | 'rejected' | 'expired';

export interface PendingPairing {
  session_id: string;
  direction: PairDirection;
  node_id: string;
  short_id: string;
  name: string;
  platform: string;
  version: string;
  /** The six digits that MUST match the other machine's screen. */
  sas_digits: string;
  /** The same value as four PGP words — far easier to compare across a room
   *  than six digits, and much harder to misread as matching when it isn't. */
  sas_words: string[];
  decision: PairDecision;
  expires_in_s: number;
}

export interface PairingState {
  armed: boolean;
  arm_remaining_s: number;
  pending: PendingPairing[];
  last_error: string | null;
}

export interface SelfNode {
  node_id: string | null;
  short_id: string | null;
  name: string;
}

export interface PeerRow {
  node_id: string;
  short_id: string;
  name: string;
  platform: string;
  version: string;
  last_host: string;
  last_port: number;
  /** Address the user pinned, if any. Observed traffic never overwrites it. */
  pinned_host: string;
  pinned_port: number;
  paired_at: string;
  last_seen_at: string | null;
}

// --- discovery -------------------------------------------------------------

export type DiscoverySource = 'mdns' | 'broadcast' | 'manual' | 'paired';

export interface DiscoveredNode {
  node_id: string;
  short_id: string;
  name: string;
  host: string;
  port: number;
  /** Which mechanisms have seen it. Shown because "found by broadcast but not
   *  mDNS" is the signature of multicast being filtered on this network, and
   *  naming that saves someone an hour of guessing. */
  sources: DiscoverySource[];
  platform: string;
  version: string;
  paired: boolean;
  /** null until probed. `false` while `sources` is non-empty is the
   *  access-point-isolation signature: we can see it advertise but cannot
   *  open a connection to it. */
  reachable: boolean | null;
  age_s: number;
}

export interface DiscoveryState {
  mdns: boolean;
  broadcast: boolean;
  nodes: DiscoveredNode[];
}

// --- jobs ------------------------------------------------------------------

export type JobState =
  | 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'rejected';

export interface JobProgress {
  /** null where the runtime does not give enough to compute one. A progress
   *  bar that lies is worse than one that admits it does not know. */
  fraction: number | null;
  stage: string;
  detail: string;
  frames_done: number | null;
  frames_total: number | null;
  rate: string;
  eta_seconds: number | null;
}

export interface Job {
  job_id: string;
  runtime: string;
  label: string;
  submitted_by: string;
  args: Record<string, unknown>;
  resources: {
    cpu_cores: number;
    ram_bytes: number;
    wall_seconds: number;
    needs_gpu: boolean;
    preferred_encoders: string[];
  };
  state: JobState;
  progress: JobProgress;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
  exit_code: number | null;
  error: string;
  log_tail: string[];
  outputs: string[];
  peak_ram_bytes: number;
  /** What the OS was actually made to enforce for this job.
   *
   *  Null for a job that never started, and for a peer running a version that
   *  predates it. Carried per job rather than read off the node's caps because
   *  a Job Object or a cgroup scope can fail for one job and not the next. */
  enforcement: Enforcement | null;
  /** Why this job went where it did, when the scheduler placed it.
   *
   *  Null for a job the submitter aimed at a node itself. The shape is the
   *  scheduler's own Decision -- the same one the demo renders -- because the
   *  agent runs the identical function and hands its output straight through. */
  placement: Decision | null;
}

/** How strongly a cap is actually held.
 *
 *  `kernel` does not mean the same mechanism everywhere: Linux OOM-kills a
 *  cgroup that exceeds its memory cap, while a Windows Job Object makes the
 *  allocation fail inside the process. Both genuinely bound the job; only one
 *  is fatal. `notes` carries the difference in words. */
export type Strength = 'kernel' | 'rlimit' | 'advisory';

export interface Enforcement {
  ram: Strength;
  cpu: Strength;
  wall: Strength;
  notes: string[];
}

export interface RuntimeInfo {
  name: string;
  available: boolean;
  description: string;
}

export interface JobCaps {
  max_cores: number;
  max_ram_bytes: number;
  max_wall_seconds: number;
  allow_gpu: boolean;
  /** One line naming what this OS can actually enforce. Shown next to the caps
   *  because a cap that silently is not enforced is worse than no cap. */
  enforcement: string;
  /** Whether this OS can hold the memory and CPU caps at all.
   *
   *  A flag rather than sniffing `enforcement` for a phrase: the UI used to
   *  test that string for 'cannot enforce', which only ever matched the macOS
   *  wording, so a Windows node whose Job Object had failed showed no warning
   *  at all. */
  enforced: boolean;
}

export interface JobsState {
  caps: JobCaps;
  runtimes: RuntimeInfo[];
  jobs: Job[];
}
