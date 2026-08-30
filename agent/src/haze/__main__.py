"""`python -m haze`.

Routes through the same entry point as the `haze` console script, so both
present recoverable errors the same way. They diverged once: the console script
was fixed to show a clean message and `python -m haze` still dumped a
traceback, which the integration tests use and so would have kept passing.
"""

from haze.cli import main

if __name__ == "__main__":
    main()
