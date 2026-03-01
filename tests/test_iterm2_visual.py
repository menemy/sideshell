#!/usr/bin/env python3
"""Visual test for iTerm2 - TABS, SPLITS, STYLES."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sideshell_mcp.backends.iterm2_backend import ITermBackend
from sideshell_mcp.backends.base import SplitDirection


async def visual_demo():
    backend = ITermBackend()

    if not backend.is_available:
        print("ERROR: iTerm2 not available")
        return

    await backend.connect()

    print("\n=== iTerm2 VISUAL DEMO ===")
    print("Watch iTerm2!\n")
    await asyncio.sleep(2)

    created_sessions = []

    # Alert
    print("▶ Show alert...")
    await asyncio.sleep(2)
    await backend.show_alert("Demo", "iTerm2 demo starting!")
    await asyncio.sleep(3)

    # === NEW WINDOW ===
    print("\n>>> NEW WINDOW <<<")
    await asyncio.sleep(2)

    print("▶ Creating new window...")
    await asyncio.sleep(2)
    result = await backend.create_window()
    print(f"   {result}")
    # Extract session ID
    import re
    match = re.search(r'([0-9a-fA-F-]{36})', result)
    if match:
        created_sessions.append(match.group(1))
    await asyncio.sleep(3)

    # === TAB ===
    print("\n>>> NEW TAB <<<")
    await asyncio.sleep(2)

    print("▶ Creating new tab...")
    await asyncio.sleep(2)
    result = await backend.create_tab()
    print(f"   {result}")
    match = re.search(r'([0-9a-fA-F-]{36})', result)
    if match:
        created_sessions.append(match.group(1))
    await asyncio.sleep(3)

    # === SPLIT ===
    print("\n>>> SPLITS <<<")
    await asyncio.sleep(2)

    if created_sessions:
        session = created_sessions[-1]

        print("▶ HORIZONTAL split...")
        await asyncio.sleep(2)
        result = await backend.split_pane(SplitDirection.HORIZONTAL, session)
        print(f"   {result}")
        match = re.search(r'([0-9a-fA-F-]{36})', result)
        if match:
            created_sessions.append(match.group(1))
        await asyncio.sleep(3)

        print("▶ VERTICAL split...")
        await asyncio.sleep(2)
        result = await backend.split_pane(SplitDirection.VERTICAL, session)
        print(f"   {result}")
        match = re.search(r'([0-9a-fA-F-]{36})', result)
        if match:
            created_sessions.append(match.group(1))
        await asyncio.sleep(3)

    # === STYLES ===
    print("\n>>> STYLES <<<")
    await asyncio.sleep(2)

    if created_sessions:
        session = created_sessions[-1]

        print("▶ Setting appearance (title, badge, color)...")
        await asyncio.sleep(2)
        result = await backend.set_appearance(
            session_id=session,
            title="DEMO TAB",
            badge="TEST",
            color="blue"
        )
        print(f"   {result}")
        await asyncio.sleep(3)

    # === COMMAND ===
    print("\n>>> EXECUTE COMMAND <<<")
    await asyncio.sleep(2)

    if created_sessions:
        session = created_sessions[-1]

        print("▶ Running 'echo HELLO'...")
        await asyncio.sleep(2)
        await backend.execute_command("echo '=== HELLO FROM iTerm2 ==='", session)
        await asyncio.sleep(3)

    # === COLOR PRESET ===
    print("\n>>> COLOR PRESET <<<")
    await asyncio.sleep(2)

    print("▶ Listing color presets...")
    await asyncio.sleep(2)
    result = await backend.list_color_presets()
    presets = result.split('\n')[:5]  # First 5
    print(f"   Found: {', '.join(presets)}...")
    await asyncio.sleep(2)

    # Done
    await backend.show_alert("Done", "Demo complete!")
    print("\n=== DONE ===")
    print(f"Created {len(created_sessions)} sessions - NOT cleaned up")
    print("Close manually or they will stay open")


if __name__ == "__main__":
    asyncio.run(visual_demo())
