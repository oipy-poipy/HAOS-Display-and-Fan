FROM ghcr.io/home-assistant/aarch64-base:3.22

LABEL \
  io.hass.name="HA Pi Panel" \
  io.hass.description="OLED status display and fan controller for Home Assistant OS on Raspberry Pi." \
  io.hass.arch="aarch64" \
  io.hass.type="addon" \
  io.hass.version="0.1.2"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_VERSION=0.1.2

RUN apk add --no-cache \
      bash \
      i2c-tools \
      libgpiod \
      linux-headers \
      py3-pip \
      py3-pillow \
      py3-psutil \
      python3 \
      ttf-dejavu \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip==25.1.1 setuptools==80.9.0 wheel==0.45.1 \
    && /opt/venv/bin/pip install \
      luma.core==2.4.2 \
      luma.oled==3.14.0 \
      paho-mqtt==2.1.0 \
      pillow==11.2.1 \
      psutil==7.0.0 \
      python-periphery==2.4.1 \
      requests==2.32.4 \
      smbus2==0.5.0

ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /usr/src/ha-pi-panel
COPY run.sh /run.sh
COPY app ./app
RUN chmod a+x /run.sh

CMD ["/run.sh"]
