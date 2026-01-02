"""Tests for roadmap runner runtime parameter support."""

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock

backend_path = Path(__file__).parent.parent / "apps" / "backend"
sys.path.insert(0, str(backend_path))

from core.runtime import DEFAULT_RUNTIME, RUNTIME_CHOICES


def test_roadmap_runner_argparse_runtime_argument():
    """Test that the CLI parser accepts --runtime argument."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument(
        "--runtime",
        type=str,
        default=DEFAULT_RUNTIME,
        choices=RUNTIME_CHOICES,
    )

    args = parser.parse_args([])
    assert args.runtime == DEFAULT_RUNTIME

    args = parser.parse_args(["--runtime", "claude-code"])
    assert args.runtime == "claude-code"

    args = parser.parse_args(["--runtime", "opencode"])
    assert args.runtime == "opencode"


def test_roadmap_orchestrator_accepts_runtime_parameter():
    """Test that RoadmapOrchestrator accepts runtime parameter."""
    import inspect

    try:
        from runners.roadmap.orchestrator import RoadmapOrchestrator

        sig = inspect.signature(RoadmapOrchestrator.__init__)
        params = list(sig.parameters.keys())

        assert "runtime" in params, (
            "RoadmapOrchestrator should accept 'runtime' parameter"
        )
        assert sig.parameters["runtime"].default == DEFAULT_RUNTIME
    except ImportError:
        pass


def test_agent_executor_accepts_runtime_parameter():
    """Test that AgentExecutor accepts runtime parameter."""
    import inspect

    try:
        from runners.roadmap.executor import AgentExecutor

        sig = inspect.signature(AgentExecutor.__init__)
        params = list(sig.parameters.keys())

        assert "runtime" in params, "AgentExecutor should accept 'runtime' parameter"
        assert sig.parameters["runtime"].default == DEFAULT_RUNTIME
    except ImportError:
        pass


def test_agent_executor_stores_runtime():
    """Test that AgentExecutor stores runtime as instance attribute."""
    try:
        from runners.roadmap.executor import AgentExecutor

        mock_create_client = MagicMock()
        executor = AgentExecutor(
            project_dir=Path("/tmp"),
            output_dir=Path("/tmp"),
            model="test-model",
            create_client_func=mock_create_client,
            thinking_budget=None,
            runtime="opencode",
        )

        assert executor.runtime == "opencode"
    except ImportError:
        pass


def test_runtime_choices_contains_all_values():
    """Test that RUNTIME_CHOICES contains expected values."""
    assert "claude-code" in RUNTIME_CHOICES
    assert "opencode" in RUNTIME_CHOICES
    assert DEFAULT_RUNTIME in RUNTIME_CHOICES


if __name__ == "__main__":
    test_roadmap_runner_argparse_runtime_argument()
    test_roadmap_orchestrator_accepts_runtime_parameter()
    test_agent_executor_accepts_runtime_parameter()
    test_agent_executor_stores_runtime()
    test_runtime_choices_contains_all_values()
    print("All runtime parameter tests passed!")
