import type { AnchorHTMLAttributes, MouseEvent } from 'react';

import { navigate } from '@/lib/router';

interface RouteLinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  to: string;
}

/** An in-app link that stays a real link.
 *
 *  Renders a genuine `href`, so ⌘-click, middle-click, "copy link address" and
 *  the status bar preview all still work, and intercepts only the plain left
 *  click — the one case a client-side transition serves better than a reload.
 */
export function RouteLink({ to, onClick, ...rest }: RouteLinkProps) {
  const handle = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented) return;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    event.preventDefault();
    navigate(to);
  };

  return <a {...rest} href={to} onClick={handle} />;
}
