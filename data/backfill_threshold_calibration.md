# 裏取りキューv2 閾値較正メモ

- source: `data/event_occurrence_backfill_plan.json`
- accepted_observations: 24
- excluded_low_observations: 8
- promote_candidate_count: 2
- recommendation: none
- reason: Keep automatic promotion unchanged. Review excluded low rows in the multi_video_* buckets first; single-video rows should stay manual.

## bucket counts

| bucket | accepted | excluded_low |
| --- | ---: | ---: |
| multi_video | 2 | 1 |
| multi_video_multi_channel | 16 | 0 |
| multi_video_song_context | 0 | 2 |
| multi_video_song_rich | 6 | 0 |
| single_video_song_context | 0 | 2 |
| single_weak | 0 | 3 |

## review-first candidates

| bucket | videos | channels | songs | year | date | event | venue | sample |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| multi_video_song_context | 2 | 1 | 10 | 2023 | 2023-07-17 | 自由が丘納涼盆踊り大会 | 自由が丘駅前ロータリー 特設会場 | やる気で音頭　2023年自由が丘納涼盆踊り大会１　東京都目黒区 https://www.youtube.com/watch?v=QPxuVq-Nv3w |
| multi_video_song_context | 2 | 1 | 10 | 2023 | 2023-03-12 | 飛鳥山盆踊り | 飛鳥山公園 | しながわ中央公園盆踊り　2023年3月12日　じょんから女節・品川音頭・大森甚句・波乗りジョニー・房州よいとこ・ベイサイドブギ・湘南盆踊り・水軍ばやし・我は海の子・飛び魚音頭・お台場音頭・ポ https://www.youtube.com/watch?v=-dahLlLBKHo |
