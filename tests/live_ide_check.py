#!/usr/bin/env python3
"""Live end-to-end check of an IDE bridge backend (vscode or intellij).

Drives a REAL running IDE (VS Code/Cursor or a JetBrains IDE) through the
sideshell backend over its Unix-socket / named-pipe bridge, using unique
sentinel markers and verifying real effects (not just "no error").

Prerequisites: the IDE is running with the sideshell extension/plugin, the
bridge socket exists under ~/.sideshell/, and terminal access is approved
(VS Code: `sideshell.allowAccess`; JetBrains: SideshellSettings.approved).

Usage:
    python tests/live_ide_check.py vscode
    python tests/live_ide_check.py intellij

Exits 0 if all checks pass, 1 on failure, 77 if the IDE/bridge isn't available
(treated as "skipped" rather than failed).
"""

import asyncio
import os
import re
import sys

from sideshell_mcp.backends.base import ControlKey

R: list[tuple[str, bool, str]] = []


def rec(name: str, ok: bool, detail: str = "") -> None:
    R.append((name, ok, detail))
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: {detail}")


def sid(text: str | None) -> str | None:
    m = re.search(r"Session:\s*(\S+)", text or "")
    return m.group(1) if m else None


def make_backend(ide: str):
    if ide == "vscode":
        from sideshell_mcp.backends.vscode_backend import VSCodeBackend

        return VSCodeBackend()
    if ide == "intellij":
        from sideshell_mcp.backends.intellij_backend import IntelliJBackend

        return IntelliJBackend()
    raise SystemExit(f"unknown ide '{ide}' (expected vscode|intellij)")


async def main(ide: str) -> int:
    backend = make_backend(ide)
    marker = f"{ide.upper()}_{os.getpid()}"

    connected = await backend.connect()
    if not connected:
        print(f"{ide} bridge not available (IDE not running / no socket) — skipping")
        return 77
    rec("connect", True, "True")

    created: list[str] = []
    try:
        # create a fresh terminal session
        tab = await backend.create_tab()
        s = sid(tab)
        if s:
            created.append(s)
        rec("create_tab", s is not None, (tab or "").strip()[:80])

        # execute a command that prints a unique marker; verify it comes back
        await asyncio.sleep(1.0)
        out = await backend.execute_command(f"echo {marker}", session_id=s, wait=True, timeout=12, watch_for="silence")
        # With shell integration the marker is captured; without it (VS Code
        # fallback) the command is still sent — read_terminal is the real check.
        rec("execute (wait)", bool(out), (out or "").replace("\n", " ").strip()[:90])

        # read the terminal back — the marker must be visible
        await asyncio.sleep(0.6)
        scr = await backend.read_terminal(lines=50, session_id=s)
        rec("read effect", marker in (scr or ""), f"saw {marker}={marker in (scr or '')}, {len(scr or '')} chars")

        # send a real Ctrl+C
        ctl = await backend.send_control(ControlKey.C, session_id=s)
        rec("control C", "ent" in (ctl or "") or "ontrol" in (ctl or ""), (ctl or "").strip()[:60])

        # close the session — it must really be gone
        cl = await backend.close_session(session_id=s, force=True)
        ok_close = "lose" in (cl or "").lower() or "closed" in (cl or "").lower()
        if ok_close and s in created:
            created.remove(s)
        rec("close-session", ok_close, (cl or "").strip()[:60])

    except Exception as e:
        import traceback

        traceback.print_exc()
        rec("EXCEPTION", False, str(e))
    finally:
        for sess in created:
            try:
                await backend.close_session(session_id=sess, force=True)
            except Exception:
                pass
        await backend.disconnect()

    passed = sum(1 for _, ok, _ in R if ok)
    failed = len(R) - passed
    print(f"\n{'=' * 56}\nRESULT [{ide}]: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    ide_arg = sys.argv[1] if len(sys.argv) > 1 else "vscode"
    sys.exit(asyncio.run(main(ide_arg)))
