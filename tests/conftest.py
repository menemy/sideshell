"""Pytest configuration, fixtures, and shared test utilities."""

import asyncio
from typing import Generator


# =============================================================================
# Shared Test Configuration
# =============================================================================

# Visual delay between operations (seconds)
# Set to 0 for fast testing, 0.6 for visual observation
TEST_DELAY = 0.6


async def delay():
    """Delay for visual observation during tests."""
    if TEST_DELAY > 0:
        await asyncio.sleep(TEST_DELAY)


class BaseTestSuite:
    """Base class for backend test suites."""

    def __init__(self):
        self.passed = 0
        self.failed = 0

    async def _delay(self):
        """Delay for visual observation."""
        await delay()

    def _assert(self, condition: bool, message: str):
        """Assert helper with counting and visual output."""
        if condition:
            self.passed += 1
            print(f"  ✓ {message}")
        else:
            self.failed += 1
            print(f"  ✗ {message}")

    async def run_tests(self, tests: list):
        """Run a list of test methods with delays."""
        for test in tests:
            try:
                await test()
                await self._delay()
            except Exception as e:
                self.failed += 1
                print(f"  ✗ ERROR in {test.__name__}: {e}")

        return self.passed, self.failed


# =============================================================================
# Pytest fixtures (only loaded when running with pytest)
# =============================================================================

try:
    import pytest

    @pytest.fixture(scope="session")
    def event_loop() -> Generator:
        """Create an instance of the default event loop for the test session."""
        loop = asyncio.get_event_loop_policy().new_event_loop()
        yield loop
        loop.close()
except ImportError:
    pass  # pytest not installed, skip fixtures
