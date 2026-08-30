# Deploying & Updating Haze

- **Live demo:** https://REPLACE_ME-haze.web.app
- **Repo:** https://github.com/CodeMaster747/Haze
- **Hosting:** Firebase Hosting, deployed automatically by GitHub Actions
- **Package:** `haze-agent` on PyPI

---

## The rule that makes this free

> **No account used by this project has a payment method attached, and none ever
> gets one.**

This is a property of the *accounts*, not of the code, and it is what turns
"probably free" into "cannot bill". Every limit below is a hard stop — an error
or a disabled site — rather than an overage charge.

| Surface | Free allowance | What happens at the limit |
|---|---|---|
| Firebase Hosting (Spark) | 10 GB storage · **360 MB/day transfer** | Site is disabled until the next period. Never billed. |
| GitHub Actions | Unlimited on **public** repos | n/a |
| PyPI + GitHub Releases | Unlimited for public projects | n/a |
| The Haze network itself | Runs on your machines | n/a — there is no backend |

Three ways to break it, so they are written down:

1. **Upgrading Firebase to Blaze.** Blaze requires a card, and every hard limit
   becomes a billable overage. Cloud Functions have required Blaze since
   Feb 2026 — Haze deliberately uses none, which is why Spark is sufficient.
2. **Making the repo private.** Actions silently starts drawing on the
   2,000 min/month allowance and can bill past it. GitHub Pages would also stop
   working without Pro.
3. **Adding a macOS runner to CI.** They drain the allowance at a 10× multiplier
   if the repo is ever private. `ci.yml` uses `ubuntu-24.04` only.

At the current ~66 KB gzipped bundle, 360 MB/day is roughly 5,000 cold visits.
If that is ever exceeded the demo goes dark until the next day. The documented
contingency is a Cloudflare Pages mirror (unmetered bandwidth, no card) — noted
here rather than adopted, because it means a second vendor.

---

## First-time setup — deploying the demo

The repo ships with `REPLACE_ME-haze` as a placeholder. Everything below is
once-only. **Pick a globally unique project id** — Firebase ids are shared
across all users, so `haze` alone will be taken.

```bash
# 1. Log in, and confirm which Google account you are on.
#    Firebase project ids are per-account, and it is easy to create the project
#    under a different account than the one you expected.
firebase login
firebase projects:list

# 2. Create the project. Spark plan by default — do NOT add a billing account.
firebase projects:create haze-<something-unique> --display-name "Haze"

# 3. Enable Hosting for it (once; the deploy fails with a clear error if not).
firebase apps:create WEB Haze --project haze-<something-unique>

# 4. Point the repo at it. One command, so nothing is missed:
PROJECT=haze-<something-unique>
sed -i '' "s/REPLACE_ME-haze/$PROJECT/g" .firebaserc web/.env.production \
  web/.env.example DEPLOY.md README.md 2>/dev/null || \
sed -i "s/REPLACE_ME-haze/$PROJECT/g" .firebaserc web/.env.production \
  web/.env.example DEPLOY.md README.md

# 5. Prove it deploys by hand before trusting CI with it.
make build-demo
firebase deploy --only hosting --project $PROJECT
#    -> https://<project>.web.app

# 6. Hand the same ability to GitHub Actions.
#    Firebase console -> Project settings -> Service accounts -> Generate new
#    private key. Downloads a JSON file.
gh secret set FIREBASE_SERVICE_ACCOUNT_HAZE --repo CodeMaster747/Haze \
  --body "$(cat ~/Downloads/<the-downloaded>.json)"
gh variable set FIREBASE_PROJECT_ID --repo CodeMaster747/Haze --body "$PROJECT"

# 7. Commit the wiring. Both deploy workflows switch themselves on the moment
#    FIREBASE_PROJECT_ID exists — until then they skip, so the repo stays green.
git add -A && git commit -m "wire up the Firebase project" && git push
```

Then delete the downloaded service-account JSON. It grants deploy rights to the
project and there is no reason for it to stay in Downloads.

## First-time setup — publishing the agent

Only needed if you want `uv tool install haze-agent` to work for other people.
The project works fully without this.

```bash
# 1. Create the PyPI project via Trusted Publishing, BEFORE any upload:
#    https://pypi.org/manage/account/publishing/
#      PyPI project name : haze-agent
#      Owner             : CodeMaster747
#      Repository        : Haze
#      Workflow          : release.yml
#      Environment       : pypi
#    (`haze` itself is taken, which is why the distribution is `haze-agent`.)

# 2. Create the matching GitHub environment so the workflow can use it.
gh api -X PUT repos/CodeMaster747/Haze/environments/pypi

# 3. Dry run: builds, checks the wheel contains the dashboard, publishes nothing.
gh workflow run "Publish to PyPI" --repo CodeMaster747/Haze --ref main

# 4. Release for real. The workflow refuses if the tag and the version in
#    agent/pyproject.toml disagree — a PyPI release cannot be replaced.
git tag v0.1.0 && git push --tags
```

---

## The everyday update flow

```bash
make check              # ruff, mypy, pytest, eslint, tsc, vitest — same as CI
git add -A
git commit -m "Describe what you changed"
git push
```

Pushing to `main` runs **CI** (agent + web + a check that the wheel really
contains the dashboard), then **Deploy**, which publishes the demo bundle.
Changes are live ~1–2 minutes after the push.

```bash
gh run list  --repo CodeMaster747/Haze --limit 5
gh run watch --repo CodeMaster747/Haze
```

## Pull requests get a preview URL

```bash
git checkout -b my-change
git push -u origin my-change
gh pr create --fill
```

CI runs, and a preview deploy is posted as a PR comment (expires after 7 days).
Preview deploys are skipped for forks, which cannot read repository secrets.

## Rolling back

Fastest path is the Firebase console → Hosting → Release history → `⋮` →
**Roll back**. Otherwise:

```bash
git revert <bad-commit-sha> && git push
```

---

## Two builds from one source tree

This is the part that is easy to get wrong.

| Command | Output | Data source | Goes to |
|---|---|---|---|
| `npm run build` | `web/dist` | `HttpAgentSource` — real agent | Copied into the Python wheel |
| `npm run build:demo` | `web/dist` | `SimSource` — in-browser simulation | Firebase Hosting |

`VITE_HAZE_MODE=demo` is baked in at build time via a Vite `define`, so the
unused source is dead-code-eliminated. That matters in both directions: the
hosted bundle ships **no** code that could contact a local agent, and the agent
bundle ships **no** simulation code that could be mistaken for real telemetry.

**The deploy workflow must run `build:demo`.** Deploying the agent build would
publish a page that tries to open `ws://127.0.0.1:7433` from an HTTPS origin —
which Safari blocks outright and Chrome gates behind a permission prompt.

---

---

## What's configured (reference)

| Thing | Where | Notes |
|---|---|---|
| CI | `.github/workflows/ci.yml` | agent · web · wheel-contains-dashboard |
| Live deploy | `.github/workflows/firebase-hosting-merge.yml` | push to `main` + manual dispatch |
| PyPI release | `.github/workflows/release.yml` | on a `v*` tag; Trusted Publishing, no token |
| PR preview | `.github/workflows/firebase-hosting-pull-request.yml` | 7-day expiry, skipped for forks |
| Hosting config | `firebase.json` | serves `web/dist`, SPA rewrite, asset caching |
| Project alias | `.firebaserc` | |
| Public build values | `web/.env.production` | committed on purpose — no secrets exist |
| Deploy credential | secret `FIREBASE_SERVICE_ACCOUNT_HAZE` | |
| Project id | variable `FIREBASE_PROJECT_ID` | |

---

## Common issues

- **`Input required and not supplied: firebaseServiceAccount`** — the secret is
  missing. Re-add it with the `gh secret set` command above.

- **The wheel installs but the dashboard is a "not built" placeholder.**
  `agent/src/haze/webui/` is gitignored (it is a build artifact), and hatchling
  honours `.gitignore`. The `artifacts` entry in `agent/pyproject.toml` is what
  forces it into the wheel. `make verify-wheel` checks this, and so does CI.

- **The demo page is blank / stuck "connecting".** It was probably built with
  `npm run build` instead of `npm run build:demo`, so it is trying to reach a
  local agent that is not there.

- **`haze up` says the console needs a token.** The dashboard was opened by hand
  at `127.0.0.1:7433` rather than via the tokenised URL. Run `haze open`.

- **Site returns 404 after hitting the daily cap.** Firebase Spark disables
  hosting for the rest of the period rather than billing. Wait, or deploy the
  Cloudflare Pages mirror.

- **`firebase deploy` says the site does not exist.** Hosting has not been
  enabled for the project. Run `firebase apps:create WEB Haze --project <id>`,
  or enable Hosting once in the console.

- **PyPI publish fails with "Trusted Publishing exchange failure".** The
  publisher on pypi.org does not match. All four of owner, repository, workflow
  filename (`release.yml`) and environment (`pypi`) must agree exactly, and the
  GitHub environment must exist.

- **Tag pushed but nothing published.** The workflow refuses when the tag and
  `agent/pyproject.toml`'s version disagree. Bump one to match, delete the tag
  (`git tag -d v0.1.0 && git push --delete origin v0.1.0`) and re-tag.
