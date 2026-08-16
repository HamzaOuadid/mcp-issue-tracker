from __future__ import annotations

import pytest

from mcp_issue_tracker.config import ServerConfig
from mcp_issue_tracker.registry import ToolRegistrationError, ToolRegistry, ToolSpec


def test_default_config_registers_all_declared_tools():
    config = ServerConfig.default()
    registry = ToolRegistry(config)
    for name, cfg in config.tools.items():
        registry.register(ToolSpec(name=name, read_only=cfg.read_only, cost_units=cfg.cost_units, description=cfg.description))
    described = {d["name"] for d in registry.describe_all()}
    assert described == set(config.tools.keys())


def test_write_tools_default_to_read_only_unless_allowlisted():
    config = ServerConfig.default()
    registry = ToolRegistry(config)
    for name, cfg in config.tools.items():
        registry.register(ToolSpec(name=name, read_only=cfg.read_only, cost_units=cfg.cost_units, description=cfg.description))
    assert registry.default_read_only_check() is True
    assert registry.is_write_allowed("create_issue") is False
    assert registry.is_write_allowed("search_issues") is True  # read-only tools are always "allowed"


def test_write_tool_becomes_callable_once_allowlisted():
    config = ServerConfig.default()
    config.allowed_write_tools = ["create_issue"]
    registry = ToolRegistry(config)
    registry.register(ToolSpec(name="create_issue", read_only=False, cost_units=5, description="x"))
    assert registry.is_write_allowed("create_issue") is True


def test_unknown_tool_is_never_write_allowed():
    config = ServerConfig.default()
    registry = ToolRegistry(config)
    assert registry.is_write_allowed("does_not_exist") is False


def test_registering_undeclared_tool_raises():
    config = ServerConfig(tools={})
    registry = ToolRegistry(config)
    with pytest.raises(ToolRegistrationError):
        registry.register(ToolSpec(name="mystery_tool", read_only=True, cost_units=1, description="x"))


def test_code_config_mismatch_raises():
    # server.yaml says get_issue is read_only=True; code claiming
    # read_only=False for the same name must be refused at registration,
    # not silently accepted.
    config = ServerConfig.default()
    registry = ToolRegistry(config)
    with pytest.raises(ToolRegistrationError):
        registry.register(ToolSpec(name="get_issue", read_only=False, cost_units=1, description="x"))
