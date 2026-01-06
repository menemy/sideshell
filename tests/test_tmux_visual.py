#!/usr/bin/env python3
"""Visual test for tmux - TABS, SPLITS, STYLES."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sideshell_mcp.backends.tmux_backend import TmuxBackend
from sideshell_mcp.backends.base import SplitDirection


async def visual_demo():
    backend = TmuxBackend()
    await backend.connect()

    session = "demo"

    print(f"\n=== TMUX DEMO: TABS + SPLITS + STYLES ===")
    print("Watch Terminal.app!\n")
    await asyncio.sleep(2)

    # Alert
    print("▶ Alert...")
    await backend.show_alert("Start", "Demo starting!")
    await asyncio.sleep(3)

    # === TABS ===
    print("\n>>> TABS (look at status bar at BOTTOM) <<<")
    await asyncio.sleep(2)

    print("▶ Creating TAB 1...")
    await asyncio.sleep(2)
    result = await backend.create_tab()
    print(f"   {result}")
    await asyncio.sleep(3)

    print("▶ Running command in new tab...")
    panes_result = await backend._tmux("list-panes", "-a", "-F", "#{pane_id}")
    panes = panes_result.strip().split('\n')
    if panes:
        await backend.execute_command("echo '=== NEW TAB ==='", panes[-1])
    await asyncio.sleep(3)

    print("▶ Creating TAB 2...")
    await asyncio.sleep(2)
    await backend.create_tab()
    await asyncio.sleep(3)

    print("▶ Renaming tab to 'DEMO'...")
    await asyncio.sleep(2)
    await backend.rename_window("DEMO")
    await asyncio.sleep(3)

    await backend.show_alert("Tabs", "Check bottom status bar!")
    await asyncio.sleep(3)

    # === STYLES ===
    print("\n>>> STYLES <<<")
    await asyncio.sleep(2)

    panes_result = await backend._tmux("list-panes", "-a", "-F", "#{pane_id}")
    panes = panes_result.strip().split('\n')
    current_pane = panes[-1] if panes else None

    if current_pane:
        print("▶ Setting pane title...")
        await asyncio.sleep(2)
        await backend.set_appearance(session_id=current_pane, title="STYLED PANE")
        await asyncio.sleep(3)

        print("▶ Setting pane color (green)...")
        await asyncio.sleep(2)
        await backend.set_appearance(session_id=current_pane, color="green")
        await asyncio.sleep(3)

    # === SPLIT ===
    print("\n>>> SPLIT <<<")
    await asyncio.sleep(2)

    print("▶ HORIZONTAL split...")
    await asyncio.sleep(2)
    await backend.split_pane(SplitDirection.HORIZONTAL, current_pane)
    await asyncio.sleep(3)

    print("▶ VERTICAL split...")
    await asyncio.sleep(2)
    await backend.split_pane(SplitDirection.VERTICAL, current_pane)
    await asyncio.sleep(3)

    # Done
    await backend.show_alert("Done", "Demo complete!")
    print("\n=== DONE ===")
    print("Panes stay open - check Terminal.app!")


if __name__ == "__main__":
    asyncio.run(visual_demo())
