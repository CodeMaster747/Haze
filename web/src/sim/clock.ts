/** A virtual clock.
 *
 *  The simulation advances by explicit ticks rather than reading `Date.now()`,
 *  which is what makes a run reproducible: the same seed and the same sequence
 *  of actions produce the same trace every time, in a browser and in CI.
 *
 *  It also means the demo can be paused, or run faster than real time, without
 *  any of the simulation code knowing.
 */
export class VirtualClock {
  private millis = 0;
  private rate = 1;
  private paused = false;

  get now(): number {
    return this.millis;
  }

  get seconds(): number {
    return this.millis / 1000;
  }

  get isPaused(): boolean {
    return this.paused;
  }

  get speed(): number {
    return this.rate;
  }

  setSpeed(rate: number): void {
    this.rate = Math.max(0.1, Math.min(20, rate));
  }

  setPaused(paused: boolean): void {
    this.paused = paused;
  }

  /** Advance by a real-time delta, scaled by the current speed. Returns the
   *  virtual milliseconds elapsed, which is 0 while paused. */
  advance(realDeltaMs: number): number {
    if (this.paused) return 0;
    // Clamped: a backgrounded tab can hand back a delta of many seconds, and
    // simulating all of it at once makes jobs leap forward in a way that looks
    // like a bug.
    const delta = Math.min(realDeltaMs, 250) * this.rate;
    this.millis += delta;
    return delta;
  }

  reset(): void {
    this.millis = 0;
    this.paused = false;
  }
}
