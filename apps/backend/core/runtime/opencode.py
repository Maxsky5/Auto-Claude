"""
OpenCode Runtime
================

Runtime implementation for OpenCode CLI.
Uses subprocess to communicate with the `opencode` command.
"""

import asyncio
import json
import logging
import os
import subprocess
from typing import Any, AsyncIterator

from .base import AgentRuntimeBase
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


class OpenCodeRuntime(AgentRuntimeBase):
    """
    Runtime implementation for OpenCode.

    This communicates with the `opencode` CLI tool via subprocess,
    similar to how claude-agent-sdk wraps the `claude` CLI.
    """

    def __init__(
        self,
        options: RuntimeOptions,
        security: SecurityConfig | None = None,
    ):
        """
        Initialize the OpenCode runtime.

        Args:
            options: Runtime configuration options
            security: Optional security configuration
        """
        super().__init__(options, security)
        self._process: asyncio.subprocess.Process | None = None
        self._response_queue: asyncio.Queue[AgentMessage] = asyncio.Queue()
        self._available_models: list[dict[str, Any]] | None = None

    @staticmethod
    def is_available() -> bool:
        """
        Check if OpenCode CLI is available on the system.

        Returns:
            True if `opencode` command is available
        """
        try:
            result = subprocess.run(
                ["opencode", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def get_available_models() -> list[dict[str, Any]]:
        """
        Get list of available models from OpenCode.

        Returns:
            List of model configurations with id, provider, etc.
        """
        try:
            result = subprocess.run(
                ["opencode", "models"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning(f"Failed to get OpenCode models: {result.stderr}")
                return []

            models = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                provider = line.split("/")[0] if "/" in line else "unknown"
                models.append(
                    {
                        "id": line,
                        "provider": provider,
                    }
                )
            return models

        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.warning(f"Error getting OpenCode models: {e}")
            return []

    @staticmethod
    def get_model_providers() -> list[str]:
        """
        Get list of available model providers.

        Returns:
            List of provider names (e.g., ['anthropic', 'openai', 'google'])
        """
        models = OpenCodeRuntime.get_available_models()
        providers = set()
        for model in models:
            if "provider" in model:
                providers.add(model["provider"])
            elif "/" in model.get("id", ""):
                # Extract provider from id (e.g., "anthropic/claude-sonnet-4-5")
                providers.add(model["id"].split("/")[0])
        return sorted(providers)

    def _resolve_model_id(self, model: str) -> str:
        """Pass through model ID directly - no translation needed."""
        return model

    async def query(self, message: str) -> None:
        """
        Send a query to OpenCode.

        This starts a new OpenCode process with the given prompt.
        """
        self._running = True

        # Resolve model ID to OpenCode format
        model_id = self._resolve_model_id(self.options.model)

        # Build the command
        cmd = [
            "opencode",
            "run",
            "--model",
            model_id,
            "--format",
            "json",
        ]

        final_message = message
        if self.options.system_prompt:
            final_message = f"{self.options.system_prompt}\n\n{message}"

        cmd.append(final_message)

        # Set up environment
        env = os.environ.copy()
        env["OPENCODE_NON_INTERACTIVE"] = "1"

        logger.debug(f"Starting OpenCode: {' '.join(cmd[:6])}...")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,  # Ensure we don't hang waiting for input
                cwd=str(self.options.project_dir.resolve()),
                env=env,
            )
        except FileNotFoundError:
            self._running = False
            raise RuntimeError(
                "OpenCode CLI not found. Please install it: npm install -g opencode-ai"
            )

    async def receive_response(self):
        """
        Receive streaming response from OpenCode.

        Parses the output stream and yields unified AgentMessage objects.
        """
        if not self._process or not self._process.stdout:
            return

        try:
            while True:
                line = await self._process.stdout.readline()

                if not line:
                    break

                line_str = ""
                try:
                    line_str = line.decode().strip()
                    if not line_str:
                        continue

                    event = json.loads(line_str)
                    parsed_messages = self._parse_json_event(event)
                    for msg in parsed_messages:
                        yield msg

                except (json.JSONDecodeError, UnicodeDecodeError):
                    if line_str and not line_str.startswith("{"):
                        yield AgentMessage(
                            role=MessageRole.ASSISTANT,
                            content=[ContentBlock(type=BlockType.TEXT, text=line_str)],
                        )

            await self._process.wait()

            if self._process.returncode != 0:
                stderr_bytes = (
                    await self._process.stderr.read() if self._process.stderr else b""
                )
                stderr = stderr_bytes.decode()
                if stderr:
                    yield AgentMessage(
                        role=MessageRole.ASSISTANT,
                        content=[
                            ContentBlock(
                                type=BlockType.TEXT,
                                text=f"\n[Error] {stderr}",
                            )
                        ],
                    )

        finally:
            self._running = False

    def _parse_json_event(self, event: dict[str, Any]) -> list[AgentMessage]:
        """
        Parse a JSON event from OpenCode.

        Args:
            event: Parsed JSON event

        Returns:
            List of AgentMessages extracted from the event
        """
        messages = []
        event_type = event.get("type")
        part = event.get("part", {})

        if event_type == "text":
            text = part.get("text", "")
            if text:
                messages.append(
                    AgentMessage(
                        role=MessageRole.ASSISTANT,
                        content=[ContentBlock(type=BlockType.TEXT, text=text)],
                    )
                )

        elif event_type == "tool_use":
            tool_name = part.get("tool")
            state = part.get("state", {})
            status = state.get("status")
            input_data = state.get("input", {})
            output_data = state.get("output", "")

            messages.append(
                AgentMessage(
                    role=MessageRole.ASSISTANT,
                    content=[
                        ContentBlock(
                            type=BlockType.TOOL_USE,
                            tool_name=tool_name,
                            tool_input=input_data,
                        )
                    ],
                )
            )

            if status == "completed":
                output_str = str(output_data) if output_data is not None else ""

                messages.append(
                    AgentMessage(
                        role=MessageRole.USER,
                        content=[
                            ContentBlock(
                                type=BlockType.TOOL_RESULT,
                                text=output_str,
                                is_error="Error:" in output_str
                                or "failed" in output_str.lower(),
                            )
                        ],
                    )
                )

        return messages

    async def stop(self) -> None:
        """Stop the OpenCode process."""
        if self._process:
            try:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._process.kill()
            except ProcessLookupError:
                pass
            self._process = None
        self._running = False

    def get_runtime_name(self) -> str:
        """Get the runtime name."""
        return "opencode"

    def get_capabilities(self) -> RuntimeCapabilities:
        """Get the capabilities of OpenCode runtime."""
        return RuntimeCapabilities(
            extended_thinking=False,  # Only Claude models support this
            mcp_servers=True,
            subagents=False,  # Not implemented yet
            structured_output=True,
            streaming=True,
        )

    @classmethod
    def get_runtime_type(cls) -> RuntimeType:
        """Get the runtime type identifier."""
        return "opencode"

    def supports_extended_thinking(self) -> bool:
        return False

    def supports_mcp_servers(self) -> bool:
        """
        Check if MCP servers are supported.

        OpenCode has its own MCP server configuration.
        """
        return True

    def validate_model(self, model: str) -> bool:
        """Validate that a model is available in OpenCode."""
        resolved = self._resolve_model_id(model)
        if self._available_models is None:
            self._available_models = self.get_available_models()

        # Check if model exists in available models
        for available in self._available_models:
            if available.get("id") == resolved:
                return True
            if available.get("name") == resolved:
                return True

        # If we couldn't fetch models, allow it (will fail at runtime if invalid)
        if not self._available_models:
            return True

        return False
