"""
Runtime Factory Module
======================

Factory for creating agent runtimes based on configuration.
This is THE single entry point for creating AI agent runtimes.

Usage:
    from core.runtime import create_agent_runtime

    runtime = create_agent_runtime(
        project_dir=project_dir,
        spec_dir=spec_dir,
        model="claude-sonnet-4-5",
        agent_type="coder"
    )
"""

import logging
import subprocess
from pathlib import Path
from typing import Any

from .base import AgentRuntimeBase
from .claude_code import ClaudeCodeRuntime
from .opencode import OpenCodeRuntime
from .types import (
    DEFAULT_RUNTIME,
    RuntimeInfo,
    RuntimeOptions,
    RuntimeType,
    SecurityConfig,
    get_runtime_config,
)

logger = logging.getLogger(__name__)

RUNTIME_CLASSES: dict[RuntimeType, type[AgentRuntimeBase]] = {
    "claude-code": ClaudeCodeRuntime,
    "opencode": OpenCodeRuntime,
}


def get_runtime_class(runtime: RuntimeType) -> type[AgentRuntimeBase]:
    runtime_class = RUNTIME_CLASSES.get(runtime)
    if runtime_class is None:
        raise ValueError(f"Unknown runtime type: {runtime}")
    return runtime_class


def _validate_runtime_installed(runtime: str) -> None:
    """Raise RuntimeError if the specified runtime is not installed."""
    available = detect_available_runtimes()
    if runtime == "claude-code" and not available.get("claude-code"):
        raise RuntimeError(
            "Claude Code CLI is not installed or not accessible.\n"
            "Install it with: npm install -g @anthropic-ai/claude-code\n"
            "Then run: claude setup-token"
        )
    elif runtime == "opencode" and not available.get("opencode"):
        raise RuntimeError(
            "OpenCode CLI is not installed or not accessible.\n"
            "Install it with: npm install -g opencode-ai\n"
            "Then configure your API keys for your preferred provider."
        )


def detect_available_runtimes() -> dict[str, bool]:
    """
    Detect which runtimes are available on the system.

    Returns:
        Dict mapping runtime names to availability status
    """
    runtimes = {}

    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        runtimes["claude-code"] = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        runtimes["claude-code"] = False

    # Check for OpenCode
    runtimes["opencode"] = OpenCodeRuntime.is_available()

    return runtimes


def _get_default_system_prompt(project_dir: Path) -> str:
    """Get the default system prompt for agents."""
    return (
        f"You are an expert full-stack developer building production-quality software. "
        f"Your working directory is: {project_dir.resolve()}\n"
        f"Your filesystem access is RESTRICTED to this directory only. "
        f"Use relative paths (starting with ./) for all file operations. "
        f"Never use absolute paths or try to access files outside your working directory.\n\n"
        f"You follow existing code patterns, write clean maintainable code, and verify "
        f"your work through thorough testing. You communicate progress through Git commits "
        f"and build-progress.txt updates."
    )


def create_agent_runtime(
    project_dir: Path,
    spec_dir: Path,
    model: str,
    agent_type: str = "coder",
    *,  # Force keyword arguments below
    max_thinking_tokens: int | None = None,
    output_format: dict | None = None,
    max_turns: int = 1000,
    agents: dict | None = None,
    runtime: RuntimeType = DEFAULT_RUNTIME,
    system_prompt: str | None = None,
    allowed_tools: list[str] | None = None,
    mcp_servers: dict[str, dict[str, Any]] | None = None,
    security: SecurityConfig | None = None,
    project_capabilities: dict[str, bool] | None = None,
    linear_enabled: bool = False,
    mcp_config: dict[str, Any] | None = None,
) -> AgentRuntimeBase:
    """
    Create an agent runtime - THE unified factory function.

    This is the ONLY function that should be used to create agent runtimes.

    Args:
        project_dir: Root directory for the project
        spec_dir: Directory containing the spec
        model: Model ID to use (e.g., "claude-sonnet-4-5", "google/gemini-2.0-flash")
        agent_type: Agent type identifier ("coder", "planner", "qa_reviewer", etc.)
        max_thinking_tokens: Token budget for extended thinking (None = disabled)
        output_format: Optional structured output format
        agents: Optional subagent definitions
        runtime: Runtime type ("claude-code" or "opencode")
        system_prompt: Optional system prompt override
        allowed_tools: Optional list of allowed tools
        mcp_servers: Optional MCP server configurations
        security: Optional security configuration
        project_capabilities: Optional detected project capabilities
        linear_enabled: Whether Linear integration is enabled
        mcp_config: Optional per-project MCP configuration

    Returns:
        Configured AgentRuntimeBase instance

    Example:
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
    _validate_runtime_installed(runtime)

    # Build options
    options = RuntimeOptions(
        model=model,
        system_prompt=system_prompt or _get_default_system_prompt(project_dir),
        project_dir=project_dir,
        spec_dir=spec_dir,
        agent_type=agent_type,
        allowed_tools=allowed_tools,
        mcp_servers=mcp_servers,
        max_thinking_tokens=max_thinking_tokens,
        output_format=output_format,
        max_turns=max_turns,
        agents=agents,
        security=security,
        project_capabilities=project_capabilities,
        linear_enabled=linear_enabled,
        mcp_config=mcp_config,
    )

    # Create the appropriate runtime
    runtime_class = get_runtime_class(runtime)
    logger.info(f"Creating {runtime} runtime")
    instance = runtime_class(options=options, security=security)

    if max_thinking_tokens and not instance.supports_extended_thinking():
        logger.warning(
            f"Extended thinking requested but runtime {runtime} does not support it. "
            "Extended thinking will be disabled."
        )
        options.max_thinking_tokens = None

    return instance


# =============================================================================
# Runtime Information
# =============================================================================


def get_runtime_info(runtime: RuntimeType = DEFAULT_RUNTIME) -> RuntimeInfo:
    """
    Get information about a runtime including static config and dynamic availability.

    Args:
        runtime: Runtime type to get info for

    Returns:
        RuntimeInfo with config, availability, version, and models
    """
    config = get_runtime_config(runtime)
    info = RuntimeInfo(config=config)

    if runtime == "claude-code":
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                info.available = True
                info.version = result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    elif runtime == "opencode":
        if OpenCodeRuntime.is_available():
            info.available = True
            info.models = OpenCodeRuntime.get_available_models()
            info.providers = OpenCodeRuntime.get_model_providers()

    return info
