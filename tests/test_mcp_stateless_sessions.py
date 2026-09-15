"""Regression tests for stateless MCP sessions across replicas.

With sessions held in a per-process dict on ``MCPToolGateway`` and more than
one ``adcs-api`` replica behind the ingress, a tool call routed to a different
pod than ``initialize`` fails with "MCP session ... not found" — 5 of 10 calls
in a deployment with 2 replicas. Such a map also grows without bound unless
something evicts it.

Sessions are stateless: ``initialize`` issues a self-describing token that
any replica can decode. These tests pin that property by exercising **two
independent gateway instances**, which is what two pods look like in-process.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest

from adcs.mcp.revision_negotiation import MCPFallbackReason
from adcs.mcp.tool_gateway import MCPToolGateway

_REVISIONS = ("2025-11-25", "2025-06-18", "2024-11-05")


def _gateway() -> MCPToolGateway:
    # Session handling never touches the query service, so a stub suffices.
    return MCPToolGateway(
        public_query_service=cast(Any, object()),
        supported_revisions=_REVISIONS,
        primary_revision=_REVISIONS[0],
    )


def test_session_from_one_replica_is_valid_on_another() -> None:
    """THE regression: pod A issues the session, pod B must accept it."""
    pod_a, pod_b = _gateway(), _gateway()

    issued = pod_a.initialize(requested_revision="2025-06-18")
    session = pod_b.get_session(session_id=issued.session_id)

    assert session.session_id == issued.session_id
    assert session.negotiated_revision == issued.negotiated_revision == "2025-06-18"


def test_negotiation_details_survive_the_round_trip() -> None:
    """The token carries the full negotiation outcome, not just the revision."""
    pod_a, pod_b = _gateway(), _gateway()

    # An unknown revision forces a fallback, so the flags are non-default.
    issued = pod_a.initialize(requested_revision="1999-01-01")
    session = pod_b.get_session(session_id=issued.session_id)

    assert session.negotiated_revision == issued.negotiated_revision
    assert session.fallback_applied is issued.fallback_applied is True
    assert session.fallback_reason == issued.fallback_reason
    assert session.fallback_reason is not MCPFallbackReason.NONE
    assert session.requested_revision == "1999-01-01"


def test_every_replica_accepts_every_issued_session() -> None:
    """No affinity required: any of N replicas serves any of M sessions."""
    replicas = [_gateway() for _ in range(3)]
    sessions = [g.initialize(requested_revision=None).session_id for g in replicas]

    for replica in replicas:
        for session_id in sessions:
            assert replica.get_session(session_id=session_id).negotiated_revision in _REVISIONS


@pytest.mark.parametrize(
    "session_id",
    [
        "",
        "bogus-session",
        "mcps1.",
        "mcps1.!!!!not-base64!!!!",
        "mcps9.eyJ2IjogMX0",  # unknown token version prefix
        str(uuid4()),  # legacy pre-stateless UUID session id
    ],
)
def test_malformed_session_tokens_are_rejected(session_id: str) -> None:
    """A token must still prove `initialize` happened — arbitrary ids are refused."""
    with pytest.raises(KeyError):
        _gateway().get_session(session_id=session_id)


def test_gateway_keeps_no_session_state() -> None:
    """Guard against reintroducing the per-process session map."""
    gateway = _gateway()
    gateway.initialize(requested_revision=None)

    leaked = [
        name
        for name in vars(gateway)
        if "session" in name.lower() and isinstance(getattr(gateway, name), dict)
    ]
    assert leaked == [], f"gateway is holding session state again: {leaked}"


def test_sessions_are_unique_per_initialize() -> None:
    """Distinct calls must not collide even with identical negotiation input."""
    gateway = _gateway()
    issued = {gateway.initialize(requested_revision="2025-06-18").session_id for _ in range(5)}
    assert len(issued) == 5
