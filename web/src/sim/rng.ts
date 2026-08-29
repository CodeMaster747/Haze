/** Seeded PRNG (mulberry32).
 *
 *  The demo must be deterministic: the same seed produces the same cluster
 *  behaviour on every visit and in CI. That is what lets the browser simulation
 *  be checked against the Python scheduler's golden corpus in M4 — an
 *  unseeded Math.random() would make that conformance test impossible.
 */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Ornstein-Uhlenbeck step: mean-reverting noise.
 *
 *  A plain random walk wanders off to 0% or 100% and stays there; independent
 *  samples jitter implausibly. Mean reversion gives load that drifts and
 *  recovers the way a real machine's does, which is what makes the demo read as
 *  telemetry rather than as a random number generator.
 */
export function ouStep(current: number, mean: number, reversion: number, volatility: number, rand: () => number): number {
  const shock = (rand() - 0.5) * 2 * volatility;
  return Math.min(100, Math.max(0, current + reversion * (mean - current) + shock));
}
