#!/usr/bin/env python3
"""Visual test for WezTerm - TABS, SPLITS, STYLES."""

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sideshell_mcp.backends.wezterm_backend import WezTermBackend
from sideshell_mcp.backends.base import SplitDirection


async def visual_demo():
    backend = WezTermBackend()

    if not backend.is_available:
        print("ERROR: WezTerm not available")
        return

    connected = await backend.connect()
    if not connected:
        print("ERROR: Failed to connect to WezTerm")
        return

    print("\n=== WezTerm VISUAL DEMO ===")
    print("Watch WezTerm!\n")
    await asyncio.sleep(2)

    created_panes = []

    def extract_pane_id(result):
        match = re.search(r'pane[_\s]*(?:id)?[:\s]*(\d+)', result.lower())
        if match:
            return match.group(1)
        match = re.search(r':\s*(\d+)$', result)
        if match:
            return match.group(1)
        match = re.search(r'\b(\d+)\b', result)
        return match.group(1) if match else None

    # === NEW WINDOW ===
    print("\n>>> NEW WINDOW <<<")
    await asyncio.sleep(2)

    print("▶ Creating new window...")
    await asyncio.sleep(2)
    result = await backend.create_window()
    print(f"   {result}")
    pane_id = extract_pane_id(result)
    if pane_id:
        created_panes.append(pane_id)
    await asyncio.sleep(3)

    # === TAB ===
    print("\n>>> NEW TAB <<<")
    await asyncio.sleep(2)

    print("▶ Creating new tab...")
    await asyncio.sleep(2)
    result = await backend.create_tab()
    print(f"   {result}")
    pane_id = extract_pane_id(result)
    if pane_id:
        created_panes.append(pane_id)
    await asyncio.sleep(3)

    # === SPLIT ===
    print("\n>>> SPLITS <<<")
    await asyncio.sleep(2)

    if created_panes:
        pane = created_panes[-1]

        print("▶ HORIZONTAL split...")
        await asyncio.sleep(2)
        result = await backend.split_pane(SplitDirection.HORIZONTAL, pane)
        print(f"   {result}")
        new_pane = extract_pane_id(result)
        if new_pane:
            created_panes.append(new_pane)
        await asyncio.sleep(3)

        print("▶ VERTICAL split...")
        await asyncio.sleep(2)
        result = await backend.split_pane(SplitDirection.VERTICAL, pane)
        print(f"   {result}")
        new_pane = extract_pane_id(result)
        if new_pane:
            created_panes.append(new_pane)
        await asyncio.sleep(3)

    # === STYLES ===
    print("\n>>> STYLES <<<")
    await asyncio.sleep(2)

    print("▶ Setting tab title...")
    await asyncio.sleep(2)
    result = await backend.set_appearance(title="DEMO TAB")
    print(f"   {result}")
    await asyncio.sleep(3)

    print("▶ Setting window title...")
    await asyncio.sleep(2)
    result = await backend.set_window_title("WezTerm DEMO")
    print(f"   {result}")
    await asyncio.sleep(3)

    # === COMMAND ===
    print("\n>>> EXECUTE COMMAND <<<")
    await asyncio.sleep(2)

    if created_panes:
        pane = created_panes[-1]

        print("▶ Running 'echo HELLO'...")
        await asyncio.sleep(2)
        await backend.execute_command("echo '=== HELLO FROM WezTerm ==='", pane)
        await asyncio.sleep(3)

    # Done
    print("\n=== DONE ===")
    print(f"Created {len(created_panes)} panes - NOT cleaned up")


if __name__ == "__main__":
    asyncio.run(visual_demo())
