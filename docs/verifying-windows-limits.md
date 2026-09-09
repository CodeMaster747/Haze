# Verifying the Windows caps by hand

CI runs on `ubuntu-24.04` only. The unit tests in `agent/tests/test_limits.py`
cover the arithmetic, the structure layouts and every failure path with a fake
kernel32, and `mypy --platform win32` typechecks the ctypes layer — but none of
that proves the kernel is enforcing anything. That takes a Windows machine and
twenty minutes.

Do this before trusting the "Real" rows in the README's enforcement table.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".\agent[dev]"
.venv\Scripts\haze up
```

`haze jobs status` should now print a caps line reading *"Windows Job Objects
enforce memory and CPU caps (a memory cap makes allocations fail rather than
killing the job)"*. If it says anything else, stop — nothing below will mean
what you think it means.

## 1. Prove the memory cap is the kernel, not the watchdog

This is the test that matters, and it is easy to fake yourself out on: the
executor's own `_watch` loop polls RSS every 500 ms and kills a job that
overruns, so a job dying near its cap proves **nothing** on its own. That
watchdog would pass this test on a machine with no Job Object support at all.

The two mechanisms are distinguishable, and you should confirm both directions.

**The signature differs.** The watchdog writes an error of the form
`exceeded its memory cap (N MiB used, M MiB allowed)` and sets the state to
FAILED itself. A kernel refusal never produces that string — the allocation
fails *inside* the process, and what you get is the job's own reaction to
`MemoryError` / a NULL `malloc`, reported through `_describe_exit`.

Submit a job with `ram_bytes` = 512 MiB that runs:

```python
python -c "b=[]\nwhile True: b.append(bytearray(64<<20))"
```

Under the cap it must raise `MemoryError` after roughly eight iterations. Then
run the identical command with the cap raised to 8 GiB and confirm it sails well
past 512 MiB. If both runs die at the same point, the cap is not doing anything.

**Take the watchdog out of the picture.** Temporarily raise `MEMORY_POLL_S` in
`agent/src/haze/jobs/executor.py` to something like `60.0` and give the job a
generous `wall_seconds`. The poll now cannot be what caught it. If the job still
stops at its cap, that was the kernel.

**Confirm from outside.** In Process Explorer the process appears under a Job
(the lower pane shows the job's limits); Task Manager's *Commit size* column for
it should flatten *at* the cap rather than overshooting it and then vanishing.
Flattening is the tell — an OOM kill overshoots first, a commit limit never lets
it.

## 2. Prove the CPU cap

Run a `hashbench` job with `cpu_cores` = 2 on a machine with 16 logical
processors. Task Manager's total CPU for the process should sit near 12.5%, not
near 100%. Note that this is a share of the *whole machine* — a Job Object's
`CpuRate` is not the Linux `CPUQuota=200%` convention, and getting those two
confused is the single most likely way for this to be silently wrong.

If the caps line says the CPU share is advisory, CPU rate control was refused by
this Windows build. That is reported honestly rather than papered over; the
memory cap is still real.

## 3. Prove the teardown, which was broken on Windows entirely

Before this change, `_terminate` raised `AttributeError` on Windows (no
`signal.SIGKILL`, no `os.killpg`), so cancel, the timeout and the watchdog all
failed silently and the job kept running.

- Cancel a running job from the dashboard. It must actually stop.
- Start a job that spawns helpers (an ffmpeg transcode), then kill the **agent**
  outright with Task Manager. Every child must disappear with it — that is
  `KILL_ON_JOB_CLOSE`, and it is the one thing Windows does better here than the
  POSIX path.
- Let a job exceed its `wall_seconds` and confirm it is stopped.

## 4. Prove the honest failure path

Make `winjob._load_kernel32` raise, or point `CreateJobObjectW` at a bad name,
and re-run any job. It must still **run** — a node that refuses work because Job
Objects were unavailable is worse than one that runs it and says so — while the
dashboard shows the caps as advisory and the warning banner appears. A silent
downgrade to advisory would be the worst outcome of all, which is why
`test_a_job_object_that_could_not_be_created_stays_advisory` exists.

## CI has a Windows runner now

It did not when this document was written, and the argument against one is worth
keeping because it is what changed. Actions is unmetered on **public**
repositories, so a `windows-2022` job is free today — but it stops being free the
moment this repo goes private, where Windows minutes bill at a 2x multiplier
against the 2,000-minute monthly allowance (macOS, which `ci.yml` forbids
outright, is 10x). Against a hard zero-cost rule, a runner whose cost is
contingent on a repository setting is a trap set for later.

What flipped it was the condition this section named: *if Haze ever grows real
Windows users, revisit it.* `scripts/install.ps1` and `haze autostart` exist to
make a Windows gaming PC a donor machine that its owner can set up without
opening a terminal. Shipping that while testing none of it on Windows would be
worse than the cost risk. The `windows-2022` job in `ci.yml` is pinned, not
`windows-latest`, consistent with the policy at the top of that file — and the
trap is still set, so if this repo ever goes private, read that cost note again.

The job proves four things, and it is worth being precise about which:

1. `scripts/install.ps1` runs to completion against the real uv and the real
   PyPI. It installs the **published** `haze-agent`, not the checkout — it is a
   test of the bootstrap, not of the code underneath it.
2. `pytest agent/tests -q` runs on Windows. This is where `winjob.py`'s kernel32
   calls finally meet a kernel rather than `FakeKernel32`.
3. `haze autostart enable`/`status`/`disable` writes and removes its entries —
   and asserts the file lands in the folder
   `[Environment]::GetFolderPath('Startup')` reports, which is the check that
   catches `autostart.startup_dir()` deriving the wrong path from `%APPDATA%`.
4. `haze up` serves the tokenised console and returns 200.

**What it still does not prove, and why this document is still here.** Section 1
above is about distinguishing a kernel commit limit from the executor's own
polling watchdog, and the tell is watching Task Manager's Commit size *flatten*
at the cap rather than overshoot. That is an observation a person makes, not an
assertion a runner makes. A CI job can confirm a job died near its cap; it
cannot confirm *what killed it*, which is the entire question. Nor can it judge
whether the minimised Haze window reads as reassuring or alarming to the person
whose PC it is running on. Run this document by hand before a release that
touches `jobs/limits.py`, `jobs/winjob.py`, or `jobs/executor.py`.
