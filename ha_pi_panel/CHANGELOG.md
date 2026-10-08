# Changelog

## 0.2.0

- Show the Home Assistant host address instead of the add-on container address.
  `{ip}` and `{hostname}` now come from the Supervisor `/network/info` and
  `/host/info` endpoints, which needs the new `hassio_api` permission. The
  socket based lookup stays as a fallback and container ranges are rejected.
- Entity tokens accept attributes, fallbacks, and formatting:
  `{ha:sensor.outdoor_temperature,weather.forecast_home@temperature|1°C}`.
- Weather states such as `partlycloudy` render as readable labels.
- Missing entity ids, rejected tokens, and failed requests are logged once as a
  warning instead of being silently rendered as `--`.
- Page lines support an inverted header bar (`#` prefix) and right aligned
  values (tab separator), and the default pages were rebuilt around them.
- New `{clock}` and `{uptime_short}` tokens for narrow panels.
- One Core API request now serves every token of the same entity.

## 0.1.2

- Fix startup crash by sourcing `/usr/lib/bashio/bashio.sh` instead of the
  `/usr/lib/bashio/bashio` shebang wrapper, which aborts when sourced without a
  script argument.

## 0.1.1

- Fix add-on startup by sourcing bashio before using bashio logging and service helpers.

## 0.1.0

- Initial experimental release.
- SSD1306 128x64 and 128x32 display support with optional SH1106 mode.
- GPIO on/off fan backend, mock backend, experimental software PWM, and optional sysfs PWM.
- MQTT discovery for fan, sensors, switch, select, and hardware fault entities.
- Home Assistant API proxy support for display page entity tokens.
