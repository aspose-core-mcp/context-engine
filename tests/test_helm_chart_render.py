from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_CHART_DIR = Path(__file__).resolve().parents[1] / "infra" / "helm" / "adcs"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _render(*extra_args: str) -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["helm", "template", "adcs", str(_CHART_DIR), *extra_args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return [doc for doc in yaml.safe_load_all(completed.stdout) if doc]


def _network_policy(documents: list[dict[str, Any]]) -> dict[str, Any]:
    return next(doc for doc in documents if doc["kind"] == "NetworkPolicy")


def test_default_render_produces_valid_kubernetes_objects() -> None:
    documents = _render()

    assert documents
    for document in documents:
        assert document.get("apiVersion") and document.get("kind"), document

    policy = _network_policy(documents)["spec"]
    # Kubernetes rejects a peer that is not a list item, so every rule must hold lists.
    assert all(isinstance(rule["from"], list) for rule in policy["ingress"])
    assert all(isinstance(rule["to"], list) for rule in policy["egress"])
    for rule in policy["ingress"]:
        for peer in rule["from"]:
            assert set(peer) <= {"podSelector", "namespaceSelector", "ipBlock"}, peer


def test_egress_entries_accept_ip_blocks_for_external_services() -> None:
    documents = _render(
        "--set-string",
        "networkPolicy.egressTo[0].ipBlock.cidr=10.20.0.0/16",
        "--set",
        "networkPolicy.egressTo[0].ports[0].port=5432",
    )

    egress = _network_policy(documents)["spec"]["egress"]
    ip_rules = [rule for rule in egress if rule["to"] and "ipBlock" in rule["to"][0]]
    assert ip_rules == [
        {"to": [{"ipBlock": {"cidr": "10.20.0.0/16"}}], "ports": [{"port": 5432}]}
    ]
