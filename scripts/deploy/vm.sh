#!/bin/sh
# Run from any directory; keep one project name for persistent volume identity.
set -eu
cd "$(dirname "$0")/../.."
exec docker compose --project-name adcs-vm --env-file .env.vm -f docker-compose.vm.yml "$@"
