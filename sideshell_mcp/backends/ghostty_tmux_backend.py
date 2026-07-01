"""Ghostty hybrid backend — native AppleScript layout + tmux read/execute engine.

Ghostty 1.3+ ships a native AppleScript dictionary (see
``/Applications/Ghostty.app/Contents/Resources/Ghostty.sdef``) that can create
windows/tabs/splits, focus/close surfaces, and send input — but it exposes **no
way to read terminal contents** (the ``terminal`` object only has ``id``,
``name``/title and ``working directory``).

Reading output and the ``wait``/``watch_for`` completion modes are core to
sideshell, so we keep tmux as the read/execute engine. Hence the ``ghostty_tmux``
hybrid:

- **Layout** (split / new tab / new window / focus / close) is done **natively
  via AppleScript** — real Ghostty splits, no ugly tmux borders.
- Each native surface runs **its own tmux session** (``tmux new-session -A -s
  <name>``). sideshell sends keys and captures output through that tmux session.
- sideshell creates both halves together, so the mapping
  ``tmux session name -> Ghostty terminal id`` is deterministic, not guessed.

Public ``session_id`` is the tmux session name (e.g. ``sideshell_4711_2_ab12``);
all inherited :class:`TmuxBackend` methods target it directly with ``-t``. The
Ghostty terminal id (a UUID) is only needed for AppleScript focus/close.

Robustness:
- The name->terminal-id map is **persisted** to ``~/.sideshell/ghostty-sessions.json``
  and **reconciled** against live Ghostty surfaces + tmux sessions, so sessions
  survive an MCP-server restart and externally-closed surfaces are pruned.
- Every id interpolated into an AppleScript string literal is validated against
  :data:`_SAFE_ID` first, so attacker-influenced ``session_id`` tool arguments
  cannot inject AppleScript.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from .base import SessionInfo, SplitDirection
from .tmux_backend import TmuxBackend

logger = logging.getLogger(__name__)

# Ghostty terminal ids are UUIDs / "tab-group-..." ids; our tmux session names are
# sideshell_<pid>_<n>_<token>. All match this; anything else (quotes, spaces,
# newlines, AppleScript metacharacters) is rejected before osascript interpolation.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")

_STATE_DIR = Path.home() / ".sideshell"
_STATE_FILE = _STATE_DIR / "ghostty-sessions.json"


class GhosttyTmuxBackend(TmuxBackend):
    """Ghostty backend: native AppleScript layout + tmux read/execute engine."""

    def __init__(self) -> None:
        super().__init__()
        # tmux session name -> Ghostty terminal id (UUID)
        self._ghostty_terminals: dict[str, str] = {}
        self._counter = 0
        # Per-process token so PID reuse cannot collide with a stale tmux session
        # that ``tmux new-session -A`` would otherwise silently attach to.
        self._token = uuid.uuid4().hex[:4]
        # Serialize read-modify-write of the session map + state file so
        # concurrent create/close/reconcile calls can't corrupt either.
        self._state_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "ghostty_tmux"

    @property
    def is_available(self) -> bool:
        """Available when tmux (engine), osascript, and Ghostty are all present."""
        if shutil.which("tmux") is None or shutil.which("osascript") is None:
            return False
        return (
            os.path.exists("/Applications/Ghostty.app")
            or os.path.exists(os.path.expanduser("~/Applications/Ghostty.app"))
            or shutil.which("ghostty") is not None
            or os.environ.get("GHOSTTY_RESOURCES_DIR") is not None
            or os.environ.get("TERM_PROGRAM") == "ghostty"
        )

    # --- AppleScript helpers --------------------------------------------------

    @staticmethod
    def _safe_id(value: str | None) -> bool:
        """True if `value` is safe to interpolate into an AppleScript string."""
        if not value:
            return False
        return _SAFE_ID.match(value) is not None

    async def _osascript(self, script: str) -> str:
        """Run an AppleScript snippet via osascript (stdin) and return stdout."""
        proc = await asyncio.create_subprocess_exec(
            "osascript",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(script.encode())
        if proc.returncode != 0:
            err = stderr.decode().strip()
            raise RuntimeError(f"osascript error: {err}")
        return stdout.decode().strip()

    def _new_session_name(self) -> str:
        """Generate a unique tmux session name for a new surface."""
        self._counter += 1
        return f"sideshell_{os.getpid()}_{self._counter}_{self._token}"

    def _tmux_launch_cmd(self, name: str) -> str:
        """The command a new Ghostty surface runs: attach/create its tmux session."""
        return f"{self._get_tmux_path()} new-session -A -s {name}"

    async def _wait_for_session(self, name: str, max_wait: float = 4.0) -> bool:
        """Poll until the tmux session exists (surface finished launching tmux)."""
        elapsed = 0.0
        while elapsed < max_wait:
            code, _, _ = await self._run_tmux("has-session", "-t", name)
            if code == 0:
                return True
            await asyncio.sleep(0.2)
            elapsed += 0.2
        return False

    async def _close_surface(self, term_id: str) -> None:
        """Best-effort close of a Ghostty surface by terminal id."""
        if not self._safe_id(term_id):
            return
        try:
            await self._osascript(f'tell application "Ghostty" to close (first terminal whose id is "{term_id}")')
        except Exception as e:
            logger.debug(f"close surface {term_id} failed: {e}")

    # --- Persistence + reconciliation ----------------------------------------

    def _load_state(self) -> None:
        try:
            if _STATE_FILE.exists():
                data = json.loads(_STATE_FILE.read_text())
                if isinstance(data, dict):
                    for k, v in data.items():
                        if self._safe_id(str(k)) and self._safe_id(str(v)):
                            self._ghostty_terminals[str(k)] = str(v)
        except Exception as e:
            logger.debug(f"ghostty state load failed: {e}")

    def _save_state(self) -> None:
        try:
            _STATE_DIR.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(json.dumps(self._ghostty_terminals))
            _STATE_FILE.chmod(0o600)
        except Exception as e:
            logger.debug(f"ghostty state save failed: {e}")

    async def _live_terminal_ids(self) -> set[str] | None:
        """Set of currently-existing Ghostty terminal ids, or None on query failure."""
        script = (
            'tell application "Ghostty"\n'
            '    set out to ""\n'
            "    repeat with t in terminals\n"
            "        set out to out & (id of t) & linefeed\n"
            "    end repeat\n"
            "    return out\n"
            "end tell"
        )
        try:
            raw = await self._osascript(script)
        except Exception:
            return None
        return {ln.strip() for ln in raw.splitlines() if ln.strip()}

    async def _reconcile(self) -> None:
        """Drop mappings whose Ghostty surface or tmux session is gone.

        - surface closed externally (Cmd+W) but tmux session lingers detached ->
          kill the orphaned tmux session and drop the mapping;
        - tmux session died -> drop the mapping.
        """
        if not self._ghostty_terminals:
            return
        live = await self._live_terminal_ids()
        async with self._state_lock:
            changed = False
            for name, term_id in list(self._ghostty_terminals.items()):
                code, _, _ = await self._run_tmux("has-session", "-t", name)
                dead_tmux = code != 0
                dead_surface = live is not None and term_id not in live
                if dead_surface and not dead_tmux:
                    await self._run_tmux("kill-session", "-t", name)
                if dead_surface or dead_tmux:
                    del self._ghostty_terminals[name]
                    changed = True
            if changed:
                self._save_state()

    # --- Connection -----------------------------------------------------------

    async def connect(self) -> bool:
        """Ensure the tmux server is up and recover any persisted sessions.

        We do NOT create a hidden detached session — surfaces are created on
        demand via AppleScript.
        """
        try:
            await self._run_tmux("start-server")
            self._connected = True
            self._load_state()
            await self._reconcile()
            logger.info("ghostty_tmux backend connected (tmux engine ready)")
            return True
        except Exception as e:
            logger.error(f"ghostty_tmux backend failed to connect: {e}")
            return False

    # --- Session creation (native AppleScript) --------------------------------

    async def _finish_create(self, name: str, term_id: str, command: str | None) -> str | None:
        """Shared post-create step. Returns an error string, or None on success."""
        if not await self._wait_for_session(name):
            # tmux never came up — close the dead surface and report instead of
            # reporting a phantom success with an unusable session_id.
            await self._close_surface(term_id)
            await self._run_tmux("kill-session", "-t", name)
            return f"Error: Ghostty surface opened but its tmux session '{name}' did not start; surface closed."
        async with self._state_lock:
            self._ghostty_terminals[name] = term_id
            self._save_state()
        if command:
            await self._tmux("send-keys", "-t", name, "--", command, "Enter")
        return None

    async def create_window(self, profile: str | None = None, command: str | None = None) -> str:
        """Create a new native Ghostty window running its own tmux session."""
        name = self._new_session_name()
        launch = self._tmux_launch_cmd(name)
        script = f'''tell application "Ghostty"
    set cfg to new surface configuration
    set command of cfg to "{launch}"
    set w to new window with configuration cfg
    return id of (focused terminal of selected tab of w)
end tell'''
        try:
            term_id = await self._osascript(script)
        except Exception as e:
            return f"Error creating Ghostty window: {e!s}"

        err = await self._finish_create(name, term_id, command)
        return err or f"Created Ghostty window. session_id: {name}"

    async def create_tab(self, profile: str | None = None, command: str | None = None) -> str:
        """Create a new native Ghostty tab running its own tmux session."""
        name = self._new_session_name()
        launch = self._tmux_launch_cmd(name)
        # Ghostty's `new tab` requires an explicit target window.
        script = f'''tell application "Ghostty"
    set cfg to new surface configuration
    set command of cfg to "{launch}"
    set t to new tab in front window with configuration cfg
    return id of (focused terminal of t)
end tell'''
        try:
            term_id = await self._osascript(script)
        except Exception as e:
            logger.warning(f"Ghostty new tab failed ({e}); creating a window instead")
            return await self.create_window()

        err = await self._finish_create(name, term_id, command)
        return err or f"Created Ghostty tab. session_id: {name}"

    async def split_pane(self, direction: SplitDirection, session_id: str | None = None) -> str:
        """Split a Ghostty surface natively; the new pane runs its own tmux session."""
        name = self._new_session_name()
        launch = self._tmux_launch_cmd(name)
        gdir = "right" if direction == SplitDirection.HORIZONTAL else "down"

        # Resolve the source terminal to split (validated before interpolation).
        if session_id and session_id in self._ghostty_terminals:
            src_clause = f'(first terminal whose id is "{self._ghostty_terminals[session_id]}")'
        elif session_id:
            if not self._safe_id(session_id):
                return f"Error: invalid session_id {session_id!r}"
            src_clause = f'(first terminal whose id is "{session_id}")'
        else:
            src_clause = "focused terminal of selected tab of front window"

        script = f'''tell application "Ghostty"
    set cfg to new surface configuration
    set command of cfg to "{launch}"
    set src to {src_clause}
    set newTerm to split src direction {gdir} with configuration cfg
    return id of newTerm
end tell'''
        try:
            term_id = await self._osascript(script)
        except Exception as e:
            logger.warning(f"Ghostty split failed ({e}); creating a window instead")
            return await self.create_window()

        err = await self._finish_create(name, term_id, None)
        if err:
            return err
        dtext = "horizontally" if direction == SplitDirection.HORIZONTAL else "vertically"
        return f"Split {dtext}. session_id: {name}"

    async def create_session(self, profile: str | None = None) -> str:
        """Smart creation: split the current Ghostty surface so the session lands
        next to whatever is in front (the sidecar sits beside the AI's terminal),
        matching iTerm2/tmux/kitty/wezterm. split_pane falls back to a new window
        when there's nothing to split. For an explicit new window, use the
        new-window tool (create_window)."""
        return await self.split_pane(SplitDirection.HORIZONTAL)

    # --- Focus / current / close (native AppleScript) -------------------------

    def _resolve_terminal_id(self, session_id: str) -> str:
        """Map a tmux session name to its Ghostty terminal id (or pass through)."""
        return self._ghostty_terminals.get(session_id, session_id)

    async def focus_session(self, session_id: str) -> str:
        """Focus a Ghostty surface, bringing its window to the front."""
        term_id = self._resolve_terminal_id(session_id)
        if not self._safe_id(term_id):
            return f"Error: invalid session id {session_id!r}"
        try:
            await self._osascript(f'tell application "Ghostty" to focus (first terminal whose id is "{term_id}")')
            return f"Focused {session_id}"
        except Exception as e:
            return f"Error focusing session: {e!s}"

    async def get_current_active_session_id(self) -> str | None:
        """Return the focused surface as a sideshell session id (tmux name) when
        managed, the raw Ghostty terminal id otherwise, or None if no window."""
        try:
            term_id = await self._osascript(
                'tell application "Ghostty" to return id of (focused terminal of selected tab of front window)'
            )
        except Exception:
            return None
        if not term_id:
            return None
        for name, tid in self._ghostty_terminals.items():
            if tid == term_id:
                return name
        return term_id

    async def _get_active_pane(self) -> str | None:
        """Resolve the 'current' session for execute/read when none is given.

        Prefers the focused surface (if sideshell-managed); otherwise the most
        recently created managed session. Avoids targeting the AI's own surface.
        """
        sid = await self.get_current_active_session_id()
        if sid and sid in self._ghostty_terminals:
            return sid
        if self._ghostty_terminals:
            return next(reversed(self._ghostty_terminals))
        return None

    async def close_session(self, session_id: str | None = None, force: bool = False) -> str:
        """Close a Ghostty surface and kill its tmux session."""
        target = session_id or await self._get_active_pane()
        if not target:
            return "No active session found"

        if not force and await self.is_ai_session(target):
            return "Cannot close AI session. Specify a different session_id."

        term_id = self._resolve_terminal_id(target)
        if not self._safe_id(term_id):
            return f"Error: invalid session id {target!r}"

        closed_ok = True
        try:
            await self._osascript(f'tell application "Ghostty" to close (first terminal whose id is "{term_id}")')
        except Exception as e:
            closed_ok = False
            logger.warning(f"Ghostty close surface failed: {e}")

        # If the close failed AND the surface is still alive, keep the mapping so
        # the caller can retry — don't orphan it.
        if not closed_ok:
            live = await self._live_terminal_ids()
            if live is not None and term_id in live:
                return f"Error: failed to close Ghostty surface for {target} (still open)"

        async with self._state_lock:
            if target in self._ghostty_terminals:
                await self._run_tmux("kill-session", "-t", target)
                del self._ghostty_terminals[target]
                self._save_state()
        return f"Closed {target}"

    # --- Listing / state ------------------------------------------------------

    async def get_session(self, session_id: str | None = None) -> SessionInfo | None:
        """Get session info, preserving the sideshell session_id (tmux name)."""
        # A specific id that isn't a live managed surface (e.g. it was closed) must
        # return None — otherwise the tmux get_session fallback resolves to the
        # active pane and we'd stamp the requested id on it, masquerading a dead
        # session as alive.
        if session_id is not None and session_id not in self._ghostty_terminals:
            return None
        info = await super().get_session(session_id)
        if info and session_id:
            info.session_id = session_id
        return info

    async def get_terminal_state(self, session_id: str | None = None) -> str:
        """Terminal state restricted to sideshell-managed Ghostty surfaces.

        (The inherited tmux implementation would report the entire tmux server,
        including the user's unrelated sessions.)
        """
        if session_id:
            return await super().get_terminal_state(session_id)

        await self._reconcile()
        sessions = []
        for name, term_id in list(self._ghostty_terminals.items()):
            info = await self.get_session(name)
            sessions.append(
                {
                    "session_id": name,
                    "ghostty_terminal_id": term_id,
                    "command": info.job if info else None,
                    "path": info.path if info else None,
                    "columns": info.columns if info else 0,
                    "rows": info.rows if info else 0,
                }
            )
        return json.dumps(
            {
                "backend": "ghostty_tmux",
                "managed_sessions": sessions,
                "total": len(sessions),
                "active_session": await self.get_current_active_session_id(),
            },
            indent=2,
        )

    async def list_sessions(self) -> str:
        """List sideshell-managed Ghostty surfaces (id, title, working dir)."""
        await self._reconcile()
        if not self._ghostty_terminals:
            return "No sideshell sessions yet.\nUse 'new-window', 'new-tab' or 'split' to create one."

        # Pull live title/working-directory for managed terminals from Ghostty.
        script = """tell application "Ghostty"
    set out to ""
    repeat with t in terminals
        set out to out & (id of t) & "||" & (name of t) & "||" & (working directory of t) & linefeed
    end repeat
    return out
end tell"""
        details: dict[str, tuple[str, str]] = {}
        try:
            raw = await self._osascript(script)
            for line in raw.splitlines():
                parts = line.split("||")
                if len(parts) >= 3:
                    details[parts[0]] = (parts[1], parts[2])
        except Exception as e:
            logger.debug(f"Ghostty list query failed: {e}")

        lines = [f"Total: {len(self._ghostty_terminals)} sideshell session(s)\n"]
        for name, term_id in self._ghostty_terminals.items():
            title, cwd = details.get(term_id, ("?", "?"))
            alive = "" if term_id in details else " (surface closed?)"
            lines.append(f"  [{name}] {title} @ {cwd}{alive}")
        return "\n".join(lines)
