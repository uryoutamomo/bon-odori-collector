from sync_public_event_source_urls_to_site import build_site_events, merge_source_urls


def test_merge_source_urls_adds_missing_collector_url_without_losing_official():
    site_sources = [
        {"label": "公式告知あり", "url": "https://example.com/official", "kind": "official"},
        {"label": "告知HPあり", "url": "", "kind": "web", "count": 1},
    ]
    collector_sources = [
        {"label": "告知HPあり", "url": "https://example.com/official", "kind": "web"},
        {"label": "告知HPあり", "url": "https://example.com/extra", "kind": "web"},
    ]

    merged, additions = merge_source_urls(site_sources, collector_sources)

    assert [source["url"] for source in additions] == ["https://example.com/extra"]
    assert [source["url"] for source in merged] == [
        "https://example.com/official",
        "https://example.com/extra",
    ]
    assert merged[0]["kind"] == "official"


def test_build_site_events_updates_only_matching_events():
    collector = [
        {
            "name": "追加元盆踊り",
            "venue": "広場",
            "source_urls": [{"url": "https://example.com/source", "kind": "web"}],
        },
        {
            "name": "siteにない盆踊り",
            "venue": "公園",
            "source_urls": [{"url": "https://example.com/missing", "kind": "web"}],
        },
    ]
    site = [
        {
            "name": "追加元盆踊り",
            "venue": "広場",
            "source_urls": [{"url": "", "kind": "web", "count": 1}],
        }
    ]

    proposed, rows, missing = build_site_events(collector, site)

    assert proposed[0]["source_urls"] == [{"url": "https://example.com/source", "kind": "web"}]
    assert rows[0]["added_urls"] == ["https://example.com/source"]
    assert missing == ["siteにない盆踊り␟公園"]
