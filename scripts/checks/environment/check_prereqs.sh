#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

ok_count=0
warn_count=0
fail_count=0

red() { printf "\033[31m%s\033[0m\n" "$1"; }
green() { printf "\033[32m%s\033[0m\n" "$1"; }
yellow() { printf "\033[33m%s\033[0m\n" "$1"; }

check_cmd() {
  local name="$1"
  local required="$2"

  if command -v "$name" >/dev/null 2>&1; then
    green "[OK] $name: $(command -v "$name")"
    ok_count=$((ok_count + 1))
  else
    if [[ "$required" == "required" ]]; then
      red "[FAIL] $name is required but not found"
      fail_count=$((fail_count + 1))
    else
      yellow "[WARN] $name not found (optional/recommended)"
      warn_count=$((warn_count + 1))
    fi
  fi
}

check_python_version() {
  if ! command -v python3 >/dev/null 2>&1; then
    red "[FAIL] python3 is required"
    fail_count=$((fail_count + 1))
    return
  fi

  local version
  version="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
  local major minor
  major="${version%%.*}"
  minor="${version#*.}"
  minor="${minor%%.*}"

  if (( major > 3 || (major == 3 && minor >= 12) )); then
    green "[OK] python3 version: $version"
    ok_count=$((ok_count + 1))
  else
    red "[FAIL] python3>=3.12 required, found $version"
    fail_count=$((fail_count + 1))
  fi
}

check_node_version() {
  if ! command -v node >/dev/null 2>&1; then
    yellow "[WARN] node not found (required later for Next.js admin frontend)"
    warn_count=$((warn_count + 1))
    return
  fi

  local raw major
  raw="$(node -v | sed 's/^v//')"
  major="${raw%%.*}"

  if (( major >= 20 )); then
    green "[OK] node version: v$raw"
    ok_count=$((ok_count + 1))
  else
    yellow "[WARN] node>=20 recommended, found v$raw"
    warn_count=$((warn_count + 1))
  fi
}

check_docker_compose() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    green "[OK] docker compose plugin available"
    ok_count=$((ok_count + 1))
    return
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    green "[OK] docker-compose standalone available"
    ok_count=$((ok_count + 1))
    return
  fi

  red "[FAIL] docker compose is required for local integration tests"
  fail_count=$((fail_count + 1))
}

echo "Checking prerequisites for ADCS workspace: $ROOT_DIR"

check_cmd git required
check_python_version
check_node_version
check_cmd npm optional
check_cmd pnpm optional
check_cmd docker required
check_docker_compose
check_cmd kubectl optional
check_cmd helm optional
check_cmd make optional
check_cmd jq optional

echo
echo "Summary: OK=$ok_count WARN=$warn_count FAIL=$fail_count"

if (( fail_count > 0 )); then
  exit 1
fi
