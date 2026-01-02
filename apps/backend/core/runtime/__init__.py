"""
Runtime Abstraction Layer
=========================

Provides a unified interface for different agent runtimes:
- Claude Code (claude-agent-sdk)
- OpenCode (opencode-ai)
- Future runtimes (Codex, Gemini CLI, etc.)

This is THE interface for all AI interactions in Auto Claude.
Never import vendor-specific clients directly - always use this module.

Usage:
    from core.runtime import create_agent_runtime, AgentRuntimeBase

    # Create a runtime (auto-detects based on environment/config)
    runtime = create_agent_runtime(
        project_dir=project_dir,
        spec_dir=spec_dir,
        model="claude-sonnet-4-5",
        agent_type="coder",
    )

    # Use specific runtime
    runtime = create_agent_runtime(
        ...,
        runtime="opencode",
    )

    # Run agent session
    async with runtime:
        await runtime.query("Implement the feature")
        async for msg in runtime.receive_response():
            print(msg.get_text())

Type Annotations:
    # Always use AgentRuntimeBase for type hints
    def my_function(runtime: AgentRuntimeBase) -> None:
        ...
"""

from .base import AgentRuntimeBase
from .claude_code import ClaudeCodeRuntime
from .config import (
    build_mcp_servers,
    generate_security_settings,
    get_electron_debug_port,
    get_graphiti_mcp_url,
    is_electron_mcp_enabled,
    is_graphiti_mcp_enabled,
    load_claude_md,
    load_project_mcp_config,
    should_use_claude_md,
    validate_custom_mcp_server,
    write_security_settings,
)
from .factory import (
    RuntimeType,
    create_agent_runtime,
    detect_available_runtimes,
    get_runtime_info,
)
from .opencode import OpenCodeRuntime
from .types import (
    DEFAULT_RUNTIME,
    RUNTIME_CHOICES,
    AgentMessage,
    RuntimeCapabilities,
    RuntimeOptions,
    BlockType,
    ContentBlock,
    MCPServerConfig,
    MessageRole,
    SecurityConfig,
    SecurityHook,
)

__all__ = [
    # Main factory function (THE entry point)
    "create_agent_runtime",
    # Factory utilities
    "detect_available_runtimes",
    "get_runtime_info",
    "RuntimeType",
    "DEFAULT_RUNTIME",
    "RUNTIME_CHOICES",
    # Base class (THE type to use for annotations)
    "AgentRuntimeBase",
    # Implementations (rarely needed directly)
    "ClaudeCodeRuntime",
    "OpenCodeRuntime",
    # Types
    "AgentMessage",
    "RuntimeCapabilities",
    "RuntimeOptions",
    "BlockType",
    "ContentBlock",
    "MCPServerConfig",
    "MessageRole",
    "SecurityConfig",
    "SecurityHook",
    # Config helpers (for advanced usage)
    "build_mcp_servers",
    "generate_security_settings",
    "load_project_mcp_config",
    "validate_custom_mcp_server",
    "write_security_settings",
    "is_graphiti_mcp_enabled",
    "get_graphiti_mcp_url",
    "is_electron_mcp_enabled",
    "get_electron_debug_port",
    "should_use_claude_md",
    "load_claude_md",
]
