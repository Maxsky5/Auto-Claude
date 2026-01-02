"""
Tests for agents/session.py runtime abstraction support.

Verifies that the session module correctly handles both:
- ClaudeSDKClient (original Claude Agent SDK)
- AgentRuntimeBase (unified runtime abstraction for OpenCode, etc.)
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "backend"))

from agents.session import (
    _is_unified_runtime,
    _extract_tool_input_display,
    _get_runtime_name,
    AgentClient,
)
from core.runtime import AgentRuntimeBase, AgentMessage, BlockType, ContentBlock


class TestRuntimeTypeDetection:
    def test_is_unified_runtime_with_claude_sdk(self):
        mock_claude = MagicMock()
        mock_claude.__class__.__name__ = "ClaudeSDKClient"
        assert _is_unified_runtime(mock_claude) is False

    def test_is_unified_runtime_with_agent_runtime(self):
        mock_runtime = MagicMock(spec=AgentRuntimeBase)
        assert _is_unified_runtime(mock_runtime) is True


class TestToolInputDisplay:
    def test_extract_pattern(self):
        result = _extract_tool_input_display({"pattern": "*.py"})
        assert result == "pattern: *.py"

    def test_extract_file_path_short(self):
        result = _extract_tool_input_display({"file_path": "/short/path.py"})
        assert result == "/short/path.py"

    def test_extract_file_path_long_truncated(self):
        long_path = "/very/long/path/to/some/deeply/nested/directory/structure/file.py"
        result = _extract_tool_input_display({"file_path": long_path})
        assert result is not None
        assert result.startswith("...")
        assert len(result) == 50

    def test_extract_command_short(self):
        result = _extract_tool_input_display({"command": "ls -la"})
        assert result == "ls -la"

    def test_extract_command_long_truncated(self):
        long_cmd = "a" * 100
        result = _extract_tool_input_display({"command": long_cmd})
        assert result is not None
        assert result.endswith("...")
        assert len(result) == 50

    def test_extract_path(self):
        result = _extract_tool_input_display({"path": "/some/path"})
        assert result == "/some/path"

    def test_extract_none_input(self):
        result = _extract_tool_input_display(None)
        assert result is None

    def test_extract_empty_dict(self):
        result = _extract_tool_input_display({})
        assert result is None

    def test_extract_non_dict(self):
        result = _extract_tool_input_display("not a dict")
        assert result is None


class TestRuntimeNameDetection:
    def test_get_runtime_name_claude_code(self):
        mock_runtime = MagicMock(spec=AgentRuntimeBase)
        mock_runtime.get_runtime_name.return_value = "claude-code"
        result = _get_runtime_name(mock_runtime)
        assert result == "claude-code"

    def test_get_runtime_name_opencode(self):
        mock_runtime = MagicMock(spec=AgentRuntimeBase)
        mock_runtime.get_runtime_name.return_value = "opencode"
        result = _get_runtime_name(mock_runtime)
        assert result == "opencode"

    def test_get_runtime_name_custom(self):
        mock_runtime = MagicMock(spec=AgentRuntimeBase)
        mock_runtime.get_runtime_name.return_value = "custom-provider"
        result = _get_runtime_name(mock_runtime)
        assert result == "custom-provider"


class TestAgentMessageProcessing:
    def test_content_block_text_type(self):
        block = ContentBlock(type=BlockType.TEXT, text="Hello world")
        assert block.type == BlockType.TEXT
        assert block.text == "Hello world"

    def test_content_block_tool_use_type(self):
        block = ContentBlock(
            type=BlockType.TOOL_USE,
            tool_name="Read",
            tool_input={"file_path": "/test.py"},
        )
        assert block.type == BlockType.TOOL_USE
        assert block.tool_name == "Read"
        assert block.tool_input == {"file_path": "/test.py"}

    def test_content_block_tool_result_type(self):
        block = ContentBlock(
            type=BlockType.TOOL_RESULT,
            text="File contents here",
            is_error=False,
        )
        assert block.type == BlockType.TOOL_RESULT
        assert block.text == "File contents here"
        assert block.is_error is False

    def test_content_block_tool_result_error(self):
        block = ContentBlock(
            type=BlockType.TOOL_RESULT,
            text="Error: file not found",
            is_error=True,
        )
        assert block.type == BlockType.TOOL_RESULT
        assert block.is_error is True


class TestAgentClientTypeAlias:
    def test_agent_client_accepts_claude_sdk(self):
        from claude_agent_sdk import ClaudeSDKClient

        def accept_client(client: AgentClient) -> str:
            return type(client).__name__

        mock = MagicMock(spec=ClaudeSDKClient)
        result = accept_client(mock)
        assert "MagicMock" in result or "ClaudeSDKClient" in result

    def test_agent_client_accepts_runtime_base(self):
        def accept_client(client: AgentClient) -> str:
            return type(client).__name__

        mock = MagicMock(spec=AgentRuntimeBase)
        result = accept_client(mock)
        assert "MagicMock" in result
