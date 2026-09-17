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
