/** Dashboard bearer token handling.
 *
 *  The agent prints a URL containing `?t=<token>` and opens it. We move that
 *  token into sessionStorage and strip it from the address bar immediately:
 *  a token sitting in the URL leaks into the browser history, into the
 *  `Referer` of any outbound request, and into anything the user copy-pastes
 *  when asking for help.
 *
 *  sessionStorage rather than localStorage so closing the tab ends the session,
 *  and so two agents opened in two tabs cannot clobber each other's token.
 */

const KEY = 'haze.token';

export function captureToken(): string | null {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get('t');

  if (fromUrl) {
    try {
      sessionStorage.setItem(KEY, fromUrl);
    } catch {
      // Private-mode Safari can throw on write. Fall through and use the value
      // in memory for this page load rather than failing to connect at all.
    }
    url.searchParams.delete('t');
    window.history.replaceState({}, '', url.pathname + url.search + url.hash);
    return fromUrl;
  }

  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function clearToken(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* nothing to do */
  }
}
