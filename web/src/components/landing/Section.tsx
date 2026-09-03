import type { ReactNode } from 'react';

/** A full-width band on the landing page.
 *
 *  Every section on the page gets its vertical rhythm from here, so the page
 *  scrolls at one cadence instead of each section choosing its own padding.
 *  `scroll-mt` keeps the sticky header off an anchored heading.
 */
export function Section({
  id,
  className = '',
  children,
}: {
  id?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className={`scroll-mt-16 py-16 sm:py-20 lg:py-24 ${className}`}>
      <div className="shell">{children}</div>
    </section>
  );
}

/** The small label above a section heading.
 *
 *  It used to be mono, uppercase and tracked out in the accent colour, which
 *  is the house style of every generated landing page on the internet and was
 *  the loudest thing in each section — a category label out-shouting the
 *  sentence it introduces. Now it is what it is: a quiet word, sitting on the
 *  rule that opens the band.
 */
export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="border-t border-text-primary pt-3 text-xs font-medium text-text-muted">
      {children}
    </p>
  );
}

/** A display heading, in the serif.
 *
 *  The only place on either screen where a serif appears. The dashboard is
 *  set entirely in Plex; giving the public site a voice of its own is the
 *  point, and it stops at the heading — body copy stays sans, because a full
 *  serif page reads as an essay rather than a product.
 */
export function Display({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <h2
      className={`text-balance font-display text-3xl font-normal text-text-primary sm:text-4xl ${className}`}
    >
      {children}
    </h2>
  );
}

interface ShowcaseProps {
  id?: string;
  label: string;
  title: string;
  children: ReactNode;
  visual: ReactNode;
}

/** Copy on one side, the product on the other.
 *
 *  Deliberately not a card: no border, no surface, no shadow. The only thing
 *  with a frame in this layout is the product visual, which is the thing worth
 *  framing.
 *
 *  The heading spans the full measure and the two columns open beneath it,
 *  rather than sitting in one of them. That is also why there is no longer a
 *  `flip`: the sections used to alternate left-right down the page, which is
 *  a rhythm you notice as a template rather than as a document. The band rule
 *  and the heading do that work now, and every section reads the same way —
 *  claim first, evidence under it.
 */
export function Showcase({ id, label, title, children, visual }: ShowcaseProps) {
  return (
    <Section id={id}>
      <SectionLabel>{label}</SectionLabel>
      <Display className="mt-5 max-w-2xl">{title}</Display>

      <div className="mt-10 grid items-start gap-10 lg:mt-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] lg:gap-16">
        <div className="max-w-lg space-y-4 text-base leading-relaxed text-text-secondary">
          {children}
        </div>
        <div className="min-w-0">{visual}</div>
      </div>
    </Section>
  );
}
