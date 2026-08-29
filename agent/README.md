# Haze — Node Agent

Pool your own machines into a private compute network. A weak laptop borrows a
desktop's GPU; a NAS lends its disks. You own every node, so there is no cloud
bill and no third party in the data path.

This package is the **Node Agent**: the process that runs on each machine. It
serves the Haze dashboard on `http://127.0.0.1:7433`, discovers and pairs with
your other machines over the LAN, reports live resources, and executes jobs
within limits you set.

## Install

```bash
uv tool install haze-agent     # or: pipx install haze-agent
haze up
```

The distribution is `haze-agent`; the command it installs is `haze`.

## Try it on one machine

```bash
haze devnet up -n 4 --open     # four agents with simulated hardware profiles
```

## Why the dashboard is served locally

A public HTTPS page can no longer reach a local agent: Safari hard-blocks it as
mixed content, and Chrome 142+ gates it behind a Local Network Access prompt
that Chrome 147 extended to WebSockets. Serving the UI from the agent's own
origin sidesteps all of it — the same choice Syncthing, Jellyfin, Home Assistant
and Ollama make.

Full documentation, architecture notes and the live demo:
**https://github.com/CodeMaster747/Haze**

MIT licensed.
