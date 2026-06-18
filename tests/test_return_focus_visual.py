#!/usr/bin/env python3
"""
Visual test for return_focus functionality.

Watch the terminal - you should see focus jumping between panes and returning.

Usage:
    uv run python tests/test_return_focus_visual.py [backend]

    backend: iterm2, tmux (default: iterm2)
"""

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sideshell_mcp.backends import BackendType, get_backend
from sideshell_mcp.server import VibeSideshellServer


def extract_session_id(text: str) -> str | None:
    """Extract session ID from result text."""
    match = re.search(r"[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}", text, re.IGNORECASE)
    if match:
        return match.group(0)
    match = re.search(r"%\d+", text)
    if match:
        return match.group(0)
    return None


async def visual_test(backend_type: BackendType):
    """Run visual return_focus test."""

    print("=" * 50)
    print(f"VISUAL TEST: return_focus - {backend_type.value}")
    print("=" * 50)
    print("\nWatch the terminal windows!")
    print("You should see focus jump between panes and return.\n")

    backend = get_backend(backend_type)

    if not backend.is_available:
        print(f"ERROR: {backend_type.value} not available")
        return

    await backend.connect()
    server = VibeSideshellServer(backend)

    test_sessions = []

    try:
        # Create test window
        print(">>> Creating test window...")
        await asyncio.sleep(1)

        result = await server._route_tool_call("new-window", {})
        main_id = extract_session_id(result)
        if main_id:
            test_sessions.append(main_id)
            print(f"    Created main: {main_id}")

        await asyncio.sleep(1)

        # Label the main pane
        await server._route_tool_call("execute", {"command": "echo '=== MAIN PANE ==='", "session_id": main_id})

        await asyncio.sleep(1)

        # Create split
        print("\n>>> Creating split pane...")
        await asyncio.sleep(1)

        split_result = await server._route_tool_call(
            "split",
            {
                "session_id": main_id,
                "direction": "h",
                "return_focus": False,  # Don't return focus
            },
        )
        split_id = extract_session_id(split_result)
        if split_id:
            test_sessions.append(split_id)
            print(f"    Created split: {split_id}")

        await asyncio.sleep(1)

        # Label the split pane
        await server._route_tool_call("execute", {"command": "echo '=== SPLIT PANE ==='", "session_id": split_id})

        await asyncio.sleep(1)

        # Focus main pane
        print("\n>>> Focusing main pane...")
        await server._route_tool_call("focus", {"session_id": main_id})
        await asyncio.sleep(1)

        # TEST 1: Execute with return_focus
        print("\n" + "=" * 50)
        print("TEST 1: Execute in SPLIT with return_focus=True")
        print("=" * 50)
        print("Watch: focus will jump to SPLIT, run command, then return to MAIN")
        await asyncio.sleep(2)

        result = await server._route_tool_call(
            "execute",
            {
                "command": "echo 'Running in SPLIT pane...' && sleep 1 && echo 'Done!'",
                "session_id": split_id,
                "wait": True,
                "timeout": 10,
                "return_focus": True,
            },
        )

        print(f"\n    Result: {'Focus returned!' if 'focus returned' in result.lower() else result[:50]}")
        await asyncio.sleep(2)

        # TEST 2: Split with return_focus
        print("\n" + "=" * 50)
        print("TEST 2: Create new split with return_focus=True")
        print("=" * 50)
        print("Watch: new pane will appear, then focus returns to current pane")
        await asyncio.sleep(2)

        result = await server._route_tool_call("split", {"session_id": main_id, "direction": "v", "return_focus": True})
        new_split = extract_session_id(result)
        if new_split:
            test_sessions.append(new_split)

        print(f"\n    Result: {'Focus returned!' if 'focus returned' in result.lower() else result[:50]}")
        await asyncio.sleep(2)

        # TEST 3: Execute WITHOUT return_focus
        print("\n" + "=" * 50)
        print("TEST 3: Execute in SPLIT with return_focus=False")
        print("=" * 50)
        print("Watch: focus will stay in SPLIT pane after command")
        await asyncio.sleep(2)

        result = await server._route_tool_call(
            "execute",
            {
                "command": "echo 'Focus should STAY here'",
                "session_id": split_id,
                "wait": True,
                "timeout": 10,
                "return_focus": False,
            },
        )

        print("\n    Result: Focus stayed in split pane")
        await asyncio.sleep(2)

        print("\n" + "=" * 50)
        print("VISUAL TEST COMPLETE")
        print("=" * 50)
        print("\nCleaning up test sessions...")

    finally:
        # Cleanup
        for sid in test_sessions:
            try:
                await backend.close_session(sid, force=True)
                print(f"    Closed: {sid}")
            except Exception:
                pass

        print("\nDone!")


if __name__ == "__main__":
    backend_name = sys.argv[1] if len(sys.argv) > 1 else "iterm2"

    backend_map = {
        "iterm2": BackendType.ITERM2,
        "tmux": BackendType.TMUX,
    }

    if backend_name not in backend_map:
        print(f"Unknown backend: {backend_name}")
        sys.exit(1)

    asyncio.run(visual_test(backend_map[backend_name]))
