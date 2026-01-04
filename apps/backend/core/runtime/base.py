"""
Runtime Base Module
===================

Abstract base class for agent runtimes. Defines the interface that all
runtimes (Claude Code, OpenCode, Codex, Gemini CLI, etc.) must implement.

This is THE interface for all AI interactions in Auto Claude.
All code should use AgentRuntimeBase, never vendor-specific clients directly.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from types import TracebackType
from typing import Any, AsyncIterator

from .types import (
    AgentMessage,
    RuntimeCapabilities,
    RuntimeOptions,
    RuntimeType,
    SecurityConfig,
)

logger = logging.getLogger(__name__)


class AgentRuntimeBase(ABC):
    """
    Abstract base class for agent runtimes.

    This is the ONLY interface that should be used for AI interactions.
    All runtimes (Claude Code, OpenCode, future runtimes) implement this.

    Usage:
        from core.runtime import create_agent_runtime

        runtime = create_agent_runtime(
            project_dir=project_dir,
            spec_dir=spec_dir,
            model="claude-sonnet-4-5",
            agent_type="coder",
        )

        async with runtime:
            await runtime.query("Implement the feature")
            async for msg in runtime.receive_response():
                print(msg.get_text())
    """

    def __init__(
        self,
        options: RuntimeOptions,
        security: SecurityConfig | None = None,
    ):
        """
        Initialize the runtime.

        Args:
            options: Runtime configuration options
            security: Optional security configuration
        """
        self.options = options
        self.security = security or SecurityConfig()
        self._running = False

    # =========================================================================
    # Required Properties (from options)
    # =========================================================================

    @property
    def model(self) -> str:
        """Get the configured model ID."""
        return self.options.model

    @property
    def project_dir(self) -> Path:
        """Get the project directory."""
        return self.options.project_dir

    @property
    def spec_dir(self) -> Path:
        """Get the spec directory."""
        return self.options.spec_dir

    @property
    def agent_type(self) -> str:
        """Get the agent type (coder, planner, qa_reviewer, etc.)."""
        return self.options.agent_type

    # =========================================================================
    # Core Abstract Methods - Must be implemented by all runtimes
    # =========================================================================

    @abstractmethod
    async def query(self, message: str) -> None:
        """
        Send a query/prompt to the agent.

        Args:
            message: The message to send
        """
        pass

    @abstractmethod
    def receive_response(self) -> AsyncIterator[AgentMessage]:
        """
        Receive streaming response from the agent.

        Yields:
            AgentMessage objects as they arrive
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the current agent session."""
        pass

    @abstractmethod
    def get_runtime_name(self) -> str:
        """
        Get the name of this runtime.

        Returns:
            Runtime identifier (e.g., 'claude-code', 'opencode')
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> RuntimeCapabilities:
        """
        Get the capabilities of this runtime.

        Returns:
            RuntimeCapabilities describing what this runtime supports
        """
        pass

    # =========================================================================
    # Optional Methods with Default Implementations
    # =========================================================================

    def is_running(self) -> bool:
        """Check if the agent session is currently running."""
        return self._running

    def supports_extended_thinking(self) -> bool:
        """Check if this runtime supports extended thinking."""
        return self.get_capabilities().extended_thinking

    def supports_mcp_servers(self) -> bool:
        """Check if this runtime supports MCP servers."""
        return self.get_capabilities().mcp_servers

    def supports_subagents(self) -> bool:
        """Check if this runtime supports subagents."""
        return self.get_capabilities().subagents

    def supports_structured_output(self) -> bool:
        """Check if this runtime supports structured output."""
        return self.get_capabilities().structured_output

    def validate_model(self, model: str) -> bool:
        """
        Validate that a model ID is supported by this runtime.

        Args:
            model: Model ID to validate

        Returns:
            True if the model is supported
        """
        # Default implementation - subclasses should override
        return True

    def get_allowed_tools(self) -> list[str]:
        """
        Get the list of allowed tools for this runtime.

        Returns:
            List of tool names that are allowed
        """
        return self.options.allowed_tools or []

    def get_mcp_servers(self) -> dict[str, dict[str, Any]]:
        """
        Get the MCP server configurations.

        Returns:
            Dict of server_id -> server_config
        """
        return self.options.mcp_servers or {}

    def get_system_prompt(self) -> str:
        """
        Get the system prompt for this runtime.

        Returns:
            The system prompt string
        """
        return self.options.system_prompt or self._get_default_system_prompt()

    def _get_default_system_prompt(self) -> str:
        """Generate the default system prompt."""
        return (
            f"You are an expert full-stack developer building production-quality software. "
            f"Your working directory is: {self.project_dir.resolve()}\n"
            f"Your filesystem access is RESTRICTED to this directory only. "
            f"Use relative paths (starting with ./) for all file operations. "
            f"Never use absolute paths or try to access files outside your working directory.\n\n"
            f"You follow existing code patterns, write clean maintainable code, and verify "
            f"your work through thorough testing. You communicate progress through Git commits "
            f"and build-progress.txt updates."
        )

    # =========================================================================
    # Security Methods
    # =========================================================================

    def _apply_security_hooks(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """
        Apply all security hooks to a tool call.

        Args:
            tool_name: Name of the tool being called
            tool_input: Input parameters for the tool

        Returns:
            (allowed, error_message) - If not allowed, error_message explains why
        """
        for hook in self.security.pre_tool_hooks:
            allowed, error = hook(tool_name, tool_input)
            if not allowed:
                return False, error
        return True, None

    # =========================================================================
    # Context Manager Support
    # =========================================================================

    async def __aenter__(self) -> "AgentRuntimeBase":
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit - ensures runtime is stopped."""
        await self.stop()

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"model={self.model}, "
            f"agent_type={self.agent_type}, "
            f"project={self.project_dir})"
        )

    @classmethod
    def get_runtime_type(cls) -> RuntimeType:
        """
        Get the runtime type identifier.

        Returns:
            The RuntimeType literal for this runtime
        """
        raise NotImplementedError("Subclasses must implement get_runtime_type()")

    @staticmethod
    def is_available() -> bool:
        """
        Check if this runtime is available on the system.

        Returns:
            True if the runtime CLI/SDK is installed and accessible
        """
        raise NotImplementedError("Subclasses must implement is_available()")

    @staticmethod
    def get_available_models() -> list[dict[str, Any]]:
        """
        Get list of available models for this runtime.

        Returns:
            List of model info dicts with at least 'id' and 'provider' keys
        """
        return []

    @staticmethod
    def run_simple_query(prompt: str, cwd: Path, timeout: int = 120) -> str:
        """
        Run a simple one-shot query using the runtime's CLI.

        This is a synchronous fallback method for when the full async
        runtime fails or isn't available. Each runtime implementation
        should use its own CLI tool.

        Args:
            prompt: The prompt to send
            cwd: Working directory for the command
            timeout: Timeout in seconds (default: 120)

        Returns:
            The response text from the CLI

        Raises:
            RuntimeError: If the CLI is not available or query fails
        """
        raise NotImplementedError(
            "Subclasses must implement run_simple_query() for CLI fallback support"
        )
