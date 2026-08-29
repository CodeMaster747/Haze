/** Calls to the local agent.
 *
 *  Same-origin: the page was served by the agent, so these are loopback →
 *  loopback and exempt from every restriction that makes a public HTTPS page
 *  unable to reach a local agent. There is no base URL to configure and no
 *  CORS to negotiate.
 *
 *  In the hosted demo build these are never called — SimSource drives the UI
 *  instead, and this module is dead-code-eliminated.
 */

import { getToken } from '@/data/token';
import type { PeerRow, SelfNode } from '@/types';

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = getToken();
  const response = await fetch(`/api/v1${path}`, {
    method,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      detail = ((await response.json()) as { detail?: string }).detail ?? detail;
    } catch {
      // Non-JSON error body; the status alone is the best we have.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const api = {
  addManualNode: (host: string, port = 0) =>
    call<unknown>('POST', '/discovery/manual', { host, port }),
  submitJob: (body: {
    runtime: string;
    args: Record<string, unknown>;
    node_id?: string;
    label?: string;
    cpu_cores?: number;
    ram_bytes?: number;
    wall_seconds?: number;
  }) => call<unknown>('POST', '/jobs', body),
  cancelJob: (jobId: string) => call<unknown>('POST', `/jobs/${jobId}/cancel`),
  listPeers: () => call<{ self: SelfNode; peers: PeerRow[] }>('GET', '/peers'),
  armPairing: (ttl_s = 180) => call<unknown>('POST', '/pairing/arm', { ttl_s }),
  disarmPairing: () => call<unknown>('POST', '/pairing/disarm'),
  initiatePairing: (host: string, port = 0) =>
    call<unknown>('POST', '/pairing/initiate', { host, port }),
  confirmPairing: (session_id: string) =>
    call<unknown>('POST', '/pairing/confirm', { session_id }),
  rejectPairing: (session_id: string) =>
    call<unknown>('POST', '/pairing/reject', { session_id }),
  unpair: (nodeId: string) => call<unknown>('DELETE', `/peers/${nodeId}`),
  pingPeer: (nodeId: string) =>
    call<{ ok: boolean; detail: string }>('POST', `/peers/${nodeId}/ping`),
};
