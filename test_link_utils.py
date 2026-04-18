import unittest

from link_utils import to_direct_stream_url


class ToDirectStreamUrlTests(unittest.TestCase):
    def test_www_dropbox_dl0_to_dl1(self):
        url = "https://www.dropbox.com/s/abc/file.mp3?dl=0"
        out = to_direct_stream_url(url)
        self.assertIn("dl.dropboxusercontent.com", out)
        self.assertIn("dl=1", out)

    def test_raw_zero_to_raw_one(self):
        url = "https://www.dropbox.com/s/abc/file.mp3?raw=0"
        out = to_direct_stream_url(url)
        self.assertIn("dl.dropboxusercontent.com", out)
        self.assertIn("raw=1", out)


if __name__ == "__main__":
    unittest.main()
