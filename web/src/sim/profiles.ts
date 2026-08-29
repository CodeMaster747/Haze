/** Synthetic hardware profiles for the demo and for `haze devnet`.
 *
 *  These mirror agent/src/haze/devnet/profiles/*.toml. Every node built from
 *  one carries `simulated: true` and MUST render with a badge — see the note
 *  in types.ts on why that is a correctness requirement and not a nicety.
 */

import type { GpuStats } from '@/types';

export interface Profile {
  name: string;
  cores: number;
  physicalCores: number;
  ramBytes: number;
  diskBytes: number;
  gpu: GpuStats | null;
  /** Baseline load this machine idles at, as a percentage. */
  cpuMean: number;
  /** Relative compute throughput, used by the scheduler demo. 1.0 = baseline. */
  speedFactor: number;
}

const GiB = 1024 ** 3;

export const PROFILES: Profile[] = [
  {
    name: 'workstation',
    cores: 16,
    physicalCores: 16,
    ramBytes: 64 * GiB,
    diskBytes: 2048 * GiB,
    gpu: {
      vendor: 'nvidia',
      name: 'RTX 4090',
      utilisation: 12,
      vram_total: 24 * GiB,
      vram_used: 2 * GiB,
      encoders: ['h264_nvenc', 'hevc_nvenc', 'av1_nvenc'],
    },
    cpuMean: 18,
    speedFactor: 4.2,
  },
  {
    name: 'laptop',
    cores: 10,
    physicalCores: 10,
    ramBytes: 24 * GiB,
    diskBytes: 512 * GiB,
    gpu: {
      vendor: 'apple',
      name: 'Apple M-series',
      utilisation: 8,
      // Unified memory: there is no separate VRAM figure to report, and the
      // sudoless ioreg path does not expose one. Showing null is honest.
      vram_total: null,
      vram_used: null,
      encoders: ['h264_videotoolbox', 'hevc_videotoolbox'],
    },
    cpuMean: 24,
    speedFactor: 1.0,
  },
  {
    name: 'nas',
    cores: 4,
    physicalCores: 4,
    ramBytes: 8 * GiB,
    diskBytes: 8192 * GiB,
    gpu: null,
    cpuMean: 6,
    speedFactor: 0.4,
  },
];
