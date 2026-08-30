import { ListChecks, Play, ShieldQuestion, X } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Callout } from '@/components/ui/Callout';
import { EmptyState } from '@/components/ui/EmptyState';
import { Code } from '@/components/ui/Code';
import { Field, Input, Select } from '@/components/ui/Field';
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
      title="Jobs"
      right={
        jobs && (
          <span
            className="inline-flex items-center gap-1.5 font-mono text-2xs text-text-dim"
            title="What this operating system can actually enforce"
          >
            <ShieldQuestion size={12} aria-hidden />
            {jobs.caps.max_cores} cores · {bytes(jobs.caps.max_ram_bytes, 0)} max
          </span>
        )
      }
    >
      {!disabled && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
          className="mb-4 flex flex-wrap items-end gap-3 border-b border-border-subtle pb-4"
        >
          <Field label="Run on" className="w-full sm:w-56">
            {(id) => (
              <Select id={id} value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="">This machine</option>
                {peers.map((p) => (
                  <option key={p.node_id} value={p.node_id}>
                    {p.name} ({p.short_id})
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <Field label="Rounds" className="w-24">
            {(id) => (
              <Input
                id={id}
                type="number"
                min={1}
                max={5000}
                mono
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))}
              />
            )}
          </Field>

          <Button type="submit" variant="primary" icon={Play} loading={busy}>
            Run benchmark
          </Button>
        </form>
      )}

      {jobs && jobs.caps.enforcement.includes('cannot enforce') && (
        <Callout tone="warn" className="mb-3">
          {jobs.caps.enforcement}. Jobs are still killed if they exceed a cap, but nothing
          prevents them exceeding it first.
        </Callout>
      )}

      {error && (
        <Callout tone="error" className="mb-3">
          {error}
        </Callout>
      )}

      {!jobs || jobs.jobs.length === 0 ? (
        <EmptyState
          icon={ListChecks}
          title="No jobs yet"
          hint={
            disabled ? undefined : (
              <>
                Run one above, or <Code>haze run hashbench</Code> from a terminal.
              </>
            )
          }
        />
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
  const name = job.label || job.runtime;

  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex items-center gap-3">
        <Badge tone={TONE[job.state]} dot>
          {job.state}
        </Badge>
        <span className="min-w-0 flex-1 truncate text-sm text-text-primary">{name}</span>

        {job.submitted_by && (
          <span className="hidden shrink-0 font-mono text-2xs text-text-dim sm:inline">
            from {job.submitted_by.split('-')[0]}
          </span>
        )}
        {job.duration_s !== null && (
          <span className="shrink-0 font-mono text-2xs tabular-nums text-text-muted">
            {duration(job.duration_s)}
          </span>
        )}
        {active && !disabled && (
          <Button
            variant="danger"
            size="sm"
            iconOnly
            icon={X}
            aria-label={`Cancel ${name}`}
            title="Cancel"
            onClick={() => void api.cancelJob(job.job_id)}
          />
        )}
      </div>

      {active && (
        <div className="mt-2.5 flex items-center gap-3">
          <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
            <div
              className={`h-full rounded-full bg-accent-primary transition-[width] duration-300 ease-out-quart ${
                fraction === null ? 'w-1/3 animate-pulse-slow' : ''
              }`}
              style={fraction === null ? undefined : { width: `${fraction * 100}%` }}
            />
          </div>
          <span className="max-w-40 shrink-0 truncate text-right font-mono text-2xs tabular-nums text-text-muted">
            {job.progress.rate || job.progress.stage}
          </span>
        </div>
      )}

      {job.error && <p className="mt-2 text-2xs text-state-error">{job.error}</p>}

      {job.state === 'succeeded' && job.progress.rate && (
        <p className="mt-1.5 font-mono text-2xs text-text-dim">
          {job.progress.rate}
          {job.peak_ram_bytes > 0 && ` · peak ${bytes(job.peak_ram_bytes)}`}
          {job.outputs.length > 0 && ` · ${job.outputs.length} file(s)`}
        </p>
      )}
    </li>
  );
}
