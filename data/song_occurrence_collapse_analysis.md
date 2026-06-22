# Song occurrence collapse analysis

- generated_at: 2026-06-21T03:40:09.280561+00:00
- scope: read_only_song_occurrence_collapse_analysis_no_writes
- duplicate_collapsed_id_count: 2
- intentional_duplicate_collapse_count: 2
- review_required_count: 0
- missing_public_song_row_count: 2
- missing_sqlite_observed_song_id_count: 2

## Rows

| decision | event | venue | year | role | normalized | source_titles | exported_titles | missing |
| --- | --- | --- | ---: | --- | --- | --- | --- | ---: |
| intentional_duplicate_collapse | 山王音頭と民踊大会 | 赤坂日枝神社 | 2025 | result | ダンシングヒーロー | ダンシングヒーロー, ダンシング・ヒーロー | ダンシングヒーロー | 1 |
| intentional_duplicate_collapse | シタマチ.ふるさと盆踊り大会 | おかちまちパンダ広場（御徒町駅南口駅前広場） | 2025 | prediction | かわいいだけじゃだめですか | かわいいだけじゃだめですか, かわいいだけじゃだめですか? | かわいいだけじゃだめですか | 1 |

## Interpretation

- Both rows collapse because punctuation variants normalize to the same song key.
- The exported preview keeps one representative row for each normalized event-song-role key.
- No event occurrence is missing; this affects duplicate public song rows only.
