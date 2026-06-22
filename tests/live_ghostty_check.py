#!/usr/bin/env python3
"""Live verification of ALL MCP methods against the ghostty_tmux backend.

Opens real Ghostty surfaces via AppleScript, each running its own tmux session,
and exercises every sideshell MCP tool + resource through the real server.
Cleans up everything at the end.
"""

import asyncio
import os
import re
import sys

from mcp.types import (
    ListResourcesRequest,
    ListResourceTemplatesRequest,
    ReadResourceRequest,
)

from sideshell_mcp.backends.ghostty_tmux_backend import GhosttyTmuxBackend
from sideshell_mcp.server import VibeSideshellServer

R = []  # (method, ok, detail)


def rec(method, ok, detail=""):
    R.append((method, ok, detail))
    mark = "OK " if ok else "FAIL"
    print(f"  [{mark}] {method}: {detail}")


def sid_of(text):
    m = re.search(r"session_id:\s*(\S+)", text)
    return m.group(1) if m else None


async def main():
    backend = GhosttyTmuxBackend()
    if not backend.is_available:
        print("ghostty_tmux not available (need Ghostty + tmux + osascript)")
        return False

    await backend.connect()
    server = VibeSideshellServer(backend)
    created = []
    marker = f"GH_{os.getpid()}"  # unique per run, used to verify real I/O

    read_handler = server.server.request_handlers[ReadResourceRequest]
    list_res = server.server.request_handlers[ListResourcesRequest]
    list_tmpl = server.server.request_handlers[ListResourceTemplatesRequest]

    try:
        # 1. list (empty)
        out = await server._route_tool_call("list", {})
        rec("list (empty)", "No sideshell sessions" in out or "Total" in out, out.split(chr(10))[0])

        # 2. new-window
        out = await server._route_tool_call("new-window", {"return_focus": False})
        a = sid_of(out)
        if a:
            created.append(a)
        rec("new-window", a is not None, out.strip())

        # 3. list (one)
        out = await server._route_tool_call("list", {})
        rec("list (one)", a in out if a else False, out.split(chr(10))[0])

        # 4. execute fire-and-forget -> the marker must really land in the surface
        fnf_marker = f"{marker}_FNF"
        out = await server._route_tool_call(
            "execute", {"command": f"echo {fnf_marker}", "session_id": a, "wait": False, "return_focus": False}
        )
        rec("execute (wait=False)", "Sent" in out, out.strip()[:60])
        await asyncio.sleep(0.6)
        scr = await server._route_tool_call("read", {"session_id": a, "lines": 40})
        rec("execute (wait=False) effect", fnf_marker in scr, f"saw {fnf_marker}={fnf_marker in scr}")

        # 5. execute wait=True (silence) -> the exact marker must appear in the result
        wait_marker = f"{marker}_WAIT"
        out = await server._route_tool_call(
            "execute",
            {
                "command": f"echo {wait_marker}",
                "session_id": a,
                "wait": True,
                "timeout": 8,
                "watch_for": "silence",
                "return_focus": False,
            },
        )
        rec("execute (wait=True)", wait_marker in out, out.strip()[:60])

        # 6. read -> the exact marker echoed above must be present in a fresh read
        out = await server._route_tool_call("read", {"session_id": a, "lines": 40})
        rec("read", wait_marker in out, f"{len(out)} chars, saw {wait_marker}={wait_marker in out}")

        # 7. control-char (clear, ctrl+l)
        out = await server._route_tool_call("control-char", {"key": "l", "session_id": a, "return_focus": False})
        rec("control-char Ctrl+L", "Ctrl+L" in out or "Sent" in out, out.strip())

        # 8. control-char arrow up (tests full key map)
        out = await server._route_tool_call("control-char", {"key": "up", "session_id": a, "return_focus": False})
        rec("control-char Up arrow", "Up" in out, out.strip())
        await server._route_tool_call("control-char", {"key": "u", "session_id": a, "return_focus": False})

        # 9. split (native, horizontal)
        out = await server._route_tool_call("split", {"direction": "h", "session_id": a, "return_focus": False})
        b = sid_of(out)
        if b:
            created.append(b)
        rec("split (native h)", b is not None, out.strip())

        # 10. new-tab (native)
        out = await server._route_tool_call("new-tab", {"return_focus": False})
        c = sid_of(out)
        if c:
            created.append(c)
        rec("new-tab (native)", c is not None, out.strip())

        # 11. new-session (smart -> split)
        out = await server._route_tool_call("new-session", {})
        d = sid_of(out)
        if d:
            created.append(d)
        rec("new-session (smart)", d is not None, out.strip())

        # 12. focus
        out = await server._route_tool_call("focus", {"session_id": a})
        rec("focus", "Focused" in out, out.strip())

        # 13. paste
        out = await server._route_tool_call("paste", {"session_id": a, "text": "echo PASTE_OK"})
        rec("paste", "Pasted" in out or "characters" in out, out.strip())
        await server._route_tool_call("control-char", {"key": "u", "session_id": a, "return_focus": False})

        # 14. clear
        out = await server._route_tool_call("clear", {"session_id": a, "return_focus": False})
        rec("clear", "cleared" in out.lower(), out.strip())

        # 15. set-appearance (title)
        out = await server._route_tool_call("set-appearance", {"session_id": a, "title": "SideshellTest"})
        ok = "title" in out.lower() or "appearance" in out.lower()
        rec("set-appearance", ok, out.strip()[:70])

        # 16. get-terminal-state (all)
        out = await server._route_tool_call("get-terminal-state", {})
        rec("get-terminal-state (all)", len(out) > 20, f"{len(out)} chars")

        # 17. get-terminal-state (one)
        out = await server._route_tool_call("get-terminal-state", {"session_id": a})
        rec("get-terminal-state (one)", a in out or "session" in out.lower(), f"{len(out)} chars")

        # 18. show-alert
        out = await server._route_tool_call("show-alert", {"title": "Hi", "message": "live test"})
        rec("show-alert", "displayed" in out.lower() or "message" in out.lower(), out.strip()[:60])

        # 19. set-color-preset
        out = await server._route_tool_call("set-color-preset", {"preset": "green", "session_id": a})
        rec("set-color-preset", "green" in out or "applied" in out.lower(), out.strip()[:60])

        # 20. list-color-presets
        out = await server._route_tool_call("list-color-presets", {})
        rec("list-color-presets", "color" in out.lower(), out.split(chr(10))[0])

        # 21. return_focus: focus A, execute in B with return_focus -> should come back to A
        await server._route_tool_call("focus", {"session_id": a})
        await asyncio.sleep(0.3)
        before = await backend.get_current_active_session_id()
        out = await server._route_tool_call(
            "execute",
            {
                "command": "echo RF",
                "session_id": b,
                "wait": True,
                "timeout": 6,
                "watch_for": "silence",
                "return_focus": True,
            },
        )
        await asyncio.sleep(0.3)
        after = await backend.get_current_active_session_id()
        rec("return_focus", "focus returned" in out.lower() or after == before, f"{before} -> {after}")

        # 22. MCP resource: sessions
        res = await read_handler(ReadResourceRequest(method="resources/read", params={"uri": "sideshell://sessions"}))
        txt = res.root.contents[0].text
        rec("resource sessions", len(txt) > 5, f"{len(txt)} chars")

        # 23. MCP resource: capabilities
        res = await read_handler(
            ReadResourceRequest(method="resources/read", params={"uri": "sideshell://capabilities"})
        )
        txt = res.root.contents[0].text
        rec("resource capabilities", '"ghostty_tmux"' in txt, "backend reported")

        # 24. resource lists
        lr = await list_res(ListResourcesRequest(method="resources/list"))
        lt = await list_tmpl(ListResourceTemplatesRequest(method="resources/templates/list"))
        rec(
            "resource lists",
            len(lr.root.resources) >= 2 and len(lt.root.resourceTemplates) >= 2,
            f"{len(lr.root.resources)} resources, {len(lt.root.resourceTemplates)} templates",
        )

        # 25. resource: session screen
        res = await read_handler(
            ReadResourceRequest(method="resources/read", params={"uri": f"sideshell://sessions/{a}/screen"})
        )
        txt = res.root.contents[0].text
        rec("resource session screen", "lines" in txt.lower(), f"{len(txt)} chars")

        # 26. close-session for all -> surfaces must really be gone afterwards
        to_close = list(created)
        closed = 0
        for s in to_close:
            out = await server._route_tool_call("close-session", {"session_id": s})
            if "Closed" in out:
                closed += 1
            await asyncio.sleep(0.2)
        created = []
        await asyncio.sleep(0.3)
        listing = await server._route_tool_call("list", {})
        still_listed = [s for s in to_close if s in listing]
        # get_session may fall back to the active surface when the exact id is
        # gone, so "gone" = not found OR resolves to a different surface.
        if to_close:
            _sess = await server.backend.get_session(to_close[-1])
            gone = _sess is None or _sess.session_id != to_close[-1]
        else:
            gone = True
        rec(
            "close-session",
            closed == len(to_close) and not still_listed and gone,
            f"closed {closed}/{len(to_close)}, still listed {still_listed}, get_session gone={gone}",
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        rec("EXCEPTION", False, str(e))
    finally:
        for s in created:
            try:
                await backend.close_session(s, force=True)
            except Exception:
                pass

    passed = sum(1 for _, ok, _ in R if ok)
    failed = sum(1 for _, ok, _ in R if not ok)
    print(f"\n{'=' * 60}\nRESULT: {passed} passed, {failed} failed")
    if failed:
        print("Failures:")
        for m, ok, d in R:
            if not ok:
                print(f"  - {m}: {d}")
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
