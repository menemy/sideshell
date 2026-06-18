# Security Policy

sideshell is a tool that lets an AI assistant run commands in a real terminal
on your machine. Because of what it does, understanding the trust model below
is more important than any single vulnerability report. Please read it before
connecting sideshell to anything.

## Trust Model

sideshell is **not a sandbox**. It does not isolate, restrict, or vet the
commands it runs. It is a bridge that gives a connected AI assistant the
ability to drive a terminal that you can see and control. Treat it accordingly.

### 1. sideshell runs shell commands chosen by the AI assistant

When you connect sideshell to an MCP client (Claude Desktop, Cursor, etc.), the
assistant on the other end decides which commands to run via the `execute`,
`paste`, and `control-char` tools. Those commands run in **your** terminal,
under **your** user account, with **your** shell's full privileges.

- Anything you can do from your shell, sideshell can do on the assistant's
  behalf — read and write files, install software, make network calls, use
  cached credentials (SSH keys, cloud CLI sessions, `git` push access), and so
  on.
- sideshell does **not** confirm, filter, or roll back commands. If the
  assistant runs `rm -rf`, sideshell runs `rm -rf`.
- **Only connect sideshell to AI assistants and MCP clients you trust.** The
  security boundary is the assistant you choose to connect, not sideshell.

The upside of the "sidecar" design is that everything is visible: commands run
in a terminal pane you can watch and interrupt at any time (Ctrl+C, close the
session, etc.). Keeping that terminal where you can see it is part of the
security model — review what is happening rather than letting it scroll by.

### 2. Prompt injection is a relevant threat

The assistant decides what to run, but its decisions are influenced by whatever
content it reads — file contents, command output, web pages, issue text, logs,
and any other untrusted input that ends up in its context. A malicious payload
embedded in that content can attempt to steer the assistant into running
commands you did not intend (this is **prompt injection**).

Because sideshell executes whatever the assistant asks for, prompt injection
against the assistant becomes command execution on your machine. Mitigations
live mostly outside sideshell, but they matter:

- Be cautious when pointing the assistant at untrusted repositories, files,
  URLs, or command output.
- Watch the sidecar terminal, especially during tasks that touch external or
  attacker-controlled content.
- Prefer least-privilege environments (a dedicated user, a VM, or a container)
  when working with untrusted material.

### 3. The IDE bridge is local-only, token-gated, and consent-gated

The VSCode and IntelliJ backends talk to their IDE plugins over a **local Unix
domain socket** under `~/.sideshell/` (e.g. `~/.sideshell/vscode.sock`,
`~/.sideshell/intellij.sock`). This transport is designed so that only
processes running as you, on the same machine, can use it:

- **Not network-accessible.** A Unix socket has no TCP/IP listener; remote
  attackers cannot reach it.
- **`0600` permissions.** The socket file and the port file
  (`~/.sideshell/<ide>-port`) are owner-readable only, so other users on the
  same machine cannot connect or read the token.
- **Token handshake.** The IDE plugin generates a fresh random 256-bit token at
  startup and writes it to the port file. The client must present that token as
  its first message; a new token is generated on each IDE restart.
- **Extension-side user consent.** On the first authenticated connection the
  plugin shows an in-IDE dialog ("Sideshell wants to access your IDE
  terminals"). Until you explicitly **Allow**, every request is rejected
  (error `-32001`). Approval is persisted in IDE settings and can be revoked
  there.

See [`extensions/API.md`](extensions/API.md) for the full protocol and the
threat/mitigation table.

### 4. The native terminal backends drive your real terminal apps

The iTerm2, tmux, Ghostty, WezTerm, Kitty, and maquake backends control
terminals that are already running as you:

- The **iTerm2** backend uses iTerm2's Python API (which you must explicitly
  enable in iTerm2 preferences).
- **tmux**, **Kitty**, and **WezTerm** are driven via their own CLI/subprocess
  control interfaces.
- The **Ghostty** backend drives Ghostty via **AppleScript** (macOS Automation)
  for layout and a per-surface **tmux** session for I/O. The first action
  triggers a macOS TCC Automation permission prompt that you must approve.
- The **maquake** backend uses a local Unix socket at `/tmp/maquake.sock`.

In every case sideshell is sending keystrokes and commands to terminals that
inherit your environment and privileges. The same "only connect trusted
assistants" rule applies.

### What sideshell does *not* do

To be explicit about the limits of the project:

- It does **not** sandbox, containerize, or virtualize the commands it runs.
- It does **not** require per-command confirmation from you.
- It does **not** scrub secrets from command output or from the assistant's
  context.
- It does **not** restrict which files, networks, or credentials a command can
  reach.

If you need those properties, run sideshell (and the assistant) inside an
environment you have isolated yourself.

## Supported Versions

Security fixes are applied to the **latest released version** on
[PyPI](https://pypi.org/project/sideshell-mcp/) and the corresponding IDE
extensions. Please upgrade to the latest release before reporting an issue, and
include the version you are running in any report.

| Version        | Supported          |
|----------------|--------------------|
| Latest release | :white_check_mark: |
| Older releases | :x:                |

## Reporting a Vulnerability

Please report security vulnerabilities **privately** rather than opening a
public issue.

Preferred channel: open a private
[**GitHub Security Advisory**](https://github.com/menemy/sideshell/security/advisories/new)
on the repository. This keeps the discussion confidential until a fix is
available.

When reporting, please include:

- A description of the issue and its impact.
- The sideshell version, backend, OS, and MCP client involved.
- Step-by-step reproduction instructions, and a proof of concept if you have
  one.

**Response window:** we aim to acknowledge a report within **5 business days**
and to provide an initial assessment within **10 business days**. Once a fix is
ready we will coordinate a release and credit you in the advisory (unless you
prefer to remain anonymous).

Please do not publicly disclose the issue until a fix has been released and we
have had a reasonable opportunity to respond.

## Scope

In scope:

- The sideshell MCP server (`sideshell_mcp`).
- The VSCode/Cursor and IntelliJ bridge extensions and their Unix-socket
  protocol.

Out of scope (by design, per the trust model above):

- The fact that a connected AI assistant can run arbitrary commands — this is
  the intended behavior. Reports here should focus on *control-plane* issues
  (e.g. the local socket being reachable by other users, the token being
  leaked, consent being bypassed), not on "the AI can run commands."
- Vulnerabilities in third-party terminals, IDEs, or the MCP client itself.
