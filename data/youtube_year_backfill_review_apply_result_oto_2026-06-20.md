# YouTube年バックフィル review 適用結果

- 生成: 2026-06-20T10:08:11.518982+00:00
- mode: apply
- fetched_descriptions: False (0 videos)
- 判定内訳: {'accept_with_songs_existing_occurrence': 1, 'hold': 2, 'merge_to_existing': 1, 'partial_merge_drop_mismatch': 1, 'reject': 2}
- manual evidence 追加: 3 items / 28 song mentions
- source再実行削除: 0 items

## accept_with_songs

| event | year | videos | evidence_items | song_mentions | unique_songs |
| --- | --- | ---: | ---: | ---: | ---: |
| 赤坂浄土寺盆踊り大会 | 2023 | 3 | 3 | 28 | 10 |

## occurrence only / hold

- 築地本願寺納涼盆踊り大会 (2024): 1 videos / 第77回築地本願寺納涼盆踊り大会の補助動画。曲目・日付の主証拠ではなく、既存2024開催回の補助として保持。

## skipped

- [hold] 奥沢交和会 (2023): 奉優会の夏の思い出動画で、盆踊りイベント名・日付・会場の直接証拠が不足。単一動画のため保留。
- [reject] 納涼盆踊り大会 (2023): 汎用名『納涼盆踊り大会』による誤マッチ。番町/緑など別会場由来で、玉川中町公園の開催回証拠ではない。
- [hold] 親子盆踊り大会 (2023): タイトルに八幡盆踊りと2023-08-14らしき日付はあるが、対象の八幡小学校・親子盆踊り大会との同一性が単一動画だけでは不足。
- [reject] 納涼盆踊り大会 (2024): 市場納涼盆踊り大会および浅草納涼盆踊り大会の動画で、玉川中町公園の開催回証拠ではない。
- [partial_merge_drop_mismatch] 郡上おどり in 青山 (2024): 2024-06-14公開の満員御礼動画は既存2024開催回の補助として保持可。2025-06-20公開の観光動画はtarget_year=2024の証拠として使わない。
