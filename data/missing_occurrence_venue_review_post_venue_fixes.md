# Missing occurrence venue review

- generated_at: 2026-06-22T04:41:31.952008+00:00
- scope: read_only_missing_occurrence_venue_review
- missing_venue_occurrence_count: 7
- actions: {'manual_name_or_venue_research_required': 1, 'manual_venue_research_required': 2, 'new_venue_candidate_needs_source': 3, 'preserve_missing_unregistered_historical_venue': 1}
- candidate_existing_venue_count: 0
- new_or_unregistered_venue_candidate_count: 4

| action | event | date | candidate venue | confidence | next step |
| --- | --- | --- | --- | --- | --- |
| manual_name_or_venue_research_required | えどぐらん（江東区） |  |  | low | verify event name and venue source before any venue_id fill |
| manual_venue_research_required | すみだ河内音頭 小盆踊り | 2026-05-16 |  | low | research exact venue before filling venue_id |
| manual_venue_research_required | 佃島の盆踊り | 2026-07-13 to 2026-07-15 |  | low | research exact venue before filling venue_id |
| new_venue_candidate_needs_source | 月島第二児童公園 盆踊り |  | 月島第二児童公園 | low | confirm address/source before creating a venue row |
| new_venue_candidate_needs_source | 鉄砲洲児童公園 盆踊り |  | 鉄砲洲児童公園 | low | confirm address/source before creating a venue row |
| preserve_missing_unregistered_historical_venue | 銀座一丁目東町会・新富町会 納涼盆踊り大会 |  | 京橋プラザ | medium | register 京橋プラザ as a venue first if current/future occurrences need a venue_id |
| new_venue_candidate_needs_source | 雷門盆踊り（浅草） |  | 雷門付近 | low | find official/current source before creating or linking a venue |
