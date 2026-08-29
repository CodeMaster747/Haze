/** The browser demo must run the SAME scheduler as the real agent.
 *
 *  `agent/tests/test_scheduler.py` writes a corpus of (nodes, job) -> decision
 *  records from the Python implementation. This replays every one against the
 *  TypeScript implementation and asserts the decisions are identical — chosen
 *  node, ordering, scores, dimensions, reasons and summary text.
 *
 *  Change one implementation and this fails until you change the other. That
 *  is what makes "the demo runs the real algorithm" a checked claim rather than
 *  a marketing one.
 *
 *  Regenerate the corpus with:  pytest agent/tests/test_scheduler.py
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { decide, type Decision, type JobRequirement, type NodeCandidate } from '@/sim/scheduler';

interface Case {
  name: string;
  nodes: NodeCandidate[];
  job: JobRequirement;
  expected: Decision;
}

const CORPUS_PATH = join(
  import.meta.dirname,
  '..',
  '..',
  'agent',
  'tests',
  'conformance',
  'scheduler_cases.json',
);

const corpus: Case[] = JSON.parse(readFileSync(CORPUS_PATH, 'utf8')) as Case[];

describe('scheduler conformance with the Python implementation', () => {
  it('has a corpus to check against', () => {
    // Guards against the corpus being deleted or emptied, which would make
    // every test below pass vacuously.
    expect(corpus.length).toBeGreaterThanOrEqual(10);
  });

  for (const testCase of corpus) {
    it(testCase.name, () => {
      const actual = decide(testCase.nodes, testCase.job);

      expect(actual.chosen).toBe(testCase.expected.chosen);
      expect(actual.summary).toBe(testCase.expected.summary);
      expect(actual.assessments.map((a) => a.node_id)).toEqual(
        testCase.expected.assessments.map((a) => a.node_id),
      );

      // Compare every field, not just the winner: the dimensions and reasons
      // are what `haze explain` and the demo's decision trace display, so a
      // divergence there is a divergence users would see.
      expect(actual.assessments).toEqual(testCase.expected.assessments);
    });
  }
});
