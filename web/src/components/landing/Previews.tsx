import type { ReactNode } from 'react';

/** Product visuals for the landing page.
 *
 *  All of these are built from the same tokens as the dashboard rather than
 *  from screenshots: nothing to load, nothing to re-export when a colour
 *  changes, and they stay sharp at any density. The transcripts are real
 *  output — the numbers below are the ones in the README and in
 *  `bench/results.md`, not invented ones.
 */

/** A shell transcript. The command sits in the frame's header because that is
 *  the title of what follows; there is no window chrome, which would be
 *  decoration standing in for a product. */
export function Terminal({ command, children }: { command: string; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border border-border-subtle bg-bg-panel">
      <div className="flex items-center gap-2 border-b border-border-subtle px-4 py-2.5">
        <span aria-hidden className="font-mono text-xs text-accent-primary">
          $
        </span>
        <code className="min-w-0 truncate font-mono text-xs text-text-secondary">{command}</code>
      </div>
      <pre className="overflow-x-auto px-4 py-4 font-mono text-2xs leading-relaxed text-text-secondary sm:text-xs">
        {children}
      </pre>
    </div>
  );
}

const WIN = 'text-accent-secondary';
const DIM = 'text-text-dim';

/** `haze explain` — the scheduler reporting every candidate, winners and
 *  losers, with the reason each one lost. */
export function ExplainPreview() {
  return (
    <Terminal command="haze explain --runtime hashbench --work 20 --input 800">
      <span className={WIN}>{'→ laptop'}</span>
      {' — desktop computes faster but is 133.18s slower\n'}
      {'  end to end once transfer is counted\n\n'}
      <span className={WIN}>{'✓ laptop'}</span>
      {'          score 1.000   ~21.04s\n'}
      {'    speed      '}
      <span className="text-accent-primary">{'█████████████░'}</span>
      {' 0.95\n'}
      {'    transfer   '}
      <span className="text-accent-primary">{'██████████████'}</span>
      {' 1.00\n'}
      <span className={DIM}>{'    · runs here — nothing to transfer\n\n'}</span>
      {'  desktop         score 0.136   ~154.22s\n'}
      {'    speed      '}
      <span className="text-accent-primary/60">{'██████████████'}</span>
      {' 1.00\n'}
      {'    transfer   '}
      <span className="text-accent-primary/60">{'█'}</span>
      <span className={DIM}>{'░░░░░░░░░░░░░'}</span>
      {' 0.13\n'}
      <span className={DIM}>
        {'    · 134.22s moving 819200 KiB each way (87% of the total)'}
      </span>
    </Terminal>
  );
}

/** `haze run` — the file goes across, progress comes back, the frames land
 *  in the job directory on the machine that submitted it. */
export function RunPreview() {
  return (
    <Terminal command="haze run blender --on desktop --blend scene.blend --frames 1-3">
      <span className="text-text-primary">{'blender on desktop\n'}</span>
      <span className="text-accent-primary">{'██████████████████████████'}</span>
      {' 100.0% 0.6s/frame\n'}
      <span className={WIN}>{'done in 1.61s'}</span>
      {' · 0.6s/frame\n'}
      <span className={DIM}>{'  …/jobs/58c22cf4/out/0001.png\n'}</span>
      <span className={DIM}>{'  …/jobs/58c22cf4/out/0002.png\n'}</span>
      <span className={DIM}>{'  …/jobs/58c22cf4/out/0003.png'}</span>
    </Terminal>
  );
}

/** The pairing code, as both machines show it.
 *
 *  Two panes side by side because that is the mechanism: the comparison
 *  between two screens is the entire security model, and a single pane would
 *  misrepresent it as something one machine can do alone.
 */
const SCREENS = [
  { label: 'this machine', meta: 'HZ4K · macOS' },
  { label: 'desktop', meta: 'HZ9T · Linux' },
];

/** The README's example code, so the page and the docs agree. */
const WORDS = ['buzzard', 'talon', 'dragnet', 'aardvark'];

export function PairingPreview() {
  return (
    <div>
      <div className="grid grid-cols-2 gap-3 sm:gap-4">
        {SCREENS.map((screen) => (
          <div
            key={screen.label}
            className="rounded-lg border border-border-subtle bg-bg-panel px-3 py-5 text-center sm:px-5 sm:py-7"
          >
            <p className="truncate font-mono text-2xs uppercase tracking-label text-text-muted">
              {screen.label}
            </p>
            {/* Same treatment as the real SasDialog: accent, semibold,
                tabular, wide-tracked digits, then the words as chips. A
                preview that restyles the thing it is previewing is a
                drawing of the product rather than the product. */}
            <p className="mt-5 font-mono text-2xl font-semibold tabular-nums tracking-digits text-accent-primary sm:text-3xl">
              385664
            </p>
            {/* A fixed 2×2 rather than the dialog's flex-wrap: at a third of
                the dialog's width, wrapping puts three words on one row and
                one orphan under them. */}
            <div className="mt-4 grid grid-cols-1 gap-1 sm:grid-cols-2">
              {WORDS.map((word) => (
                <span
                  key={word}
                  className="rounded border border-border-subtle bg-bg-tertiary px-1.5 py-0.5 font-mono text-2xs text-accent-secondary"
                >
                  {word}
                </span>
              ))}
            </div>
            <p className="mt-5 border-t border-border-subtle pt-4 font-mono text-2xs text-text-dim">
              {screen.meta}
            </p>
          </div>
        ))}
      </div>

      {/* The comparison between the two panes is the mechanism, not a caption
          about it — so it is drawn between them rather than described below. */}
      <div className="mt-4 flex items-center gap-3">
        <span aria-hidden className="h-px flex-1 bg-border-subtle" />
        <span className="text-2xs text-text-muted">both must match · both must confirm</span>
        <span aria-hidden className="h-px flex-1 bg-border-subtle" />
      </div>
    </div>
  );
}

/** What each platform can actually enforce. This table is the product's
 *  position on the subject, so it is shown rather than summarised. */
const ENFORCEMENT: { limit: string; by: string; reality: string; real: boolean }[] = [
  { limit: 'Wall clock', by: 'Haze itself', reality: 'Real everywhere', real: true },
  { limit: 'Memory · Linux', by: 'cgroups v2', reality: 'Kernel kills on breach', real: true },
  { limit: 'CPU · Linux', by: 'cgroups v2', reality: 'A genuine share', real: true },
  { limit: 'Memory · Windows', by: 'Job Objects', reality: 'Allocation fails at the cap', real: true },
  { limit: 'CPU · Windows', by: 'Job Objects', reality: 'A hard rate cap', real: true },
  { limit: 'Memory · macOS', by: 'setrlimit', reality: 'Advisory only', real: false },
  { limit: 'CPU · macOS', by: 'nice', reality: 'Not enforceable', real: false },
];

export function LimitsPreview() {
  return (
    <div className="overflow-hidden rounded-lg border border-border-subtle bg-bg-panel">
      <div className="border-b border-border-subtle px-4 py-2.5">
        <h3 className="text-sm font-medium text-text-primary">Resource limits</h3>
        <p className="mt-0.5 text-xs text-text-muted">What this machine can actually hold you to</p>
      </div>
      <table className="w-full text-left">
        <caption className="sr-only">
          Resource limits by platform, and whether each is enforced or advisory
        </caption>
        <tbody>
          {ENFORCEMENT.map((row) => (
            <tr key={row.limit} className="border-t border-border-subtle first:border-t-0">
              <th
                scope="row"
                className="whitespace-nowrap px-4 py-2.5 text-xs font-normal text-text-secondary"
              >
                {row.limit}
              </th>
              <td className="hidden px-2 py-2.5 font-mono text-2xs text-text-dim sm:table-cell">
                {row.by}
              </td>
              <td
                className={`whitespace-nowrap px-4 py-2.5 text-right text-2xs ${
                  row.real ? 'text-state-online' : 'text-state-busy'
                }`}
              >
                {row.reality}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
