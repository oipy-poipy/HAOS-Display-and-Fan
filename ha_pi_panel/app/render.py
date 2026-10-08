from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .config import DisplayPage


HA_TOKEN_RE = re.compile(r"\{ha:([^}]+)\}")
TOKEN_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")
HA_FORMAT_RE = re.compile(r"^(\d?)(.*)$", re.DOTALL)
MISSING = "--"
# A tab splits a line into a left label and a right aligned value.
ALIGN_SEP = "\t"
# A leading hash turns a line into an inverted header bar.
HEADER_PREFIX = "#"

# Home Assistant weather states are machine readable, not display ready.
WEATHER_LABELS = {
    "clear-night": "Clear",
    "cloudy": "Cloudy",
    "exceptional": "Alert",
    "fog": "Fog",
    "hail": "Hail",
    "lightning": "Storm",
    "lightning-rainy": "Storm/rain",
    "partlycloudy": "Part cloud",
    "pouring": "Heavy rain",
    "rainy": "Rain",
    "snowy": "Snow",
    "snowy-rainy": "Sleet",
    "sunny": "Sunny",
    "windy": "Windy",
    "windy-variant": "Windy",
}


@dataclass(frozen=True)
class RenderResult:
    image: Image.Image
    text_lines: list[str]


def parse_ha_spec(spec: str) -> tuple[list[str], str]:
    """Split ``entity@attr,fallback@attr|1C`` into its refs and format suffix."""
    refs_part, _, fmt = spec.partition("|")
    refs = [ref.strip() for ref in refs_part.split(",") if ref.strip()]
    return refs, fmt


def format_ha_value(value: str, fmt: str) -> str:
    value = WEATHER_LABELS.get(value, value)
    digits, suffix = HA_FORMAT_RE.match(fmt).groups()
    if digits:
        try:
            value = f"{float(value):.{int(digits)}f}"
        except ValueError:
            pass
    return value + suffix


def extract_ha_entities(pages: list[DisplayPage]) -> set[str]:
    entities: set[str] = set()
    for page in pages:
        for line in page.lines:
            for match in HA_TOKEN_RE.finditer(line):
                refs, _ = parse_ha_spec(match.group(1))
                entities.update(ref.partition("@")[0] for ref in refs)
    return entities


def _load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/ttf-dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    if _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "..."
    while text and _text_width(draw, text + ellipsis, font) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ellipsis


def render_template(line: str, tokens: dict[str, str], ha_state: Callable[[str], str] | None = None) -> str:
    def replace_ha(match: re.Match[str]) -> str:
        refs, fmt = parse_ha_spec(match.group(1))
        for ref in refs:
            value = ha_state(ref) if ha_state else MISSING
            if value and value != MISSING:
                return format_ha_value(value, fmt)
        return MISSING

    rendered = HA_TOKEN_RE.sub(replace_ha, line)

    def replace_token(match: re.Match[str]) -> str:
        return tokens.get(match.group(1), MISSING)

    return TOKEN_RE.sub(replace_token, rendered)


def plain_text(line: str) -> str:
    """Strip layout markers so the line stays readable in logs and MQTT."""
    body = line[1:] if line.startswith(HEADER_PREFIX) else line
    return body.replace(ALIGN_SEP, " ").strip()


def _draw_row(
    draw: ImageDraw.ImageDraw,
    line: str,
    font: ImageFont.ImageFont,
    width: int,
    top: int,
    row_height: int,
    gap: int,
) -> None:
    header = line.startswith(HEADER_PREFIX)
    body = line[1:] if header else line
    if header:
        draw.rectangle((0, top, width - 1, top + row_height - 1), fill=255)
    ink = 0 if header else 255
    pad = 2 if header else 1
    left, separator, right = body.partition(ALIGN_SEP)
    if separator:
        right = fit_text(draw, right.strip(), font, width - 2 * pad)
        right_width = _text_width(draw, right, font)
        left = fit_text(draw, left.strip(), font, max(1, width - right_width - 2 * pad - gap))
        draw.text((pad, top), left, font=font, fill=ink)
        draw.text((width - pad - right_width, top), right, font=font, fill=ink)
    else:
        draw.text((pad, top), fit_text(draw, body, font, width - 2 * pad), font=font, fill=ink)


def render_page(
    page: DisplayPage,
    width: int,
    height: int,
    rotate: int,
    tokens: dict[str, str],
    ha_state: Callable[[str], str] | None = None,
) -> RenderResult:
    image = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(image)
    row_height = 10 if height <= 32 else 12
    font_size = 9 if height <= 32 else 10
    font = _load_font(font_size)
    max_lines = max(1, height // row_height)
    rendered_lines = [render_template(line, tokens, ha_state) for line in page.lines[:max_lines]]
    for index, line in enumerate(rendered_lines):
        _draw_row(draw, line, font, width, index * row_height, row_height, gap=4)
    if rotate:
        image = image.rotate(rotate, expand=True)
    text_lines = [fit_text(draw, plain_text(line), font, width - 2) for line in rendered_lines]
    return RenderResult(image=image, text_lines=text_lines)
