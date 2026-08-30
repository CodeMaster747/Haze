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
 */
export default function PublicSite() {
  return useRoute() === '/cluster' ? <App /> : <LandingPage />;
}
