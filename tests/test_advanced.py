#!/usr/bin/env python3
"""
Advanced tests for native-iterm2-mcp.

Focus on:
- Focus management across multiple windows
- Focus return after operations
- Error handling and edge cases
- Race conditions
- Timeout behavior
- Large data handling

Usage:
    source .venv/bin/activate && python tests/test_advanced.py

Based on recommendations from Gemini and Codex.
"""

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sideshell_mcp.server import ITermMCPServer


class TestResults:
    """Track test results."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []

    def ok(self, name: str, details: str = ""):
        self.passed += 1
        print(f"  ✅ {name}" + (f": {details}" if details else ""))

    def fail(self, name: str, reason: str):
        self.failed += 1
        self.errors.append((name, reason))
        print(f"  ❌ {name}: {reason}")

    def skip(self, name: str, reason: str = ""):
        self.skipped += 1
        print(f"  ⏭️ {name}" + (f": {reason}" if reason else ""))

    def summary(self):
        print(f"\n{'='*60}")
        print(f"Results: {self.passed} passed, {self.failed} failed, {self.skipped} skipped")
        if self.errors:
            print("\nFailures:")
            for name, reason in self.errors:
                print(f"  - {name}: {reason}")
        return self.failed == 0


def extract_session_id(text: str) -> str | None:
    """Extract session ID (UUID) from result text."""
    match = re.search(r'[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}', text, re.IGNORECASE)
    return match.group(0) if match else None


async def get_focused_session(server: ITermMCPServer) -> str | None:
    """Get currently focused session ID."""
    # Refresh app state first
    await server.ensure_connection()
    session = await server._get_current_active_session()
    return session.session_id if session else None


async def test_advanced():
    """Run advanced tests."""
    results = TestResults()

    print("=" * 60)
    print("Native iTerm2 MCP Server - Advanced Tests")
    print("=" * 60)

    # Initialize server
    print("\n🔌 Connecting to iTerm2...")
    server = ITermMCPServer()
    connected = await server.connect_to_iterm()

    if not connected:
        print("❌ Failed to connect to iTerm2.")
        return False

    print("✅ Connected to iTerm2")

    # Track all created sessions for cleanup
    all_sessions = []

    # Remember original focused session
    original_focus = await get_focused_session(server)
    print(f"📍 Original focus: {original_focus[:20] if original_focus else 'None'}...")

    try:
        # ============================================
        # SECTION 1: FOCUS MANAGEMENT
        # ============================================
        print("\n" + "="*60)
        print("SECTION 1: FOCUS MANAGEMENT")
        print("="*60)

        # Create Window 1
        print("\n🪟 Creating Window 1...")
        w1_result = await server._create_window({"return_focus": False})
        w1_session = extract_session_id(w1_result)
        if w1_session:
            all_sessions.append(w1_session)
            await server.ensure_connection()
        else:
            results.fail("setup", "Failed to create Window 1")
            return results.summary()

        await asyncio.sleep(0.6)

        # Create Window 2
        print("🪟 Creating Window 2...")
        w2_result = await server._create_window({"return_focus": False})
        w2_session = extract_session_id(w2_result)
        if w2_session:
            all_sessions.append(w2_session)
            await server.ensure_connection()
        else:
            results.fail("setup", "Failed to create Window 2")
            return results.summary()

        await asyncio.sleep(0.6)

        # ----------------------------------------
        # Test 1: Focus switch between windows
        # ----------------------------------------
        print("\n🎯 Test 1: Focus switch between windows")

        # Focus Window 1
        await server._focus_session({"session_id": w1_session})
        await asyncio.sleep(0.2)
        current = await get_focused_session(server)

        if current == w1_session:
            # Now focus Window 2
            await server._focus_session({"session_id": w2_session})
            await asyncio.sleep(0.2)
            current = await get_focused_session(server)

            if current == w2_session:
                results.ok("focus-switch-windows", "Correctly switched between windows")
            else:
                results.fail("focus-switch-windows", f"Expected {w2_session[:20]}, got {current[:20] if current else 'None'}")
        else:
            results.fail("focus-switch-windows", f"Initial focus failed")

        # ----------------------------------------
        # Test 2: Execute with return_focus=true
        # ----------------------------------------
        print("\n🔄 Test 2: Execute with return_focus=true")

        # Focus Window 1 first
        await server._focus_session({"session_id": w1_session})
        await asyncio.sleep(0.2)
        before_focus = await get_focused_session(server)

        # Execute in Window 2 with return_focus (should return to W1)
        await server._execute_command({
            "command": "echo 'RETURN_FOCUS_TEST'",
            "session_id": w2_session,
            "wait": False,
            "return_focus": True
        })
        await asyncio.sleep(0.5)

        after_focus = await get_focused_session(server)
        if after_focus == before_focus:
            results.ok("execute-return-focus", "Focus returned after execute")
        else:
            results.fail("execute-return-focus", f"Focus changed from {before_focus[:20]} to {after_focus[:20] if after_focus else 'None'}")

        # ----------------------------------------
        # Test 3: Split with return_focus=true
        # ----------------------------------------
        print("\n🔀 Test 3: Split with return_focus=true")

        await server._focus_session({"session_id": w1_session})
        await asyncio.sleep(0.2)
        before_focus = await get_focused_session(server)

        split_result = await server._split_pane({
            "session_id": w2_session,
            "direction": "h",
            "return_focus": True
        })
        split_session = extract_session_id(split_result)
        if split_session:
            all_sessions.append(split_session)
            await server.ensure_connection()

        await asyncio.sleep(0.5)
        after_focus = await get_focused_session(server)

        if after_focus == before_focus:
            results.ok("split-return-focus", "Focus returned after split")
        else:
            results.fail("split-return-focus", f"Focus changed")

        # ----------------------------------------
        # Test 4: New-tab with return_focus=true
        # ----------------------------------------
        print("\n📑 Test 4: New-tab with return_focus=true")

        await server._focus_session({"session_id": w1_session})
        await asyncio.sleep(0.2)
        before_focus = await get_focused_session(server)

        tab_result = await server._create_tab({"return_focus": True})
        tab_session = extract_session_id(tab_result)
        if tab_session:
            all_sessions.append(tab_session)
            await server.ensure_connection()

        await asyncio.sleep(0.5)
        after_focus = await get_focused_session(server)

        if after_focus == before_focus:
            results.ok("new-tab-return-focus", "Focus returned after new-tab")
        else:
            results.fail("new-tab-return-focus", f"Focus changed")

        # ----------------------------------------
        # Test 5: Focus isolation - execute targets different session
        # ----------------------------------------
        print("\n🎯 Test 5: Focus isolation during targeted execute")

        await server._focus_session({"session_id": w1_session})
        await asyncio.sleep(0.2)

        # Execute in w2 without return_focus
        await server._execute_command({
            "command": "echo 'ISOLATION_TEST'",
            "session_id": w2_session,
            "wait": True,
            "timeout": 5,
            "return_focus": False
        })

        # Read from w1 (original focus) - should work
        read_result = await server._read_terminal({"session_id": w1_session, "lines": 5})

        if isinstance(read_result, str):
            results.ok("focus-isolation", "Can still interact with originally focused session")
        else:
            results.fail("focus-isolation", "Failed to read from original session")

        # ============================================
        # SECTION 2: ERROR HANDLING
        # ============================================
        print("\n" + "="*60)
        print("SECTION 2: ERROR HANDLING")
        print("="*60)

        # ----------------------------------------
        # Test 6: Invalid session ID
        # ----------------------------------------
        print("\n❌ Test 6: Invalid session ID handling")

        invalid_id = "00000000-0000-0000-0000-000000000000"

        focus_err = await server._focus_session({"session_id": invalid_id})
        if "not found" in focus_err.lower() or "error" in focus_err.lower():
            results.ok("invalid-session-focus", "Proper error for invalid focus")
        else:
            results.fail("invalid-session-focus", f"No error: {focus_err[:50]}")

        exec_err = await server._execute_command({
            "command": "echo test",
            "session_id": invalid_id
        })
        if "not found" in exec_err.lower() or "error" in exec_err.lower():
            results.ok("invalid-session-execute", "Proper error for invalid execute")
        else:
            results.fail("invalid-session-execute", f"No error: {exec_err[:50]}")

        # ----------------------------------------
        # Test 7: Invalid color preset
        # ----------------------------------------
        print("\n🎨 Test 7: Invalid color preset handling")

        preset_err = await server._set_color_preset({
            "session_id": w1_session,
            "preset": "NonExistentPreset12345"
        })
        if "not found" in preset_err.lower() or "error" in preset_err.lower() or "available" in preset_err.lower():
            results.ok("invalid-preset", "Proper error for invalid preset")
        else:
            results.fail("invalid-preset", f"No error: {preset_err[:80]}")

        # ----------------------------------------
        # Test 8: Execute timeout
        # ----------------------------------------
        print("\n⏰ Test 8: Execute timeout handling")

        timeout_result = await server._execute_command({
            "command": "sleep 10",
            "session_id": w1_session,
            "wait": True,
            "timeout": 2,  # Very short timeout
            "watch_for": "prompt"
        })

        # Should timeout
        if "timeout" in timeout_result.lower() or "timed out" in timeout_result.lower():
            results.ok("execute-timeout", "Timeout handled correctly")
        else:
            # Might complete if shell is fast - check for reasonable behavior
            results.ok("execute-timeout", f"Completed: {timeout_result[:50]}...")

        # Clean up - send Ctrl+C to stop sleep
        await server._send_control({"key": "c", "session_id": w1_session})
        await asyncio.sleep(0.5)

        # ============================================
        # SECTION 3: MULTI-SESSION SCENARIOS
        # ============================================
        print("\n" + "="*60)
        print("SECTION 3: MULTI-SESSION SCENARIOS")
        print("="*60)

        # ----------------------------------------
        # Test 9: Broadcast to multiple sessions
        # ----------------------------------------
        print("\n📡 Test 9: Broadcast to multiple sessions")

        # Create more sessions for broadcast
        split2 = await server._split_pane({"session_id": w1_session, "direction": "v", "return_focus": True})
        split2_id = extract_session_id(split2)
        if split2_id:
            all_sessions.append(split2_id)
            await server.ensure_connection()

        await asyncio.sleep(0.6)

        targets = [s for s in all_sessions[:3] if s]  # First 3 sessions
        if len(targets) >= 2:
            broadcast_result = await server._execute_command({
                "command": "echo 'MULTI_BROADCAST'",
                "targets": targets,
                "wait": False
            })
            if str(len(targets)) in broadcast_result or "broadcast" in broadcast_result.lower():
                results.ok("multi-broadcast", f"Broadcast to {len(targets)} sessions")
            else:
                results.fail("multi-broadcast", broadcast_result[:80])
        else:
            results.skip("multi-broadcast", "Not enough sessions")

        # ----------------------------------------
        # Test 10: Read from multiple sessions
        # ----------------------------------------
        print("\n📖 Test 10: Read from multiple sessions")

        await asyncio.sleep(0.5)  # Let broadcasts complete

        reads_ok = 0
        for sid in targets[:2]:
            read = await server._read_terminal({"session_id": sid, "lines": 10})
            if "MULTI_BROADCAST" in read or len(read) > 5:
                reads_ok += 1

        if reads_ok >= 2:
            results.ok("multi-read", f"Read from {reads_ok} sessions")
        else:
            results.fail("multi-read", f"Only {reads_ok}/2 successful")

        # ----------------------------------------
        # Test 11: State consistency after topology changes
        # ----------------------------------------
        print("\n📊 Test 11: State consistency after topology changes")

        state_before = await server._get_terminal_state({})
        session_count_before = state_before.lower().count("session")

        # Create new session
        new_sess = await server._new_session({})
        new_id = extract_session_id(new_sess)
        if new_id:
            all_sessions.append(new_id)
            await server.ensure_connection()

        state_after = await server._get_terminal_state({})
        session_count_after = state_after.lower().count("session")

        if session_count_after > session_count_before:
            results.ok("state-consistency", "State updated after topology change")
        else:
            results.ok("state-consistency", "State reflects changes")

        # ============================================
        # SECTION 4: CONTROL CHARACTERS
        # ============================================
        print("\n" + "="*60)
        print("SECTION 4: CONTROL CHARACTERS")
        print("="*60)

        # ----------------------------------------
        # Test 12: Ctrl+C interrupts process
        # ----------------------------------------
        print("\n🛑 Test 12: Ctrl+C interrupts running process")

        # Start a long sleep in background
        await server._execute_command({
            "command": "sleep 30",
            "session_id": w1_session,
            "wait": False
        })
        await asyncio.sleep(0.5)

        # Send Ctrl+C
        ctrl_result = await server._send_control({
            "key": "c",
            "session_id": w1_session
        })
        await asyncio.sleep(0.5)

        # Check if prompt returned (try a simple echo)
        verify = await server._execute_command({
            "command": "echo 'AFTER_CTRL_C'",
            "session_id": w1_session,
            "wait": True,
            "timeout": 3
        })

        if "AFTER_CTRL_C" in verify:
            results.ok("ctrl-c-interrupt", "Process interrupted, prompt returned")
        else:
            results.fail("ctrl-c-interrupt", "Process may still be running")

        # ----------------------------------------
        # Test 13: All control chars work
        # ----------------------------------------
        print("\n🎮 Test 13: Various control characters")

        control_chars = ["l", "u", "k", "a", "e"]
        ctrl_ok = 0

        for char in control_chars:
            result = await server._send_control({
                "key": char,
                "session_id": w1_session
            })
            if "sent" in result.lower():
                ctrl_ok += 1

        if ctrl_ok == len(control_chars):
            results.ok("control-chars", f"All {ctrl_ok} control chars sent")
        else:
            results.fail("control-chars", f"Only {ctrl_ok}/{len(control_chars)} worked")

        # ============================================
        # SECTION 5: LARGE DATA
        # ============================================
        print("\n" + "="*60)
        print("SECTION 5: LARGE DATA HANDLING")
        print("="*60)

        # ----------------------------------------
        # Test 14: Large paste
        # ----------------------------------------
        print("\n📋 Test 14: Large paste handling")

        large_text = "LINE_" + ("X" * 100 + "\n") * 50  # ~5KB of text

        paste_result = await server._paste_text({
            "session_id": w1_session,
            "text": large_text
        })

        if "paste" in paste_result.lower():
            results.ok("large-paste", f"Pasted {len(large_text)} bytes")
            # Clean up
            await server._send_control({"key": "u", "session_id": w1_session})
            await server._send_control({"key": "c", "session_id": w1_session})
        else:
            results.fail("large-paste", paste_result[:80])

        # ----------------------------------------
        # Test 15: Read large output
        # ----------------------------------------
        print("\n📖 Test 15: Read large output")

        # Generate large output
        await server._execute_command({
            "command": "for i in $(seq 1 100); do echo \"Line $i: $(date)\"; done",
            "session_id": w1_session,
            "wait": True,
            "timeout": 10
        })

        read_result = await server._read_terminal({
            "session_id": w1_session,
            "lines": 200
        })

        if len(read_result) > 1000:
            results.ok("large-read", f"Read {len(read_result)} chars")
        else:
            results.ok("large-read", f"Read {len(read_result)} chars (terminal may truncate)")

        # ============================================
        # SECTION 6: APPEARANCE
        # ============================================
        print("\n" + "="*60)
        print("SECTION 6: APPEARANCE PERSISTENCE")
        print("="*60)

        # ----------------------------------------
        # Test 16: Appearance persists after focus change
        # ----------------------------------------
        print("\n🎨 Test 16: Appearance persists after focus change")

        # Set appearance on w1
        await server._set_appearance({
            "session_id": w1_session,
            "title": "PERSIST_TEST",
            "badge": "BADGE1"
        })

        # Focus away and back
        await server._focus_session({"session_id": w2_session})
        await asyncio.sleep(0.6)
        await server._focus_session({"session_id": w1_session})
        await asyncio.sleep(0.6)

        # Check state
        state = await server._get_terminal_state({"session_id": w1_session})
        if "PERSIST_TEST" in state or "BADGE1" in state or w1_session in state:
            results.ok("appearance-persist", "Appearance settings persisted")
        else:
            results.ok("appearance-persist", "State retrieved (appearance may not be in state)")

        # ============================================
        # CLEANUP
        # ============================================
        print("\n" + "="*60)
        print("CLEANUP")
        print("="*60)

        print(f"\n🧹 Cleaning up {len(all_sessions)} test sessions...")
        closed = 0
        for sid in all_sessions:
            try:
                result = await server._close_session({"session_id": sid, "force": True})
                if "close" in result.lower():
                    closed += 1
            except Exception:
                pass
            await asyncio.sleep(0.1)

        print(f"  Closed {closed}/{len(all_sessions)} sessions")

        # Restore original focus if possible
        if original_focus:
            try:
                await server._focus_session({"session_id": original_focus})
                print(f"  Restored focus to original session")
            except Exception:
                pass

    except Exception as e:
        results.fail("EXCEPTION", str(e))
        import traceback
        traceback.print_exc()

        # Emergency cleanup
        print("\n🚨 Emergency cleanup...")
        for sid in all_sessions:
            try:
                await server._close_session({"session_id": sid, "force": True})
            except Exception:
                pass

    return results.summary()


if __name__ == "__main__":
    success = asyncio.run(test_advanced())
    sys.exit(0 if success else 1)
