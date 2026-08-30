import { LINKS } from '@/lib/links';
import { RouteLink } from '@/components/ui/RouteLink';
import { Wordmark } from '@/components/ui/Wordmark';

/** Four columns of destinations that exist, and nothing else.
 *
 *  The disclaimer at the bottom is not boilerplate: this site shows a cluster
 *  of machines that do not exist, and every surface that renders one has to
 *  say so.
 */
const COLUMNS: { heading: string; links: { label: string; href: string; route?: true }[] }[] = [
  {
    heading: 'Product',
    links: [
      { label: 'Simulated cluster', href: '/cluster', route: true },
      { label: 'Install', href: LINKS.install },
      { label: 'Pairing', href: LINKS.pairing },
      { label: 'Resource limits', href: LINKS.limits },
    ],
  },
  {
    heading: 'Learn to use',
    links: [
      { label: 'Getting started', href: LINKS.repo },
      { label: 'Why it chose that', href: LINKS.explain },
      { label: 'Discovery on your network', href: LINKS.discovery },
      { label: 'Architecture', href: LINKS.architecture },
    ],
  },
  {
    heading: 'Support',
    links: [
      { label: 'Report an issue', href: LINKS.issues },
      { label: 'Discussions', href: LINKS.discussions },
      { label: 'Security disclosure', href: LINKS.security },
      { label: 'Simulated vs real', href: LINKS.simulatedVsReal },
    ],
  },
  {
    heading: 'Project',
    links: [
      { label: 'Source on GitHub', href: LINKS.repo },
      { label: 'Roadmap', href: LINKS.roadmap },
      { label: 'Measured overhead', href: LINKS.benchmark },
      { label: 'Deploy notes', href: LINKS.deploy },
    ],
  },
];

const ITEM =
  'rounded text-sm text-text-muted transition-colors ease-out-quart hover:text-text-primary';

export function LandingFooter() {
  return (
    <footer className="border-t border-border-subtle">
      <div className="shell py-16">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,2.6fr)]">
          <div>
            <Wordmark />
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-text-muted">
              A private compute network made of machines you already own. No cloud provider, no
              account, no bill.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-x-8 gap-y-10 sm:grid-cols-4">
            {COLUMNS.map((column) => (
              <nav key={column.heading} aria-label={column.heading}>
                <h2 className="text-xs font-medium text-text-primary">{column.heading}</h2>
                <ul className="mt-4 space-y-2.5">
                  {column.links.map((link) => (
                    <li key={link.label}>
                      {link.route ? (
                        <RouteLink to={link.href} className={ITEM}>
                          {link.label}
                        </RouteLink>
                      ) : (
                        <a href={link.href} className={ITEM}>
                          {link.label}
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </nav>
            ))}
          </div>
        </div>

        <div className="mt-14 flex flex-col gap-3 border-t border-border-subtle pt-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-2xs text-text-dim">
            © {new Date().getFullYear()} Haze ·{' '}
            <a href={LINKS.licence} className="rounded hover:text-text-muted">
              MIT licensed
            </a>
          </p>
          <p className="text-2xs text-text-dim">
            The cluster on this site is simulated. Every node it shows is badged as such.
          </p>
        </div>
      </div>
    </footer>
  );
}
