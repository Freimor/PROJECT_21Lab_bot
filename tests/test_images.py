from lab21_bot.services.images import prepare_browser_image, sniffed_image_type


def test_sniff_rejects_mislabeled_heic() -> None:
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32
    assert sniffed_image_type(heic) == "image/heif"
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 8
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    assert sniffed_image_type(jpeg) == "image/jpeg"
    assert sniffed_image_type(png) == "image/png"


def test_prepare_keeps_real_jpeg_even_if_labeled_png() -> None:
    jpeg = b"\xff\xd8\xff\xe0" + b"rest"
    content, content_type = prepare_browser_image(jpeg, "image/png")
    assert content == jpeg
    assert content_type == "image/jpeg"


def test_prepare_converts_heic_when_decoder_is_available() -> None:
    try:
        import pillow_heif
        from PIL import Image
    except ImportError:
        return
    import io

    source = Image.new("RGB", (8, 8), (20, 40, 60))
    raw = io.BytesIO()
    pillow_heif.from_pillow(source).save(raw, quality=50)
    heic = raw.getvalue()
    assert sniffed_image_type(heic) == "image/heif"
    content, content_type = prepare_browser_image(heic, "image/png")
    assert content_type == "image/jpeg"
    assert content.startswith(b"\xff\xd8\xff")
