# Changelog

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
