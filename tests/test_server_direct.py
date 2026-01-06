#!/usr/bin/env python3
"""
Direct server tests for vibe-sideshell.

Tests run in an isolated environment that gets cleaned up after.

Usage:
    uv run python tests/test_server_direct.py [backend]

    backend: iterm2, tmux (default: iterm2)

Requirements:
    - iTerm2 running with Python API enabled, OR
    - tmux running

Test Coverage:
    - All MCP tools (execute, read, split, new-window, etc.)
    - return_focus functionality
    - wait modes (silence, prompt, output)
"""

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sideshell_mcp.server import VibeSideshellServer
from sideshell_mcp.backends import BackendType, get_backend


class TestResults:
    """Track test results."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, name: str, details: str = ""):
        self.passed += 1
        print(f"  ✓ {name}" + (f": {details}" if details else ""))

    def fail(self, name: str, reason: str):
        self.failed += 1
        self.errors.append((name, reason))
        print(f"  ✗ {name}: {reason}")

    def summary(self):
        print(f"\n{'='*50}")
        print(f"Results: {self.passed} passed, {self.failed} failed")
        if self.errors:
            print("\nFailures:")
            for name, reason in self.errors:
                print(f"  - {name}: {reason}")
        return self.failed == 0


def extract_session_id(text: str) -> str | None:
    """Extract session ID from result text."""
    # iTerm2 UUID format
    match = re.search(r'[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}', text, re.IGNORECASE)
    if match:
        return match.group(0)
    # tmux pane format %N
    match = re.search(r'%\d+', text)
    if match:
        return match.group(0)
    return None


async def test_all(backend_type: BackendType):
    """Run all tests."""
    results = TestResults()

    print("=" * 50)
    print(f"vibe-sideshell Server Tests - {backend_type.value}")
    print("=" * 50)

    # Initialize backend and server
    print(f"\n Connecting to {backend_type.value}...")
    backend = get_backend(backend_type)

    if not backend.is_available:
        print(f"ERROR: {backend_type.value} not available")
        return False

    connected = await backend.connect()
    if not connected:
        print(f"ERROR: Failed to connect to {backend_type.value}")
        return False

    server = VibeSideshellServer(backend)
    print(f"OK Connected to {backend_type.value}")

    # Track sessions to close
    test_sessions = []
    main_session_id = None

    try:
        # ============================================
        # TEST 1: new-window / new-tab
        # ============================================
        print("\n Test 1: create test environment")
        result = await server._route_tool_call("new-window", {})
        main_session_id = extract_session_id(result)

        if main_session_id:
            test_sessions.append(main_session_id)
            results.ok("new-window", f"Created: {main_session_id[:20]}...")
        else:
            results.fail("new-window", f"No session ID: {result[:100]}")
            return results.summary()

        await asyncio.sleep(0.5)

        # ============================================
        # TEST 2: list
        # ============================================
        print("\n Test 2: list")
        list_result = await server._route_tool_call("list", {})

        if main_session_id in list_result or "pane" in list_result.lower():
            results.ok("list", "Found sessions")
        else:
            results.fail("list", "No sessions in list")

        # ============================================
        # TEST 3: execute fire-and-forget
        # ============================================
        print("\n Test 3: execute (fire-and-forget)")
        exec_result = await server._route_tool_call("execute", {
            "command": "echo 'TEST_MARKER'",
            "session_id": main_session_id,
            "wait": False
        })
        if "sent" in exec_result.lower():
            results.ok("execute fire-and-forget")
        else:
            results.fail("execute fire-and-forget", exec_result[:100])

        await asyncio.sleep(0.5)

        # ============================================
        # TEST 4: execute wait=true
        # ============================================
        print("\n Test 4: execute wait=true")
        exec_wait = await server._route_tool_call("execute", {
            "command": "echo 'WAIT_MARKER'",
            "session_id": main_session_id,
            "wait": True,
            "timeout": 10,
            "watch_for": "silence"
        })
        if "Completed" in exec_wait or "WAIT_MARKER" in exec_wait:
            results.ok("execute wait=true", "Output captured")
        else:
            results.fail("execute wait=true", f"No output: {exec_wait[:100]}")

        await asyncio.sleep(0.5)

        # ============================================
        # TEST 5: read
        # ============================================
        print("\n Test 5: read")
        read_result = await server._route_tool_call("read", {
            "session_id": main_session_id,
            "lines": 20
        })
        if len(read_result) > 10:
            results.ok("read", f"{len(read_result)} chars")
        else:
            results.fail("read", "Empty content")

        # ============================================
        # TEST 6: control-char
        # ============================================
        print("\n Test 6: control-char")
        ctrl_result = await server._route_tool_call("control-char", {
            "key": "l",
            "session_id": main_session_id
        })
        if "sent" in ctrl_result.lower() or "Ctrl" in ctrl_result:
            results.ok("control-char")
        else:
            results.fail("control-char", ctrl_result[:100])

        await asyncio.sleep(0.5)

        # ============================================
        # TEST 7: split
        # ============================================
        print("\n Test 7: split")
        split_result = await server._route_tool_call("split", {
            "session_id": main_session_id,
            "direction": "h"
        })
        split_session = extract_session_id(split_result)
        if split_session:
            test_sessions.append(split_session)
            results.ok("split", f"New pane: {split_session}")
        else:
            results.fail("split", split_result[:100])

        await asyncio.sleep(0.5)

        # ============================================
        # TEST 8: return_focus (execute)
        # ============================================
        print("\n Test 8: return_focus (execute)")

        if split_session:
            # Focus main session first
            await server._route_tool_call("focus", {"session_id": main_session_id})
            await asyncio.sleep(0.3)

            current_before = await backend.get_current_active_session_id()

            # Execute in split session with return_focus
            exec_rf = await server._route_tool_call("execute", {
                "command": "echo 'RETURN_FOCUS_TEST'",
                "session_id": split_session,
                "wait": True,
                "timeout": 5,
                "return_focus": True
            })

            await asyncio.sleep(0.5)
            current_after = await backend.get_current_active_session_id()

            if "focus returned" in exec_rf.lower() or current_after == current_before:
                results.ok("return_focus execute", "Focus returned")
            else:
                results.fail("return_focus execute", f"{current_before} -> {current_after}")
        else:
            results.fail("return_focus execute", "No split session")

        # ============================================
        # TEST 9: return_focus (split)
        # ============================================
        print("\n Test 9: return_focus (split)")

        current_before = await backend.get_current_active_session_id()

        split_rf = await server._route_tool_call("split", {
            "session_id": main_session_id,
            "direction": "v",
            "return_focus": True
        })
        new_split = extract_session_id(split_rf)
        if new_split:
            test_sessions.append(new_split)

        await asyncio.sleep(0.5)
        current_after = await backend.get_current_active_session_id()

        if "focus returned" in split_rf.lower() or current_after == current_before:
            results.ok("return_focus split", "Focus returned")
        else:
            results.fail("return_focus split", f"{current_before} -> {current_after}")

        # ============================================
        # TEST 10: focus
        # ============================================
        print("\n Test 10: focus")
        focus_result = await server._route_tool_call("focus", {
            "session_id": main_session_id
        })
        if "focus" in focus_result.lower():
            results.ok("focus")
        else:
            results.fail("focus", focus_result[:100])

        await asyncio.sleep(0.3)

        # ============================================
        # TEST 11: clear
        # ============================================
        print("\n Test 11: clear")
        clear = await server._route_tool_call("clear", {
            "session_id": main_session_id
        })
        if "clear" in clear.lower():
            results.ok("clear")
        else:
            results.fail("clear", clear[:100])

        # ============================================
        # TEST 12: paste
        # ============================================
        print("\n Test 12: paste")
        paste = await server._route_tool_call("paste", {
            "session_id": main_session_id,
            "text": "echo 'PASTE_TEST'"
        })
        if "paste" in paste.lower() or "characters" in paste.lower():
            results.ok("paste")
            await server._route_tool_call("control-char", {"key": "u", "session_id": main_session_id})
        else:
            results.fail("paste", paste[:100])

        # ============================================
        # TEST 13: get-terminal-state
        # ============================================
        print("\n Test 13: get-terminal-state")
        state = await server._route_tool_call("get-terminal-state", {})
        if len(state) > 20:
            results.ok("get-terminal-state")
        else:
            results.fail("get-terminal-state", state[:100])

        # ============================================
        # TEST 14: MCP Resources - list_resources
        # ============================================
        print("\n Test 14: MCP Resources - list_resources")
        from mcp.types import ListResourcesRequest, ListResourceTemplatesRequest, ReadResourceRequest

        list_res_handler = server.server.request_handlers[ListResourcesRequest]
        res_result = await list_res_handler(ListResourcesRequest(method="resources/list"))
        resources = res_result.root.resources
        if len(resources) >= 2:
            resource_uris = [str(r.uri) for r in resources]
            if "sideshell://sessions" in resource_uris and "sideshell://capabilities" in resource_uris:
                results.ok("list_resources", f"{len(resources)} resources")
            else:
                results.fail("list_resources", f"Missing resources: {resource_uris}")
        else:
            results.fail("list_resources", f"Expected 2+ resources, got {len(resources)}")

        # ============================================
        # TEST 15: MCP Resources - list_resource_templates
        # ============================================
        print("\n Test 15: MCP Resources - list_resource_templates")
        list_templates_handler = server.server.request_handlers[ListResourceTemplatesRequest]
        tmpl_result = await list_templates_handler(
            ListResourceTemplatesRequest(method="resources/templates/list")
        )
        templates = tmpl_result.root.resourceTemplates
        if len(templates) >= 2:
            template_uris = [t.uriTemplate for t in templates]
            has_session = any("{session_id}" in u for u in template_uris)
            has_screen = any("screen" in u for u in template_uris)
            if has_session and has_screen:
                results.ok("list_resource_templates", f"{len(templates)} templates")
            else:
                results.fail("list_resource_templates", f"Missing templates: {template_uris}")
        else:
            results.fail("list_resource_templates", f"Expected 2+ templates, got {len(templates)}")

        # ============================================
        # TEST 16: MCP Resources - read sideshell://sessions
        # ============================================
        print("\n Test 16: read resource - sessions")
        read_handler = server.server.request_handlers[ReadResourceRequest]
        read_result = await read_handler(
            ReadResourceRequest(method="resources/read", params={"uri": "sideshell://sessions"})
        )
        sessions_content = read_result.root.contents[0].text if read_result.root.contents else ""
        if len(sessions_content) > 10:
            results.ok("read sessions", f"{len(sessions_content)} chars")
        else:
            results.fail("read sessions", "Empty content")

        # ============================================
        # TEST 17: MCP Resources - read sideshell://capabilities
        # ============================================
        print("\n Test 17: read resource - capabilities")
        read_result = await read_handler(
            ReadResourceRequest(method="resources/read", params={"uri": "sideshell://capabilities"})
        )
        caps_content = read_result.root.contents[0].text if read_result.root.contents else ""
        if "backend" in caps_content and "features" in caps_content:
            results.ok("read capabilities")
        else:
            results.fail("read capabilities", caps_content[:100])

        # ============================================
        # TEST 18: MCP Resources - read sideshell://sessions/{id}
        # ============================================
        print("\n Test 18: read resource - session details")
        if main_session_id:
            read_result = await read_handler(
                ReadResourceRequest(
                    method="resources/read",
                    params={"uri": f"sideshell://sessions/{main_session_id}"}
                )
            )
            session_detail = read_result.root.contents[0].text if read_result.root.contents else ""
            if len(session_detail) > 5:
                results.ok("read session details", f"{len(session_detail)} chars")
            else:
                results.fail("read session details", "Empty content")
        else:
            results.fail("read session details", "No main_session_id")

        # ============================================
        # TEST 19: MCP Resources - read sideshell://sessions/{id}/screen
        # ============================================
        print("\n Test 19: read resource - session screen")
        if main_session_id:
            read_result = await read_handler(
                ReadResourceRequest(
                    method="resources/read",
                    params={"uri": f"sideshell://sessions/{main_session_id}/screen"}
                )
            )
            screen_content = read_result.root.contents[0].text if read_result.root.contents else ""
            if len(screen_content) > 0:
                results.ok("read session screen", f"{len(screen_content)} chars")
            else:
                results.fail("read session screen", "Empty screen")
        else:
            results.fail("read session screen", "No main_session_id")

        # ============================================
        # TEST 20: close-session (cleanup)
        # ============================================
        print("\n Test 20: close-session (cleanup)")
        closed = 0
        for sid in test_sessions:
            close_result = await server._route_tool_call("close-session", {
                "session_id": sid
            })
            if "close" in close_result.lower():
                closed += 1
            await asyncio.sleep(0.2)

        if closed >= len(test_sessions) - 1:  # Allow 1 miss due to window close
            results.ok("close-session", f"Closed {closed} sessions")
        else:
            results.fail("close-session", f"Closed {closed}/{len(test_sessions)}")

    except Exception as e:
        results.fail("EXCEPTION", str(e))
        import traceback
        traceback.print_exc()
    finally:
        # Emergency cleanup
        for sid in test_sessions:
            try:
                await backend.close_session(sid, force=True)
            except Exception:
                pass

    return results.summary()


if __name__ == "__main__":
    # Parse backend from args
    backend_name = sys.argv[1] if len(sys.argv) > 1 else "iterm2"

    backend_map = {
        "iterm2": BackendType.ITERM2,
        "tmux": BackendType.TMUX,
        "wezterm": BackendType.WEZTERM,
        "kitty": BackendType.KITTY,
    }

    if backend_name not in backend_map:
        print(f"Unknown backend: {backend_name}")
        print(f"Available: {', '.join(backend_map.keys())}")
        sys.exit(1)

    success = asyncio.run(test_all(backend_map[backend_name]))
    sys.exit(0 if success else 1)
