#!/usr/bin/env python3
"""Verify ADCS Helm packaging baseline for production deployment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART_DIR = ROOT / "infra" / "helm" / "adcs"
TEMPLATES_DIR = CHART_DIR / "templates"

REQUIRED_TEMPLATE_FILES = (
    "deployment-api.yaml",
    "deployment-mcp-gateway.yaml",
    "deployment-worker.yaml",
    "deployment-scheduler.yaml",
    "service-api.yaml",
    "service-mcp-gateway.yaml",
    "ingress-public-api.yaml",
    "ingress-admin-api.yaml",
    "ingress-mcp-gateway.yaml",
    "hpa-api.yaml",
    "hpa-mcp-gateway.yaml",
    "pdb-api.yaml",
    "pdb-mcp-gateway.yaml",
    "networkpolicy.yaml",
    "serviceaccount.yaml",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify ADCS Helm packaging baseline.")
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional JSON output path for CI aggregation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    failures: list[str] = []

    chart = _load_yaml(CHART_DIR / "Chart.yaml", failures)
    values = _load_yaml(CHART_DIR / "values.yaml", failures)

    if isinstance(chart, dict):
        if chart.get("apiVersion") != "v2":
            failures.append("Chart.yaml must set apiVersion: v2.")
        if not chart.get("name"):
            failures.append("Chart.yaml must define chart name.")

    if isinstance(values, dict):
        failures.extend(_validate_values(values))

    for name in REQUIRED_TEMPLATE_FILES:
        path = TEMPLATES_DIR / name
        if not path.exists():
            failures.append(f"Missing required Helm template: {path.as_posix()}.")

    failures.extend(_validate_template_contracts())

    status = "pass"
    if failures:
        status = "fail"
        for item in failures:
            print(f"[fail] {item}")
        print(f"[summary] Helm packaging verification failed ({len(failures)} issues).")
    else:
        print("[pass] Helm packaging baseline is valid.")

    if isinstance(args.output_json, str) and args.output_json.strip():
        output_path = Path(args.output_json.strip())
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {
                    "status": status,
                    "failures": failures,
                    "chart_dir": CHART_DIR.as_posix(),
                    "templates_dir": TEMPLATES_DIR.as_posix(),
                },
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"[info] Helm packaging report JSON: {output_path.as_posix()}")

    return 0 if status == "pass" else 1


def _load_yaml(path: Path, failures: list[str]) -> dict[str, Any] | None:
    if not path.exists():
        failures.append(f"Missing required YAML file: {path.as_posix()}.")
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        failures.append(f"Failed to parse YAML `{path.as_posix()}`: {exc}")
        return None
    if not isinstance(payload, dict):
        failures.append(f"YAML root must be object: {path.as_posix()}.")
        return None
    return payload


def _validate_values(values: dict[str, Any]) -> list[str]:
    failures: list[str] = []

    for required_key in ("global", "api", "mcpGateway", "worker", "scheduler", "networkPolicy"):
        if required_key not in values:
            failures.append(f"values.yaml missing key `{required_key}`.")

    api = values.get("api")
    if isinstance(api, dict):
        hpa = api.get("hpa")
        pdb = api.get("pdb")
        if not isinstance(hpa, dict) or not bool(hpa.get("enabled")):
            failures.append("values.yaml: api.hpa.enabled must be true for production baseline.")
        if not isinstance(pdb, dict) or not bool(pdb.get("enabled")):
            failures.append("values.yaml: api.pdb.enabled must be true for production baseline.")

    mcp = values.get("mcpGateway")
    if isinstance(mcp, dict):
        hpa = mcp.get("hpa")
        pdb = mcp.get("pdb")
        if not isinstance(hpa, dict) or not bool(hpa.get("enabled")):
            failures.append(
                "values.yaml: mcpGateway.hpa.enabled must be true for production baseline."
            )
        if not isinstance(pdb, dict) or not bool(pdb.get("enabled")):
            failures.append(
                "values.yaml: mcpGateway.pdb.enabled must be true for production baseline."
            )

    global_cfg = values.get("global")
    if isinstance(global_cfg, dict):
        secret_env = global_cfg.get("secretEnv")
        if not isinstance(secret_env, dict) or "ADCS_API_KEY" not in secret_env:
            failures.append("values.yaml: global.secretEnv.ADCS_API_KEY is required.")

    return failures


def _validate_template_contracts() -> list[str]:
    failures: list[str] = []

    deployment_templates = (
        TEMPLATES_DIR / "deployment-api.yaml",
        TEMPLATES_DIR / "deployment-mcp-gateway.yaml",
        TEMPLATES_DIR / "deployment-worker.yaml",
        TEMPLATES_DIR / "deployment-scheduler.yaml",
    )
    for template in deployment_templates:
        content = template.read_text(encoding="utf-8")
        for required in ("resources:", "livenessProbe:", "readinessProbe:"):
            if required not in content:
                failures.append(f"{template.name} missing required block `{required}`.")

    ingress_public = (TEMPLATES_DIR / "ingress-public-api.yaml").read_text(encoding="utf-8")
    ingress_admin = (TEMPLATES_DIR / "ingress-admin-api.yaml").read_text(encoding="utf-8")
    if "api.ingress.public" not in ingress_public:
        failures.append("ingress-public-api.yaml must use public ingress values.")
    if "api.ingress.admin" not in ingress_admin:
        failures.append("ingress-admin-api.yaml must use admin ingress values.")

    network_policy = (TEMPLATES_DIR / "networkpolicy.yaml").read_text(encoding="utf-8")
    if "kind: NetworkPolicy" not in network_policy:
        failures.append("networkpolicy.yaml must define NetworkPolicy resource.")

    return failures


if __name__ == "__main__":
    raise SystemExit(main())
