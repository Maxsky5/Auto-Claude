"""
Claude Code Runtime
===================

Runtime implementation wrapping the Claude Agent SDK (claude-agent-sdk).
This provides the ClaudeSDKClient interface through our unified abstraction.

This is the primary runtime for Auto Claude, providing full access to:
- Extended thinking (ultrathink, high, medium levels)
- MCP servers (Context7, Linear, Graphiti, Electron, Puppeteer)
- Subagents for parallel work
- Structured output with JSON schema validation
- Security hooks for Bash command validation
"""

import logging
import os
from pathlib import Path
from typing import Any, AsyncIterator

from .base import AgentRuntimeBase
from .config import (
    build_mcp_servers,
    generate_security_settings,
    get_electron_debug_port,
    is_graphiti_mcp_enabled,
    load_claude_md,
    load_project_mcp_config,
    should_use_claude_md,
    write_security_settings,
)
from .types import (
    AgentMessage,
    RuntimeCapabilities,
    RuntimeOptions,
    RuntimeType,
    BlockType,
    ContentBlock,
    MessageRole,
    SecurityConfig,
)

logger = logging.getLogger(__name__)


class ClaudeCodeRuntime(AgentRuntimeBase):
    """
    Runtime implementation for Claude Code (claude-agent-sdk).

    This wraps the existing ClaudeSDKClient and provides the unified
    AgentRuntime interface.
    """

    def __init__(
        self,
        options: RuntimeOptions,
        security: SecurityConfig | None = None,
        sdk_client: Any | None = None,
    ):
        """
        Initialize the Claude Code runtime.

        Args:
            options: Runtime configuration options
            security: Optional security configuration
            sdk_client: Optional pre-configured ClaudeSDKClient instance
        """
        super().__init__(options, security)
        self._sdk_client = sdk_client
        self._initialized = sdk_client is not None

    def _ensure_initialized(self) -> None:
        """Ensure the SDK client is initialized."""
        if self._initialized:
            return

        # Import here to avoid circular imports and allow lazy loading
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        from claude_agent_sdk.types import HookMatcher

        from core.auth import get_sdk_env_vars, require_auth_token
        from security import bash_security_hook

        # Get OAuth token
        oauth_token = require_auth_token()
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token

        # Get SDK env vars
        sdk_env = get_sdk_env_vars()

        # Write security settings
        settings_file = self._write_security_settings()

        # Build options
        sdk_options = ClaudeAgentOptions(
            model=self.options.model,
            system_prompt=self.options.system_prompt,
            allowed_tools=self.options.allowed_tools,
            mcp_servers=self.options.mcp_servers or {},
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="Bash", hooks=[bash_security_hook]),
                ],
            },
            max_turns=self.options.max_turns,
            cwd=str(self.options.project_dir.resolve()),
            settings=str(settings_file.resolve()),
            env=sdk_env,
            max_thinking_tokens=self.options.max_thinking_tokens,
        )

        # Add optional parameters
        if self.options.output_format:
            sdk_options.output_format = self.options.output_format
        if self.options.agents:
            sdk_options.agents = self.options.agents

        self._sdk_client = ClaudeSDKClient(options=sdk_options)
        self._initialized = True

    def _write_security_settings(self) -> Path:
        required_servers = self._get_required_servers()
        graphiti_enabled = "graphiti" in required_servers and is_graphiti_mcp_enabled()
        browser_tools = self._get_browser_tools_permissions(required_servers)

        security_settings = generate_security_settings(
            project_dir=self.options.project_dir,
            spec_dir=self.options.spec_dir,
            required_servers=required_servers,
            graphiti_enabled=graphiti_enabled,
            browser_tools_permissions=browser_tools,
        )

        return write_security_settings(self.options.project_dir, security_settings)

    def _get_required_servers(self) -> set[str]:
        if self.options.mcp_servers:
            return set(self.options.mcp_servers.keys())
        return set()

    def _get_browser_tools_permissions(self, required_servers: set[str]) -> list[str]:
        from agents.tools_pkg import ELECTRON_TOOLS, PUPPETEER_TOOLS

        if "electron" in required_servers:
            return list(ELECTRON_TOOLS)
        elif "puppeteer" in required_servers:
            return list(PUPPETEER_TOOLS)
        return []

    async def query(self, message: str) -> None:
        """Send a query to Claude Code."""
        self._ensure_initialized()
        self._running = True
        await self._sdk_client.query(message)

    async def receive_response(self) -> AsyncIterator[AgentMessage]:
        """Receive streaming response from Claude Code."""
        self._ensure_initialized()

        async for msg in self._sdk_client.receive_response():
            yield self._convert_message(msg)

        self._running = False

    async def stop(self) -> None:
        """Stop the Claude Code session."""
        if self._sdk_client:
            # SDK may have a stop method
            if hasattr(self._sdk_client, "stop"):
                await self._sdk_client.stop()
        self._running = False

    def _convert_message(self, sdk_msg: Any) -> AgentMessage:
        """
        Convert a Claude SDK message to our unified AgentMessage format.

        Args:
            sdk_msg: Message from the Claude SDK

        Returns:
            Unified AgentMessage
        """
        msg_type = type(sdk_msg).__name__
        content_blocks: list[ContentBlock] = []

        if msg_type == "AssistantMessage" and hasattr(sdk_msg, "content"):
            role = MessageRole.ASSISTANT
            for block in sdk_msg.content:
                block_type = type(block).__name__

                if block_type == "TextBlock" and hasattr(block, "text"):
                    content_blocks.append(
                        ContentBlock(type=BlockType.TEXT, text=block.text)
                    )
                elif block_type == "ToolUseBlock" and hasattr(block, "name"):
                    content_blocks.append(
                        ContentBlock(
                            type=BlockType.TOOL_USE,
                            tool_name=block.name,
                            tool_input=getattr(block, "input", {}),
                            tool_id=getattr(block, "id", None),
                        )
                    )
                elif block_type == "ThinkingBlock" and hasattr(block, "thinking"):
                    content_blocks.append(
                        ContentBlock(type=BlockType.THINKING, text=block.thinking)
                    )

        elif msg_type == "UserMessage" and hasattr(sdk_msg, "content"):
            role = MessageRole.USER
            for block in sdk_msg.content:
                block_type = type(block).__name__

                if block_type == "ToolResultBlock":
                    content_blocks.append(
                        ContentBlock(
                            type=BlockType.TOOL_RESULT,
                            text=str(getattr(block, "content", "")),
                            tool_id=getattr(block, "tool_use_id", None),
                            is_error=getattr(block, "is_error", False),
                        )
                    )
        else:
            # Unknown message type - wrap as-is
            role = MessageRole.ASSISTANT
            content_blocks.append(ContentBlock(type=BlockType.TEXT, text=str(sdk_msg)))

        return AgentMessage(role=role, content=content_blocks, raw=sdk_msg)

    def get_runtime_name(self) -> str:
        """Get the runtime name."""
        return "claude-code"

    def get_capabilities(self) -> RuntimeCapabilities:
        """Get the capabilities of Claude Code runtime."""
        return RuntimeCapabilities(
            extended_thinking=True,
            mcp_servers=True,
            subagents=True,
            structured_output=True,
            streaming=True,
        )

    @classmethod
    def get_runtime_type(cls) -> RuntimeType:
        """Get the runtime type identifier."""
        return "claude-code"

    def supports_extended_thinking(self) -> bool:
        """Claude Code supports extended thinking."""
        return True

    def supports_mcp_servers(self) -> bool:
        """Claude Code supports MCP servers."""
        return True

    def validate_model(self, model: str) -> bool:
        """Validate a Claude model ID."""
        # Claude models start with "claude-" or are shorthands
        valid_prefixes = ("claude-", "opus", "sonnet", "haiku")
        return any(model.startswith(prefix) for prefix in valid_prefixes)

    @property
    def sdk_client(self) -> Any:
        """Get the underlying SDK client (for backwards compatibility)."""
        self._ensure_initialized()
        return self._sdk_client

    @staticmethod
    def run_simple_query(prompt: str, cwd: Path, timeout: int = 120) -> str:
        import subprocess

        try:
            result = subprocess.run(
                ["claude", "--print", "-p", prompt],
                capture_output=True,
                text=True,
                cwd=str(cwd),
                timeout=timeout,
            )
            if result.returncode == 0:
                return result.stdout
            raise RuntimeError(
                f"Claude CLI failed with exit code {result.returncode}: {result.stderr}"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Claude CLI timed out after {timeout}s")
        except FileNotFoundError:
            raise RuntimeError(
                "Claude CLI not found. Please install: npm install -g @anthropic-ai/claude-code"
            )
