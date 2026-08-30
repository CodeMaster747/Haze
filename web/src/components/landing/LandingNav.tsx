import { Button } from '@/components/ui/Button';
import { LINKS } from '@/lib/links';
import { Wordmark } from '@/components/ui/Wordmark';
import { navigate } from '@/lib/router';

/** The public site's header.
 *
 *  Deliberately the same geometry, height and surface as the dashboard's own
 *  header, so arriving at the cluster does not feel like arriving at a
 *  different product. It carries three anchors and one action; below `md`
 *  the anchors are dropped rather than folded into a menu, because a menu that
 *  exists to hold three links to content the reader is about to scroll past is
 *  a control with nothing to do.
 */
const SECTIONS = [
  { href: '#placement', label: 'Features' },
  { href: '#how-it-works', label: 'How it works' },
  { href: '#trust', label: 'Security' },
];

export function LandingNav() {
  return (
    <header className="sticky top-0 z-20 border-b border-border-subtle bg-bg-primary/90 backdrop-blur-md">
      <div className="shell flex h-14 items-center gap-6">
        <Wordmark />

        <nav aria-label="Sections" className="hidden items-center gap-1 md:flex">
          {SECTIONS.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="rounded-md px-2.5 py-1.5 text-sm text-text-muted transition-colors ease-out-quart hover:bg-bg-hover hover:text-text-primary"
            >
              {item.label}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <a
            href={LINKS.repo}
            className="hidden rounded-md px-2.5 py-1.5 text-sm text-text-muted transition-colors ease-out-quart hover:bg-bg-hover hover:text-text-primary sm:block"
          >
            GitHub
          </a>
          <Button variant="primary" size="lg" onClick={() => navigate('/cluster')}>
            Get started
          </Button>
        </div>
      </div>
    </header>
  );
}
