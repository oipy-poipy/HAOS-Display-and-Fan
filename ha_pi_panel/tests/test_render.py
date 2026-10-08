from app.config import DisplayPage
from app.render import extract_ha_entities, render_page, render_template


def test_template_renders_tokens_and_missing_ha_state():
    line = "CPU {cpu_temp_c} Outside {ha:sensor.outdoor_temperature}"

    assert render_template(line, {"cpu_temp_c": "42.0"}) == "CPU 42.0 Outside --"


def test_template_renders_ha_state():
    line = "Outside {ha:sensor.outdoor_temperature}"

    assert render_template(line, {}, lambda entity_id: "72") == "Outside 72"


def test_extract_ha_entities():
    pages = [DisplayPage("Home", ["A {ha:sensor.one}", "B {ha:weather.home}"])]

    assert extract_ha_entities(pages) == {"sensor.one", "weather.home"}


def test_render_128x32_limits_lines():
    page = DisplayPage("Small", ["1", "2", "3", "4", "5"])

    result = render_page(page, 128, 32, 0, {}, None)

    assert result.image.size == (128, 32)
    assert len(result.text_lines) <= 3


def test_template_uses_first_available_fallback_ref():
    line = "Out {ha:sensor.missing,weather.home@temperature|1°C}"
    states = {"sensor.missing": "--", "weather.home@temperature": "12.345"}

    assert render_template(line, {}, states.get) == "Out 12.3°C"


def test_template_drops_suffix_when_no_ref_resolves():
    line = "Out {ha:sensor.missing,sensor.gone|1°C}"

    assert render_template(line, {}, lambda ref: "--") == "Out --"


def test_template_prettifies_weather_state():
    assert render_template("{ha:weather.home}", {}, lambda ref: "partlycloudy") == "Part cloud"


def test_template_keeps_non_numeric_value_when_rounding_requested():
    assert render_template("{ha:sensor.x|1}", {}, lambda ref: "idle") == "idle"


def test_extract_ha_entities_splits_fallbacks_and_attributes():
    pages = [DisplayPage("Home", ["{ha:sensor.one,weather.home@temperature|1°C}"])]

    assert extract_ha_entities(pages) == {"sensor.one", "weather.home"}


def test_render_page_strips_layout_markers_from_text_lines():
    page = DisplayPage("System", ["#{hostname}\t{clock}", "CPU\t{cpu_temp_c}°C"])

    result = render_page(page, 128, 64, 0, {"hostname": "pi", "clock": "21:04", "cpu_temp_c": "44.1"}, None)

    assert result.text_lines == ["pi 21:04", "CPU 44.1°C"]


def test_render_page_header_inverts_the_row():
    page = DisplayPage("System", ["#Header"])

    result = render_page(page, 128, 64, 0, {}, None)

    # Inverted rows paint a filled bar, so the last pixel of the row is lit.
    assert result.image.getpixel((127, 0)) == 255
    assert result.image.getpixel((127, 40)) == 0


def test_render_page_right_aligns_the_value_after_a_tab():
    page = DisplayPage("System", ["CPU\t44.1°C"])

    result = render_page(page, 128, 64, 0, {}, None)
    lit_columns = [x for x in range(128) if any(result.image.getpixel((x, y)) for y in range(12))]

    assert lit_columns[0] < 10
    assert lit_columns[-1] > 110
