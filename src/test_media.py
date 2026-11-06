import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from PIL import Image
from media import allowed_image, image_png, load_image


class MediaTests(unittest.TestCase):
    def blob(self, mode="PNG"):
        stream = io.BytesIO()
        Image.new("RGB", (500, 250), "orange").save(stream, mode)
        return stream.getvalue()

    def response(self, blob=b"", status=200, location=""):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = status
        response.headers = {"Location": location}
        response.iter_content.return_value = [blob]
        return response

    def test_jpeg_and_png_are_decoded_to_visible_scaled_png(self):
        for mode in ["JPEG", "PNG", "WEBP"]:
            with Image.open(io.BytesIO(image_png(self.blob(mode)))) as result:
                self.assertEqual(result.format, "PNG")
                self.assertEqual(result.size, (256, 128))

    def test_current_steam_cdn_and_asset_specific_paths_allowed(self):
        self.assertTrue(allowed_image("https://community.steamstatic.com/economy/image/opaque-painted-token/256fx256f"))
        for url in ["http://community.steamstatic.com/economy/image/a", "https://evil.test/economy/image/a",
                    "https://community.steamstatic.com/login", "https://x@community.steamstatic.com/economy/image/a"]:
            self.assertFalse(allowed_image(url))

    def test_cdn_redirect_and_cache_do_not_need_steam_session(self):
        with tempfile.TemporaryDirectory() as directory:
            session = MagicMock()
            url = "https://community.steamstatic.com/economy/image/paint-one/256fx256f"
            final = "https://community.akamai.steamstatic.com/economy/image/paint-one/256fx256f"
            session.get.side_effect = [self.response(status=302, location=final), self.response(self.blob("JPEG"))]
            first = load_image(url, Path(directory), session)
            second = load_image(url, Path(directory), session)
            self.assertEqual(first, second)
            self.assertEqual(session.get.call_count, 2)
            self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    def test_external_redirect_is_never_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            session = MagicMock()
            session.get.side_effect = lambda *a, **kw: self.response(status=302, location="https://evil.test/image")
            with self.assertRaises(ValueError):
                load_image("https://community.steamstatic.com/economy/image/a", Path(directory), session)
            self.assertTrue(all(allowed_image(call.args[0]) for call in session.get.call_args_list))

    def test_corrupt_image_is_not_cached_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            session = MagicMock()
            session.get.side_effect = lambda *a, **kw: self.response(b"<html>error</html>")
            with self.assertRaises(ValueError):
                load_image("https://community.steamstatic.com/economy/image/a", Path(directory), session)
            self.assertEqual(list(Path(directory).iterdir()), [])
