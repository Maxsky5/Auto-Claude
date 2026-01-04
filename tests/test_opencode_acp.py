"""
Tests for OpenCode Runtime ACP functionality.

Comprehensive tests for the critical 30s timeout fix and ACP protocol handling.
"""

import sys
from pathlib import Path
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(str(Path(__file__).parent.parent / "apps/backend"))

from core.runtime.types import (
    RuntimeOptions,
    RuntimeCapabilities,
    AgentMessage,
    MessageRole,
    ContentBlock,
    BlockType,
)
from core.runtime.opencode import OpenCodeRuntime, ACP_PROTOCOL_VERSION


@pytest.fixture
def mock_runtime_options(tmp_path):
    return RuntimeOptions(
        model="anthropic/claude-sonnet-4-5",
        system_prompt="Test Prompt",
        project_dir=tmp_path / "project",
        spec_dir=tmp_path / "spec",
    )


@pytest.fixture
def opencode_runtime(mock_runtime_options):
    return OpenCodeRuntime(mock_runtime_options)


class TestACPSessionTimeout:
    """Critical tests for the 30s session/new timeout fix."""

    def test_session_new_timeout_value_is_30s(self):
        """Verify that _create_session uses 30s timeout for session/new."""
        import inspect

        source = inspect.getsource(OpenCodeRuntime._create_session)
        assert "timeout=30.0" in source, (
            "session/new timeout should be 30s to accommodate MCP server loading"
        )

    def test_initialize_timeout_value_is_10s(self):
        """Verify that _initialize_acp uses 10s timeout."""
        import inspect

        source = inspect.getsource(OpenCodeRuntime._initialize_acp)
        assert "timeout=10.0" in source, "initialize timeout should remain at 10s"

    def test_session_creation_calls_wait_with_30s(self, opencode_runtime):
        """Verify that _create_session calls _wait_for_response with 30s timeout."""

        async def run_test():
            timeout_captured = None

            async def mock_send(_method, _params=None):
                return 1

            async def mock_wait(req_id, timeout=30.0):
                nonlocal timeout_captured
                timeout_captured = timeout
                return {"sessionId": "test-123"}

            opencode_runtime._send_jsonrpc = mock_send
            opencode_runtime._wait_for_response = mock_wait

            session_id = await opencode_runtime._create_session()

            assert session_id == "test-123"
            assert timeout_captured == 30.0, (
                f"Expected 30s timeout, got {timeout_captured}"
            )

        asyncio.run(run_test())


class TestJSONRPCHandling:
    """Tests for JSON-RPC message handling."""

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_response_success(self, opencode_runtime):
        """Test handling successful JSON-RPC responses."""
        future = asyncio.get_running_loop().create_future()
        opencode_runtime._pending_requests[1] = future

        await opencode_runtime._handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 1, "result": {"data": "test"}}
        )

        assert future.done()
        assert future.result() == {"data": "test"}

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_response_error(self, opencode_runtime):
        """Test handling JSON-RPC error responses."""
        future = asyncio.get_running_loop().create_future()
        opencode_runtime._pending_requests[1] = future

        await opencode_runtime._handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32600, "message": "Invalid Request"},
            }
        )

        assert future.done()
        with pytest.raises(RuntimeError, match="Invalid Request"):
            future.result()

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_notification(self, opencode_runtime):
        """Test handling JSON-RPC notifications (no id)."""
        await opencode_runtime._handle_jsonrpc_message(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"update": {"sessionUpdate": "test"}},
            }
        )

    @pytest.mark.asyncio
    async def test_handle_finish_response_signals_completion(self, opencode_runtime):
        """Test that finish signals are properly handled."""
        await opencode_runtime._handle_jsonrpc_message(
            {"jsonrpc": "2.0", "id": 1, "result": {"stopReason": "end_turn"}}
        )

        msg = await asyncio.wait_for(
            opencode_runtime._response_queue.get(), timeout=1.0
        )
        assert msg is None


class TestSessionUpdateHandling:
    """Tests for session update message handling."""

    @pytest.mark.asyncio
    async def test_handle_text_chunk(self, opencode_runtime):
        """Test handling text chunk updates with newline triggers immediate flush."""
        update = {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "Hello, world!\n"},
        }

        await opencode_runtime._handle_session_update(update)

        msg = await asyncio.wait_for(
            opencode_runtime._response_queue.get(), timeout=1.0
        )
        assert msg is not None
        assert msg.role == MessageRole.ASSISTANT
        assert len(msg.content) == 1
        assert msg.content[0].type == BlockType.TEXT
        assert msg.content[0].text == "Hello, world!\n"

    @pytest.mark.asyncio
    async def test_handle_empty_text_chunk_ignored(self, opencode_runtime):
        """Test that empty text chunks are ignored and don't affect buffer."""
        update = {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": ""},
        }

        await opencode_runtime._handle_session_update(update)

        assert opencode_runtime._response_queue.empty()
        assert opencode_runtime._text_buffer == ""

    @pytest.mark.asyncio
    async def test_handle_agent_message_with_text(self, opencode_runtime):
        """Test handling complete agent messages with text."""
        update = {
            "sessionUpdate": "agent_message",
            "content": [
                {"type": "text", "text": "First block"},
                {"type": "text", "text": "Second block"},
            ],
        }

        await opencode_runtime._handle_session_update(update)

        msg1 = await asyncio.wait_for(
            opencode_runtime._response_queue.get(), timeout=1.0
        )
        msg2 = await asyncio.wait_for(
            opencode_runtime._response_queue.get(), timeout=1.0
        )

        assert msg1.content[0].text == "First block"
        assert msg2.content[0].text == "Second block"

    @pytest.mark.asyncio
    async def test_handle_agent_message_with_tool_use(self, opencode_runtime):
        """Test handling agent messages with tool use."""
        update = {
            "sessionUpdate": "agent_message",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Read",
                    "input": {"file_path": "/path/to/file.py"},
                }
            ],
        }

        await opencode_runtime._handle_session_update(update)

        msg = await asyncio.wait_for(
            opencode_runtime._response_queue.get(), timeout=1.0
        )
        assert msg.content[0].type == BlockType.TOOL_USE
        assert msg.content[0].tool_name == "Read"
        assert msg.content[0].tool_input == {"file_path": "/path/to/file.py"}

    @pytest.mark.asyncio
    async def test_handle_finish_update(self, opencode_runtime):
        """Test handling finish updates."""
        for update_type in ["finish", "agent_finish", "session_finish"]:
            update = {"sessionUpdate": update_type}

            await opencode_runtime._handle_session_update(update)

            msg = await asyncio.wait_for(
                opencode_runtime._response_queue.get(), timeout=1.0
            )
            assert msg is None

    @pytest.mark.asyncio
    async def test_handle_update_with_type_field(self, opencode_runtime):
        """Test handling updates with 'type' field instead of 'sessionUpdate'."""
        update = {
            "type": "agent_message_chunk",
            "content": {"type": "text", "text": "Using type field\n"},
        }

        await opencode_runtime._handle_session_update(update)

        msg = await asyncio.wait_for(
            opencode_runtime._response_queue.get(), timeout=1.0
        )
        assert msg.content[0].text == "Using type field\n"

    @pytest.mark.asyncio
    async def test_text_chunks_batched_until_newline(self, opencode_runtime):
        """Test that multiple text chunks are batched until newline."""
        chunks = ["Hello", ", ", "world", "!\n"]
        for chunk in chunks:
            update = {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": chunk},
            }
            await opencode_runtime._handle_session_update(update)

        msg = await asyncio.wait_for(
            opencode_runtime._response_queue.get(), timeout=1.0
        )
        assert msg.content[0].text == "Hello, world!\n"
        assert opencode_runtime._response_queue.empty()

    @pytest.mark.asyncio
    async def test_text_buffer_flushed_on_timeout(self, opencode_runtime):
        """Test that buffered text is flushed after timeout."""
        update = {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "No newline here"},
        }
        await opencode_runtime._handle_session_update(update)

        assert opencode_runtime._text_buffer == "No newline here"
        assert opencode_runtime._response_queue.empty()

        await asyncio.sleep(0.2)

        msg = await asyncio.wait_for(
            opencode_runtime._response_queue.get(), timeout=1.0
        )
        assert msg.content[0].text == "No newline here"
        assert opencode_runtime._text_buffer == ""

    @pytest.mark.asyncio
    async def test_text_buffer_flushed_on_agent_message(self, opencode_runtime):
        """Test that buffered text is flushed when agent_message arrives."""
        chunk_update = {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "Buffered"},
        }
        await opencode_runtime._handle_session_update(chunk_update)

        assert opencode_runtime._text_buffer == "Buffered"

        message_update = {
            "sessionUpdate": "agent_message",
            "content": [{"type": "text", "text": "Complete message"}],
        }
        await opencode_runtime._handle_session_update(message_update)

        msg1 = await asyncio.wait_for(
            opencode_runtime._response_queue.get(), timeout=1.0
        )
        assert msg1.content[0].text == "Buffered"

        msg2 = await asyncio.wait_for(
            opencode_runtime._response_queue.get(), timeout=1.0
        )
        assert msg2.content[0].text == "Complete message"

    @pytest.mark.asyncio
    async def test_text_buffer_flushed_on_finish(self, opencode_runtime):
        """Test that buffered text is flushed when finish arrives."""
        chunk_update = {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "Final words"},
        }
        await opencode_runtime._handle_session_update(chunk_update)

        finish_update = {"sessionUpdate": "finish"}
        await opencode_runtime._handle_session_update(finish_update)

        msg1 = await asyncio.wait_for(
            opencode_runtime._response_queue.get(), timeout=1.0
        )
        assert msg1.content[0].text == "Final words"

        msg2 = await asyncio.wait_for(
            opencode_runtime._response_queue.get(), timeout=1.0
        )
        assert msg2 is None


class TestRuntimeProperties:
    """Tests for runtime properties and capabilities."""

    def test_get_runtime_name(self, opencode_runtime):
        """Test get_runtime_name returns 'opencode'."""
        assert opencode_runtime.get_runtime_name() == "opencode"

    def test_get_runtime_type(self):
        """Test get_runtime_type class method."""
        assert OpenCodeRuntime.get_runtime_type() == "opencode"

    def test_get_capabilities(self, opencode_runtime):
        """Test get_capabilities returns correct values."""
        caps = opencode_runtime.get_capabilities()

        assert caps.extended_thinking is False
        assert caps.mcp_servers is True
        assert caps.subagents is False
        assert caps.structured_output is True
        assert caps.streaming is True

    def test_supports_extended_thinking(self, opencode_runtime):
        """Test supports_extended_thinking returns False."""
        assert opencode_runtime.supports_extended_thinking() is False

    def test_supports_mcp_servers(self, opencode_runtime):
        """Test supports_mcp_servers returns True."""
        assert opencode_runtime.supports_mcp_servers() is True


class TestModelValidation:
    """Tests for model validation."""

    @patch("subprocess.run")
    def test_validate_model_success(self, mock_run, opencode_runtime):
        """Test successful model validation."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "anthropic/claude-sonnet-4-5\nopenai/gpt-4"

        opencode_runtime._available_models = None
        assert opencode_runtime.validate_model("anthropic/claude-sonnet-4-5") is True

    @patch("subprocess.run")
    def test_validate_model_not_found(self, mock_run, opencode_runtime):
        """Test model validation when model not in list."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "anthropic/claude-sonnet-4-5\nopenai/gpt-4"

        opencode_runtime._available_models = None
        assert opencode_runtime.validate_model("unknown/model") is False

    @patch("subprocess.run")
    def test_validate_model_allows_any_when_fetch_fails(
        self, mock_run, opencode_runtime
    ):
        """Test that model validation allows any model when fetch fails."""
        mock_run.side_effect = FileNotFoundError()

        opencode_runtime._available_models = None
        assert opencode_runtime.validate_model("any/model") is True


class TestStaticMethods:
    """Tests for static methods."""

    @patch("subprocess.run")
    def test_is_available_true(self, mock_run):
        """Test is_available returns True when CLI is available."""
        mock_run.return_value.returncode = 0
        assert OpenCodeRuntime.is_available() is True

    @patch("subprocess.run")
    def test_is_available_false_not_found(self, mock_run):
        """Test is_available returns False when CLI not found."""
        mock_run.side_effect = FileNotFoundError()
        assert OpenCodeRuntime.is_available() is False

    @patch("subprocess.run")
    def test_is_available_false_nonzero_exit(self, mock_run):
        """Test is_available returns False on non-zero exit."""
        mock_run.return_value.returncode = 1
        assert OpenCodeRuntime.is_available() is False

    @patch("subprocess.run")
    def test_get_available_models(self, mock_run):
        """Test get_available_models parses output correctly."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "anthropic/claude-sonnet\nopenai/gpt-4\n"

        models = OpenCodeRuntime.get_available_models()

        assert len(models) == 2
        assert models[0]["id"] == "anthropic/claude-sonnet"
        assert models[0]["provider"] == "anthropic"
        assert models[1]["id"] == "openai/gpt-4"
        assert models[1]["provider"] == "openai"

    @patch("subprocess.run")
    def test_get_model_providers(self, mock_run):
        """Test get_model_providers returns unique providers."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = (
            "anthropic/claude-sonnet\nanthropic/claude-opus\nopenai/gpt-4"
        )

        providers = OpenCodeRuntime.get_model_providers()

        assert "anthropic" in providers
        assert "openai" in providers
        assert len(providers) == 2

    @patch("subprocess.run")
    def test_run_simple_query_success(self, mock_run, tmp_path):
        """Test run_simple_query returns output on success."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Hello from OpenCode"

        result = OpenCodeRuntime.run_simple_query("test", tmp_path)

        assert result == "Hello from OpenCode"
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert "opencode" in args[0][0]
        assert "run" in args[0][0]

    @patch("subprocess.run")
    def test_run_simple_query_failure(self, mock_run, tmp_path):
        """Test run_simple_query raises on failure."""
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "Error occurred"

        with pytest.raises(RuntimeError, match="OpenCode CLI failed"):
            OpenCodeRuntime.run_simple_query("test", tmp_path)

    @patch("subprocess.run")
    def test_run_simple_query_timeout(self, mock_run, tmp_path):
        """Test run_simple_query raises on timeout."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="opencode", timeout=120)

        with pytest.raises(RuntimeError, match="timed out"):
            OpenCodeRuntime.run_simple_query("test", tmp_path)
