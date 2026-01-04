"""
Runtime Types Module
====================

Shared types for agent runtime abstraction layer.
These types provide a unified interface across different runtimes
(Claude Code, OpenCode, Codex, Gemini CLI, etc.)
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Literal, Protocol


class MessageRole(Enum):
    """Role of a message in the conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"


class BlockType(Enum):
    """Type of content block in a message."""

    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"


@dataclass
class ContentBlock:
    """A block of content within a message."""

    type: BlockType
    text: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_id: str | None = None
    is_error: bool = False


@dataclass
class AgentMessage:
    """
    Unified message type for all runtimes.

    This abstraction allows handling messages from Claude Code SDK,
    OpenCode, or any other runtime in a consistent way.
    """

    role: MessageRole
    content: list[ContentBlock] = field(default_factory=list)
    raw: Any = None  # Original message from the runtime

    def get_text(self) -> str:
        """Extract all text content from the message."""
        return "".join(
            block.text
            for block in self.content
            if block.type == BlockType.TEXT and block.text
        )

    def get_tool_uses(self) -> list[ContentBlock]:
        """Get all tool use blocks from the message."""
        return [block for block in self.content if block.type == BlockType.TOOL_USE]

    def get_tool_results(self) -> list[ContentBlock]:
        """Get all tool result blocks from the message."""
        return [block for block in self.content if block.type == BlockType.TOOL_RESULT]


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server."""

    id: str
    name: str
    type: str  # "command" or "http"
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format for SDK consumption."""
        if self.type == "command":
            return {
                "command": self.command or "npx",
                "args": self.args or [],
            }
        else:  # http
            result: dict[str, Any] = {
                "type": "http",
                "url": self.url or "",
            }
            if self.headers:
                result["headers"] = self.headers
            return result


class SecurityHook(Protocol):
    """Protocol for security hooks that validate tool calls."""

    def __call__(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """
        Validate a tool call.

        Args:
            tool_name: Name of the tool being called
            tool_input: Input parameters for the tool

        Returns:
            (allowed, error_message) - If not allowed, error_message explains why
        """
        ...


@dataclass
class SecurityConfig:
    """Security configuration for the agent runtime."""

    sandbox_enabled: bool = True
    allowed_paths: list[str] = field(default_factory=list)
    pre_tool_hooks: list[SecurityHook] = field(default_factory=list)


# Runtime type literals for type safety
RuntimeType = Literal["claude-code", "opencode"]

# List of all valid runtime choices (for argparse, validation, etc.)
RUNTIME_CHOICES: list[RuntimeType] = ["claude-code", "opencode"]

# Default runtime to use when none specified
DEFAULT_RUNTIME: RuntimeType = "claude-code"


@dataclass
class RuntimeCapabilities:
    """Describes what a runtime supports."""

    extended_thinking: bool = False
    mcp_servers: bool = False
    subagents: bool = False
    structured_output: bool = False
    streaming: bool = True


@dataclass
class RuntimeConfig:
    """Static configuration for a runtime (mirrors frontend RuntimeConfig)."""

    id: RuntimeType
    name: str
    has_dynamic_models: bool
    supports_thinking: bool
    requires_auth: bool
    model_prefix: str
    fast_model: str
    capabilities: RuntimeCapabilities = field(default_factory=RuntimeCapabilities)


RUNTIME_CONFIGS: dict[RuntimeType, RuntimeConfig] = {
    "claude-code": RuntimeConfig(
        id="claude-code",
        name="Claude Code",
        has_dynamic_models=False,
        supports_thinking=True,
        requires_auth=True,
        model_prefix="",
        fast_model="claude-haiku-4-5",
        capabilities=RuntimeCapabilities(
            extended_thinking=True,
            mcp_servers=True,
            subagents=True,
            structured_output=True,
        ),
    ),
    "opencode": RuntimeConfig(
        id="opencode",
        name="OpenCode",
        has_dynamic_models=True,
        supports_thinking=False,
        requires_auth=False,
        model_prefix="anthropic/",
        fast_model="opencode/grok-code",
        capabilities=RuntimeCapabilities(
            extended_thinking=False,
            mcp_servers=True,
            subagents=False,
            structured_output=True,
        ),
    ),
}


def get_runtime_config(runtime: RuntimeType) -> RuntimeConfig:
    """Get static configuration for a runtime."""
    return RUNTIME_CONFIGS.get(runtime, RUNTIME_CONFIGS[DEFAULT_RUNTIME])


@dataclass
class RuntimeInfo:
    """Runtime information including static config and dynamic availability."""

    config: RuntimeConfig
    available: bool = False
    version: str | None = None
    models: list[dict[str, Any]] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)


@dataclass
class RuntimeOptions:
    """
    Unified options for configuring an agent runtime.

    This provides a consistent interface for configuring any runtime,
    with runtime-specific options handled by subclasses or adapters.
    """

    # Required options
    model: str
    project_dir: Path
    spec_dir: Path

    # Agent configuration
    agent_type: str = "coder"
    system_prompt: str | None = None

    # Tool and MCP configuration
    allowed_tools: list[str] | None = None
    mcp_servers: dict[str, dict[str, Any]] | None = None

    # Thinking and output
    max_thinking_tokens: int | None = None
    max_turns: int = 1000
    output_format: dict[str, Any] | None = None

    # Subagents
    agents: dict[str, Any] | None = None

    # Security
    security: SecurityConfig | None = None

    # Project capabilities (detected from project analysis)
    project_capabilities: dict[str, bool] | None = None

    # Linear integration
    linear_enabled: bool = False

    # Per-project MCP configuration
    mcp_config: dict[str, Any] | None = None


class AgentRuntime(Protocol):
    """
    Protocol defining the interface for agent runtimes.

    All runtimes (Claude Code, OpenCode, etc.) must implement this interface.
    """

    async def query(self, message: str) -> None:
        """
        Send a query/prompt to the agent.

        Args:
            message: The message to send
        """
        ...

    def receive_response(self) -> AsyncIterator[AgentMessage]:
        """
        Receive streaming response from the agent.

        Yields:
            AgentMessage objects as they arrive
        """
        ...

    async def stop(self) -> None:
        """Stop the current agent session."""
        ...

    def is_running(self) -> bool:
        """Check if the agent session is currently running."""
        ...

    def get_runtime_name(self) -> str:
        """Get the name of this runtime."""
        ...

    def get_capabilities(self) -> RuntimeCapabilities:
        """Get the capabilities of this runtime."""
        ...
