import { Panel } from '@/components/ui/Panel';
import type { Assessment, Decision } from '@/sim/scheduler';

const DIMENSION_HELP: Record<string, string> = {
  speed: 'how fast this node computes',
  headroom: 'how much of it is free right now',
  transfer: 'share of the total spent computing rather than moving bytes',
  affinity: 'has the hardware this job asked for',
};

/** Why the scheduler chose what it chose.
 *
 *  Shows every candidate, not just the winner. A scheduler you cannot
 *  interrogate is indistinguishable from a random one, and the losers are
 *  where the reasoning actually lives.
 */
export function DecisionTrace({ decision }: { decision: Decision | null }) {
  if (!decision) {
    return (
      <Panel title="scheduler">
        <p className="py-6 text-center text-sm text-text-muted">
          Submit a job to see how it gets placed.
        </p>
      </Panel>
    );
  }

  return (
    <Panel title="why it chose that">
      <p className="mb-4 text-sm text-accent-secondary">{decision.summary}</p>
      <ul className="space-y-3">
        {decision.assessments.map((a) => (
          <Candidate key={a.node_id} assessment={a} won={a.node_id === decision.chosen} />
        ))}
      </ul>
      <p className="mt-4 border-t border-border-subtle pt-3 text-[11px] leading-relaxed text-text-dim">
        The ranking minimises predicted end-to-end time — compute plus moving the bytes. The
        four bars explain it; they are not what is being maximised.
      </p>
    </Panel>
  );
}

function Candidate({ assessment, won }: { assessment: Assessment; won: boolean }) {
  return (
    <li
      className={`rounded border px-3 py-2.5 ${
        won
          ? 'border-accent-primary/40 bg-accent-subtle'
          : assessment.eligible
            ? 'border-border-subtle'
            : 'border-border-subtle opacity-55'
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm text-text-primary">
          {won && <span className="mr-1 text-accent-primary">✓</span>}
          {assessment.name}
        </span>
        <span className="font-mono text-[11px] text-text-muted">
          {assessment.eligible ? `~${assessment.estimated_seconds}s` : 'ineligible'}
        </span>
      </div>

      {assessment.eligible && (
        <div className="mt-2 grid gap-1">
          {Object.entries(assessment.dimensions).map(([key, value]) => (
            <div key={key} className="flex items-center gap-2" title={DIMENSION_HELP[key]}>
              <span className="w-16 shrink-0 font-mono text-[10px] text-text-dim">{key}</span>
              <div className="h-1 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
                <div
                  className="h-full rounded-full bg-accent-primary/70"
                  style={{ width: `${Math.round(value * 100)}%` }}
                />
              </div>
              <span className="w-8 shrink-0 text-right font-mono text-[10px] text-text-dim">
                {value.toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      )}

      <ul className="mt-1.5 space-y-0.5">
        {assessment.reasons.map((reason, i) => (
          <li key={i} className="font-mono text-[11px] text-text-dim">
            · {reason}
          </li>
        ))}
      </ul>
    </li>
  );
}
