# 曲予測較正レポート

- scored_count: 95
- scored_event_count: 5
- mean_brier: 0.017007

## イベント別

| event | venue | scored | present | mean_probability | mean_soft_label | mean_brier |
|---|---|---:|---:|---:|---:|---:|
| Min-Yoi's盆踊り | 日本民謡会館 | 40 | 40 | 0.8647 | 0.95 | 0.039273 |
| 国立旭通りジューンフェスタ盆踊り | 国立旭通り | 6 | 6 | 0.99 | 0.95 | 0.0016 |
| 山王音頭と民踊大会 | 山王パークタワー公開空地 | 19 | 19 | 0.8 | 0.8 | 0.0 |
| 横浜開港祭 BON ODORI | パシフィコ横浜プラザ広場 | 10 | 10 | 0.99 | 0.95 | 0.0016 |
| 飛鳥山公園盆踊り会（有志サークル） | 飛鳥山公園 | 20 | 20 | 0.974 | 0.95 | 0.00096 |

## 信頼度キー別

| reliability_key | scored | present | mean_probability | mean_soft_label | mean_brier | suggested_reliability | delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| semi_official_setlist | 19 | 19 | 0.8 | 0.8 | 0.0 | 0.8 | 0.0 |
| unknown | 76 | 76 | 0.9199 | 0.95 | 0.021259 | 0.95 | 0.0301 |

## 山王メモ

- 2026-06-13 現地確認で、落合弘民踊研究会の事前告知19曲が過不足なく全一致。
- 山王19曲は probability=0.80 / soft_label=0.80 / Brier=0.0。
- `semi_official_setlist` は suggested_reliability=0.80 / delta=0.0 で、今回の1件では更新不要。
