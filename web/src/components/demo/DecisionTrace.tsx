import { Check, Route } from 'lucide-react';

import { EmptyState } from '@/components/ui/EmptyState';
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
      <Panel title="Scheduler">
        <EmptyState
          icon={Route}
          title="No placement yet"
          hint="Submit a job and the full ranking — winner and losers — appears here."
        />
      </Panel>
    );
  }

  return (
    <Panel title="Why it chose that">
      <p className="text-sm leading-relaxed text-text-primary">{decision.summary}</p>

      {/* Full-bleed rows separated by hairlines rather than a stack of nested
          cards: these are one ranked list, and boxing each entry made the
          panel read as four unrelated panels. */}
      <ul className="-mx-4 mt-4 divide-y divide-border-subtle border-y border-border-subtle">
        {decision.assessments.map((a) => (
          <Candidate key={a.node_id} assessment={a} won={a.node_id === decision.chosen} />
        ))}
      </ul>

      <p className="mt-4 text-2xs leading-relaxed text-text-dim">
        The ranking minimises predicted end-to-end time — compute plus moving the bytes. The four
        bars explain it; they are not what is being maximised.
      </p>
    </Panel>
  );
}

function Candidate({ assessment, won }: { assessment: Assessment; won: boolean }) {
  return (
    <li
      className={`px-4 py-3 ${won ? 'bg-accent-subtle' : ''} ${
        assessment.eligible ? '' : 'opacity-55'
      }`}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span
          className={`flex min-w-0 items-baseline gap-1.5 text-sm ${
            won ? 'font-medium text-accent-primary' : 'text-text-primary'
          }`}
        >
          {won && <Check size={12} strokeWidth={2.5} aria-label="chosen" className="shrink-0" />}
          <span className="min-w-0 truncate">{assessment.name}</span>
        </span>
        <span className="shrink-0 font-mono text-2xs tabular-nums text-text-muted">
          {assessment.eligible ? `~${assessment.estimated_seconds}s` : 'ineligible'}
        </span>
      </div>

      {assessment.eligible && (
        <div className="mt-2.5 space-y-1.5">
          {Object.entries(assessment.dimensions).map(([key, value]) => (
            <div key={key} className="flex items-center gap-2" title={DIMENSION_HELP[key]}>
              <span className="w-16 shrink-0 text-2xs text-text-dim">{key}</span>
              <div className="h-1 min-w-0 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
                <div
                  className="h-full rounded-full bg-accent-primary/70 transition-[width] duration-300 ease-out-quart"
                  style={{ width: `${Math.round(value * 100)}%` }}
                />
              </div>
              <span className="w-7 shrink-0 text-right font-mono text-2xs tabular-nums text-text-dim">
                {value.toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      )}

      {assessment.reasons.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {assessment.reasons.map((reason, i) => (
            <li
              key={i}
              className="text-2xs leading-relaxed text-text-dim before:mr-1.5 before:content-['·']"
            >
              {reason}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
