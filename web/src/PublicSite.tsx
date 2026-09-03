import { useLayoutEffect } from 'react';

import App from '@/App';
import { LandingPage } from '@/components/landing/LandingPage';
import { useRoute } from '@/lib/router';

/** The hosted site's two screens.
 *
 *  Anything that is not the cluster is the landing page, because Firebase
 *  rewrites every unmatched path to index.html — so a mistyped URL should land
 *  somewhere that explains what this is, not on a 404 the host cannot serve.
 *
 *  `App` is mounted only on /cluster, which is also why the landing page costs
 *  nothing to sit on: the simulation's 250 ms tick does not start until you
 *  ask for it.
 *
 *  The two screens do not share a palette, and the switch is made here on
 *  <html> rather than on a wrapper inside the page. The body background, the
 *  overscroll gutter and the scrollbars all resolve against the document
 *  element; themed any lower and a light page would sit in a black frame the
 *  moment someone scrolled past the end of it. `useLayoutEffect` so the
 *  attribute lands before paint and the site never flashes the wrong palette.
 */
export default function PublicSite() {
  const route = useRoute();
  const isCluster = route === '/cluster';

  useLayoutEffect(() => {
    const root = document.documentElement;
    if (isCluster) delete root.dataset.theme;
    else root.dataset.theme = 'paper';
  }, [isCluster]);

  return isCluster ? <App /> : <LandingPage />;
}
