import { Eyebrow, Section } from '@/components/landing/Section';

/** Three commands, which is genuinely all of it.
 *
 *  Worth a section because the honest answer to "what do I have to do" is
 *  short, and showing that it is short is more persuasive than saying so.
 */
const STEPS = [
  {
    n: '01',
    title: 'Start an agent on each machine',
    body: 'One install, one command. The agent serves its own dashboard locally and announces itself on the network.',
    command: 'uv tool install haze-agent\nhaze up',
  },
  {
    n: '02',
    title: 'Pair them',
    body: 'Both screens show the same six digits. Confirm on both — neither side can pair alone, and that comparison is the security model.',
    command: 'haze pair --serve        # first machine\nhaze pair --host <address>   # second',
  },
  {
    n: '03',
    title: 'Send it work',
    body: 'Name a machine or let the scheduler choose. Inputs go across, progress comes back, outputs land where you submitted from.',
    command: 'haze run blender --on desktop --blend scene.blend',
  },
];

export function HowItWorks() {
  return (
    <Section id="how-it-works" className="border-t border-border-subtle bg-bg-secondary">
      <Eyebrow>How it works</Eyebrow>
      <h2 className="mt-3 max-w-xl text-balance text-2xl font-medium tracking-tight text-text-primary sm:text-3xl">
        Three commands from one machine to two.
      </h2>

      <ol className="mt-12 grid gap-10 lg:grid-cols-3 lg:gap-8">
        {STEPS.map((step) => (
          <li key={step.n} className="flex min-w-0 flex-col border-t border-border pt-6">
            <span aria-hidden className="font-mono text-2xs tracking-label text-text-dim">
              {step.n}
            </span>
            <h3 className="mt-3 text-base font-medium text-text-primary">{step.title}</h3>
            <p className="mb-4 mt-2 text-sm leading-relaxed text-text-secondary">{step.body}</p>
            <pre className="mt-auto overflow-x-auto rounded-md border border-border-subtle bg-bg-tertiary px-3 py-2.5 font-mono text-2xs leading-relaxed text-text-secondary">
              <code>{step.command}</code>
            </pre>
          </li>
        ))}
      </ol>
    </Section>
  );
}
