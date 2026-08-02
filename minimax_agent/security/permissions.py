"""Four-level permission model: allow / ask / deny / force_ask.

`allow`     - tool runs without prompting the user
`ask`       - prompt the user the first time per session, remember the answer
`deny`      - tool is rejected with an error
`force_ask` - tool always prompts the user, no memory of past answers
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    FORCE_ASK = "force_ask"


# Default policy: read-only tools are allowed, mutating tools ask, dangerous ones deny.
DEFAULT_POLICY: dict[str, Decision] = {
    "file_read": Decision.ALLOW,
    "file_write": Decision.ASK,
    "file_edit": Decision.ASK,
    "bash": Decision.ASK,
    "grep": Decision.ALLOW,
    "glob": Decision.ALLOW,
    "web_search": Decision.ALLOW,
    "todo": Decision.ALLOW,
}


@dataclass
class PermissionManager:
    """Resolves permission decisions and remembers user answers per session."""

    policy: dict[str, Decision] = field(default_factory=lambda: dict(DEFAULT_POLICY))
    # Tools the user has explicitly approved this session (for `ask`).
    approved: set[str] = field(default_factory=set)

    def decide(self, tool_name: str) -> Decision:
        """Return the effective decision for a tool.

        - `force_ask` / `deny` always win.
        - `ask` is downgraded to `allow` if the user has already approved
          the tool this session.
        - Unknown tools default to `ask` (safer than silent allow).
        """
        decision = self.policy.get(tool_name, Decision.ASK)
        if decision == Decision.ASK and tool_name in self.approved:
            return Decision.ALLOW
        return decision

    def approve(self, tool_name: str) -> None:
        """Record that the user approved a tool for the rest of the session."""
        self.approved.add(tool_name)

    def set_policy(self, tool_name: str, decision: Decision) -> None:
        """Override the policy for a specific tool."""
        self.policy[tool_name] = decision
