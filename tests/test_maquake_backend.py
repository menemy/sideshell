"""Integration tests for maquake backend.

Requires maquake to be running with socket at /tmp/maquake.sock.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sideshell_mcp.backends.maquake_backend import MaQuakeBackend
from sideshell_mcp.backends.base import ControlKey, SplitDirection


async def test_all():
    backend = MaQuakeBackend()

    # 1. is_available
    print(f"1. is_available: {backend.is_available}")
    assert backend.is_available, "maquake socket not found"

    # 2. connect
    ok = await backend.connect()
    print(f"2. connect: {ok}")
    assert ok, "Failed to connect"

    # 3. list_sessions
    sessions = await backend.list_sessions()
    print(f"3. list_sessions:\n{sessions}")

    # 4. get_current_active_session_id
    active_id = await backend.get_current_active_session_id()
    print(f"4. active_session_id: {active_id}")
    assert active_id, "No active session"

    # 5. get_session (active)
    session = await backend.get_session()
    print(f"5. get_session (active): {session}")
    assert session is not None

    # 6. get_session (by id)
    session_by_id = await backend.get_session(active_id)
    print(f"6. get_session (by id): {session_by_id}")
    assert session_by_id is not None

    # 7. get_terminal_state (all)
    state = await backend.get_terminal_state()
    print(f"7. get_terminal_state:\n{state}")

    # 8. get_terminal_state (specific)
    state_specific = await backend.get_terminal_state(active_id)
    print(f"8. get_terminal_state (specific):\n{state_specific}")

    # 9. is_ai_session
    is_ai = await backend.is_ai_session(active_id)
    print(f"9. is_ai_session: {is_ai}")

    # 10. execute_command
    exec_result = await backend.execute_command("echo maquake_test_$$")
    print(f"10. execute_command: {exec_result}")

    # 11. read_terminal
    await asyncio.sleep(0.5)
    read_result = await backend.read_terminal(lines=10)
    print(f"11. read_terminal:\n{read_result}")

    # 12. send_text (paste)
    paste_result = await backend.send_text("# pasted text")
    print(f"12. send_text: {paste_result}")

    # 13. send_control (Ctrl+C to clear pasted text)
    ctrl_result = await backend.send_control(ControlKey.C)
    print(f"13. send_control (Ctrl+C): {ctrl_result}")

    # 14. send_control (Enter)
    enter_result = await backend.send_control(ControlKey.ENTER)
    print(f"14. send_control (Enter): {enter_result}")

    # 15. send_control (unsupported key)
    unsupported = await backend.send_control(ControlKey.F1)
    print(f"15. send_control (F1, unsupported): {unsupported}")

    # 16. clear_terminal
    clear_result = await backend.clear_terminal()
    print(f"16. clear_terminal: {clear_result}")

    # 17. create_tab
    tab_result = await backend.create_tab()
    print(f"17. create_tab: {tab_result}")
    # Extract new session ID
    new_tab_id = None
    if "New tab created:" in tab_result:
        new_tab_id = tab_result.split("New tab created: ")[1].strip()

    # 18. list_sessions (should show new tab)
    sessions2 = await backend.list_sessions()
    print(f"18. list_sessions (after new tab):\n{sessions2}")

    # 19. focus_session (back to original)
    focus_result = await backend.focus_session(active_id)
    print(f"19. focus_session: {focus_result}")

    # 20. split_pane (should create tab since maquake has no splits)
    split_result = await backend.split_pane(SplitDirection.HORIZONTAL)
    print(f"20. split_pane (creates tab): {split_result}")

    # 21. create_window
    window_result = await backend.create_window()
    print(f"21. create_window: {window_result}")

    # 22. create_session
    session_result = await backend.create_session()
    print(f"22. create_session: {session_result}")

    # 23. set_appearance
    appearance_result = await backend.set_appearance(title="test")
    print(f"23. set_appearance: {appearance_result}")

    # 24. show_alert
    alert_result = await backend.show_alert("Test", "hello")
    print(f"24. show_alert: {alert_result}")

    # 25. maquake-specific: toggle/show/hide/pin/unpin
    show_result = await backend.show()
    print(f"25a. show: {show_result}")

    pin_result = await backend.pin()
    print(f"25b. pin: {pin_result}")

    unpin_result = await backend.unpin()
    print(f"25c. unpin: {unpin_result}")

    # Clean up: close the extra tabs we created
    # List all tabs and close the ones that aren't the original
    sessions3 = await backend.list_sessions()
    print(f"\n--- Cleanup ---")
    print(f"Sessions before cleanup:\n{sessions3}")

    # Close new tabs (close from the end to avoid index shifting)
    list_resp = await backend._send({"action": "list"})
    if list_resp.get("ok"):
        tabs = list_resp.get("tabs", [])
        for tab in reversed(tabs):
            if tab["session_id"] != active_id:
                close_result = await backend.close_session(tab["session_id"])
                print(f"Closed extra tab: {close_result}")

    # 26. disconnect
    await backend.disconnect()
    print(f"\n26. disconnect: done")

    print("\n=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    asyncio.run(test_all())
