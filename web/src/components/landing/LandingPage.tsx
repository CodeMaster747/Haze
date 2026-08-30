import { Hero } from '@/components/landing/Hero';
import { HowItWorks } from '@/components/landing/HowItWorks';
import { LandingFooter } from '@/components/landing/LandingFooter';
import { LandingNav } from '@/components/landing/LandingNav';
import { Showcases } from '@/components/landing/Showcases';
import { Trust, FinalCta } from '@/components/landing/Closing';

/** The public entry point.
 *
 *  Reads top to bottom as: what it is → the three things it does → what you
 *  have to do → why it can be trusted → try it. Nothing here fetches
 *  anything, nothing here runs on a timer, and the one interactive element
 *  computes its numbers locally from a pure function.
 */
export function LandingPage() {
  return (
    <div className="min-h-dvh bg-bg-primary text-text-primary">
      {/* First thing in the tab order, visible only once focused. The nav
          above carries four links the keyboard would otherwise walk through
          on every page load. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:border focus:border-border focus:bg-bg-elevated focus:px-3 focus:py-2 focus:text-sm focus:text-text-primary"
      >
        Skip to content
      </a>
      <LandingNav />
      <main id="main" tabIndex={-1}>
        <Hero />
        <Showcases />
        <HowItWorks />
        <Trust />
        <FinalCta />
      </main>
      <LandingFooter />
    </div>
  );
}
