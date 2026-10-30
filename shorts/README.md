# shorts ── ショート動画「Rootsで英単語」を自動で作る道具

アプリ本体（index.html など）は**読むだけ**で、ここ（`/shorts`）の中だけで動きます。

## 使い方
```
python3 shorts/render.py --script shorts/scripts/001_port.txt --type 1 --number 1 --out 試作.mp4
python3 shorts/render.py --script 台本.txt --voice 録音.m4a --type 1 --number 2 --out 002.mp4
```
- `--voice` … 録音（m4a / mp3 / wav）。あると、録音の長さを各テロップの文字数で分けて、画面を声に合わせます。ないときは台本の秒数どおりの無音の仮動画になります
- `--preview フォルダ` … 各カットの静止画（PNG）も書き出します（見た目の確認用）
- 出力: 1080×1920・30fps・H.264（veryfast・CRF 26）。最後に2秒のエンドカード「Rootsで英単語｜プロフのリンクから無料」が自動で付きます

必要なもの: Python 3、Pillow、cairosvg（`pip install cairosvg`。ピクトグラムを絵にする）、ffmpeg、Noto Sans CJK フォント

## 台本の書き方（1行＝1テロップ＝1カット）
```
# 語根: port
[0.0-3.0] {hook} 英単語の覚え方、語源で一発
[5.5-8.5] {root port} port は「運ぶ」
[8.5-11.0] {kata ポーター porter port(運ぶ)+er(人)} 荷物を運ぶ人
[16.5-19.5] {word support} 下から運ぶ＝支える
[26.0-30.0] {summary} port＝運ぶ、で全部わかる
```
- `[開始-終了]` … 目安の秒数。`{ }` … そのカットの画面（場面）。`{ }` がなければ、ふつうのテロップ画面
- `#` で始まる行はメモ（`# 語根: port` は summary などで使います）
- 改行したいところに `\n` を書けます（「、」「。」のあとは自動で改行を試します）

| 場面 | 書き方 | 画面 |
|---|---|---|
| hook | `{hook}` / `{hook think}` | 大きな文字＋ルーツくん（normal / teach / think / cheer） |
| root | `{root port}` / `{root port=運ぶ}` | 語根・意味・ピクトグラム（意味と絵はアプリのデータから） |
| kata | `{kata カタカナ 英語 パーツ}` | カタカナ語→英語（語源の色分け）→分解 |
| word | `{word support}` | アプリの単語データから：色分け・意味・英検級・ピクトグラム |
| summary | `{summary}` | ここまでに出た語根・カタカナ語・受験単語のまとめ（3秒以上止める） |
| text | `{text}` | テロップだけ（ルーツくん） |

### 型②雑学（意外な語源）
| 場面 | 書き方 | 画面 |
|---|---|---|
| trivia | `{trivia danger}` | 「意外な語源」＋単語を大きく＋今の意味＋ルーツくん |
| origin | `{origin danger}` | もともとの意味（語源パーツの色分け・ピクトグラム） |
| reveal | `{reveal danger}` | 「むかし（語根の意味）」▼「いま（今の意味）」 |

### 型③推理（カウントダウン→分解→正解）
| 場面 | 書き方 | 画面 |
|---|---|---|
| quiz | `{quiz interrupt}` | 単語だけ（色なし）＋「この意味、わかる？」 |
| count | `{count interrupt}` | 3・2・1 のカウントダウン（1秒ずつ。3秒より短いと3秒にのばす） |
| split | `{split interrupt}` | 分解（色分け＋パーツの絵と意味） |
| answer | `{answer interrupt}` | 「正解」＋意味・英検級・パーツ |

### 型④ペア（左右で比べる）
| 場面 | 書き方 | 画面 |
|---|---|---|
| pair | `{pair precede proceed}` | 左右に2語。パーツの絵と意味、下に今の意味 |
| pairsum | `{pairsum}` | 2語の一覧＋テロップの文を大きく（1行まとめ。3秒以上止める） |

試作の台本: `scripts/001_port.txt`（①）・`002_danger.txt`（②）・`003_interrupt.txt`（③）・`004_precede_proceed.txt`（④）

## データの作り直し（アプリの単語が増えたとき）
```
cd shorts/tools && npm install && node extract_assets.js
```
index.html から `shorts/data/words.json`（単語・意味・語源パーツ・色の種類）と `shorts/data/picto.json`（ピクトグラム）を作り直します。
色はアプリと同じ（接頭 #2F5D9E・語根 #B5652B・接尾 #4F7A5E、アクセント紫 #534AB7）。
