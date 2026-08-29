/** Live connection to the Node Agent on this machine.
 *
 *  Same-origin by construction: the page was served by the agent, so every
 *  request here is loopback -> loopback. That is the exemption that makes this
 *  work at all — a public https origin reaching 127.0.0.1 is blocked outright
 *  in Safari and gated behind a Local Network Access prompt in Chrome 142+
 *  (extended to WebSockets in Chrome 147). We never make that request.
 */

import type { ClusterUpdate, DataSource } from '@/data/DataSource';
import { captureToken } from '@/data/token';
import type {
  DiscoveryState,
  Job,
  JobsState,
  LinkState,
  NodeInfo,
  PairingState,
  Telemetry,
} from '@/types';

const WS_PROTOCOL = 'haze.v1';

/** Reconnect backoff. Jittered so that several agents restarting together
 *  (a laptop waking from sleep) do not resynchronise into a thundering herd. */
const BACKOFF_MS = [500, 1_000, 2_000, 4_000, 8_000, 15_000];

export class HttpAgentSource implements DataSource {
  readonly kind = 'agent' as const;

  private socket: WebSocket | null = null;
  private timer: number | null = null;
  private attempt = 0;
  private stopped = false;
  private nodes: NodeInfo[] = [];
  private pairing: PairingState | undefined;
  private discovery: DiscoveryState | undefined;
  private jobs: JobsState | undefined;

  subscribe(onUpdate: (update: ClusterUpdate) => void): () => void {
    const token = captureToken();

    const emit = (link: LinkState) =>
      onUpdate({
        nodes: this.nodes,
        link,
        pairing: this.pairing,
        discovery: this.discovery,
        jobs: this.jobs,
      });

    if (!token) {
      // No token means the page was opened by hand rather than by `haze up`.
      // Say so precisely — this is by far the most likely first-run confusion.
      emit('unauthorised');
      return () => undefined;
    }

    const connect = () => {
      if (this.stopped) return;
      emit(this.attempt === 0 ? 'connecting' : 'retrying');

      const url = `ws://${window.location.host}/ws`;
      // The token rides in the subprotocol rather than the query string so it
      // stays out of URLs, referrers and the agent's access log. The agent
      // echoes back only the plain `haze.v1` name.
      const socket = new WebSocket(url, [WS_PROTOCOL, `haze.token.${token}`]);
      this.socket = socket;

      socket.onopen = () => {
        this.attempt = 0;
      };

      socket.onmessage = (event) => {
        // The agent multiplexes telemetry and pairing down one socket: a
        // pairing dialog has to appear the instant a peer knocks, and a second
        // socket would double the auth surface for one low-rate event stream.
        const msg = JSON.parse(event.data as string) as
          | { type: 'snapshot' | 'telemetry'; data: Telemetry }
          | { type: 'pairing'; data: PairingState }
          | { type: 'discovery'; data: DiscoveryState }
          | { type: 'jobs'; data: JobsState }
          | { type: 'job'; data: Job };

        if (msg.type === 'pairing') {
          this.pairing = msg.data;
        } else if (msg.type === 'discovery') {
          this.discovery = msg.data;
        } else if (msg.type === 'jobs') {
          this.jobs = msg.data;
        } else if (msg.type === 'job') {
          // A single job changed. Splice it in rather than refetching the
          // whole list: job updates arrive several times a second while
          // something is running.
          this.jobs = this.jobs && {
            ...this.jobs,
            jobs: [
              msg.data,
              ...this.jobs.jobs.filter((j) => j.job_id !== msg.data.job_id),
            ],
          };
        } else if (msg.type === 'snapshot' || msg.type === 'telemetry') {
          this.nodes = [
            {
              name: msg.data.node_name,
              node_id: null,
              status: 'online',
              simulated: msg.data.simulated ?? false,
              is_self: true,
              telemetry: msg.data,
            },
          ];
        } else {
          return;
        }
        emit('live');
      };

      socket.onclose = (event) => {
        this.socket = null;
        if (this.stopped) return;
        // 1008 is the agent refusing us (bad token or foreign origin).
        // Retrying cannot fix either, so stop and tell the user.
        if (event.code === 1008) {
          emit('unauthorised');
          return;
        }
        const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)] ?? 15_000;
        this.attempt += 1;
        emit('retrying');
        this.timer = window.setTimeout(connect, delay + Math.random() * 400);
      };

      socket.onerror = () => {
        // onclose always follows; retry logic lives there so it is not doubled.
      };
    };

    connect();

    return () => {
      this.stopped = true;
      if (this.timer !== null) window.clearTimeout(this.timer);
      this.socket?.close(1000, 'navigating away');
      this.socket = null;
    };
  }
}
