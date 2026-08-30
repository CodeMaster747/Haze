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
 */
export function Hero() {
  return (
    <section className="border-b border-border-subtle">
      <div className="shell grid animate-fade-in items-center gap-12 pb-16 pt-14 sm:pt-16 lg:grid-cols-[minmax(0,1.08fr)_minmax(0,1fr)] lg:gap-16 lg:pb-24 lg:pt-20">
        <div>
          <h1 className="max-w-xl text-balance text-4xl font-medium text-text-primary sm:text-5xl">
            Run it on the machine that should run it.
          </h1>

          <p className="mt-6 max-w-xl text-pretty text-xl leading-relaxed text-text-secondary">
            Haze pools the computers you already own into one private cluster. Submit a job from
            the laptop, run it on the desktop&rsquo;s GPU, get the result back — over a connection
            only your machines can open.
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

        <div className="min-w-0 lg:pl-4">
          <PlacementPreview />
          <p className="mt-3 text-xs leading-relaxed text-text-dim">
            The same scheduler the agent runs, deciding on real numbers in this page. Change
            the link between the machines and watch it change its mind.
          </p>
        </div>
      </div>
    </section>
  );
}
