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

/** The small mono label above a section heading. Same treatment as the panel
 *  titles this UI used before they moved to sans — it survives here because
 *  on a marketing page a category label genuinely is not prose. */
export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-2xs uppercase tracking-label text-accent-primary">{children}</p>
  );
}

interface ShowcaseProps {
  id?: string;
  eyebrow: string;
  title: string;
  children: ReactNode;
  visual: ReactNode;
  /** Puts the visual on the left at `lg` and up. Alternated down the page so
   *  the eye has somewhere new to land in each section. */
  flip?: boolean;
}

/** Copy on one side, the product on the other.
 *
 *  Deliberately not a card: no border, no surface, no shadow. The only thing
 *  with a frame in this layout is the product visual, which is the thing worth
 *  framing. Below `lg` both columns stack with the text first — a visual you
 *  meet before its explanation is decoration.
 */
export function Showcase({ id, eyebrow, title, children, visual, flip = false }: ShowcaseProps) {
  return (
    <Section id={id}>
      <div className="grid items-center gap-10 lg:grid-cols-2 lg:gap-16">
        <div className={flip ? 'lg:order-2' : undefined}>
          <Eyebrow>{eyebrow}</Eyebrow>
          <h2 className="mt-3 max-w-lg text-balance text-2xl font-medium tracking-tight text-text-primary sm:text-3xl">
            {title}
          </h2>
          <div className="mt-5 max-w-lg space-y-4 text-base leading-relaxed text-text-secondary">
            {children}
          </div>
        </div>
        <div className={`min-w-0 ${flip ? 'lg:order-1' : ''}`}>{visual}</div>
      </div>
    </Section>
  );
}
