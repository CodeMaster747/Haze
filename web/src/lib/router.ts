/** Two routes, and that is the entire requirement.
 *
 *  The public site opens on the landing page and hands off to the cluster at
 *  `/cluster`. There are no loaders, no nested layouts, no route params and no
 *  data revalidation, so what is actually needed is the History API plus a
 *  subscription.
 *
 *  Measured rather than assumed: wiring `react-router-dom` v7 up to exactly
 *  these two routes cost **+13.9 KB gzipped** on a 77 KB bundle, against 5.7 KB
 *  for the whole landing page. That is a real price here and not a vanity
 *  metric — Firebase Hosting's free tier *disables* the site when the daily
 *  transfer cap is exceeded rather than billing for it, so every kilobyte is
 *  bought with visits. The dependency was dropped from package.json rather than
 *  left declared and unused; bring it back the day this needs a third route
 *  with data behind it.
 *
 *  Hash targets (`#how-it-works`) are deliberately not routed. Those are
 *  in-page anchors and the browser's own behaviour is the correct one.
 */

import { useSyncExternalStore } from 'react';

type Listener = () => void;

const listeners = new Set<Listener>();

function notify(): void {
  for (const listener of listeners) listener();
}

/** The popstate handler is attached on first subscribe rather than at module
 *  scope, so importing this file has no side effect and the agent build can
 *  drop it entirely along with the rest of the landing page. */
function subscribe(listener: Listener): () => void {
  if (listeners.size === 0) window.addEventListener('popstate', notify);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener('popstate', notify);
  };
}

function currentPath(): string {
  return window.location.pathname;
}

export function useRoute(): string {
  return useSyncExternalStore(subscribe, currentPath, () => '/');
}

export function navigate(to: string): void {
  if (to === currentPath()) return;
  window.history.pushState(null, '', to);
  notify();
  // A route change is a new page. Restoring position is the browser's job on
  // back/forward, which is why this only runs on a push.
  window.scrollTo(0, 0);
}
