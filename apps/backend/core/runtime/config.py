"""
Runtime Configuration Helpers
==============================

Configuration helpers for the runtime abstraction layer.
These functions handle project-specific MCP configuration, security settings,
and other configuration tasks that were previously in core/client.py.

This module is used by ClaudeCodeRuntime and the factory to configure runtimes.
"""

import copy
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from prompts_pkg.project_context import detect_project_capabilities, load_project_index

logger = logging.getLogger(__name__)


# =============================================================================
# Project Index Cache
# =============================================================================
# Caches project index and capabilities to avoid reloading on every create_client() call.
# This significantly reduces the time to create new agent sessions.

_PROJECT_INDEX_CACHE: dict[str, tuple[dict[str, Any], dict[str, bool], float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minute TTL
_CACHE_LOCK = threading.Lock()  # Protects _PROJECT_INDEX_CACHE access


def get_cached_project_data(
    project_dir: Path,
) -> tuple[dict[str, Any], dict[str, bool]]:
    """
    Get project index and capabilities with caching.

    Args:
        project_dir: Path to the project directory

    Returns:
        Tuple of (project_index, project_capabilities)
    """

    key = str(project_dir.resolve())
    now = time.time()
    debug = os.environ.get("DEBUG", "").lower() in ("true", "1")

    # Check cache with lock
    with _CACHE_LOCK:
        if key in _PROJECT_INDEX_CACHE:
            cached_index, cached_capabilities, cached_time = _PROJECT_INDEX_CACHE[key]
            cache_age = now - cached_time
            if cache_age < _CACHE_TTL_SECONDS:
                if debug:
                    print(
                        f"[ClientCache] Cache HIT for project index (age: {cache_age:.1f}s / TTL: {_CACHE_TTL_SECONDS}s)"
                    )
                logger.debug(f"Using cached project index for {project_dir}")
                # Return deep copies to prevent callers from corrupting the cache
                return copy.deepcopy(cached_index), copy.deepcopy(cached_capabilities)
            elif debug:
                print(
                    f"[ClientCache] Cache EXPIRED for project index (age: {cache_age:.1f}s > TTL: {_CACHE_TTL_SECONDS}s)"
                )

    # Cache miss or expired - load fresh data (outside lock to avoid blocking)
    load_start = time.time()
    logger.debug(f"Loading project index for {project_dir}")
    project_index = load_project_index(project_dir)
    project_capabilities = detect_project_capabilities(project_index)

    if debug:
        load_duration = (time.time() - load_start) * 1000
        print(
            f"[ClientCache] Cache MISS - loaded project index in {load_duration:.1f}ms"
        )

    # Store in cache with lock - use double-checked locking pattern
    # Re-check if another thread populated the cache while we were loading
    with _CACHE_LOCK:
        if key in _PROJECT_INDEX_CACHE:
            cached_index, cached_capabilities, cached_time = _PROJECT_INDEX_CACHE[key]
            cache_age = time.time() - cached_time
            if cache_age < _CACHE_TTL_SECONDS:
                # Another thread already cached valid data while we were loading
                if debug:
                    print(
                        "[ClientCache] Cache was populated by another thread, using cached data"
                    )
                # Return deep copies to prevent callers from corrupting the cache
                return copy.deepcopy(cached_index), copy.deepcopy(cached_capabilities)
        # Either no cache entry or it's expired - store our fresh data
        _PROJECT_INDEX_CACHE[key] = (project_index, project_capabilities, time.time())

    # Return the freshly loaded data (no need to copy since it's not from cache)
    return project_index, project_capabilities


def invalidate_project_cache(project_dir: Path | None = None) -> None:
    """
    Invalidate the project index cache.

    Args:
        project_dir: Specific project to invalidate, or None to clear all
    """
    with _CACHE_LOCK:
        if project_dir is None:
            _PROJECT_INDEX_CACHE.clear()
            logger.debug("Cleared all project index cache entries")
        else:
            key = str(project_dir.resolve())
            if key in _PROJECT_INDEX_CACHE:
                del _PROJECT_INDEX_CACHE[key]
                logger.debug(f"Invalidated project index cache for {project_dir}")


# =============================================================================
# MCP Server Validation
# =============================================================================


def validate_custom_mcp_server(server: dict) -> bool:
    """
    Validate a custom MCP server configuration for security.

    Ensures only expected fields with valid types are present.
    Rejects configurations that could lead to command injection.

    Args:
        server: Dict representing a custom MCP server configuration

    Returns:
        True if valid, False otherwise
    """
    if not isinstance(server, dict):
        return False

    # Required fields
    required_fields = {"id", "name", "type"}
    if not all(field in server for field in required_fields):
        logger.warning(
            f"Custom MCP server missing required fields: {required_fields - server.keys()}"
        )
        return False

    # Validate field types
    if not isinstance(server.get("id"), str) or not server["id"]:
        return False
    if not isinstance(server.get("name"), str) or not server["name"]:
        return False
    if server.get("type") not in ("command", "http"):
        logger.warning(f"Invalid MCP server type: {server.get('type')}")
        return False

    # Allowlist of safe executable commands for MCP servers
    SAFE_COMMANDS = {
        "npx",
        "npm",
        "node",
        "python",
        "python3",
        "uv",
        "uvx",
    }

    # Blocklist of dangerous shell commands
    DANGEROUS_COMMANDS = {
        "bash",
        "sh",
        "cmd",
        "powershell",
        "pwsh",
        "/bin/bash",
        "/bin/sh",
        "/bin/zsh",
        "/usr/bin/bash",
        "/usr/bin/sh",
        "zsh",
        "fish",
    }

    # Dangerous interpreter flags
    DANGEROUS_FLAGS = {
        "--eval",
        "-e",
        "-c",
        "--exec",
        "-m",
        "-p",
        "--print",
        "--input-type=module",
        "--experimental-loader",
        "--require",
        "-r",
    }

    # Type-specific validation
    if server["type"] == "command":
        if not isinstance(server.get("command"), str) or not server["command"]:
            logger.warning("Command-type MCP server missing 'command' field")
            return False

        command = server.get("command", "")

        # Reject paths - commands must be bare names only
        if "/" in command or "\\" in command:
            logger.warning(
                f"Rejected command with path in MCP server: {command}. "
                f"Commands must be bare names without path separators."
            )
            return False

        if command in DANGEROUS_COMMANDS:
            logger.warning(
                f"Rejected dangerous command in MCP server: {command}. "
                f"Shell commands are not allowed for security reasons."
            )
            return False

        if command not in SAFE_COMMANDS:
            logger.warning(
                f"Rejected unknown command in MCP server: {command}. "
                f"Only allowed commands: {', '.join(sorted(SAFE_COMMANDS))}"
            )
            return False

        # Validate args
        if "args" in server:
            if not isinstance(server["args"], list):
                return False
            if not all(isinstance(arg, str) for arg in server["args"]):
                return False
            for arg in server["args"]:
                if arg in DANGEROUS_FLAGS:
                    logger.warning(
                        f"Rejected dangerous flag '{arg}' in MCP server args. "
                        f"Interpreter code execution flags are not allowed."
                    )
                    return False
    elif server["type"] == "http":
        if not isinstance(server.get("url"), str) or not server["url"]:
            logger.warning("HTTP-type MCP server missing 'url' field")
            return False
        if "headers" in server:
            if not isinstance(server["headers"], dict):
                return False
            if not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in server["headers"].items()
            ):
                return False

    # Optional description
    if "description" in server and not isinstance(server.get("description"), str):
        return False

    # Reject unexpected fields
    allowed_fields = {
        "id",
        "name",
        "type",
        "command",
        "args",
        "url",
        "headers",
        "description",
    }
    unexpected_fields = set(server.keys()) - allowed_fields
    if unexpected_fields:
        logger.warning(f"Custom MCP server has unexpected fields: {unexpected_fields}")
        return False

    return True


# =============================================================================
# Project MCP Configuration
# =============================================================================


def load_project_mcp_config(project_dir: Path) -> dict[str, Any]:
    """
    Load MCP configuration from project's .auto-claude/.env file.

    Returns a dict of MCP-related env vars:
    - CONTEXT7_ENABLED (default: true)
    - LINEAR_MCP_ENABLED (default: true)
    - ELECTRON_MCP_ENABLED (default: false)
    - PUPPETEER_MCP_ENABLED (default: false)
    - AGENT_MCP_<agent>_ADD (per-agent MCP additions)
    - AGENT_MCP_<agent>_REMOVE (per-agent MCP removals)
    - CUSTOM_MCP_SERVERS (JSON array of custom server configs)

    Args:
        project_dir: Path to the project directory

    Returns:
        Dict of MCP configuration values
    """
    env_path = project_dir / ".auto-claude" / ".env"
    if not env_path.exists():
        return {}

    config: dict[str, Any] = {}
    mcp_keys = {
        "CONTEXT7_ENABLED",
        "LINEAR_MCP_ENABLED",
        "ELECTRON_MCP_ENABLED",
        "PUPPETEER_MCP_ENABLED",
    }

    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip("\"'")
                    # Include global MCP toggles
                    if key in mcp_keys:
                        config[key] = value
                    # Include per-agent MCP overrides
                    elif key.startswith("AGENT_MCP_"):
                        config[key] = value
                    # Include custom MCP servers
                    elif key == "CUSTOM_MCP_SERVERS":
                        try:
                            parsed = json.loads(value)
                            if not isinstance(parsed, list):
                                logger.warning(
                                    "CUSTOM_MCP_SERVERS must be a JSON array"
                                )
                                config["CUSTOM_MCP_SERVERS"] = []
                            else:
                                valid_servers = []
                                for i, server in enumerate(parsed):
                                    if validate_custom_mcp_server(server):
                                        valid_servers.append(server)
                                    else:
                                        logger.warning(
                                            f"Skipping invalid custom MCP server at index {i}"
                                        )
                                config["CUSTOM_MCP_SERVERS"] = valid_servers
                        except json.JSONDecodeError:
                            logger.warning(
                                f"Failed to parse CUSTOM_MCP_SERVERS JSON: {value}"
                            )
                            config["CUSTOM_MCP_SERVERS"] = []
    except Exception as e:
        logger.debug(f"Failed to load project MCP config from {env_path}: {e}")

    return config


# =============================================================================
# Environment Helpers
# =============================================================================


def is_graphiti_mcp_enabled() -> bool:
    """
    Check if Graphiti MCP server integration is enabled.

    Requires GRAPHITI_MCP_URL to be set (e.g., http://localhost:8000/mcp/)
    """
    return bool(os.environ.get("GRAPHITI_MCP_URL"))


def get_graphiti_mcp_url() -> str:
    """Get the Graphiti MCP server URL."""
    return os.environ.get("GRAPHITI_MCP_URL", "http://localhost:8000/mcp/")


def is_electron_mcp_enabled() -> bool:
    """
    Check if Electron MCP server integration is enabled.

    Requires ELECTRON_MCP_ENABLED to be set to 'true'.
    """
    return os.environ.get("ELECTRON_MCP_ENABLED", "").lower() == "true"


def get_electron_debug_port() -> int:
    """Get the Electron remote debugging port (default: 9222)."""
    return int(os.environ.get("ELECTRON_DEBUG_PORT", "9222"))


def should_use_claude_md() -> bool:
    """Check if CLAUDE.md instructions should be included in system prompt."""
    return os.environ.get("USE_CLAUDE_MD", "").lower() == "true"


def load_claude_md(project_dir: Path) -> str | None:
    """
    Load CLAUDE.md content from project root if it exists.

    Args:
        project_dir: Root directory of the project

    Returns:
        Content of CLAUDE.md if found, None otherwise
    """
    claude_md_path = project_dir / "CLAUDE.md"
    if claude_md_path.exists():
        try:
            return claude_md_path.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


# =============================================================================
# Security Settings Generation
# =============================================================================


def generate_security_settings(
    project_dir: Path,
    spec_dir: Path,
    required_servers: set[str],
    graphiti_enabled: bool = False,
    browser_tools_permissions: list[str] | None = None,
) -> dict[str, Any]:
    """
    Generate security settings for the Claude SDK.

    Args:
        project_dir: Root directory for the project
        spec_dir: Directory containing the spec
        required_servers: Set of required MCP server IDs
        graphiti_enabled: Whether Graphiti MCP is enabled
        browser_tools_permissions: List of browser tool names to allow

    Returns:
        Security settings dict ready to be written to file
    """
    from agents.tools_pkg import CONTEXT7_TOOLS, GRAPHITI_MCP_TOOLS, LINEAR_TOOLS

    project_path_str = str(project_dir.resolve())
    spec_path_str = str(spec_dir.resolve())
    browser_tools = browser_tools_permissions or []

    security_settings = {
        "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True},
        "permissions": {
            "defaultMode": "acceptEdits",
            "allow": [
                # Allow all file operations within the project directory
                "Read(./**)",
                "Write(./**)",
                "Edit(./**)",
                "Glob(./**)",
                "Grep(./**)",
                # Also allow absolute paths
                f"Read({project_path_str}/**)",
                f"Write({project_path_str}/**)",
                f"Edit({project_path_str}/**)",
                f"Glob({project_path_str}/**)",
                f"Grep({project_path_str}/**)",
                # Allow spec directory explicitly
                f"Read({spec_path_str}/**)",
                f"Write({spec_path_str}/**)",
                f"Edit({spec_path_str}/**)",
                # Bash permission (validated by security hook)
                "Bash(*)",
                # Web tools
                "WebFetch(*)",
                "WebSearch(*)",
                # MCP tools based on required servers
                *(
                    [f"{tool}(*)" for tool in CONTEXT7_TOOLS]
                    if "context7" in required_servers
                    else []
                ),
                *(
                    [f"{tool}(*)" for tool in LINEAR_TOOLS]
                    if "linear" in required_servers
                    else []
                ),
                *(
                    [f"{tool}(*)" for tool in GRAPHITI_MCP_TOOLS]
                    if graphiti_enabled
                    else []
                ),
                *[f"{tool}(*)" for tool in browser_tools],
            ],
        },
    }

    return security_settings


def write_security_settings(
    project_dir: Path,
    security_settings: dict[str, Any],
) -> Path:
    """
    Write security settings to a file and return the path.

    Args:
        project_dir: Project directory to write settings in
        security_settings: Settings dict to write

    Returns:
        Path to the written settings file
    """
    settings_file = project_dir / ".claude_settings.json"
    with open(settings_file, "w") as f:
        json.dump(security_settings, f, indent=2)
    return settings_file


# =============================================================================
# MCP Server Configuration
# =============================================================================


def build_mcp_servers(
    required_servers: set[str],
    spec_dir: Path,
    project_dir: Path,
    linear_api_key: str = "",
    mcp_config: dict[str, Any] | None = None,
    auto_claude_tools_enabled: bool = False,
) -> dict[str, dict[str, Any]]:
    """
    Build the MCP servers configuration based on required servers.

    Args:
        required_servers: Set of required MCP server IDs
        spec_dir: Directory containing the spec
        project_dir: Root project directory
        linear_api_key: Linear API key if available
        mcp_config: Per-project MCP configuration
        auto_claude_tools_enabled: Whether auto-claude tools are available

    Returns:
        Dict of MCP server configurations for the SDK
    """
    from agents.tools_pkg import create_auto_claude_mcp_server

    mcp_servers: dict[str, dict[str, Any]] = {}

    if "context7" in required_servers:
        mcp_servers["context7"] = {
            "command": "npx",
            "args": ["-y", "@upstash/context7-mcp"],
        }

    if "electron" in required_servers:
        mcp_servers["electron"] = {
            "command": "npm",
            "args": ["exec", "electron-mcp-server"],
        }

    if "puppeteer" in required_servers:
        mcp_servers["puppeteer"] = {
            "command": "npx",
            "args": ["puppeteer-mcp-server"],
        }

    if "linear" in required_servers:
        mcp_servers["linear"] = {
            "type": "http",
            "url": "https://mcp.linear.app/mcp",
            "headers": {"Authorization": f"Bearer {linear_api_key}"},
        }

    if "graphiti" in required_servers and is_graphiti_mcp_enabled():
        mcp_servers["graphiti-memory"] = {
            "type": "http",
            "url": get_graphiti_mcp_url(),
        }

    if "auto-claude" in required_servers and auto_claude_tools_enabled:
        auto_claude_mcp_server = create_auto_claude_mcp_server(spec_dir, project_dir)
        if auto_claude_mcp_server:
            mcp_servers["auto-claude"] = auto_claude_mcp_server

    # Add custom MCP servers from project config
    if mcp_config:
        custom_servers = mcp_config.get("CUSTOM_MCP_SERVERS", [])
        for custom in custom_servers:
            server_id = custom.get("id")
            if not server_id or server_id not in required_servers:
                continue
            server_type = custom.get("type", "command")
            if server_type == "command":
                mcp_servers[server_id] = {
                    "command": custom.get("command", "npx"),
                    "args": custom.get("args", []),
                }
            elif server_type == "http":
                server_config: dict[str, Any] = {
                    "type": "http",
                    "url": custom.get("url", ""),
                }
                if custom.get("headers"):
                    server_config["headers"] = custom["headers"]
                mcp_servers[server_id] = server_config

    return mcp_servers
