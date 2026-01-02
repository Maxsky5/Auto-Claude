"""
Claude SDK client wrapper for AI analysis.
"""

import json
from pathlib import Path
from typing import Any

from core.runtime import create_agent_runtime, AgentRuntimeBase, BlockType


class ClaudeAnalysisClient:
    """Wrapper for Claude SDK client with analysis-specific configuration."""

    DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
    ALLOWED_TOOLS = ["Read", "Glob", "Grep"]
    MAX_TURNS = 50

    def __init__(self, project_dir: Path):
        """
        Initialize Claude client.

        Args:
            project_dir: Root directory of project being analyzed
        """
        self.project_dir = project_dir
        self._validate_oauth_token()

    def _validate_oauth_token(self) -> None:
        """Validate that an authentication token is available."""
        from core.auth import require_auth_token

        require_auth_token()  # Raises ValueError if no token found

    async def run_analysis_query(self, prompt: str) -> str:
        """
        Run a Claude query for analysis.

        Args:
            prompt: The analysis prompt

        Returns:
            Claude's response text
        """
        # Security settings are handled by create_agent_runtime
        client = self._create_client()

        async with client:
            await client.query(prompt)
            return await self._collect_response(client)

    def _create_client(self) -> AgentRuntimeBase:
        """
        Create configured agent backend.

        Returns:
            AgentRuntimeBase instance
        """
        system_prompt = (
            f"You are a senior software architect analyzing this codebase. "
            f"Your working directory is: {self.project_dir.resolve()}\n"
            f"Use Read, Grep, and Glob tools to analyze actual code. "
            f"Output your analysis as valid JSON only."
        )

        # Create backend using unified factory
        # This automatically handles security settings, MCPs, etc.
        return create_agent_runtime(
            project_dir=self.project_dir,
            spec_dir=self.project_dir,  # Use project dir as spec dir for analysis
            model=self.DEFAULT_MODEL,
            agent_type="coder",  # Use coder permissions for full access
            system_prompt=system_prompt,
            allowed_tools=self.ALLOWED_TOOLS,
            max_turns=self.MAX_TURNS,
        )

    async def _collect_response(self, client: AgentRuntimeBase) -> str:
        """
        Collect text response from Claude client.

        Args:
            client: AgentRuntimeBase instance

        Returns:
            Collected response text
        """
        response_text = ""

        async for msg in client.receive_response():
            msg_type = type(msg).__name__

            if msg_type == "AgentMessage":
                for block in msg.content:
                    if block.type == BlockType.TEXT and block.text:
                        response_text += block.text

        return response_text
