"""Compatibility entry point for previously installed AgentLedger Git hooks."""

from agent_session_commit.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
