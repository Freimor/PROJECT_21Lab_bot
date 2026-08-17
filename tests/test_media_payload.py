from types import SimpleNamespace

from lab21_bot.handlers import _is_gif_document, _meme_payload_from_messages


def _msg(**kwargs):
    defaults = {
        "photo": None,
        "animation": None,
        "video": None,
        "document": None,
        "text": None,
        "caption": None,
        "sticker": None,
        "voice": None,
        "video_note": None,
        "audio": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_meme_payload_accepts_animation() -> None:
    animation = SimpleNamespace(file_id="gif-file")
    payload = _meme_payload_from_messages(
        [_msg(animation=animation, caption="буу")]
    )
    assert payload is not None
    text, media = payload
    assert text == "буу"
    assert media == [{"type": "animation", "file_id": "gif-file"}]


def test_meme_payload_accepts_gif_document() -> None:
    doc = SimpleNamespace(file_id="doc-gif", mime_type="image/gif", file_name="lol.gif")
    payload = _meme_payload_from_messages([_msg(document=doc)])
    assert payload is not None
    _, media = payload
    assert media == [{"type": "document", "file_id": "doc-gif"}]


def test_meme_payload_rejects_video() -> None:
    video = SimpleNamespace(file_id="vid")
    assert _meme_payload_from_messages([_msg(video=video)]) is None


def test_is_gif_document() -> None:
    assert _is_gif_document(
        _msg(document=SimpleNamespace(mime_type="image/gif", file_name="a.bin"))
    )
    assert _is_gif_document(
        _msg(document=SimpleNamespace(mime_type="application/octet-stream", file_name="x.gif"))
    )
    assert not _is_gif_document(
        _msg(document=SimpleNamespace(mime_type="application/pdf", file_name="a.pdf"))
    )
