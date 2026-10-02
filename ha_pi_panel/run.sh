#!/usr/bin/env bash
set -euo pipefail

export OPTIONS_PATH="${OPTIONS_PATH:-/data/options.json}"

# bashio.sh is the sourceable library; /usr/lib/bashio/bashio is the
# `#!/usr/bin/env bashio` shebang wrapper and refuses to be sourced bare.
if [ -f /usr/lib/bashio/bashio.sh ]; then
  # shellcheck source=/dev/null
  source /usr/lib/bashio/bashio.sh
fi

log_info() {
  if declare -F bashio::log.info >/dev/null; then
    bashio::log.info "$1"
  else
    echo "$1"
  fi
}

log_warning() {
  if declare -F bashio::log.warning >/dev/null; then
    bashio::log.warning "$1"
  else
    echo "WARNING: $1"
  fi
}

log_info "Starting HA Pi Panel"

if declare -F bashio::services.available >/dev/null && bashio::services.available "mqtt"; then
  export MQTT_HOST="$(bashio::services mqtt host)"
  export MQTT_PORT="$(bashio::services mqtt port)"
  export MQTT_USERNAME="$(bashio::services mqtt username)"
  export MQTT_PASSWORD="$(bashio::services mqtt password)"
  log_info "MQTT service discovered at ${MQTT_HOST}:${MQTT_PORT}"
else
  log_warning "MQTT service is not available; MQTT discovery will stay disabled unless MQTT variables are provided."
fi

exec python3 -m app.main
