"""
Tests for insights_runner.py to ensure runtime handling.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

# Add apps/backend to path
sys.path.append(str(Path(__file__).parent.parent / "apps/backend"))

# Force mock roadmap module into sys.modules BEFORE any imports
sys.modules["roadmap"] = MagicMock()

# Import the module directly (we'll mock its dependencies in each test)
import runners.insights_runner


async def async_generator():
    """Empty async generator for mocking receive_response."""
    return
    yield  # This makes it an async generator


@pytest.mark.asyncio
async def test_run_with_sdk_passes_runtime():
    """Test that run_with_sdk passes runtime to create_agent_runtime."""

    project_dir = "/tmp/project"
    message = "test message"
    history = []
    runtime = "opencode"

    # Configure mock client
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.query = AsyncMock()
    mock_client.receive_response = MagicMock(return_value=async_generator())

    with (
        patch.object(
            runners.insights_runner,
            "create_agent_runtime",
            return_value=mock_client,
        ) as mock_create,
        patch.object(
            runners.insights_runner, "build_system_prompt", return_value="system prompt"
        ),
    ):
        await runners.insights_runner.run_with_sdk(
            project_dir=project_dir, message=message, history=history, runtime=runtime
        )

        # Verify create_agent_runtime was called with runtime
        mock_create.assert_called()
        call_args = mock_create.call_args[1]
        assert call_args["runtime"] == "opencode"
        assert call_args["project_dir"] == Path(project_dir).resolve()


@pytest.mark.asyncio
async def test_run_with_sdk_skips_auth_for_opencode():
    """Test that run_with_sdk skips auth checks for opencode."""

    project_dir = "/tmp/project"
    message = "test message"
    history = []
    runtime = "opencode"

    # Configure mock client
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.query = AsyncMock()
    mock_client.receive_response = MagicMock(return_value=async_generator())

    with (
        patch.object(
            runners.insights_runner,
            "create_agent_runtime",
            return_value=mock_client,
        ),
        patch.object(
            runners.insights_runner, "build_system_prompt", return_value="system prompt"
        ),
        patch.object(
            runners.insights_runner, "ensure_claude_code_oauth_token"
        ) as mock_ensure,
    ):
        await runners.insights_runner.run_with_sdk(
            project_dir=project_dir, message=message, history=history, runtime=runtime
        )

        # Verify ensure_claude_code_oauth_token was NOT called for opencode
        mock_ensure.assert_not_called()


@pytest.mark.asyncio
async def test_run_with_sdk_enforces_auth_for_claudecode():
    """Test that run_with_sdk enforces auth checks for claude-code."""

    project_dir = "/tmp/project"
    message = "test message"
    history = []
    runtime = "claude-code"

    with (
        patch.object(runners.insights_runner, "get_auth_token", return_value=None),
        patch.object(runners.insights_runner, "_run_simple_fallback") as mock_simple,
    ):
        await runners.insights_runner.run_with_sdk(
            project_dir=project_dir, message=message, history=history, runtime=runtime
        )

        # Should fall back to simple mode due to no token
        mock_simple.assert_called_once()
