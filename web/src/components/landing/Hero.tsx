import { Button } from '@/components/ui/Button';
import { InstallCommand } from '@/components/landing/InstallCommand';
import { PlacementPreview } from '@/components/landing/PlacementPreview';
import { navigate } from '@/lib/router';

/** What Haze is, and one thing that proves it.
 *
 *  The visual beside the copy is the scheduler actually running, not an
 *  illustration of one — see PlacementPreview. That is the whole reason the
 *  hero can be this short: the panel makes the argument the copy would
 *  otherwise have to.
 *
 *  The headline takes the full measure and the page opens underneath it,
 *  rather than sitting in the left half of a two-column band with the product
 *  shot in the right. The two-column version is the shape every product page
 *  has, and it caps the headline at whatever fits in half a screen; this one
 *  gets to be the size it deserves and the rule under it does the work of
 *  separating the claim from the evidence.
 */
export function Hero() {
  return (
    <section className="border-b border-border-subtle">
      <div className="shell animate-fade-in pb-16 pt-14 sm:pt-16 lg:pb-24 lg:pt-20">
        <h1 className="max-w-4xl text-balance font-display text-4xl font-normal leading-[1.06] text-text-primary sm:text-5xl lg:text-6xl">
          Run it on the machine that{' '}
          <em className="italic text-accent-primary">should</em> run it.
        </h1>

        <div className="mt-10 grid gap-10 border-t border-border-subtle pt-10 lg:mt-14 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1fr)] lg:items-center lg:gap-16 lg:pt-12">
          <div>
            <p className="max-w-xl text-pretty text-xl leading-relaxed text-text-secondary">
              Haze pools the computers you already own into one private cluster. Submit a job from
              the laptop, run it on the desktop&rsquo;s GPU, get the result back — over a
              connection only your machines can open.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Button variant="primary" size="xl" onClick={() => navigate('/cluster')}>
                Get started
              </Button>
              <InstallCommand size="xl" />
            </div>

            <p className="mt-6 text-xs text-text-muted">
              No cloud provider, no account, no bill. MIT licensed.
            </p>
          </div>

          <div className="min-w-0">
            <PlacementPreview />
            <p className="mt-3 text-xs leading-relaxed text-text-dim">
              The same scheduler the agent runs, deciding on real numbers in this page. Change
              the link between the machines and watch it change its mind.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
