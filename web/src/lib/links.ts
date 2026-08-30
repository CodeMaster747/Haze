/** Every off-site destination the public page links to, in one place.
 *
 *  All of these resolve to something that exists today — a file in the repo or
 *  a heading in the README. A footer full of plausible-looking links to
 *  nothing is worse than a shorter footer, so where a destination does not
 *  exist yet, there is no link for it.
 */
export const REPO = 'https://github.com/CodeMaster747/Haze';

const readme = (anchor: string) => `${REPO}#${anchor}`;
const file = (path: string) => `${REPO}/blob/main/${path}`;

export const LINKS = {
  repo: REPO,
  issues: `${REPO}/issues/new`,
  discussions: `${REPO}/discussions`,
  licence: file('LICENSE'),
  architecture: file('docs/architecture.md'),
  security: file('SECURITY.md'),
  deploy: file('DEPLOY.md'),
  benchmark: file('bench/results.md'),
  install: readme('install'),
  pairing: readme('pair-two-machines'),
  explain: readme('why-did-it-choose-that'),
  limits: readme('resource-limits-honestly'),
  overhead: readme('measured-overhead'),
  discovery: readme('discovery'),
  simulatedVsReal: readme('simulated-vs-real'),
  roadmap: readme('roadmap'),
} as const;
