import { CircleAlert, Play, ShieldQuestion, X } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { bytes, duration } from '@/lib/format';
import { api } from '@/lib/api';
import type { Job, JobState, JobsState, PeerRow } from '@/types';

const TONE: Record<JobState, 'online' | 'busy' | 'offline' | 'error' | 'neutral'> = {
  succeeded: 'online',
  running: 'busy',
  queued: 'neutral',
  cancelled: 'offline',
  failed: 'error',
  rejected: 'error',
};

export function JobsPanel({
  jobs,
  peers,
  disabled,
}: {
  jobs: JobsState | null;
  peers: PeerRow[];
  disabled: boolean;
}) {
  const [target, setTarget] = useState('');
  const [rounds, setRounds] = useState(300);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.submitJob({
        runtime: 'hashbench',
        args: { rounds },
        node_id: target,
        label: target ? 'benchmark (remote)' : 'benchmark (local)',
        cpu_cores: 1,
        wall_seconds: 900,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="jobs"
      right={
        jobs && (
          <span
            className="inline-flex items-center gap-1.5 font-mono text-[10px] text-text-dim"
            title="What this operating system can actually enforce"
          >
            <ShieldQuestion size={11} />
            {jobs.caps.max_cores} cores · {bytes(jobs.caps.max_ram_bytes, 0)} max
          </span>
        )
      }
    >
      {!disabled && (
        <div className="mb-4 flex flex-wrap items-end gap-2 border-b border-border-subtle pb-4">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-text-muted">run on</span>
            <select
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="rounded border border-border bg-bg-tertiary px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent-primary/60"
            >
              <option value="">this machine</option>
              {peers.map((p) => (
                <option key={p.node_id} value={p.node_id}>
                  {p.name} ({p.short_id})
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-text-muted">rounds</span>
            <input
              type="number"
              min={1}
              max={5000}
              value={rounds}
              onChange={(e) => setRounds(Number(e.target.value))}
              className="w-24 rounded border border-border bg-bg-tertiary px-2 py-1.5 font-mono text-sm text-text-primary outline-none focus:border-accent-primary/60"
            />
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={() => void submit()}
            className="rounded border border-accent-primary/50 bg-accent-subtle px-3 py-1.5 text-sm text-accent-primary transition hover:bg-accent-primary/20 disabled:opacity-40"
          >
            <Play size={12} className="inline" /> run benchmark
          </button>
        </div>
      )}

      {jobs && jobs.caps.enforcement.includes('cannot enforce') && (
        <p className="mb-3 flex items-start gap-2 rounded border border-state-busy/25 bg-state-busy/5 px-2.5 py-2 text-[11px] leading-relaxed text-text-secondary">
          <CircleAlert size={12} className="mt-0.5 shrink-0 text-state-busy" />
          {jobs.caps.enforcement}. Jobs are still killed if they exceed a cap, but nothing
          prevents them exceeding it first.
        </p>
      )}

      {error && <p className="mb-3 text-xs text-state-error">{error}</p>}

      {!jobs || jobs.jobs.length === 0 ? (
        <p className="py-6 text-center text-sm text-text-muted">
          No jobs yet{disabled ? '.' : ' — run one above, or `haze run hashbench`.'}
        </p>
      ) : (
        <ul className="divide-y divide-border-subtle">
          {jobs.jobs.slice(0, 8).map((job) => (
            <JobRow key={job.job_id} job={job} disabled={disabled} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function JobRow({ job, disabled }: { job: Job; disabled: boolean }) {
  const fraction = job.progress.fraction;
  const active = job.state === 'running' || job.state === 'queued';

  return (
    <li className="py-2.5 first:pt-0 last:pb-0">
      <div className="flex items-center gap-2.5">
        <Badge tone={TONE[job.state]}>{job.state}</Badge>
        <span className="min-w-0 flex-1 truncate text-sm text-text-primary">
          {job.label || job.runtime}
        </span>
        {job.submitted_by && (
          <span className="font-mono text-[10px] text-text-dim">
            from {job.submitted_by.split('-')[0]}
          </span>
        )}
        {job.duration_s !== null && (
          <span className="font-mono text-[11px] text-text-muted">{duration(job.duration_s)}</span>
        )}
        {active && !disabled && (
          <button
            type="button"
            onClick={() => void api.cancelJob(job.job_id)}
            title="Cancel"
            className="rounded border border-border px-1.5 py-0.5 text-text-muted transition hover:border-state-error/50 hover:text-state-error"
          >
            <X size={11} />
          </button>
        )}
      </div>

      {active && (
        <div className="mt-2 flex items-center gap-2.5">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
            <div
              className={`h-full rounded-full bg-accent-primary transition-[width] duration-300 ease-out-quart ${
                fraction === null ? 'animate-pulse-slow w-1/3' : ''
              }`}
              style={fraction === null ? undefined : { width: `${fraction * 100}%` }}
            />
          </div>
          <span className="w-32 shrink-0 text-right font-mono text-[11px] text-text-muted">
            {job.progress.rate || job.progress.stage}
          </span>
        </div>
      )}

      {job.error && <p className="mt-1.5 text-[11px] text-state-error">{job.error}</p>}

      {job.state === 'succeeded' && job.progress.rate && (
        <p className="mt-1 font-mono text-[11px] text-text-dim">
          {job.progress.rate}
          {job.peak_ram_bytes > 0 && ` · peak ${bytes(job.peak_ram_bytes)}`}
          {job.outputs.length > 0 && ` · ${job.outputs.length} file(s)`}
        </p>
      )}
    </li>
  );
}
