"""Provider-side verification — replays consumer pacts against the live ADCS API.

Run after consumer pacts are generated/published:

    # Local: use file-based pact
    python tests/contracts/provider/verify_adcs_provider.py \\
        --pact pacts/ai-ide-consumer-adcs-mcp-gateway.json \\
        --provider-url http://localhost:8080

    # CI: pull from broker
    python tests/contracts/provider/verify_adcs_provider.py \\
        --broker-url https://pact-broker.example.com \\
        --provider-url http://localhost:8080

The broker is self-hosted
(see infra/pact-broker/).
"""

from __future__ import annotations

import argparse
import sys

try:
    from pact import Verifier
except ImportError:  # pragma: no cover — extras not installed
    print(
        "ERROR: pact-python not installed. Install via:\n"
        "  pip install -e '.[dev,contracts]'",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider-url",
        default="http://localhost:8080",
        help="Live ADCS API URL to verify against",
    )
    parser.add_argument("--pact", help="Path to local pact JSON (alternative to --broker-url)")
    parser.add_argument("--broker-url", help="Pact Broker URL")
    parser.add_argument("--broker-username", default="pactread")
    parser.add_argument("--broker-password", default="pactread")
    parser.add_argument(
        "--publish-results",
        action="store_true",
        help="Publish verification results back to broker",
    )
    parser.add_argument(
        "--provider-states-setup-url",
        help="Provider-state setup endpoint, for pacts whose interactions declare states",
    )
    parser.add_argument(
        "--provider-version",
        default="local-dev",
        help="Provider version tag (e.g. git short SHA)",
    )
    args = parser.parse_args()

    verifier = Verifier(
        provider="adcs-mcp-gateway",
        provider_base_url=args.provider_url,
    )

    common: dict[str, object] = {}
    if args.provider_states_setup_url:
        common["provider_states_setup_url"] = args.provider_states_setup_url

    if args.pact:
        success_code, _ = verifier.verify_pacts(args.pact, **common)
    elif args.broker_url:
        success_code, _ = verifier.verify_with_broker(
            broker_url=args.broker_url,
            broker_username=args.broker_username,
            broker_password=args.broker_password,
            publish_version=args.provider_version,
            publish_verification_results=args.publish_results,
            **common,
        )
    else:
        print("ERROR: pass either --pact or --broker-url", file=sys.stderr)
        return 2

    return success_code


if __name__ == "__main__":
    sys.exit(main())
