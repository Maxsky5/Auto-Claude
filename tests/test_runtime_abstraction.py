"""
Tests for the Runtime Abstraction Layer.

Phase 1 Tests: Base interface, capabilities, factory functions.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / "apps/backend"))

import asyncio
import pytest
import warnings
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from core.runtime.types import (
    RuntimeOptions,
    RuntimeCapabilities,
    AgentMessage,
    MessageRole,
    ContentBlock,
    BlockType,
    SecurityConfig,
)
from core.runtime.base import AgentRuntimeBase
from core.runtime.opencode import OpenCodeRuntime
from core.runtime.claude_code import ClaudeCodeRuntime
from core.runtime.factory import (
    create_agent_runtime,
    detect_available_runtimes,
    get_runtime_info,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_runtime_options(tmp_path):
    return RuntimeOptions(
        model="claude-sonnet-4-5-20250929",
        system_prompt="Test Prompt",
        project_dir=tmp_path / "project",
        spec_dir=tmp_path / "spec",
    )


@pytest.fixture
def mock_runtime_options_with_extras(tmp_path):
    """Runtime options with all new Phase 1 fields."""
    return RuntimeOptions(
        model="claude-sonnet-4-5-20250929",
        system_prompt="Test Prompt",
        project_dir=tmp_path / "project",
        spec_dir=tmp_path / "spec",
        agent_type="coder",
        allowed_tools=["Read", "Write", "Bash"],
        mcp_servers={"context7": {"command": "npx", "args": ["-y", "@context7/mcp"]}},
        security=SecurityConfig(sandbox_enabled=True, allowed_paths=["/project"]),
        project_capabilities={"has_python": True, "has_nodejs": False},
        linear_enabled=True,
        mcp_config={"custom_server": {"enabled": True}},
    )


# =============================================================================
# Phase 1: RuntimeCapabilities Tests
# =============================================================================


class TestRuntimeCapabilities:
    """Tests for the RuntimeCapabilities dataclass."""

    def test_default_capabilities(self):
        """Test default capability values."""
        caps = RuntimeCapabilities()
        assert caps.extended_thinking is False
        assert caps.mcp_servers is False
        assert caps.subagents is False
        assert caps.structured_output is False
        assert caps.streaming is True

    def test_custom_capabilities(self):
        """Test custom capability values."""
        caps = RuntimeCapabilities(
            extended_thinking=True,
            mcp_servers=True,
            subagents=True,
            structured_output=True,
            streaming=False,
        )
        assert caps.extended_thinking is True
        assert caps.mcp_servers is True
        assert caps.subagents is True
        assert caps.structured_output is True
        assert caps.streaming is False


# =============================================================================
# Phase 1: RuntimeOptions Tests
# =============================================================================


class TestRuntimeOptions:
    """Tests for the RuntimeOptions dataclass."""

    def test_required_fields(self, tmp_path):
        """Test that required fields are enforced."""
        options = RuntimeOptions(
            model="test-model",
            project_dir=tmp_path / "project",
            spec_dir=tmp_path / "spec",
        )
        assert options.model == "test-model"
        assert options.project_dir == tmp_path / "project"
        assert options.spec_dir == tmp_path / "spec"

    def test_optional_fields(self, mock_runtime_options_with_extras):
        """Test that optional fields are properly set."""
        options = mock_runtime_options_with_extras
        assert options.agent_type == "coder"
        assert options.allowed_tools == ["Read", "Write", "Bash"]
        assert "context7" in options.mcp_servers
        assert options.security.sandbox_enabled is True
        assert options.project_capabilities["has_python"] is True
        assert options.linear_enabled is True
        assert options.mcp_config["custom_server"]["enabled"] is True

    def test_default_values(self, tmp_path):
        """Test default values for optional fields."""
        options = RuntimeOptions(
            model="test-model",
            project_dir=tmp_path / "project",
            spec_dir=tmp_path / "spec",
        )
        assert options.agent_type == "coder"
        assert options.system_prompt is None
        assert options.allowed_tools is None
        assert options.mcp_servers is None
        assert options.max_thinking_tokens is None
        assert options.max_turns == 1000
        assert options.output_format is None
        assert options.agents is None
        assert options.security is None
        assert options.project_capabilities is None
        assert options.linear_enabled is False
        assert options.mcp_config is None


# =============================================================================
# Phase 1: AgentRuntimeBase Tests
# =============================================================================


class TestAgentRuntimeBase:
    """Tests for the abstract base class interface."""

    def test_properties_from_options(self, mock_runtime_options):
        """Test that properties are correctly derived from options."""
        runtime = OpenCodeRuntime(mock_runtime_options)
        assert runtime.model == mock_runtime_options.model
        assert runtime.project_dir == mock_runtime_options.project_dir
        assert runtime.spec_dir == mock_runtime_options.spec_dir
        assert runtime.agent_type == "coder"

    def test_is_running_default(self, mock_runtime_options):
        """Test is_running default value."""
        runtime = OpenCodeRuntime(mock_runtime_options)
        assert runtime.is_running() is False

    def test_get_allowed_tools_empty(self, mock_runtime_options):
        """Test get_allowed_tools returns empty list when not set."""
        runtime = OpenCodeRuntime(mock_runtime_options)
        assert runtime.get_allowed_tools() == []

    def test_get_allowed_tools_with_values(self, mock_runtime_options_with_extras):
        """Test get_allowed_tools returns configured values."""
        runtime = OpenCodeRuntime(mock_runtime_options_with_extras)
        assert runtime.get_allowed_tools() == ["Read", "Write", "Bash"]

    def test_get_mcp_servers_empty(self, mock_runtime_options):
        """Test get_mcp_servers returns empty dict when not set."""
        runtime = OpenCodeRuntime(mock_runtime_options)
        assert runtime.get_mcp_servers() == {}

    def test_get_mcp_servers_with_values(self, mock_runtime_options_with_extras):
        """Test get_mcp_servers returns configured values."""
        runtime = OpenCodeRuntime(mock_runtime_options_with_extras)
        servers = runtime.get_mcp_servers()
        assert "context7" in servers
        assert servers["context7"]["command"] == "npx"

    def test_get_system_prompt_custom(self, mock_runtime_options):
        """Test get_system_prompt returns custom prompt when set."""
        runtime = OpenCodeRuntime(mock_runtime_options)
        assert runtime.get_system_prompt() == "Test Prompt"

    def test_get_system_prompt_default(self, tmp_path):
        """Test get_system_prompt returns default prompt when not set."""
        options = RuntimeOptions(
            model="test-model",
            project_dir=tmp_path / "project",
            spec_dir=tmp_path / "spec",
        )
        runtime = OpenCodeRuntime(options)
        prompt = runtime.get_system_prompt()
        assert "expert full-stack developer" in prompt
        assert str(tmp_path / "project") in prompt

    def test_repr(self, mock_runtime_options):
        """Test string representation."""
        runtime = OpenCodeRuntime(mock_runtime_options)
        repr_str = repr(runtime)
        assert "OpenCodeRuntime" in repr_str
        assert mock_runtime_options.model in repr_str


# =============================================================================
# Phase 1: Capabilities Methods Tests
# =============================================================================


class TestCapabilitiesMethods:
    """Tests for capability helper methods."""

    def test_supports_extended_thinking_opencode(self, mock_runtime_options):
        """OpenCode doesn't support extended thinking."""
        runtime = OpenCodeRuntime(mock_runtime_options)
        assert runtime.supports_extended_thinking() is False

    def test_supports_mcp_servers_opencode(self, mock_runtime_options):
        """OpenCode supports MCP servers."""
        runtime = OpenCodeRuntime(mock_runtime_options)
        assert runtime.supports_mcp_servers() is True

    def test_supports_subagents_opencode(self, mock_runtime_options):
        """OpenCode doesn't support subagents yet."""
        runtime = OpenCodeRuntime(mock_runtime_options)
        assert runtime.supports_subagents() is False

    def test_supports_structured_output_opencode(self, mock_runtime_options):
        """OpenCode supports structured output."""
        runtime = OpenCodeRuntime(mock_runtime_options)
        assert runtime.supports_structured_output() is True

    @patch("subprocess.run")
    def test_claude_code_capabilities(self, mock_run, mock_runtime_options):
        """ClaudeCode supports all capabilities."""
        mock_run.return_value.returncode = 0
        runtime = ClaudeCodeRuntime(mock_runtime_options)
        caps = runtime.get_capabilities()
        assert caps.extended_thinking is True
        assert caps.mcp_servers is True
        assert caps.subagents is True
        assert caps.structured_output is True


# =============================================================================
# Phase 1: get_runtime_type Tests
# =============================================================================


class TestGetRuntimeType:
    """Tests for the get_runtime_type class method."""

    def test_opencode_runtime_type(self):
        """Test OpenCodeRuntime.get_runtime_type()."""
        assert OpenCodeRuntime.get_runtime_type() == "opencode"

    def test_claude_code_runtime_type(self):
        """Test ClaudeCodeRuntime.get_runtime_type()."""
        assert ClaudeCodeRuntime.get_runtime_type() == "claude-code"


# =============================================================================
# Phase 1: Factory Tests - create_agent_runtime
# =============================================================================


class TestCreateAgentRuntime:
    """Tests for the new create_agent_runtime factory function."""

    @patch("subprocess.run")
    def test_create_claude_code_runtime(self, mock_run, mock_runtime_options):
        """Test creating a Claude Code runtime."""
        mock_run.return_value.returncode = 0
        runtime = create_agent_runtime(
            project_dir=mock_runtime_options.project_dir,
            spec_dir=mock_runtime_options.spec_dir,
            model=mock_runtime_options.model,
            runtime="claude-code",
        )
        assert isinstance(runtime, ClaudeCodeRuntime)
        assert runtime.get_runtime_name() == "claude-code"

    @patch("subprocess.run")
    def test_create_opencode_runtime(self, mock_run, mock_runtime_options):
        """Test creating an OpenCode runtime."""
        mock_run.return_value.returncode = 0
        runtime = create_agent_runtime(
            project_dir=mock_runtime_options.project_dir,
            spec_dir=mock_runtime_options.spec_dir,
            model=mock_runtime_options.model,
            runtime="opencode",
        )
        assert isinstance(runtime, OpenCodeRuntime)
        assert runtime.get_runtime_name() == "opencode"

    @patch("subprocess.run")
    def test_create_runtime_with_all_options(self, mock_run, tmp_path):
        """Test creating a runtime with all new options."""
        mock_run.return_value.returncode = 0
        security = SecurityConfig(sandbox_enabled=True)
        runtime = create_agent_runtime(
            project_dir=tmp_path / "project",
            spec_dir=tmp_path / "spec",
            model="claude-sonnet-4-5",
            agent_type="qa_reviewer",
            max_thinking_tokens=10000,
            runtime="opencode",
            system_prompt="Custom prompt",
            allowed_tools=["Read", "Write"],
            mcp_servers={"test": {"command": "test"}},
            security=security,
            project_capabilities={"has_python": True},
            linear_enabled=True,
            mcp_config={"custom": {"enabled": True}},
        )
        assert isinstance(runtime, OpenCodeRuntime)
        assert runtime.agent_type == "qa_reviewer"
        assert runtime.get_system_prompt() == "Custom prompt"
        assert runtime.get_allowed_tools() == ["Read", "Write"]

    @patch("subprocess.run")
    def test_default_runtime_selection(self, mock_run, mock_runtime_options):
        """Test default runtime selection."""
        mock_run.return_value.returncode = 0
        runtime = create_agent_runtime(
            project_dir=mock_runtime_options.project_dir,
            spec_dir=mock_runtime_options.spec_dir,
            model=mock_runtime_options.model,
        )
        assert isinstance(runtime, ClaudeCodeRuntime)
        assert runtime.get_runtime_name() == "claude-code"


# =============================================================================
# Phase 1: get_runtime_info Tests
# =============================================================================


class TestGetRuntimeInfo:
    """Tests for the get_runtime_info function."""

    @patch("subprocess.run")
    def test_claude_code_info(self, mock_run):
        """Test getting Claude Code runtime info."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "1.0.0"
        info = get_runtime_info("claude-code")
        assert info["type"] == "claude-code"
        assert info["available"] is True
        assert info["features"]["extended_thinking"] is True
        assert info["features"]["mcp_servers"] is True

    @patch("subprocess.run")
    def test_opencode_info(self, mock_run):
        """Test getting OpenCode runtime info."""
        mock_run.return_value.returncode = 0
        info = get_runtime_info("opencode")
        assert info["type"] == "opencode"
        assert info["available"] is True
        assert info["features"]["extended_thinking"] is False


# =============================================================================
# Existing Tests (from original file)
# =============================================================================


@patch("subprocess.run")
def test_detect_available_runtimes(mock_run):
    mock_run.return_value.returncode = 0

    available = detect_available_runtimes()
    assert available["claude-code"] is True
    assert available["opencode"] is True


@patch("subprocess.run")
def test_create_runtime_factory(mock_run, mock_runtime_options):
    mock_run.return_value.returncode = 0

    runtime = create_agent_runtime(
        project_dir=mock_runtime_options.project_dir,
        spec_dir=mock_runtime_options.spec_dir,
        model=mock_runtime_options.model,
        runtime="claude-code",
    )
    assert isinstance(runtime, ClaudeCodeRuntime)
    assert runtime.get_runtime_name() == "claude-code"

    runtime = create_agent_runtime(
        project_dir=mock_runtime_options.project_dir,
        spec_dir=mock_runtime_options.spec_dir,
        model=mock_runtime_options.model,
        runtime="opencode",
    )
    assert isinstance(runtime, OpenCodeRuntime)
    assert runtime.get_runtime_name() == "opencode"


@pytest.mark.asyncio
async def test_opencode_query_flow(mock_runtime_options):
    runtime = OpenCodeRuntime(mock_runtime_options)

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        mock_process = AsyncMock()
        mock_process.stdout.readline.side_effect = [
            b'{"type": "text", "part": {"text": "Hello"}}',
            b"",
        ]
        mock_process.returncode = 0
        mock_process.wait.return_value = None
        mock_exec.return_value = mock_process

        await runtime.query("Hello")

        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert "opencode" in args
        assert "run" in args

        messages = []
        async for msg in runtime.receive_response():
            messages.append(msg)

        assert len(messages) == 1
        assert messages[0].role == MessageRole.ASSISTANT
        assert messages[0].content[0].text == "Hello"


@pytest.mark.asyncio
async def test_runtime_context_manager(mock_runtime_options):
    """Test that runtimes support async context manager protocol."""
    runtime = OpenCodeRuntime(mock_runtime_options)

    runtime.stop = AsyncMock()

    async with runtime as r:
        assert r is runtime
        assert isinstance(r, OpenCodeRuntime)

    runtime.stop.assert_called_once()
