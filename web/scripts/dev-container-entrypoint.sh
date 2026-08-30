#!/bin/sh
set -eu

PNPM_VERSION="10.15.1"
export CI=true
export COREPACK_DEFAULT_TO_LATEST=0

corepack enable
corepack prepare "pnpm@$PNPM_VERSION" --activate
pnpm config set registry https://registry.npmmirror.com

dependency_fingerprint() {
  directory="$1"
  (
    cd "$directory"
    sha256sum package.json pnpm-lock.yaml | sha256sum | cut -d ' ' -f 1
  )
}

ensure_dependencies() {
  directory="$1"
  expected_binary="$2"
  install_mode="$3"
  stamp="$directory/node_modules/.financial-platform-dependencies.sha256"
  installed_lock="$directory/node_modules/.pnpm/lock.yaml"
  fingerprint="$(dependency_fingerprint "$directory")"
  install_required=false

  if [ ! -x "$expected_binary" ]; then
    install_required=true
  elif [ -f "$stamp" ]; then
    if [ "$(cat "$stamp")" != "$fingerprint" ]; then
      install_required=true
    fi
  elif [ ! -f "$installed_lock" ] || ! cmp -s "$directory/pnpm-lock.yaml" "$installed_lock"; then
    install_required=true
  fi

  if [ "$install_required" = true ]; then
    echo "Dependencies changed in $directory; installing..."
    if [ "$install_mode" = "ignore-scripts" ]; then
      (cd "$directory" && pnpm install --frozen-lockfile --ignore-scripts)
    else
      (cd "$directory" && pnpm install --frozen-lockfile)
    fi
  else
    echo "Dependencies unchanged in $directory; skipping install."
  fi

  printf '%s\n' "$fingerprint" > "$stamp"
}

ensure_dependencies \
  /workspace/agent-runtime \
  /workspace/agent-runtime/node_modules/.bin/tsc \
  ignore-scripts
ensure_dependencies \
  /workspace/web \
  /workspace/web/node_modules/.bin/next \
  standard

cd /workspace/agent-runtime
pnpm run build
pnpm exec tsc -p tsconfig.json --watch &
runtime_watch_pid=$!

next_pid=""
cleanup() {
  if [ -n "$next_pid" ]; then
    kill "$next_pid" 2>/dev/null || true
  fi
  kill "$runtime_watch_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

cd /workspace/web
pnpm exec next dev --webpack --hostname 0.0.0.0 &
next_pid=$!
set +e
wait "$next_pid"
exit_code=$?
set -e

trap - INT TERM EXIT
cleanup
exit "$exit_code"
