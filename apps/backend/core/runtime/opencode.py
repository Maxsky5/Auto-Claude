"""
OpenCode Runtime
================

Runtime implementation for OpenCode CLI.
Uses ACP (Agent Client Protocol) via stdio for true streaming support.
"""

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

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

ACP_PROTOCOL_VERSION = 1


class OpenCodeRuntime(AgentRuntimeBase):
    # Flush buffer after this many seconds of no new chunks
    TEXT_BUFFER_FLUSH_TIMEOUT = 1  # 1sec

    def __init__(
        self,
        options: RuntimeOptions,
        security: SecurityConfig | None = None,
    ):
        super().__init__(options, security)
        self._process: asyncio.subprocess.Process | None = None
        self._response_queue: asyncio.Queue[AgentMessage | None] = asyncio.Queue()
        self._available_models: list[dict[str, Any]] | None = None
        self._session_id: str | None = None
        self._request_id: int = 0
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._initialized: bool = False
        # Text buffering for batching streaming chunks
        self._text_buffer: str = ""
        self._flush_task: asyncio.Task | None = None

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
        return model

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send_jsonrpc(self, method: str, params: dict | None = None) -> int:
        if not self._process or not self._process.stdin:
            raise RuntimeError("ACP process not started")

        req_id = self._next_request_id()
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params:
            request["params"] = params

        line = json.dumps(request) + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()
        return req_id

    async def _wait_for_response(self, req_id: int, timeout: float = 30.0) -> dict:
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending_requests[req_id] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending_requests.pop(req_id, None)

    async def _read_stdout_loop(self):
        if not self._process or not self._process.stdout:
            return

        while True:
            try:
                line_bytes = await self._process.stdout.readline()
                if not line_bytes:
                    break

                line_str = line_bytes.decode().strip()
                if not line_str:
                    continue

                try:
                    msg = json.loads(line_str)
                    await self._handle_jsonrpc_message(msg)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from ACP: {line_str[:100]}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reading ACP output: {e}")
                break

    async def _drain_stderr(self):
        if not self._process or not self._process.stderr:
            return
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _handle_jsonrpc_message(self, msg: dict):
        msg_id = msg.get("id")

        if msg_id is not None and msg_id in self._pending_requests:
            future = self._pending_requests.get(msg_id)
            if future and not future.done():
                if "error" in msg:
                    future.set_exception(
                        RuntimeError(msg["error"].get("message", str(msg["error"])))
                    )
                else:
                    future.set_result(msg.get("result", {}))

        elif msg_id is not None and "result" in msg:
            result = msg.get("result", {})
            if result.get("stopReason"):
                await self._response_queue.put(None)

        elif msg.get("method") == "session/update":
            params = msg.get("params", {})
            update = params.get("update", {})
            await self._handle_session_update(update)

    async def _flush_text_buffer(self) -> None:
        if self._text_buffer:
            await self._response_queue.put(
                AgentMessage(
                    role=MessageRole.ASSISTANT,
                    content=[ContentBlock(type=BlockType.TEXT, text=self._text_buffer)],
                )
            )
            self._text_buffer = ""

    def _cancel_flush_task(self) -> None:
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            self._flush_task = None

    async def _schedule_flush(self) -> None:
        self._cancel_flush_task()

        async def delayed_flush():
            await asyncio.sleep(self.TEXT_BUFFER_FLUSH_TIMEOUT)
            await self._flush_text_buffer()

        self._flush_task = asyncio.create_task(delayed_flush())

    async def _handle_session_update(self, update: dict):
        update_type = update.get("sessionUpdate") or update.get("type")
        content = update.get("content", {})

        if update_type == "agent_message_chunk":
            if content.get("type") == "text":
                text = content.get("text", "")
                if text:
                    self._text_buffer += text
                    if "\n" in text:
                        self._cancel_flush_task()
                        await self._flush_text_buffer()
                    else:
                        await self._schedule_flush()

        elif update_type == "agent_message":
            self._cancel_flush_task()
            await self._flush_text_buffer()

            for block in update.get("content", []):
                if block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        await self._response_queue.put(
                            AgentMessage(
                                role=MessageRole.ASSISTANT,
                                content=[ContentBlock(type=BlockType.TEXT, text=text)],
                            )
                        )
                elif block.get("type") == "tool_use":
                    await self._response_queue.put(
                        AgentMessage(
                            role=MessageRole.ASSISTANT,
                            content=[
                                ContentBlock(
                                    type=BlockType.TOOL_USE,
                                    tool_name=block.get("name", ""),
                                    tool_input=block.get("input", {}),
                                )
                            ],
                        )
                    )

        elif update_type in ("finish", "agent_finish", "session_finish"):
            self._cancel_flush_task()
            await self._flush_text_buffer()
            await self._response_queue.put(None)

        elif update_type == "tool_call":
            self._cancel_flush_task()
            await self._flush_text_buffer()

            tool_name = update.get("title", "") or update.get("name", "unknown")
            tool_id = update.get("toolCallId", "")
            raw_input = update.get("rawInput", {})

            await self._response_queue.put(
                AgentMessage(
                    role=MessageRole.ASSISTANT,
                    content=[
                        ContentBlock(
                            type=BlockType.TOOL_USE,
                            tool_name=tool_name,
                            tool_input=raw_input,
                            tool_id=tool_id,
                        )
                    ],
                )
            )

        elif update_type == "tool_call_update":
            tool_id = update.get("toolCallId", "")
            status = update.get("status", "")
            raw_output = update.get("rawOutput", "")
            content_list = update.get("content", [])

            result_text = raw_output
            if not result_text and content_list:
                for item in content_list:
                    if isinstance(item, dict) and item.get("type") == "text":
                        result_text = item.get("text", "")
                        break

            is_error = status == "failed"

            await self._response_queue.put(
                AgentMessage(
                    role=MessageRole.USER,
                    content=[
                        ContentBlock(
                            type=BlockType.TOOL_RESULT,
                            text=result_text[:500] if result_text else "",
                            tool_id=tool_id,
                            is_error=is_error,
                        )
                    ],
                )
            )

    async def _start_acp_process(self):
        env = os.environ.copy()
        env["OPENCODE_NON_INTERACTIVE"] = "1"

        cmd = ["opencode", "acp", "--cwd", str(self.options.project_dir.resolve())]

        logger.debug(f"Starting OpenCode ACP: {' '.join(cmd)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError:
            self._running = False
            raise RuntimeError(
                "OpenCode CLI not found. Please install it: npm install -g opencode-ai"
            )

        self._reader_task = asyncio.create_task(self._read_stdout_loop())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _initialize_acp(self):
        if self._initialized:
            return

        req_id = await self._send_jsonrpc(
            "initialize",
            {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "clientInfo": {"name": "auto-claude", "version": "1.0.0"},
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": True,
                },
            },
        )

        await self._wait_for_response(req_id, timeout=10.0)
        self._initialized = True

    async def _create_session(self) -> str:
        req_id = await self._send_jsonrpc(
            "session/new",
            {
                "cwd": str(self.options.project_dir.resolve()),
                "mcpServers": [],
            },
        )

        # session/new takes 10-15s as OpenCode loads MCP servers
        result = await self._wait_for_response(req_id, timeout=30.0)
        session_id = result.get("sessionId") or result.get("session_id")
        if not session_id:
            raise RuntimeError("Failed to create ACP session: no session ID returned")
        return session_id

    async def query(self, message: str) -> None:
        self._running = True

        if not self._process:
            await self._start_acp_process()
            await self._initialize_acp()
            self._session_id = await self._create_session()

        final_message = message
        if self.options.system_prompt:
            final_message = f"{self.options.system_prompt}\n\n{message}"

        model_id = self._resolve_model_id(self.options.model)

        prompt_content = [{"type": "text", "text": final_message}]

        await self._send_jsonrpc(
            "session/prompt",
            {
                "sessionId": self._session_id,
                "prompt": prompt_content,
                "model": model_id,
            },
        )

    async def receive_response(self):
        if not self._process:
            return

        try:
            while True:
                msg = await asyncio.wait_for(self._response_queue.get(), timeout=300.0)
                if msg is None:
                    break
                yield msg
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for ACP response")
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    async def stop(self) -> None:
        self._cancel_flush_task()

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None

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
        self._initialized = False
        self._session_id = None

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

    @staticmethod
    def run_simple_query(prompt: str, cwd: Path, timeout: int = 120) -> str:
        try:
            result = subprocess.run(
                ["opencode", "run", "--format", "text", prompt],
                capture_output=True,
                text=True,
                cwd=str(cwd),
                timeout=timeout,
                env={**os.environ, "OPENCODE_NON_INTERACTIVE": "1"},
            )
            if result.returncode == 0:
                return result.stdout
            raise RuntimeError(
                f"OpenCode CLI failed with exit code {result.returncode}: {result.stderr}"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"OpenCode CLI timed out after {timeout}s")
        except FileNotFoundError:
            raise RuntimeError(
                "OpenCode CLI not found. Please install: npm install -g opencode-ai"
            )
