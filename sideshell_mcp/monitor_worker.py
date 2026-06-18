#!/usr/bin/env python3
"""Standalone monitor worker - runs ScreenStreamer in isolated process."""

import asyncio
import json
import sys

import iterm2


async def monitor_output(session_id: str, timeout: float) -> dict:
    """Monitor session for output changes."""
    connection = await iterm2.Connection.async_create()
    app = await iterm2.async_get_app(connection)

    # Find session
    target_session = None
    for window in app.windows:
        for tab in window.tabs:
            for s in tab.sessions:
                if s.session_id == session_id:
                    target_session = s
                    break

    if not target_session:
        return {"error": f"Session {session_id} not found"}

    loop = asyncio.get_running_loop()
    start = loop.time()

    initial_contents = await target_session.async_get_screen_contents()
    initial_lines = [
        initial_contents.line(i).string if initial_contents.line(i) else ""
        for i in range(initial_contents.number_of_lines)
    ]
    initial_hash = hash(tuple(initial_lines))

    async with target_session.get_screen_streamer(want_contents=True) as streamer:
        while True:
            now = loop.time()
            if (now - start) >= timeout:
                break
            try:
                remaining = timeout - (now - start)
                new_contents = await asyncio.wait_for(streamer.async_get(), timeout=min(remaining, 1.0))
                if not new_contents:
                    continue

                current_lines = [
                    new_contents.line(i).string if new_contents.line(i) else ""
                    for i in range(new_contents.number_of_lines)
                ]
                current_hash = hash(tuple(current_lines))

                if current_hash != initial_hash:
                    new_content = [line for line in current_lines if line.strip() and line not in initial_lines]
                    elapsed = loop.time() - start
                    result = {
                        "success": True,
                        "elapsed": elapsed,
                        "new_content": new_content[-20:] if new_content else [],
                    }
                    print(json.dumps(result), flush=True)
                    import os

                    os._exit(0)
            except TimeoutError:
                continue

    return {"timeout": True, "elapsed": timeout}


async def monitor_silence(session_id: str, timeout: float, threshold: float = 2.0) -> dict:
    """Monitor session for silence."""
    connection = await iterm2.Connection.async_create()
    app = await iterm2.async_get_app(connection)

    # Find session
    target_session = None
    for window in app.windows:
        for tab in window.tabs:
            for s in tab.sessions:
                if s.session_id == session_id:
                    target_session = s
                    break

    if not target_session:
        return {"error": f"Session {session_id} not found"}

    loop = asyncio.get_running_loop()
    start = loop.time()

    initial_contents = await target_session.async_get_screen_contents()
    initial_lines = [
        initial_contents.line(i).string if initial_contents.line(i) else ""
        for i in range(initial_contents.number_of_lines)
    ]
    initial_hash = hash(tuple(initial_lines))
    last_change = loop.time()

    async with target_session.get_screen_streamer(want_contents=True) as streamer:
        while True:
            now = loop.time()
            if (now - start) >= timeout:
                break
            try:
                remaining = timeout - (now - start)
                new_contents = await asyncio.wait_for(streamer.async_get(), timeout=min(remaining, threshold))
                if new_contents:
                    current_lines = [
                        new_contents.line(i).string if new_contents.line(i) else ""
                        for i in range(new_contents.number_of_lines)
                    ]
                    current_hash = hash(tuple(current_lines))
                    if current_hash != initial_hash:
                        initial_hash = current_hash
                        last_change = loop.time()
            except TimeoutError:
                silence_duration = loop.time() - last_change
                if silence_duration >= threshold:
                    result = {"success": True, "silence_duration": silence_duration}
                    print(json.dumps(result), flush=True)
                    import os

                    os._exit(0)

    silence_duration = loop.time() - last_change
    if silence_duration >= threshold:
        result = {"success": True, "silence_duration": silence_duration}
        print(json.dumps(result), flush=True)
        import os

        os._exit(0)
    return {"timeout": True, "elapsed": timeout}


def main() -> None:
    if len(sys.argv) < 4:
        print(json.dumps({"error": "Usage: monitor_worker.py <mode> <session_id> <timeout>"}), flush=True)
        sys.exit(1)

    mode = sys.argv[1]
    session_id = sys.argv[2]
    timeout = float(sys.argv[3])

    if mode == "output":
        result = asyncio.run(monitor_output(session_id, timeout))
    elif mode == "silence":
        result = asyncio.run(monitor_silence(session_id, timeout))
    else:
        result = {"error": f"Unknown mode: {mode}"}

    # Only reaches here on timeout or error (success cases use os._exit)
    if result is not None:
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
