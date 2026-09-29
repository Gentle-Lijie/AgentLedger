"""Compatibility entry point for previously installed Git hooks."""

from agentledger.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
