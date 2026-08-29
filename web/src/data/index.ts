import type { DataSource } from '@/data/DataSource';
import { HttpAgentSource } from '@/data/HttpAgentSource';
import { SimSource } from '@/data/SimSource';

/** Pick the source for this build.
 *
 *  `__HAZE_DEMO__` is a compile-time constant (vite `define`), not a runtime
 *  check, so the unused source is dead-code-eliminated. That matters in both
 *  directions: the demo build ships no code that could ever contact a local
 *  agent, and the agent build ships no simulation code that could be mistaken
 *  for real telemetry.
 */
export function createDataSource(): DataSource {
  return __HAZE_DEMO__ ? new SimSource() : new HttpAgentSource();
}

export type { DataSource, ClusterUpdate } from '@/data/DataSource';
