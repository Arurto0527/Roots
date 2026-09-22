# Roots — Claude Code 用の説明書

語源で覚える英単語アプリ。高校生向け。GitHub Pages で公開している。
公開URL: https://arurto0527.github.io/Roots/
作っている人はアプリ開発の初心者。説明は中高生にもわかる言葉で、日本語で書くこと。

## ファイル構成
- `index.html` … アプリ本体。修正するのはほぼこのファイルだけ
  - `<script type="text/babel">` の中に React のコード（JSX）と単語データが入っている
  - `<script type="application/json" id="roots-audio-index">` は音声ファイルの一覧（自動生成なので手で書き換えない）
- `audio/us/*.m4a`, `audio/uk/*.m4a` … 収録済みの発音（Piper で作成）。**開かない・読まない・変更しない**
- `sw.js` … オフライン用の保存係（Service Worker）

## 音声のしくみ
- ファイル名 = 英文（前後の空白を除く）の FNV-1a 32bit ハッシュ（UTF-16 の charCodeAt で計算）を8桁の16進数にしたもの
  - 計算は index.html の `clipHash()` と同じ方法
- `speak(text)` は、一覧にハッシュがあれば `audio/<us|uk>/<hash>.m4a` を再生し、なければ端末の読み上げ（speechSynthesis）を使う
- そのため、単語や例文の英文を変えると、その文は端末の読み上げになる。音声を作り直す必要があることをユーザーに伝える

## ルール
- デザインの基本: スマホ重視（max-width 430px）、ボタンは min-height 56px、文字サイズは 16px
- 学習データは localStorage に保存している。保存するときのキー名や形式を変えるときは、今までのデータが消えないようにする
- `audio/` と `roots-audio-index` の中身を context に読み込まない（大きいので）
- 大きな変更をする前に、何をどう変えるか先に説明する
- 音声ファイルを作り直したとき、または sw.js を変更したときは、sw.js の `VERSION` を1つ上げる

## 動作確認
- ローカルで確認するとき: このフォルダで `python3 -m http.server 8000` を実行し、http://localhost:8000 を開く
  （index.html をダブルクリックで開くと、音声や Service Worker が動かない）
- 公開: GitHub Desktop で Commit → Push すると、1〜3分で公開URLに反映される

## 単語を追加するときの決まり（No.101〜150 の作業で固めたもの）
- 仕様書は `claude/word-data-spec.md`。単語データは `RAW_WORDS`（index.html の中）
- **見出し語と並び順は `claude/leap-word-list.md`（LEAP 2300語）に従う。** アプリの No.n ＝ LEAP の No.n
  （2026-09-22 時点で No.1〜550 まで一致済み。次に足すのは No.551 attach から）
- **Part α（お試し用）は必ず全単語のいちばん後ろ**。本編を増やしたぶんだけ α の id を後ろへずらす。α の中身は書き換えない
  - 番号を変えたら `ALPHA_FROM` を新しい α の先頭番号に、`WORDS_LAYOUT` を1つ上げる
  - 単語帳の○×の記録は番号で保存しているので、`v3IdToNew` のような読み替えを足す（学習記録そのものは見出し語でひも付いているので消えない）
- 検査は2つ。**追加作業のあとは必ず両方**通す
  - `node validate.js` … 単語データそのもの（`--add 新しい語のファイル` で追加ぶんだけ、`--only 1-100` で範囲指定）
  - `node check-all.js` … つけ忘れ（ピクトグラム・語源コラム・英検レベル・音声・番号）。NG 0件が目標
  - ピクトグラムの見た目は `node preview-picto.js` で画像にして、必ず目で確認する
  - 単語を書くときは10語ずつ「機械チェック → 読み直し → サブエージェントによる第三者チェック」の3回を通す
- 新しい語根が増えたら、`ROOT_NOTES`（語源コラム）と `PICTO_ROOT`（ピクトグラム）も足す。別綴りは `ROOT_ALIAS` でまとめる

## 音声の作り方（Piper）
- `pip install piper-tts` ＋ 声のモデル `en_US-lessac-high`（米）/ `en_GB-cori-high`（英）
- **`ESPEAK_DATA_PATH` には「espeak-ng-data フォルダを含む親フォルダ」を指定する**（発音データの場所が固定されていて、そのままでは動かない）
- wav で作って `afconvert -f m4af -d aac@22050 -b 64000 -c 1` で m4a にする（既存の音声と同じ形式）
- 必要な英文は「見出し語・例文2つ・関連語」。作ったら `roots-audio-index` を作り直す

## sw.js の決まり（2026-09 に変更）
- 音声の保存（`AUDIO_CACHE`）は `VERSION` と切り離してある。**`VERSION` を上げても音声は消えない**
- アプリ本体は「保存版をすぐ表示 → 裏で新版を取得」。新版があれば画面下に「新しい版があります」と出す
- アプリ本体を変えたら `VERSION` を1つ上げる（音声だけ作り足したときは上げなくてよい）
