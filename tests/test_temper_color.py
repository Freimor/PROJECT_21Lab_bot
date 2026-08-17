from lab21_bot.data import contrast_ink, temper_color


def test_temper_color_endpoints() -> None:
    assert temper_color(0, 10) == "#f5e6a3"
    assert temper_color(10, 10) == "#3a6bc4"
    assert temper_color(0, 0) == "#f5e6a3"


def test_contrast_ink() -> None:
    assert contrast_ink("#f5e6a3") == "#1a120c"
    assert contrast_ink("#3a6bc4") == "#ebecec"
