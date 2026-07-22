import json
import os
from pathlib import Path

from notion_support.notion_api import NotionApi, plain_text
from notion_config import EVENT_DATA_SOURCE_ID, VENUE_DATA_SOURCE_ID


STATE_PATH = Path(__file__).parent / "data" / "venue_review_state.json"


VENUES = [
    {
        "queue_name": "日本民謡会館",
        "venue_name": "日本民謡会館",
        "aliases": ["日本民謡会館", "日本民謡協会ホール"],
        "region": "品川区",
        "address": "東京都品川区南品川6-8-20",
        "access": "大井町駅から徒歩圏内",
        "source_url": "https://www.youtube.com/watch?v=9lkufMdYu2c",
        "memo": "2026-05-31に日本民謡協会ホールでMin-Yoi's盆踊り開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "Min-Yoi's盆踊り",
            "date": "2026-05-31",
            "status": "終了",
            "source_url": "https://www.youtube.com/watch?v=9lkufMdYu2c",
            "month": "5月",
            "pattern_type": "不明",
            "pattern_detail": "2026-05-31（日）開催記録。次回日程は未確認。",
        },
    },
    {
        "queue_name": "鮫洲入江広場",
        "venue_name": "鮫洲入江広場公園",
        "aliases": ["鮫洲入江広場", "鮫洲入江広場公園", "鮫洲入江公園"],
        "region": "品川区",
        "address": "東京都品川区東大井1-16-15",
        "access": "京急 鮫洲駅から徒歩約5分",
        "source_url": "https://x.com/mizu516AforReal/status/2062799802266710143",
        "memo": "2026-06-06のゆり園イベント内で晴盆の盆踊り枠あり。",
        "in_tsukiji": True,
        "event": {
            "name": "鮫洲入江広場公園 ゆり園盆踊り",
            "date": "2026-06-06",
            "status": "終了",
            "source_url": "https://x.com/mizu516AforReal/status/2062799802266710143",
            "month": "6月",
            "pattern_type": "不明",
            "pattern_detail": "2026-06-06（土）14:30から晴盆の盆踊り枠。次回日程は未確認。",
        },
    },
    {
        "queue_name": "西大井広場",
        "venue_name": "西大井広場公園",
        "aliases": ["西大井広場", "西大井広場公園"],
        "region": "品川区",
        "address": "東京都品川区西大井1丁目4-10",
        "access": "横須賀線・湘南新宿ライン 西大井駅から徒歩約5分",
        "source_url": "https://bonmaru.zenmin-odori.jp/archives/202668",
        "memo": "2025-09-27に品川区民まつりの盆踊りの部として開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "品川区民まつり 西大井広場公園 盆踊り",
            "date": "2025-09-27",
            "status": "終了",
            "source_url": "https://bonmaru.zenmin-odori.jp/archives/202668",
            "month": "9月",
            "pattern_type": "不明",
            "pattern_detail": "2025-09-27 17:40～18:30の開催記録。通常は9月のどこか1日。2026年日程は未確認。",
        },
    },
    {
        "queue_name": "向島百花会館",
        "venue_name": "向島百花会館",
        "aliases": ["向島百花会館"],
        "region": "墨田区",
        "address": "東京都墨田区東向島3-29-5",
        "access": "東向島駅・曳舟駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2026/01/00g-sumida-q.html",
        "memo": "2026-03-01に西図子「盆踊りとおでんの宴」開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "西図子 盆踊りとおでんの宴",
            "date": "2026-03-01",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2026/01/00g-sumida-q.html",
            "month": "3月",
            "pattern_type": "不明",
            "pattern_detail": "2026-03-01（日）14:00-17:00開催記録。東京音頭、スカイツリー踊り、河内音頭など。",
        },
    },
    {
        "queue_name": "桜フェスタ商店街",
        "venue_name": "都立大学駅西口緑道",
        "aliases": ["都立大学駅西口緑道", "桜フェスタ商店街"],
        "region": "目黒区",
        "address": "東京都目黒区中根1-3-10",
        "access": "東急東横線 都立大学駅すぐ",
        "source_url": "https://minato-bon-odori.blogspot.com/2026/01/00j-meguro-q.html",
        "memo": "元候補名「桜フェスタ商店街」はイベント名寄り。会場は都立大学駅西口緑道として登録。",
        "in_tsukiji": False,
        "event": {
            "name": "桜フェスタ商店街 みんなで盆踊り",
            "date": "2026-03-29",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2026/01/00j-meguro-q.html",
            "month": "3月",
            "pattern_type": "不明",
            "pattern_detail": "2026-03-29（日）15:15から演舞＆みんなで盆踊り。主催は富志美会（都立大学駅前商店会）。",
        },
    },
    {
        "queue_name": "真土公園",
        "venue_name": "真土公園",
        "aliases": ["真土公園"],
        "region": "荒川区",
        "address": "東京都荒川区西日暮里1-26-9",
        "access": "新三河島駅・三河島駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2026/01/00r-arakawa-q.html",
        "memo": "2026-02-22に荒川盆踊り会 初踊り開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "荒川盆踊り会 初踊り",
            "date": "2026-02-22",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2026/01/00r-arakawa-q.html",
            "month": "2月",
            "pattern_type": "不明",
            "pattern_detail": "2026-02-22（日）13:00-17:00開催記録。協賛は鞆絵太鼓。",
        },
    },
    {
        "queue_name": "あらかわ遊園アリスの広場",
        "venue_name": "あらかわ遊園アリスの広場",
        "aliases": ["あらかわ遊園アリスの広場", "アリスの広場"],
        "region": "荒川区",
        "address": "東京都荒川区西尾久6-35-11",
        "access": "都電荒川線 荒川遊園地前停留場から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2026/01/00r-arakawa-q.html",
        "memo": "2026-03-15の第60回あらかわ青年大会 アリストックで盆踊り3曲の記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "第60回あらかわ青年大会 アリストック",
            "date": "2026-03-15",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2026/01/00r-arakawa-q.html",
            "month": "3月",
            "pattern_type": "不明",
            "pattern_detail": "2026-03-15（日）13:15から納涼太鼓 大場連が盆踊り3曲。曲目は東京音頭、炭坑節、荒川音頭。",
        },
    },
    {
        "queue_name": "代々木公園",
        "venue_name": "代々木公園野外ステージ",
        "aliases": ["代々木公園野外ステージ", "代々木公園"],
        "region": "渋谷区",
        "address": "東京都渋谷区神南2-3",
        "access": "原宿駅・明治神宮前駅・代々木公園駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2026/01/00m-shibuya-q.html",
        "memo": "2026-03-15にグリーン アイルランド フェスティバル内でアイリッシュ盆踊り開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "グリーン アイルランド フェスティバル 2026 アイリッシュ盆踊り",
            "date": "2026-03-15",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2026/01/00m-shibuya-q.html",
            "month": "3月",
            "pattern_type": "不明",
            "pattern_detail": "2026-03-15（日）13:30からアイリッシュ盆踊り約20分。イベント全体は3/14-15に代々木公園イベント広場で開催。",
        },
    },
    {
        "queue_name": "さかもと朝顔広場",
        "venue_name": "さかもと朝顔広場（旧坂本小学校跡地）",
        "aliases": ["さかもと朝顔広場", "旧坂本小学校跡地"],
        "region": "台東区",
        "address": "東京都台東区下谷1-12-8",
        "access": "入谷駅・鶯谷駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00f-taito-p.html",
        "memo": "2025-08-23に坂本町会「納涼祭」内で納涼踊り開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "坂本町会 納涼祭",
            "date": "2025-08-23",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00f-taito-p.html",
            "month": "8月",
            "pattern_type": "不明",
            "pattern_detail": "2025-08-23（土）17:00-21:00、納涼踊りは19:00から。雨天時翌日順延。",
        },
    },
    {
        "queue_name": "大井銀座商店街",
        "venue_name": "大井町駅前中央通り",
        "aliases": ["大井町駅前中央通り", "大井銀座商店街", "大井駅前中央通り商店街"],
        "region": "品川区",
        "address": "東京都品川区大井1丁目付近",
        "access": "大井町駅から徒歩すぐ",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00i-sinagawa-p.html",
        "memo": "大井どんたく夏まつりの会場。大井銀座商店街振興組合などが関係。",
        "in_tsukiji": True,
        "event": {
            "name": "第71回大井どんたく夏まつり 初日 盆踊り",
            "date": "2025-08-23",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00i-sinagawa-p.html",
            "month": "8月",
            "pattern_type": "不明",
            "pattern_detail": "2025-08-23（土）18:00から盆踊り。大井どんたく音頭、品川音頭、東京音頭、品川甚句など。",
        },
    },
    {
        "queue_name": "大井駅前中央通り商店街",
        "venue_name": "大井町駅前中央通り",
        "aliases": ["大井町駅前中央通り", "大井銀座商店街", "大井駅前中央通り商店街"],
        "region": "品川区",
        "address": "東京都品川区大井1丁目付近",
        "access": "大井町駅から徒歩すぐ",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00i-sinagawa-p.html",
        "memo": "大井どんたく夏まつりの会場。大井銀座商店街振興組合・大井光学通り商店街・大井駅前中央通り商店街が関係。",
        "in_tsukiji": True,
        "event": {
            "name": "第71回大井どんたく夏まつり 初日 盆踊り",
            "date": "2025-08-23",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00i-sinagawa-p.html",
            "month": "8月",
            "pattern_type": "不明",
            "pattern_detail": "2025-08-23（土）18:00から盆踊り。大井どんたく音頭、品川音頭、東京音頭、品川甚句など。",
        },
    },
    {
        "queue_name": "旗の台稲荷通り商店街",
        "venue_name": "旗の台稲荷通り商店街",
        "aliases": ["旗の台稲荷通り商店街", "旗の台稲荷通り商店会"],
        "region": "品川区",
        "address": "東京都品川区旗の台5-3-5付近",
        "access": "旗の台駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00i-sinagawa-p.html",
        "memo": "2025-10-18に旗の台稲荷通り商店会盆踊り「盆ROCK」開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "旗の台稲荷通り商店会盆踊り 盆ROCK",
            "date": "2025-10-18",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00i-sinagawa-p.html",
            "month": "10月",
            "pattern_type": "不明",
            "pattern_detail": "2025-10-18（土）15:00-19:00。17:00-19:00に盆ROCK。",
        },
    },
    {
        "queue_name": "豊町一丁目会館",
        "venue_name": "豊町一丁目会館前",
        "aliases": ["豊町一丁目会館", "豊町一丁目会館前"],
        "region": "品川区",
        "address": "東京都品川区豊町1-4-14",
        "access": "戸越駅・戸越公園駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00i-sinagawa-p.html",
        "memo": "2025-09-13に戸越八幡神社例大祭 奉納盆踊り大会開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "戸越八幡神社例大祭 奉納盆踊り大会",
            "date": "2025-09-13",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00i-sinagawa-p.html",
            "month": "9月",
            "pattern_type": "不明",
            "pattern_detail": "2025-09-13（土）18:00-20:00開催記録。戸越銀座音頭ほか。",
        },
    },
    {
        "queue_name": "すみだ産業会館",
        "venue_name": "すみだ産業会館サンライズホール",
        "aliases": ["すみだ産業会館", "すみだ産業会館サンライズホール"],
        "region": "墨田区",
        "address": "東京都墨田区江東橋3-9-10",
        "access": "錦糸町駅から徒歩すぐ",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
        "memo": "2025-01-11にすみだ輪おどり区民感謝デー開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "第10回 すみだ輪おどり区民感謝デー",
            "date": "2025-01-11",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
            "month": "1月",
            "pattern_type": "不明",
            "pattern_detail": "2025-01-11（土）13:00-16:00開催記録。墨田区で踊られている盆踊り定番曲を多数用意。",
        },
    },
    {
        "queue_name": "伸成町会会館",
        "venue_name": "伸成町会会館前 路上",
        "aliases": ["伸成町会会館", "伸成町会会館前"],
        "region": "墨田区",
        "address": "東京都墨田区押上3-19-6",
        "access": "押上駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
        "memo": "2025-09-13〜14に押上三丁目伸成町会の祭礼踊り開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "押上三丁目伸成町会 飛木稲荷神社神幸大祭 祭礼踊り",
            "date": "2025-09-13",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
            "month": "9月",
            "pattern_type": "不明",
            "pattern_detail": "2025-09-13（土）〜14（日）19:00から開催記録。例年21:00まで。",
        },
    },
    {
        "queue_name": "向島1丁目旧町会会館",
        "venue_name": "向島1丁目旧町会会館前",
        "aliases": ["向島1丁目旧町会会館", "向島一丁目旧町会会館"],
        "region": "墨田区",
        "address": "東京都墨田区向島1-2付近",
        "access": "とうきょうスカイツリー駅・本所吾妻橋駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
        "memo": "2025-09-13に向島一丁目 牛嶋神社 ミニ奉納踊り開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "向島一丁目 牛嶋神社 ミニ奉納踊り",
            "date": "2025-09-13",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
            "month": "9月",
            "pattern_type": "不明",
            "pattern_detail": "2025-09-13（土）19:00から開催記録。",
        },
    },
    {
        "queue_name": "報恩寺",
        "venue_name": "報恩寺境内",
        "aliases": ["報恩寺", "報恩寺境内"],
        "region": "墨田区",
        "address": "東京都墨田区太平1-26付近",
        "access": "錦糸町駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
        "memo": "2025-09-12〜13に太平一丁目 牛嶋神社 奉納踊り開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "太平一丁目 牛嶋神社 奉納踊り",
            "date": "2025-09-12",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
            "month": "9月",
            "pattern_type": "不明",
            "pattern_detail": "2025-09-12（金）〜13（土）19:00-20:45頃開催記録。",
        },
    },
    {
        "queue_name": "押上二丁目町会会館",
        "venue_name": "押上二丁目町会会館前 路上",
        "aliases": ["押上二丁目町会会館", "押上二丁目町会会館前"],
        "region": "墨田区",
        "address": "東京都墨田区押上2-19-12",
        "access": "押上駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
        "memo": "2025-09-13に押上二町目町会 飛木稲荷神社神幸大祭 奉納おどり開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "押上二町目町会 飛木稲荷神社神幸大祭 奉納おどり",
            "date": "2025-09-13",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
            "month": "9月",
            "pattern_type": "不明",
            "pattern_detail": "2025-09-13（土）19:00から開催記録。2018年は21:00まで。",
        },
    },
    {
        "queue_name": "石一町会会館",
        "venue_name": "石一町会会館前",
        "aliases": ["石一町会会館", "石一町会会館前"],
        "region": "墨田区",
        "address": "東京都墨田区石原1-7-3",
        "access": "両国駅・蔵前駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
        "memo": "2025-09-13に石原一丁目 牛嶋神社 奉納踊り開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "石原一丁目 牛嶋神社 奉納踊り",
            "date": "2025-09-13",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
            "month": "9月",
            "pattern_type": "不明",
            "pattern_detail": "2025-09-13（土）18:00から開催記録。2024年は20:30まで。",
        },
    },
    {
        "queue_name": "菊一お祭り広場",
        "venue_name": "中和小学校 校庭",
        "aliases": ["菊一お祭り広場", "中和小学校"],
        "region": "墨田区",
        "address": "東京都墨田区菊川1-18-10",
        "access": "菊川駅・森下駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
        "memo": "元候補名「菊一お祭り広場」は大会名寄り。会場は中和小学校校庭として登録。",
        "in_tsukiji": True,
        "event": {
            "name": "菊川一丁目町会 菊一お祭り広場・盆踊り大会",
            "date": "2025-09-27",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00g-sumida-p.html",
            "month": "9月",
            "pattern_type": "不明",
            "pattern_detail": "2025-09-27（土）〜28（日）17:00-20:30。18:00納涼踊り開始。",
        },
    },
    {
        "queue_name": "ハマサイト前広場",
        "venue_name": "ハマサイト前広場・汐留ビルディング外構",
        "aliases": ["ハマサイト前広場", "汐留ビルディング外構"],
        "region": "港区",
        "address": "東京都港区海岸1-2-34",
        "access": "浜松町駅・大門駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00c-minato-p.html",
        "memo": "2025-08-22に第16回ハマサイトの夏祭り開催記録あり。例年、盆踊りの合間にライブ演奏あり。",
        "in_tsukiji": True,
        "event": {
            "name": "第16回ハマサイトの夏祭り",
            "date": "2025-08-22",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00c-minato-p.html",
            "month": "8月",
            "pattern_type": "不明",
            "pattern_detail": "2025-08-22（金）16:00-21:00開催記録。例年、盆踊りの合間にライブ演奏等あり。",
        },
    },
    {
        "queue_name": "下落合公園",
        "venue_name": "下落合公園",
        "aliases": ["下落合公園"],
        "region": "新宿区",
        "address": "東京都新宿区下落合4-18",
        "access": "下落合駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
        "memo": "2025-07-19〜20に下落合四丁目町会「盆踊り大会」開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "下落合四丁目町会 盆踊り大会",
            "date": "2025-07-19",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
            "month": "7月",
            "pattern_type": "不明",
            "pattern_detail": "2025-07-19（土）〜20（日）18:00-21:00開催記録。",
        },
    },
    {
        "queue_name": "北柏木公園",
        "venue_name": "北柏木公園",
        "aliases": ["北柏木公園"],
        "region": "新宿区",
        "address": "東京都新宿区北新宿4-12",
        "access": "東中野駅・落合駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
        "memo": "2025-07-25〜27に北新宿四丁目盆踊り大会開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "北新宿四丁目 盆踊り大会",
            "date": "2025-07-25",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
            "month": "7月",
            "pattern_type": "不明",
            "pattern_detail": "2025-07-25（金）〜27（日）18:00-21:00開催記録。",
        },
    },
    {
        "queue_name": "北新宿公園",
        "venue_name": "北新宿公園",
        "aliases": ["北新宿公園"],
        "region": "新宿区",
        "address": "東京都新宿区北新宿3-20",
        "access": "大久保駅・東中野駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
        "memo": "2025-08-02〜03に柏木地区6町会盆踊り大会開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "柏木地区6町会盆踊り大会",
            "date": "2025-08-02",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
            "month": "8月",
            "pattern_type": "不明",
            "pattern_detail": "2025-08-02（土）〜03（日）18:00-21:00開催記録。",
        },
    },
    {
        "queue_name": "原町天祖神社",
        "venue_name": "原町天祖神社",
        "aliases": ["原町天祖神社"],
        "region": "新宿区",
        "address": "東京都新宿区原町1-42",
        "access": "牛込柳町駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
        "memo": "2025-09-15に原町一丁目町会「天祖神社例大祭 盆踊り」開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "原町一丁目町会 天祖神社例大祭 盆踊り",
            "date": "2025-09-15",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
            "month": "9月",
            "pattern_type": "不明",
            "pattern_detail": "2025-09-15（月祝）17:00-20:00開催記録。",
        },
    },
    {
        "queue_name": "新大久保商店街",
        "venue_name": "JR新大久保駅北側から東方向",
        "aliases": ["新大久保商店街", "JR新大久保駅北側"],
        "region": "新宿区",
        "address": "東京都新宿区百人町1丁目付近",
        "access": "新大久保駅から徒歩すぐ",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
        "memo": "2025-10-13に大久保まつりパレード内で百人町民民謡おどりの記録あり。観覧のみとの記載。",
        "in_tsukiji": False,
        "event": {
            "name": "第42回大久保まつり パレード 百人町民民謡おどり",
            "date": "2025-10-13",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
            "month": "10月",
            "pattern_type": "不明",
            "pattern_detail": "2025-10-13（月祝）12:00-14:40頃。13:30から鉄砲隊・百人町民民謡おどり。飛び入り不可、観覧のみ。",
        },
    },
    {
        "queue_name": "旧四谷第四小学校",
        "venue_name": "四谷ひろばグラウンド（旧四谷第四小学校）",
        "aliases": ["旧四谷第四小学校", "四谷ひろばグラウンド"],
        "region": "新宿区",
        "address": "東京都新宿区四谷4-20",
        "access": "四谷三丁目駅・新宿御苑前駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
        "memo": "2025-07-19〜20に第25回 四谷納涼踊り大会開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "第25回 四谷納涼踊り大会",
            "date": "2025-07-19",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
            "month": "7月",
            "pattern_type": "不明",
            "pattern_detail": "2025-07-19（土）〜20（日）18:00-21:00、納涼踊り開催記録。",
        },
    },
    {
        "queue_name": "清水川橋公園",
        "venue_name": "清水川橋公園",
        "aliases": ["清水川橋公園"],
        "region": "新宿区",
        "address": "東京都新宿区下落合1-1",
        "access": "高田馬場駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
        "memo": "2025-07-19に下落合町会知久会「第9回盆踊り」開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "下落合町会知久会 第9回盆踊り",
            "date": "2025-07-19",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
            "month": "7月",
            "pattern_type": "不明",
            "pattern_detail": "2025-07-19（土）17:00-21:00開催記録。雨天中止。",
        },
    },
    {
        "queue_name": "鶴巻小学校",
        "venue_name": "鶴巻小学校",
        "aliases": ["鶴巻小学校"],
        "region": "新宿区",
        "address": "東京都新宿区早稲田鶴巻町140-140",
        "access": "早稲田駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
        "memo": "2025-07-12に納涼盆踊り大会＆子ども祭り開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "鶴巻小学校 納涼盆踊り大会＆子ども祭り",
            "date": "2025-07-12",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00d-shinjuku-p.html",
            "month": "7月",
            "pattern_type": "不明",
            "pattern_detail": "2025-07-12（土）16:00-19:00開催記録。",
        },
    },
    {
        "queue_name": "学生会館",
        "venue_name": "東京大学駒場キャンパス 学生会館東",
        "aliases": ["東京大学駒場キャンパス 学生会館東", "学生会館"],
        "region": "目黒区",
        "address": "東京都目黒区駒場3-8-1",
        "access": "駒場東大前駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00j-meguro-p.html",
        "memo": "2025-11-23〜24に駒場祭にあわせて盆踊り in 駒場東大開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "盆踊り in 駒場東大",
            "date": "2025-11-23",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00j-meguro-p.html",
            "month": "11月",
            "pattern_type": "不明",
            "pattern_detail": "2025-11-23（日）〜24（月振）各日14:00-15:30。23日は伝統曲とアニソン盆踊り、24日は世界盆踊り。",
        },
    },
    {
        "queue_name": "権之助坂商店街",
        "venue_name": "JR目黒駅西口前",
        "aliases": ["権之助坂商店街", "JR目黒駅西口前"],
        "region": "目黒区",
        "address": "東京都目黒区下目黒3-21-9付近",
        "access": "目黒駅から徒歩すぐ",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00j-meguro-p.html",
        "memo": "2025-07-27に権之助坂商店街の地域のふれあい盆踊り大会開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "地域のふれあい第37回盆踊り大会",
            "date": "2025-07-27",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00j-meguro-p.html",
            "month": "7月",
            "pattern_type": "不明",
            "pattern_detail": "2025-07-27（日）10:00-20:00頃。盆踊りは17:00から19:40頃まで。",
        },
    },
    {
        "queue_name": "目黒川船入場広場",
        "venue_name": "フナイリバ（目黒川船入場広場）",
        "aliases": ["目黒川船入場広場", "フナイリバ"],
        "region": "目黒区",
        "address": "東京都目黒区中目黒1-11-18",
        "access": "中目黒駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00j-meguro-p.html",
        "memo": "2025-08-30〜31に中目黒盆踊り大会開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "中目黒盆踊り大会 2025",
            "date": "2025-08-30",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00j-meguro-p.html",
            "month": "8月",
            "pattern_type": "不明",
            "pattern_detail": "2025-08-30（土）〜31（日）17:00-21:00。盆踊りスタートは17:30。",
        },
    },
    {
        "queue_name": "祐天寺",
        "venue_name": "祐天寺境内",
        "aliases": ["祐天寺", "祐天寺境内"],
        "region": "目黒区",
        "address": "東京都目黒区中目黒5-24-53",
        "access": "祐天寺駅から徒歩圏内",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00j-meguro-p.html",
        "memo": "2025-07-16〜18に祐天寺み魂まつり こども盆踊り大会開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "第90回 祐天寺み魂まつり こども盆踊り大会",
            "date": "2025-07-16",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00j-meguro-p.html",
            "month": "7月",
            "pattern_type": "不明",
            "pattern_detail": "2025-07-16（水）〜18（金）17:30-21:00。初日は雨のため中止。",
        },
    },
    {
        "queue_name": "自由が丘商店街",
        "venue_name": "自由が丘駅前ロータリー 特設会場",
        "aliases": ["自由が丘商店街", "自由が丘駅前ロータリー"],
        "region": "目黒区",
        "address": "東京都目黒区自由が丘1丁目付近",
        "access": "自由が丘駅正面口前",
        "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00j-meguro-p.html",
        "memo": "2025-07-19〜21に自由が丘納涼盆踊り大会開催記録あり。",
        "in_tsukiji": False,
        "event": {
            "name": "自由が丘納涼盆踊り大会",
            "date": "2025-07-19",
            "status": "終了",
            "source_url": "https://minato-bon-odori.blogspot.com/2025/01/00j-meguro-p.html",
            "month": "7月",
            "pattern_type": "不明",
            "pattern_detail": "2025-07-19（土）〜21（月祝）18:00-21:00。自由が丘商店街振興組合、自由が丘住区青少年委員会。",
        },
    },
    {
        "queue_name": "歌舞伎町商店街",
        "venue_name": "歌舞伎町シネシティ広場",
        "aliases": ["歌舞伎町シネシティ広場", "歌舞伎町商店街"],
        "region": "新宿区",
        "address": "東京都新宿区歌舞伎町1-20",
        "access": "西武新宿駅・新宿駅から徒歩圏内",
        "source_url": "https://www.kanko-shinjuku.jp/event/c082/article_4606.html",
        "memo": "既存会場へ寄せる。歌舞伎町商店街振興組合「歌舞伎町BON ODORI」の会場。",
        "in_tsukiji": False,
        "event": {
            "name": "歌舞伎町BON ODORI",
            "date": "2025-08-16",
            "status": "終了",
            "source_url": "https://www.kanko-shinjuku.jp/event/c082/article_4606.html",
            "month": "8月",
            "pattern_type": "不明",
            "pattern_detail": "2025-08-16（土）開催記録。歌舞伎町商店街振興組合主催。",
        },
    },
]


def title_prop(text):
    return {"title": [{"text": {"content": text}}]}


def text_prop(text):
    return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}


def select_prop(name):
    return {"select": {"name": name}}


def date_prop(date):
    return {"date": {"start": date}}


def find_venue(api, aliases):
    for alias in aliases:
        rows = api.query_data_source(
            VENUE_DATA_SOURCE_ID,
            {
                "filter": {"property": "会場名", "title": {"contains": alias}},
                "page_size": 10,
            },
        )
        if rows:
            return rows[0]
    return None


def find_event(api, event_name):
    rows = api.query_data_source(
        EVENT_DATA_SOURCE_ID,
        {
            "filter": {"property": "イベント名", "title": {"contains": event_name}},
            "page_size": 10,
        },
    )
    return rows[0] if rows else None


def create_venue(api, item):
    props = {
        "会場名": title_prop(item["venue_name"]),
        "所在区・市": text_prop(item["region"]),
        "住所": text_prop(item["address"]),
        "アクセス": text_prop(item["access"]),
        "出典URL": {"url": item["source_url"]},
        "過去メモ": text_prop(item["memo"]),
        "規模": select_prop("小"),
        "築地30分圏内": {"checkbox": item["in_tsukiji"]},
        "要レビュー": {"checkbox": False},
    }
    return api.request(
        "POST",
        "/pages",
        {"parent": {"data_source_id": VENUE_DATA_SOURCE_ID}, "properties": props},
    )


def create_event(api, venue_page_id, item):
    event = item["event"]
    props = {
        "イベント名": title_prop(event["name"]),
        "会場": {"relation": [{"id": venue_page_id}]},
        "開催日": date_prop(event["date"]),
        "状態": select_prop(event["status"]),
        "情報源URL": {"url": event["source_url"]},
        "例年開催月": text_prop(event["month"]),
        "開催パターン種別": select_prop(event["pattern_type"]),
        "開催パターン詳細": text_prop(event["pattern_detail"]),
    }
    return api.request(
        "POST",
        "/pages",
        {"parent": {"data_source_id": EVENT_DATA_SOURCE_ID}, "properties": props},
    )


def update_state(results):
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    done = state.setdefault("research_done_2026_06_10", [])
    later = state.get("research_later", [])
    by_name = {item["queue_name"]: item for item in results}

    new_later = []
    for entry in later:
        name = entry.get("venue")
        if name not in by_name:
            new_later.append(entry)
            continue
        updated = dict(entry)
        result = by_name[name]
        updated["result"] = result["result"]
        updated["notion_url"] = result["notion_url"]
        updated["event_url"] = result["event_url"]
        done.append(updated)

    state["research_later"] = new_later
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    results = []
    for item in VENUES:
        venue = find_venue(api, item["aliases"])
        venue_created = False
        if not venue:
            venue = create_venue(api, item)
            venue_created = True

        event = find_event(api, item["event"]["name"])
        event_created = False
        if not event:
            event = create_event(api, venue["id"], item)
            event_created = True

        venue_name = plain_text(venue["properties"].get("会場名"))
        results.append(
            {
                "queue_name": item["queue_name"],
                "result": (
                    f"登録済み: {venue_name}／{item['event']['name']}"
                    if venue_created or event_created
                    else f"既存確認: {venue_name}／{item['event']['name']}"
                ),
                "notion_url": venue.get("url"),
                "event_url": event.get("url"),
            }
        )

    update_state(results)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
