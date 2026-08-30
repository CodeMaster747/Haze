import { Antenna, CircleSlash, Gauge } from 'lucide-react';

import { Section, Showcase } from '@/components/landing/Section';
import {
  ExplainPreview,
  LimitsPreview,
  PairingPreview,
  RunPreview,
} from '@/components/landing/Previews';
import { Code } from '@/components/ui/Code';

/** The three things worth a full section each, then the three worth a line.
 *
 *  Ordered the way the product is actually met: it decides, you trust it, it
 *  runs. Each visual is the corresponding surface of the real product rather
 *  than an abstraction of it.
 */
export function Showcases() {
  return (
    <>
      <Showcase
        id="placement"
        eyebrow="Placement"
        title="It picks a machine, then shows its working."
        visual={<ExplainPreview />}
      >
        <p>
          The scheduler minimises predicted end-to-end time — compute plus moving the bytes —
          rather than scoring a weighted average of niceness. A machine that computes four times
          faster still loses if shipping the input to it costs more than it saves.
        </p>
        <p>
          <Code>haze explain</Code> reports every candidate, winners and losers alike, with the
          reason each one lost. Being ineligible is elimination rather than a low score: not
          having Blender installed is not something a faster machine can outweigh.
        </p>
      </Showcase>

      <Showcase
        id="pairing"
        eyebrow="Trust"
        title="Two screens, one code, and both people have to agree."
        visual={<PairingPreview />}
        flip
      >
        <p>
          Pairing shows the same six digits and four words on both machines. The code is derived{' '}
          <em className="not-italic text-text-primary">from</em> the two public keys, so there is
          nothing to guess and nothing to type — and a machine in the middle would have to
          substitute a key, which makes the screens disagree.
        </p>
        <p>
          After that the machines hold each other&rsquo;s certificate. Every byte between them
          moves over TLS 1.3 with both ends pinned, and identity is an Ed25519 key that never
          leaves the node it belongs to.
        </p>
      </Showcase>

      <Showcase
        id="jobs"
        eyebrow="Jobs"
        title="Files across, progress back, results home."
        visual={<RunPreview />}
      >
        <p>
          The <Code>.blend</Code> streams to the desktop with the job, renders there, and the PNGs
          come back — all on the same authenticated connection, with progress arriving while it
          works.
        </p>
        <p>
          Haze does not run arbitrary commands. A job names a runtime from a fixed allowlist and
          supplies typed arguments; the runtime builds the command line. There is no shell
          anywhere in the path, and no field a peer controls becomes a command name.
        </p>
      </Showcase>

      <Showcase
        id="limits"
        eyebrow="Limits"
        title="A cap that is not enforced is worse than no cap."
        visual={<LimitsPreview />}
        flip
      >
        <p>
          You set what each machine will lend. On Linux those caps are real — cgroups v2 kills a
          job that breaches its memory limit and hands it a genuine CPU share.
        </p>
        <p>
          macOS has no equivalent, so there the CPU cap is not enforceable and the memory cap is
          advisory. The dashboard tells you which one you actually got, because a limit that
          silently does nothing makes people comfortable running work they should have thought
          harder about.
        </p>
      </Showcase>

      <Section className="border-t border-border-subtle">
        <div className="grid gap-10 sm:grid-cols-3 sm:gap-8">
          <Detail
            icon={CircleSlash}
            title="Fails in under a second"
            body="Kill a machine mid-job and the job ends with a sentence you can act on, instead of hanging on a socket read until something times out."
          />
          <Detail
            icon={Antenna}
            title="Finds machines three ways"
            body="mDNS and UDP broadcast run together rather than as a fallback chain. Seen by one and not the other means multicast is being filtered — and Haze says so."
          />
          <Detail
            icon={Gauge}
            title="Overhead you can look up"
            body="Roughly half a second, fixed: 58% of a short job's round trip and 7% of a long one. The raw runs are committed to the repository."
          />
        </div>
      </Section>
    </>
  );
}

function Detail({
  icon: Icon,
  title,
  body,
}: {
  icon: typeof Antenna;
  title: string;
  body: string;
}) {
  return (
    <div>
      <Icon size={16} strokeWidth={1.75} aria-hidden className="text-accent-primary" />
      <h3 className="mt-4 text-base font-medium text-text-primary">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-text-secondary">{body}</p>
    </div>
  );
}
