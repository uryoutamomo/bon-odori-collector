import unittest

from youtube_channels.active_video_review import video_id_from_url as review_video_id_from_url
from youtube_channels.backfill_youtube_descriptions import video_id_from_url as backfill_video_id_from_url
from youtube_channels.video_urls import video_id_from_url


class YoutubeVideoUrlsTest(unittest.TestCase):
    def test_accepts_only_supported_video_url_forms(self):
        cases = {
            "https://youtube.com/watch?v=abc123": "abc123",
            "http://www.youtube.com/watch?v=Ab_-9&t=10": "Ab_-9",
            "https://m.youtube.com/shorts/u1?feature=share": "u1",
            "https://youtu.be/abc123?si=token": "abc123",
            "https://youtu.be/u1#fragment": "u1",
            "https://www.youtube.com/watch?v=": "",
            "https://www.youtube.com/watch?v=first&v=second": "",
            "https://www.youtube.com/watch?v=abc123&v=": "",
            "https://www.youtube.com/watch?v=&v=": "",
            "https://www.youtube.com/watch?x=abc123": "",
            "https://www.youtube.com/shorts/abc123/more": "",
            "https://youtu.be/abc123/more": "",
            "https://www.youtube.com/channel/UCabc": "",
            "https://www.youtube.com/@channel": "",
            "https://www.youtube.com/playlist?list=PLabc": "",
            "https://music.youtube.com/watch?v=abc123": "",
            "https://youtube.com.evil.example/watch?v=abc123": "",
            "https://youtu.be.evil.example/abc123": "",
            "ftp://youtube.com/watch?v=abc123": "",
            "https://www.youtube.com/watch?v=bad%2Fid": "",
            "not a url": "",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(video_id_from_url(url), expected)

    def test_both_consumers_reexport_the_shared_parser(self):
        self.assertIs(review_video_id_from_url, video_id_from_url)
        self.assertIs(backfill_video_id_from_url, video_id_from_url)


if __name__ == "__main__":
    unittest.main()
