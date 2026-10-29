# DEVLOG（ショート動画の自動生成）

新しい記録を上に書きます。

## 2026-10-29（1晩目）
### やったこと
- ブランチ `shorts` を main から作成（アプリ本体は変更なし）
- リポジトリ調査
  - 単語データ: `index.html` の `RAW_WORDS`（2410件）。語源パーツは `parseRoots()`、接頭／語根／接尾の判定は `morphType()`
  - 語源の色: `LIGHT.pre #2F5D9E`（接頭）・`LIGHT.root #B5652B`（語根）・`LIGHT.suf #4F7A5E`（接尾）。アクセント紫 #534AB7
  - ピクトグラム: `PICTO_ROOT`・`PICTO_PREFIX`・`PICTO_BY_GLOSS`（48×48 の線画 SVG、`pictoFor()` で選ぶ）
  - キャラ画像: `chara/normal|teach|think|cheer.png`（ルーツくん）
  - 音声: `audio/us|uk/<ハッシュ>.m4a`（英語の発音のみ。動画には今は使っていない）
- `shorts/tools/extract_assets.js` … index.html を読むだけで `shorts/data/words.json`・`picto.json` を作る（授業用ページと同じく `function App(){` の手前までを使う）
- `shorts/render.py` の骨組み … 台本の読み込み・秒数の配分（録音があれば文字数で比例配分）・安全領域・左上ラベル・エンドカード・テロップの自動縮小（入らなければ ⚠ 警告）
- 型①の画面: hook / root / kata / word / summary
- 試作 `shorts/scripts/001_port.txt` → 35秒・0.6MB の無音動画を作成。`shorts/samples/試作_①port.mp4` に置き、この実行の会話にも添付
  - **Googleドライブへのアップロードはできませんでした**：ドライブの道具は動画を base64 の文字（約80万文字）で書き込む方式で、この長さを1文字もまちがえずに渡すのは現実的でないため。画質を落としても約55万文字。ドライブへは手で入れてもらうか、別の方法（Drive に直接書き込める道具）を検討

### 次にやること（2晩目）
- 型②雑学・③推理（3秒カウントダウン→分解→正解）・④ペア（左右分割→1行まとめ3秒）の画面と試作各1本
- 録音ありのときも、まとめ画面を3秒止める（今は録音の長さに合わせるだけ）→ 3晩目

### ユーザーに確認してほしいこと
- 試作_①port.mp4 の見た目（色・文字の大きさ・ルーツくんの出し方・テロップの位置）
- 左上ラベル「Roots #001」は、上220pxの安全領域に入らないよう y=236 から置いています
- **語源の注意**: 戦略メモのフック例「パスポート、エアポート…」の passport / airport は、アプリでは port（運ぶ）ではなく portus（港）の仲間として別にしています（opportunity と同じ）。試作では「運ぶ」の仲間のポーター・ポータブル・レポートを使いました。「港」も入れるなら別の回にするのがおすすめです
- アプリの単語帳にある port の仲間は support・import・transportation の3語だけでした（export・report などは見出し語にない）
