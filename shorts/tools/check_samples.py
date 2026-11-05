#!/usr/bin/env python3
"""動画がちゃんと再生できるか調べる。コミットする前に使う。
  python3 shorts/tools/check_samples.py            … shorts/samples/ の全部
  python3 shorts/tools/check_samples.py 動画.mp4 …  … 指定した動画だけ
1つでも問題があれば、最後に「NG」と出して終了コード1で終わる。
"""
import glob
import os
import subprocess
import sys


def check(path):
    size = os.path.getsize(path)
    if size < 100_000:
        return f"ファイルが小さすぎます（{size}バイト）"
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                          "stream=width,height,r_frame_rate:format=duration", "-of", "default=nw=1", path],
                         capture_output=True, text=True)
    info = dict(l.split("=", 1) for l in out.stdout.split() if "=" in l)
    if out.returncode != 0 or "duration" not in info:
        return "ffprobe で読めません: " + out.stderr.strip()[:80]
    if (info.get("width"), info.get("height")) != ("1080", "1920"):
        return f"大きさが {info.get('width')}×{info.get('height')} です"
    if info.get("r_frame_rate") != "30/1":
        return f"コマ数が {info.get('r_frame_rate')} です"
    sec = float(info["duration"])
    if not 30 <= sec <= 45.5:
        return f"長さが {sec:.1f}秒です（目安は30〜45秒）"
    # 最後まで実際に読んでみる（途中で切れた動画を見つけるため）
    dec = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"], capture_output=True, text=True)
    if dec.returncode != 0 or dec.stderr.strip():
        return "最後まで読めません: " + dec.stderr.strip()[:80]
    print(f"OK  {os.path.basename(path)}  {sec:.1f}秒  {size / 1e6:.2f}MB")
    return None


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    paths = sys.argv[1:] or sorted(glob.glob(os.path.join(here, "..", "samples", "*.mp4")))
    bad = 0
    for p in paths:
        problem = check(p)
        if problem:
            bad += 1
            print(f"NG  {os.path.basename(p)}  {problem}")
    print(f"{len(paths)}本中 NG {bad}本")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
