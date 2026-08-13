from unittest.mock import patch
import collect


def tweet(url, *, missing=False):
    row = {"id": url or "empty", "url": url, "text": "盆踊り", "author": {"userName": "a"}}
    if missing: row = {"text": "盆踊り", "author": {}}
    return row


def test_prepare_new_x_posts_excludes_duplicate_seen_new_seen_and_empty_urls():
    with patch.object(collect, "capture_raw_x_posts"):
        assert len(collect._prepare_new_x_posts([tweet("https://x/a"), tweet("https://x/a")], set(), set(), {})) == 1
        assert collect._prepare_new_x_posts([tweet("https://x/a")], {"https://x/a"}, set(), {}) == []
        assert collect._prepare_new_x_posts([tweet("https://x/a")], set(), {"https://x/a"}, {}) == []
        assert collect._prepare_new_x_posts([tweet("", missing=True)], set(), set(), {}) == []
