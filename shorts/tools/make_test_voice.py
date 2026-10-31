#!/usr/bin/env python3
"""録音との同期を試すための「にせの録音」を作る（日本語の声は作れないので、ピーという音で代用）
  python3 shorts/tools/make_test_voice.py 台本.txt 出力.wav [breath]
行ごとに文字数に合った長さの音を鳴らし、行の間に 0.35〜0.6 秒の間を空ける。
breath をつけると、長い行の途中にも 0.25 秒の息つぎを入れる（まちがった所で区切らないかの確認用）。
「正しい区切り」の時刻を表示するので、render.py --preview で出る timing.txt と比べる。"""
import os, sys, wave, random, numpy as np
import importlib.util
RENDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render.py")
spec = importlib.util.spec_from_file_location("r", RENDER); r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
meta, cuts = r.parse_script(sys.argv[1])
random.seed(1); sr = 22050; out = [np.zeros(int(0.3*sr))]; t = 0.3; truth = []
for c in cuts:
    n = r.count_chars(c["text"]); dur = n * random.uniform(0.11, 0.2)
    # 声のように音量がゆれる音（文の途中にも 0.1 秒の小さな息つぎ）
    tt = np.arange(int(dur*sr))/sr
    sig = 0.3*np.sin(2*np.pi*220*tt)*(0.6+0.4*np.sin(2*np.pi*3*tt))
    if n >= 8 and len(sys.argv) > 3:   # 長い行は途中で 0.25 秒の息つぎ
        k = len(sig)//2; out += [sig[:k], np.zeros(int(0.25*sr)), sig[k:]]; t += dur + 0.25
    else:
        out.append(sig); t += dur
    gap = random.uniform(0.35, 0.6); truth.append(t + gap/2)
    out.append(np.zeros(int(gap*sr))); t += gap
a = (np.concatenate(out)*32767).astype(np.int16)
w = wave.open(sys.argv[2], 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(a.tobytes()); w.close()
print("正しい区切り:", " ".join(f"{x:.2f}" for x in truth[:-1]))
