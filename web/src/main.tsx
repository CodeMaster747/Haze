import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from '@/App';
import PublicSite from '@/PublicSite';
import '@/index.css';

const root = document.getElementById('root');
if (!root) throw new Error('#root missing from index.html');

/** Which product this build is.
 *
 *  The hosted site opens on the landing page and hands off to the simulated
 *  cluster. The agent's own dashboard does not: someone who has run `haze up`
 *  and opened the console has already been introduced to the product, and
 *  putting a marketing page in front of their telemetry would be an
 *  interruption rather than an entrance.
 *
 *  `__HAZE_DEMO__` is a compile-time constant, so this is not a runtime branch
 *  — the agent build contains no landing-page code at all, and `/` is the
 *  dashboard exactly as it was before.
 */
createRoot(root).render(
  <StrictMode>{__HAZE_DEMO__ ? <PublicSite /> : <App />}</StrictMode>,
);
