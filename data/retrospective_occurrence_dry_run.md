# Retrospective occurrence dry-run

- generated_at: 2026-06-13T14:10:25.998360+00:00
- input_candidate_count: 617
- processed_candidate_count: 459
- matched_existing_candidate_count: 29
- matched_existing_occurrence_count: 13
- new_event_candidate_count: 102
- apply_performed: False

## Match Types

- event_name: 5
- event_venue: 3
- venue_month: 8
- venue_only: 13

## Skipped

- tier_hold: 158
- unmatched_song: 272
- unmatched_venue: 56

## Existing Occurrences

| event | venue | candidates | songs | match |
|---|---|---:|---:|---|
| 日本橋小学校の盆踊り（名称推定） | 日本橋小学校 | 4 | 2 | venue_only |
| イベント名未確認（晴海ふ頭公園） | 晴海ふ頭公園 | 1 | 0 | venue_only |
| 戸越宮前盆踊り | 宮前小学校 | 3 | 0 | event_name |
| 小網神社の盆踊り（名称推定） | 小網神社 | 1 | 0 | venue_month |
| Min-Yoi's盆踊り | 日本民謡会館 | 1 | 0 | venue_only |
| イベント名未確認（晴海ふ頭公園） | 晴海ふ頭公園 | 2 | 0 | venue_month |
| 中央区大江戸まつり盆おどり大会 | 浜町公園 | 3 | 0 | event_venue |
| 濱町音頭盆踊り大会 | 浜町公園 | 1 | 1 | event_name |
| 築地本願寺納涼盆踊り大会 | 築地本願寺 | 3 | 0 | venue_only |
| イベント名未確認（築地社会教育会館） | 築地社会教育会館 | 2 | 0 | venue_month |
| すみだ沖縄まつり | 錦糸公園 | 2 | 0 | event_venue |
| 奥浅草盆踊り | 隅田公園 | 4 | 0 | venue_only |
| 飛鳥山公園盆踊り会（有志サークル） | 飛鳥山公園 | 2 | 0 | venue_month |

## New Event Candidates

| priority | score | event | venue | date | flags | evidence |
|---|---:|---|---|---|---|---:|
| high | 55 | 藤沢七夕まつり | 辻堂駅北口神台公園 | 2026-07-04 | high_score | 2 |
| noise_check | 43 | 1夏祭り | 上野公園 | 2026-07-05 | bad_prefix, high_score | 1 |
| noise_check | 43 | 5月9日浅草橋マロニエまつり盆踊り |  | 2026-05-09 | bad_prefix, high_score, no_venue | 1 |
| noise_check | 43 | との盆踊り |  | 2026-06-01 | bad_prefix, high_score, no_venue | 1 |
| noise_check | 43 | は墨田区で盆博というイベントを開催します昨年夏に行った各地の盆踊り |  |  | bad_prefix, high_score, long_phrase, no_venue, sentence_fragment | 1 |
| noise_check | 43 | やります盆踊り |  | 2026-07-25 | high_score, no_venue, sentence_fragment | 1 |
| medium | 43 | ケンくんたちと盆踊り |  | 2026-03-01 | high_score, no_venue | 1 |
| medium | 43 | サンシャインシティ納涼盆踊り大会 |  | 2026-07-30 | high_score, no_venue | 1 |
| noise_check | 43 | 今年初の盆踊り |  | 2026-06-20 | bad_prefix, high_score, no_venue, sentence_fragment | 1 |
| high | 43 | 厳かな神事と伝統の盆踊り | キリストの里公園 | 2026-06-07 | high_score | 1 |
| high | 43 | 真證寺夏祭り | 真證寺 | 2026-08-08 | high_score | 1 |
| medium | 43 | 神田明神アニソン盆踊り |  | 2026-08-07 | high_score, no_venue | 1 |
| medium | 43 | 神田明神納涼祭り |  | 2026-08-07 | high_score, no_venue | 1 |
| medium | 43 | 西馬音内盆踊り |  | 2026-06-01 | high_score, no_venue | 1 |
| medium | 43 | 雷門盆踊り |  |  | high_score, no_venue | 1 |
| high | 40 | ビールと浴衣de盆踊り | 上野公園 | 2026-07-03 | high_score | 2 |
| medium | 40 | 日本の伝統的な盆踊り |  | 2026-05-31 | high_score, no_venue | 42 |
| high | 40 | 横浜の街が一体となって踊る盆踊り | プラザ広場 | 2026-06-01 | high_score | 2 |
| medium | 40 | 活気あふれる初夏の盆踊り |  | 2026-06-07 | high_score, no_venue | 4 |
| high | 40 | 潮風を感じながら踊る盆踊り | プラザ広場 | 2026-06-01 | high_score | 12 |
| noise_check | 33 | 1板橋区盆踊り |  | 2026-07-31 | bad_prefix, no_venue | 1 |
| noise_check | 33 | 7日藤沢駅前サンパール広場で開催される盆踊り | 7日藤沢駅前サンパール広場 | 2026-06-07 | bad_prefix, long_phrase | 1 |
| low | 33 | POPバンド・よさこい・盆踊り |  | 2026-03-14 | no_venue | 1 |
| low | 33 | TOKYO盆ダンス | 上野恩賜公園 | 2026-06-26 |  | 1 |
| low | 33 | aikoと盆踊り |  |  | no_venue | 1 |
| low | 33 | ええじゃないか盆踊り |  | 2026-06-09 | no_venue | 1 |
| noise_check | 33 | ここから築地本願寺盆踊り | 波除神社 | 2026-06-10 | bad_prefix | 1 |
| low | 33 | さくら公園盆踊り大会 | さくら公園 | 2026-06-11 |  | 1 |
| noise_check | 33 | すっかり盆踊り |  |  | bad_prefix, no_venue | 1 |
| noise_check | 33 | たぶん中野盆踊り大会 |  | 2026-08-02 | bad_prefix, no_venue | 1 |
| noise_check | 33 | とある盆踊り |  | 2026-05-17 | bad_prefix, no_venue | 1 |
| noise_check | 33 | は日本民謡協会の盆踊り |  | 2026-06-14 | bad_prefix, no_venue | 1 |
| low | 33 | ふるさと千川まつり |  | 2026-06-05 | no_venue | 1 |
| low | 33 | ぼす子の盆踊り |  |  | no_venue | 1 |
| low | 33 | みんなたのしい盆踊り |  |  | no_venue | 1 |
| low | 33 | やつか納涼祭 |  | 2026-08-02 | no_venue | 1 |
| noise_check | 33 | ゆりイベントで流し踊りやステージ盆踊り | と民謡会館 |  | long_phrase | 1 |
| low | 33 | アキバ盆踊り |  | 2026-06-21 | no_venue | 1 |
| low | 33 | アキバ盆踊り |  | 2026-06-27 | no_venue | 1 |
| low | 33 | アニソン盆踊り | 上野恩賜公園 | 2026-06-13 |  | 1 |
| low | 33 | フラしてるのか盆踊り |  |  | no_venue | 1 |
| low | 33 | マスカレード盆踊り |  | 2026-06-12 | no_venue | 1 |
| low | 33 | 一宮踊ろまい会様の盆踊り |  |  | no_venue | 1 |
| noise_check | 33 | 中で帰ったけどチームマスクドめっちゃ楽しかったし郷土芸能部は盆踊り |  |  | long_phrase, no_venue, sentence_fragment | 1 |
| low | 33 | 今年の新潟まつり・大民謡流し |  | 2026-08-07 | no_venue | 1 |
| low | 33 | 今日は縁あって田園調布のお祭り | 浅間神社例大祭に合わせて駅前 |  |  | 1 |
| noise_check | 33 | 今週末はこちらの元祖上郷おいでんで14時くらいから15時まで盆踊り |  |  | long_phrase, no_venue, sentence_fragment | 1 |
| low | 33 | 写楽盆踊り | 徳島駅前 | 2026-08-15 |  | 1 |
| low | 33 | 創作盆踊り |  | 2026-08-01 | no_venue | 1 |
| low | 33 | 勉強や盆踊り |  |  | no_venue | 1 |
| low | 33 | 勝手に盆踊り |  |  | no_venue | 1 |
| low | 33 | 午後2時から盆踊り | 明日狛江駅前 |  |  | 1 |
| low | 33 | 南新町納涼ふるさとまつり | 谷口ふれあい広場 | 2026-06-04 |  | 1 |
| low | 33 | 夏祭りのお話から省エネ夏祭り |  |  | no_venue | 1 |
| low | 33 | 夏祭りや盆踊り |  | 2026-06-01 | no_venue | 1 |
| low | 33 | 夕方5時半から盆踊り |  |  | no_venue | 1 |
| low | 33 | 宮前盆踊り | 荏原神社 |  |  | 1 |
| low | 33 | 小一時間盆踊り |  |  | no_venue | 1 |
| low | 33 | 日本の盆踊り |  |  | no_venue | 1 |
| low | 33 | 日本の祭り | 西浅草八幡神社 | 2026-05-17 |  | 1 |
| low | 33 | 日本丸みなと盆踊り |  | 2027-05-01 | no_venue | 1 |
| low | 33 | 昔の盆踊り |  |  | no_venue | 1 |
| low | 33 | 東根小学校盆踊り | 東根小学校 | 2026-06-13 |  | 1 |
| low | 33 | 生誕の練習を盆踊り |  |  | no_venue | 1 |
| low | 33 | 神奈川で古くから伝わる祭り |  |  | no_venue | 1 |
| low | 33 | 福島の盆踊り |  |  | no_venue | 1 |
| noise_check | 33 | 群馬県伊勢崎駅前でアニメソング盆踊り | 群馬県伊勢崎駅前 | 2026-07-19 | long_phrase | 1 |
| low | 33 | 舟渡ホール盆踊り |  | 2026-06-09 | no_venue | 1 |
| low | 33 | 西馬音内盆踊り |  |  | no_venue | 1 |
| low | 33 | 赤塚・中田出世稲荷神社盆踊り | 中田出世稲荷神社 | 2026-07-11 |  | 1 |
| low | 33 | 足寄ふるさと盆踊り |  | 2026-08-15 | no_venue | 1 |
| low | 33 | 足立区の盆踊りで最も早い盆踊り | 五反野コミュニティセンター横の公園 | 2026-06-20 |  | 1 |
| low | 33 | 高島越後盆踊り |  | 2026-06-09 | no_venue | 1 |
| noise_check | 28 | 2ヶ月先だけど今年の地域の盆踊り | 去年から花火大会と神社 |  | bad_prefix | 1 |
| low | 28 | しっかり盆踊り |  |  | no_venue | 1 |
| noise_check | 28 | そういやこないだの近所の祭りで今年初盆踊り |  |  | long_phrase, no_venue | 1 |
| low | 28 | なお今年も火の国まつり |  |  | no_venue | 1 |
| low | 28 | んーーー盆踊り |  |  | no_venue | 1 |
| low | 28 | エクストリーム盆祭り | 大阪城公園 |  |  | 1 |
| low | 28 | 一人でお祭り |  |  | no_venue | 1 |
| low | 28 | 可愛いの作ってお祭り |  |  | no_venue | 1 |
| low | 28 | 地元の日永つんつく夏祭り |  |  | no_venue | 1 |
| low | 28 | 大晦日のうちに2025年盆踊り | 第1回晴海埠頭公園 |  |  | 1 |
| low | 28 | 大須夏祭りの盆踊り |  |  | no_venue | 1 |
| low | 28 | 新宝島の盆踊り |  |  | no_venue | 1 |
| noise_check | 28 | 昨年6年ぶり復活した盆踊り |  |  | no_venue, sentence_fragment | 1 |
| low | 28 | 笠間納涼盆踊り |  |  | no_venue | 1 |
| low | 28 | 第二回小島民踊研究会大盆踊り |  |  | no_venue | 1 |
| low | 28 | 蔦屋重三郎に思いを馳せて盆踊り | 去年はあかつき公園 |  |  | 1 |
| low | 28 | 都心開催の盆ダンス |  |  | no_venue | 1 |
| low | 28 | 金沢百万石まつり |  |  | no_venue | 1 |
| low | 28 | 鳳蝶会DJCelly盆踊り |  |  | no_venue | 1 |
| low | 25 | やっぱり盆踊り |  |  | no_venue | 8 |
| low | 25 | 一宮盆踊り |  |  | no_venue | 2 |
| low | 25 | 山科の笠原寺の盆踊り（名称未確定） | 山科の笠原寺 | 2026-07-26 |  | 1 |
| low | 25 | 河原町広場の盆踊り（名称未確定） | 河原町広場 | 2026-06-01 |  | 1 |
| low | 25 | 飛鳥山公園の盆踊り（名称未確定） | 飛鳥山公園 |  |  | 1 |
| low | 25 | 鮫洲入江公園の盆踊り（名称未確定） | 鮫洲入江公園 |  |  | 1 |
| low | 23 | 去年は大江戸まつり |  | 2026-03-04 | no_venue | 1 |
| low | 23 | 鬼会と平和祭り |  | 2026-09-21 | no_venue | 1 |
| low | 20 | 西本願寺の盆踊り（名称未確定） | 西本願寺 |  |  | 1 |
| low | 20 | 鳥越まつり | 鳥越神社 | 2026-06-06 |  | 3 |
