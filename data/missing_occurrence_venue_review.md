# Missing occurrence venue review

- generated_at: 2026-06-22T03:32:15.515992+00:00
- scope: read_only_missing_occurrence_venue_review
- missing_venue_occurrence_count: 12
- actions: {'series_link_review_existing_venue_candidate': 3, 'manual_name_or_venue_research_required': 1, 'manual_venue_research_required': 3, 'new_venue_candidate_needs_source': 3, 'ready_existing_venue_candidate': 1, 'preserve_missing_unregistered_historical_venue': 1}
- candidate_existing_venue_count: 4
- new_or_unregistered_venue_candidate_count: 4

| action | event | date | candidate venue | confidence | next step |
| --- | --- | --- | --- | --- | --- |
| series_link_review_existing_venue_candidate | 郡上おどり in 青山 | 2025-06-20 to 2025-06-21 | 秩父宮ラグビー場駐車場 (`ven_a52431fddb1891f8`) | high | resolve duplicate 郡上おどり in 青山 series before applying the venue to the 2025 row |
| manual_name_or_venue_research_required | えどぐらん（江東区） |  |  | low | verify event name and venue source before any venue_id fill |
| manual_venue_research_required | すみだ河内音頭 小盆踊り | 2026-05-16 |  | low | research exact venue before filling venue_id |
| series_link_review_existing_venue_candidate | マロニエまつり盆踊り大会 | 2026-05-09 | ヒューリック浅草橋ビル前 (`ven_e82a2aed94e45d29`) | high | treat as duplicate/alias review rather than a standalone venue fill |
| manual_venue_research_required | 中野駅前大盆踊り大会 |  |  | low | check official site and create/link the exact venue if confirmed |
| manual_venue_research_required | 佃島の盆踊り | 2026-07-13 to 2026-07-15 |  | low | research exact venue before filling venue_id |
| series_link_review_existing_venue_candidate | 新橋こいち祭 | 2026-07-23 to 2026-07-24 | 桜田公園 (`ven_331b917a98238b0d`) | high | link or merge the generic 新橋こいち祭 series with the curated numbered bon-odori series before filling venue_id |
| new_venue_candidate_needs_source | 月島第二児童公園 盆踊り |  | 月島第二児童公園 | low | confirm address/source before creating a venue row |
| ready_existing_venue_candidate | 藤沢七夕まつり（DJ盆踊り大会） | 2026-07-04 | 辻堂神台公園 (`ven_61c6063cf53195b5`) | high | safe candidate for local RDB venue_id fill after deciding whether predicted 2026 rows should be materialized |
| new_venue_candidate_needs_source | 鉄砲洲児童公園 盆踊り |  | 鉄砲洲児童公園 | low | confirm address/source before creating a venue row |
| preserve_missing_unregistered_historical_venue | 銀座一丁目東町会・新富町会 納涼盆踊り大会 |  | 京橋プラザ | medium | register 京橋プラザ as a venue first if current/future occurrences need a venue_id |
| new_venue_candidate_needs_source | 雷門盆踊り（浅草） |  | 雷門付近 | low | find official/current source before creating or linking a venue |
