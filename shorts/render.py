#!/usr/bin/env python3
"""
Rootsで英単語 ── ショート動画の自動生成（縦型 1080×1920・30fps・MP4）

使い方:
  python3 shorts/render.py --script 台本.txt [--voice 録音.m4a] --type 1 --number 1 --out 出力.mp4

台本の書き方は shorts/README.md を見てください。
必要なもの: Python 3 / Pillow / cairosvg（ピクトグラムを絵にする）/ ffmpeg・ffprobe / Noto Sans CJK フォント
"""
import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

try:
    import cairosvg
except ImportError:  # ピクトグラムなしでも動くようにする
    cairosvg = None

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# ---------------------------------------------------------------- 画面の決まり
W, H, FPS = 1080, 1920, 30
SAFE_TOP = 220            # 上220pxは文字を置かない
SAFE_BOTTOM = H - 420     # 下420pxは文字を置かない（y=1500 まで使える）
SAFE_RIGHT = W - 160      # 右160pxは文字を置かない（x=920 まで使える）
LEFT = 60
CX = (LEFT + SAFE_RIGHT) // 2   # 文字を置ける範囲のまん中（x=490）
CONTENT_W = SAFE_RIGHT - LEFT   # 860px
END_CARD_SEC = 2.0
FADE_SEC = 0.2

# アプリと同じ色（index.html の LIGHT と TUTORIAL_ACCENT）
ACCENT = "#534AB7"
ACCENT_SOFT = "#EEECFA"
TEXT = "#111111"
SUB = "#595959"
LINE = "#E0E0E0"
BG = "#FFFFFF"
TYPE_COLOR = {"prefix": "#2F5D9E", "root": "#B5652B", "suffix": "#4F7A5E"}
TYPE_LABEL = {"prefix": "接頭", "root": "語根", "suffix": "接尾"}

FONT_DIR = "/usr/share/fonts/opentype/noto"
FONT_FILES = {"bold": "NotoSansCJK-Bold.ttc", "black": "NotoSansCJK-Black.ttc",
              "medium": "NotoSansCJK-Medium.ttc", "regular": "NotoSansCJK-Regular.ttc"}

WARNINGS = []


def warn(msg):
    WARNINGS.append(msg)
    print("⚠ " + msg, file=sys.stderr)


# ---------------------------------------------------------------- フォント
_font_cache = {}


def font(size, weight="bold"):
    key = (int(size), weight)
    if key not in _font_cache:
        path = os.path.join(FONT_DIR, FONT_FILES[weight])
        if not os.path.exists(path):
            path = os.path.join(FONT_DIR, FONT_FILES["bold"])
        _font_cache[key] = ImageFont.truetype(path, int(size), index=0)  # index 0 = 日本語(JP)
    return _font_cache[key]


def text_w(s, f):
    return f.getlength(s)


# ---------------------------------------------------------------- 文字の位置をすべて記録して、はみ出しを調べる
# 1枚の絵（カット）に書いた文字の四すみを全部メモしておき、
#   ・安全領域（上220px・下420px・右160px）に入っていないか
#   ・画面の左はしから出ていないか
#   ・ほかの文字と重なっていないか
# を自動で調べる。はみ出しそうな文字は、その場で少しずつ小さくして入れる。
CHECK_LOG = []          # 全カットの記録（--report で JSON に書き出す）
_cur = {"items": None, "group": 0, "name": ""}
SHRINK_MIN_RATIO = 0.6  # 元の大きさの6割までは小さくしてよい


def begin_frame(name):
    _cur["items"] = []
    _cur["name"] = name
    CHECK_LOG.append({"cut": name, "items": _cur["items"], "problems": []})


def new_group():
    """色分けした英単語のように、何回かに分けて1語を書くときは同じ組にする（重なりチェックから外す）"""
    _cur["group"] += 1
    return _cur["group"]


def out_of_safe(b, pad=2):
    x0, y0, x1, y1 = b
    why = []
    if y0 < SAFE_TOP - pad:
        why.append(f"上の安全領域（y<{SAFE_TOP}）")
    if y1 > SAFE_BOTTOM + pad:
        why.append(f"下の安全領域（y>{SAFE_BOTTOM}）")
    if x1 > SAFE_RIGHT + pad:
        why.append(f"右の安全領域（x>{SAFE_RIGHT}）")
    if x0 < 20 - pad:
        why.append("画面の左はし")
    return why


class CheckedDraw:
    """ImageDraw のかわり。text() のときに位置を記録し、安全領域から出る文字は小さくする"""

    def __init__(self, d, safe=True):
        self._d = d
        self.safe = safe   # エンドカードなど、全面の絵でも文字は安全領域に入れる

    def __getattr__(self, k):
        return getattr(self._d, k)

    def text(self, xy, s, font=None, fill=None, anchor=None, group=None, shrink=True, **kw):
        f = font
        b = self._d.textbbox(xy, s, font=f, anchor=anchor)
        if shrink and self.safe and out_of_safe(b) and hasattr(f, "font_variant"):
            size0 = f.size
            sz = size0
            while out_of_safe(b) and sz - 2 >= max(20, size0 * SHRINK_MIN_RATIO):
                sz -= 2
                f = f.font_variant(size=sz)
                b = self._d.textbbox(xy, s, font=f, anchor=anchor)
            if sz != size0:
                print(f"  ↳ {_cur['name']}: 「{s}」を {size0}px→{sz}px に小さくしました（安全領域に入れるため）",
                      file=sys.stderr)
        self._d.text(xy, s, font=f, fill=fill, anchor=anchor, **kw)
        if _cur["items"] is not None and s.strip():
            _cur["items"].append({"text": s, "box": [round(v) for v in b], "size": getattr(f, "size", 0),
                                  "group": group})
        return f


def check_frame(rec):
    """1カット分の記録を調べて、問題を rec["problems"] に入れる"""
    items = rec["items"]
    for it in items:
        why = out_of_safe(it["box"])
        if why:
            rec["problems"].append(f"「{it['text']}」が{'・'.join(why)}に入っています {it['box']}")
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a["group"] is not None and a["group"] == b["group"]:
                continue
            ax0, ay0, ax1, ay1 = a["box"]
            bx0, by0, bx1, by1 = b["box"]
            iw, ih = min(ax1, bx1) - max(ax0, bx0), min(ay1, by1) - max(ay0, by0)
            if iw <= 0 or ih <= 0:
                continue
            small = min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0)) or 1
            if iw * ih / small > 0.15:
                rec["problems"].append(f"「{a['text']}」と「{b['text']}」が重なっています")
    return rec["problems"]


# ---------------------------------------------------------------- データ（index.html から取り出したもの）
def load_data():
    wpath = os.path.join(HERE, "data", "words.json")
    ppath = os.path.join(HERE, "data", "picto.json")
    if not os.path.exists(wpath):
        sys.exit("shorts/data/words.json がありません。先に node shorts/tools/extract_assets.js を実行してください。")
    with open(wpath, encoding="utf-8") as fp:
        words = json.load(fp)["words"]
    with open(ppath, encoding="utf-8") as fp:
        pictos = json.load(fp)
    by_word = {}
    for w in words:
        by_word.setdefault(w["word"].lower(), w)
    return by_word, words, pictos


BY_WORD, WORDS, PICTOS = load_data()


def find_word(name):
    w = BY_WORD.get(name.lower())
    if not w:
        warn(f"単語データに「{name}」がありません（アプリの単語帳にない語）")
    return w


def root_info(morph):
    """語根の意味とピクトグラムを、アプリの単語データから探す"""
    k = morph.lower()
    for w in WORDS:
        for p in w["parts"]:
            if p["type"] == "root" and (p["canon"] == k or p["morph"].lower() == k):
                return {"gloss": p["gloss"], "picto": p["picto"]}
    return {"gloss": "", "picto": None}


# ---------------------------------------------------------------- ピクトグラム
_picto_cache = {}


def picto_image(pid, size, color=TEXT):
    if not pid or pid not in PICTOS or cairosvg is None:
        return None
    key = (pid, size, color)
    if key not in _picto_cache:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 48 48" '
               f'fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
               f'{PICTOS[pid]}</svg>')
        png = cairosvg.svg2png(bytestring=svg.encode("utf-8"))
        _picto_cache[key] = Image.open(io.BytesIO(png)).convert("RGBA")
    return _picto_cache[key]


_chara_cache = {}


def chara(mood, width):
    key = (mood, width)
    if key not in _chara_cache:
        path = os.path.join(REPO, "chara", mood + ".png")
        if not os.path.exists(path):
            _chara_cache[key] = None
        else:
            im = Image.open(path).convert("RGBA")
            h = round(im.height * width / im.width)
            _chara_cache[key] = im.resize((width, h), Image.LANCZOS)
    return _chara_cache[key]


# ---------------------------------------------------------------- 文字の折り返しと「はみ出したら小さく」
NO_HEAD = set("、。，．・：；！？!?）」』】〉》ー～…ぁぃぅぇぉっゃゅょァィゥェォッャュョ")


def tokenize(s):
    """英語は単語ごと、日本語は1文字ごとに区切る（行頭に来てはいけない記号はくっつける）"""
    toks = []
    for m in re.finditer(r"[A-Za-z0-9'’\-\.]+|\s+|.", s):
        t = m.group(0)
        if toks and t and t[0] in NO_HEAD:
            toks[-1] += t
        else:
            toks.append(t)
    return toks


def wrap(s, f, max_w):
    # 「、」「。」のあとで区切って、どれも1行に入るならそこで改行する（読みやすい）
    if "\n" not in s:
        chunks = [c for c in re.split(r"(?<=[、。！？])", s) if c]
        if len(chunks) > 1 and all(text_w(c, f) <= max_w for c in chunks):
            return chunks
    lines = []
    for para in s.split("\n"):
        cur = ""
        for t in tokenize(para):
            if cur and text_w(cur + t, f) > max_w and cur.strip():
                lines.append(cur.rstrip())
                cur = t.lstrip()
            else:
                cur += t
        lines.append(cur.rstrip())
    return lines


def fit_text(s, max_w, max_h, size, min_size, max_lines=3, weight="bold", spacing=1.25, where="", one_line_min=None):
    """枠に入るまで文字を小さくする。入らないときは警告を出す。
    one_line_min があれば、まずその大きさまでは1行に収めることをめざす（変なところで折り返さないため）"""
    if one_line_min and "\n" not in s:
        sz = size
        while sz >= one_line_min:
            f = font(sz, weight)
            if text_w(s, f) <= max_w and int(sz * spacing) <= max_h:
                return f, [s], int(sz * spacing)
            sz -= 4
    # 改行（\n）と「、」「。」で区切った固まりを、それぞれ1行に収められる大きさを探す
    chunks = [c for part in s.split("\n") for c in re.split(r"(?<=[、。！？])", part) if c]
    if 1 < len(chunks) <= max_lines:
        sz = size
        while sz >= min_size:
            f = font(sz, weight)
            lh = int(sz * spacing)
            if all(text_w(c, f) <= max_w for c in chunks) and lh * len(chunks) <= max_h:
                return f, chunks, lh
            sz -= 4
    sz = size
    floor = max(24, int(min_size * 0.7))   # ふつうの最小より小さくしてでも、まず枠に入れる
    while True:
        f = font(sz, weight)
        lines = wrap(s, f, max_w)
        lh = int(sz * spacing)
        widest = max((text_w(l, f) for l in lines), default=0)
        ok = len(lines) <= max_lines and lh * len(lines) <= max_h and widest <= max_w
        if ok or sz <= floor:
            if not ok:
                warn(f"文字が枠に入りきりません{where}: 「{s}」（{sz}pxまで小さくしても入らないので、台本を短くしてください）")
            elif sz < min_size:
                warn(f"文字が多いので {sz}px まで小さくしました{where}: 「{s}」（読みにくければ台本を短く）")
            return f, lines, lh
        sz -= 2 if sz <= min_size else 4


def draw_lines(d, lines, f, lh, cx, top, fill, align="center", x_left=None):
    y = top
    for l in lines:
        if align == "center":
            d.text((cx, y + lh / 2), l, font=f, fill=fill, anchor="mm")
        else:
            d.text((x_left, y + lh / 2), l, font=f, fill=fill, anchor="lm")
        y += lh
    return y


# ---------------------------------------------------------------- 語源パーツを色分けして書く
def split_colored(word, parts):
    """word の文字列を、parts（morph と type）に合わせて色つきの区切りにする"""
    segs, pos, low = [], 0, word.lower()
    for p in parts:
        m = p["morph"].lower()
        i = low.find(m, pos)
        if i < 0:
            # つづりが変わる語（ad→ac など）は、残りを次のパーツへまわす
            continue
        if i > pos:
            segs.append((word[pos:i], None))
        segs.append((word[i:i + len(m)], p["type"]))
        pos = i + len(m)
    if pos < len(word):
        segs.append((word[pos:], None))
    return segs


def draw_segs(d, segs, f, x, cy, default=TEXT):
    """色分けした1語を左から書く（1語まとめて大きさをそろえる）。右はしの x を返す"""
    g = new_group()
    word = "".join(s for s, _ in segs)
    # 1語全体で安全領域に入るか調べ、入らなければ語全体を小さくする（パーツごとに大きさが変わらないように）
    size0 = f.size
    while x + text_w(word, f) > SAFE_RIGHT and f.size - 2 >= max(20, size0 * SHRINK_MIN_RATIO):
        f = f.font_variant(size=f.size - 2)
    if f.size != size0:
        print(f"  ↳ {_cur['name']}: 「{word}」を {size0}px→{f.size}px に小さくしました（安全領域に入れるため）",
              file=sys.stderr)
    for s, t in segs:
        d.text((x, cy), s, font=f, fill=TYPE_COLOR.get(t, default), anchor="lm", group=g, shrink=False)
        x += text_w(s, f)
    return x


def draw_colored(d, segs, f, cx, cy, default=TEXT):
    total = sum(text_w(s, f) for s, _ in segs)
    while cx + total / 2 > SAFE_RIGHT and f.size > 24:   # まん中ぞろえで右に出るなら小さく
        f = f.font_variant(size=f.size - 2)
        total = sum(text_w(s, f) for s, _ in segs)
    return draw_segs(d, segs, f, cx - total / 2, cy, default)


def colored_font(segs, max_w, size, min_size=40):
    word = "".join(s for s, _ in segs)
    sz = size
    floor = max(24, int(min_size * 0.7))
    while sz > floor and text_w(word, font(sz, "black")) > max_w:
        sz -= 4 if sz > min_size else 2
    if text_w(word, font(sz, "black")) > max_w:
        warn(f"英単語が横にはみ出します: {word}")
    elif sz < min_size:
        warn(f"英単語が長いので {sz}px まで小さくしました: {word}")
    return font(sz, "black")


def rounded(d, box, r, fill=None, outline=None, width=3):
    d.rounded_rectangle(box, r, fill=fill, outline=outline, width=width)


def paste_center(img, im, cx, cy):
    if im is None:
        return
    img.paste(im, (int(cx - im.width / 2), int(cy - im.height / 2)), im)


# ---------------------------------------------------------------- 台本を読む
LINE_RE = re.compile(r"^\[\s*(\d+(?:\.\d+)?)\s*[-–〜~]\s*(\d+(?:\.\d+)?)\s*\]\s*(?:\{([^}]*)\})?\s*(.*)$")


def parse_script(path):
    meta, cuts = {}, []
    with open(path, encoding="utf-8") as fp:
        for n, raw in enumerate(fp, 1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                m = re.match(r"#\s*([^:：]+)[:：]\s*(.*)", line)
                if m:
                    meta[m.group(1).strip()] = m.group(2).strip()
                continue
            m = LINE_RE.match(line)
            if not m:
                warn(f"{n}行目の形が読めません（[0.0-2.5] のような秒数が必要）: {line}")
                continue
            a, b, tag, text = float(m.group(1)), float(m.group(2)), (m.group(3) or "").strip(), m.group(4).strip()
            kind, _, arg = tag.partition(" ")
            cuts.append({"start": a, "end": b, "kind": (kind or "text").lower(), "arg": arg.strip(),
                         "text": text.replace("\\n", "\n"), "line": n})
    if not cuts:
        sys.exit("台本にテロップの行がありません")
    return meta, cuts


def count_chars(s):
    return len(re.sub(r"[\s、。，．,.!?！？「」『』（）()・：:；;＝=＋+\-—…]", "", s)) or 1


def ffprobe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


HOLD_KINDS = ("summary", "pairsum", "count")   # 3秒以上止める場面
HOLD_SEC = 3.0
MIN_CUT_SEC = 0.6


def detect_silences(path, noise_db=-35, min_sec=0.2):
    """録音の中の「間（無音）」を探す。[(始め, 終わり), ...] を返す"""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
                          f"silencedetect=noise={noise_db}dB:d={min_sec}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    sil, start = [], None
    for line in out.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            sil.append((start, float(m.group(1))))
            start = None
    if start is not None:
        sil.append((start, ffprobe_duration(path)))
    return sil


def choose_bounds(weights, silences, total):
    """カットの区切りを、録音の「間」から選ぶ（いちばん自然な組み合わせを全部の行まとめて探す）。
    ・前の区切りから見て、残りの文字数の割合で「このへんのはず」という時刻を出す
    ・その時刻に近いほど、また間が長いほど（行と行の間は、文の中の息つぎより長い）よい
    ・近くに間がなければ、見当どおりの時刻で区切る（少しだけ減点）"""
    m = len(weights) - 1                     # 区切りの数
    if m <= 0:
        return [0.0, total], 0
    sw_suffix = [sum(weights[i:]) for i in range(len(weights))]
    cands = [((a + b) / 2, b - a) for a, b in silences]
    INF = float("inf")
    # best[i] = {時刻: (合計の減点, 前の時刻, 間に合わせたか)}
    best = [{0.0: (0.0, None, False)}]
    for i in range(1, m + 1):
        cur = {}
        for tp, (cost, _, _) in best[i - 1].items():
            rest = total - tp
            g = tp + rest * weights[i - 1] / sw_suffix[i - 1]   # このへんのはず
            sigma = max(0.8, 0.35 * rest * weights[i - 1] / sw_suffix[i - 1])
            opts = [(g, 3.0, False)]                            # 間がないときは見当どおり（減点3）
            for mid, ln in cands:
                if abs(mid - g) <= 3 * sigma:
                    opts.append((mid, -2.0 * min(ln, 1.0) / 0.5, True))
            for t, bonus, snap in opts:
                # 前の区切りから MIN_CUT_SEC 以上・残りの行にも MIN_CUT_SEC ずつ残す
                if t < tp + MIN_CUT_SEC or t > total - MIN_CUT_SEC * (m - i + 1):
                    continue
                c = cost + ((t - g) / sigma) ** 2 + bonus
                key = round(t, 3)
                if c < cur.get(key, (INF,))[0]:
                    cur[key] = (c, tp, snap)
        if not cur:   # どうしても置けないときは、文字数の割合どおり
            acc, out = 0.0, [0.0]
            for wgt in weights[:-1]:
                acc += wgt
                out.append(total * acc / sum(weights))
            return out + [total], 0
        # 候補が増えすぎないよう、よいものだけ残す
        best.append(dict(sorted(cur.items(), key=lambda kv: kv[1][0])[:60]))
    t = min(best[m], key=lambda k: best[m][k][0])
    out, snapped = [], 0
    for i in range(m, 0, -1):
        c, tp, snap = best[i][t]
        out.append(t)
        snapped += snap
        t = tp
    return [0.0] + out[::-1] + [total], snapped


def plan_voice(cuts, voice, sync="chars"):
    """録音に合わせて、各カットが録音のどこからどこまでかを決める。
    1) 文字数（--sync script なら台本の目安秒数）の割合で、区切りの時刻の見当をつける
    2) 区切りの近くに「間（無音）」があれば、そのまん中に区切りを合わせる（声の途中で画面が変わらないように）
    3) まとめ・カウントダウンは、声が短くても3秒止める（そのぶん録音に無音をはさむので、ずれない）"""
    total = ffprobe_duration(voice)
    if sync == "script":
        weights = [max(0.1, c["end"] - c["start"]) for c in cuts]
    elif sync == "mix":
        ch = [count_chars(c["text"]) for c in cuts]
        sc = [max(0.1, c["end"] - c["start"]) for c in cuts]
        weights = [a / sum(ch) + b / sum(sc) for a, b in zip(ch, sc)]
    else:
        weights = [count_chars(c["text"]) for c in cuts]
    sw = sum(weights)
    sil = detect_silences(voice)
    # 録音の最初と最後の無音は、カットの区切りに使わない（最初のカット・最後のカットに入れる）
    inner = [(a, b) for a, b in sil if a > 0.05 and b < total - 0.05]
    bounds, snapped = choose_bounds(weights, inner, total)
    print(f"録音 {total:.1f}秒・見つけた間 {len(inner)}か所・区切り {len(bounds) - 2}か所のうち {snapped}か所を間に合わせました",
          file=sys.stderr)
    if len(bounds) - 2 > 0 and snapped < (len(bounds) - 2) / 2:
        warn("録音の「間」があまり見つかりません。行と行のあいだを少し空けて読むと、画面と声がよく合います")
    t = 0.0
    for i, c in enumerate(cuts):
        a, b = bounds[i], bounds[i + 1]
        c["a0"], c["a1"] = a, b
        c["dur"] = b - a
        c["pad"] = 0.0
        if c["kind"] in HOLD_KINDS and c["dur"] < HOLD_SEC:
            c["pad"] = HOLD_SEC - c["dur"]   # 声のあとに無音をはさんで止める
            c["dur"] = HOLD_SEC
        if c["dur"] < MIN_CUT_SEC:
            warn(f"{c['line']}行目のカットが {c['dur']:.2f}秒しかありません（録音とテロップの量が合っていないかも）")
        c["t0"] = t
        t += c["dur"]
    return t


def build_voice_track(cuts, voice, out_path):
    """カットごとに録音を切り出し、止める場面には無音をはさんでつなぎ直す"""
    parts, labels = [], []
    for i, c in enumerate(cuts):
        f = f"[0:a]atrim=start={c['a0']:.4f}:end={c['a1']:.4f},asetpts=PTS-STARTPTS"
        if c["pad"] > 0:
            f += f",apad=pad_dur={c['pad']:.4f}"
        parts.append(f + f"[a{i}]")
        labels.append(f"[a{i}]")
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(cuts)}:v=0:a=1[out]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", voice, "-filter_complex", graph, "-map", "[out]",
                    "-ar", "44100", "-ac", "1", out_path], check=True)
    return out_path


def plan_timing(cuts, voice, sync="chars"):
    """各カットの長さを決める。録音があれば録音に合わせる（plan_voice）"""
    if voice:
        return plan_voice(cuts, voice, sync)
    for i, c in enumerate(cuts):
        nxt = cuts[i + 1]["start"] if i + 1 < len(cuts) else c["end"]
        c["dur"] = max(0.5, nxt - c["start"])
    for c in cuts:
        if c["kind"] in ("summary", "pairsum", "count") and c["dur"] < 3.0:
            warn(f"{c['line']}行目の{'カウントダウン' if c['kind'] == 'count' else 'まとめ画面'}が3秒より短いので、3秒にのばしました")
            c["dur"] = 3.0
    t = 0.0
    for c in cuts:
        c["t0"] = t
        t += c["dur"]
    return t


# ---------------------------------------------------------------- 画面の部品
TELOP_BOX = (LEFT, 1250, SAFE_RIGHT, 1480)


def base(number):
    img = Image.new("RGB", (W, H), BG)
    d = CheckedDraw(ImageDraw.Draw(img))
    # 左上ラベル「Roots #001」（上220pxの外＝y=236 から）
    label = f"Roots #{number:03d}"
    f = font(40, "bold")
    tw = text_w(label, f)
    rounded(d, (LEFT, 236, LEFT + tw + 48, 236 + 68), 34, fill=ACCENT)
    d.text((LEFT + 24, 236 + 34), label, font=f, fill="#FFFFFF", anchor="lm")
    return img, d


def telop(d, text, box=TELOP_BOX):
    if not text:
        return
    x0, y0, x1, y1 = box
    f, lines, lh = fit_text(text, x1 - x0 - 64, y1 - y0 - 40, 72, 44, max_lines=2, where="（テロップ）", one_line_min=56)
    h = lh * len(lines) + 44
    top = y1 - h
    rounded(d, (x0, top, x1, y1), 28, fill=ACCENT_SOFT, outline=ACCENT, width=4)
    draw_lines(d, lines, f, lh, (x0 + x1) / 2, top + 22, TEXT)


def chip(d, text, cx, cy, color, size=40, filled=False):
    f = font(size, "bold")
    tw = text_w(text, f)
    box = (cx - tw / 2 - 26, cy - size * 0.8, cx + tw / 2 + 26, cy + size * 0.8)
    if filled:
        rounded(d, box, size * 0.8, fill=color)
        d.text((cx, cy), text, font=f, fill="#FFFFFF", anchor="mm")
    else:
        rounded(d, box, size * 0.8, outline=color, width=4, fill="#FFFFFF")
        d.text((cx, cy), text, font=f, fill=color, anchor="mm")


def parse_parts(spec, root_morph):
    """'re(もとへ)+port(運ぶ)' → [{morph,gloss,type}]（語根の前は接頭・後ろは接尾の色）"""
    items = [s.strip() for s in re.split(r"[+＋]", spec) if s.strip()]
    parts = []
    for s in items:
        m = re.match(r"^([^（(]+)(?:[（(]([^）)]*)[）)])?$", s)
        morph, gloss = (m.group(1).strip(), (m.group(2) or "").strip()) if m else (s, "")
        parts.append({"morph": morph, "gloss": gloss})
    ri = next((i for i, p in enumerate(parts) if root_morph and p["morph"].lower() == root_morph.lower()), None)
    for i, p in enumerate(parts):
        if ri is None:
            p["type"] = "root"
        else:
            p["type"] = "root" if i == ri else ("prefix" if i < ri else "suffix")
        if p["type"] == "root" and not p["gloss"] and root_morph:
            p["gloss"] = root_info(root_morph)["gloss"]
    return parts


def breakdown_text(parts):
    return " ＋ ".join(f"{p['morph']}（{p['gloss']}）" if p["gloss"] else p["morph"] for p in parts)


# ---------------------------------------------------------------- 場面（カット）ごとの絵
class Ctx:
    """台本全体で共有する情報（語根・ここまでに出た語など）"""

    def __init__(self, meta, number, vtype):
        self.meta = meta
        self.number = number
        self.type = vtype
        self.root = meta.get("語根") or meta.get("root") or ""
        self.katas = []
        self.words = []


def scene_hook(ctx, c):
    img, d = base(ctx.number)
    f, lines, lh = fit_text(c["text"], CONTENT_W - 40, 520, 104, 56, max_lines=4, weight="black", where="（フック）")
    h = lh * len(lines)
    top = 640 - h / 2
    draw_lines(d, lines, f, lh, CX, top, TEXT)
    d.rectangle((CX - 90, top + h + 30, CX + 90, top + h + 42), fill=ACCENT)
    paste_center(img, chara(c["arg"] or "teach", 300), CX, 1130)
    return img


def scene_text(ctx, c):
    img, d = base(ctx.number)
    telop(d, c["text"])
    paste_center(img, chara(c["arg"] or "normal", 340), CX, 760)
    return img


def scene_root(ctx, c):
    img, d = base(ctx.number)
    arg = c["arg"] or ctx.root
    morph, _, gloss = arg.partition("=")
    morph = morph.strip()
    ctx.root = ctx.root or morph
    info = root_info(morph)
    gloss = gloss.strip() or info["gloss"]
    ctx.root_gloss = gloss
    chip(d, "語根", CX, 400, TYPE_COLOR["root"], size=40)
    f = font(200, "black")
    d.text((CX, 560), morph, font=f, fill=TYPE_COLOR["root"], anchor="mm")
    d.text((CX, 720), "＝ " + gloss, font=font(84, "bold"), fill=TEXT, anchor="mm")
    box = 380
    rounded(d, (CX - box / 2, 800, CX + box / 2, 800 + box), 28, outline=LINE, width=4)
    paste_center(img, picto_image(info["picto"], 300), CX, 800 + box / 2)
    telop(d, c["text"])
    return img


def scene_kata(ctx, c):
    """{kata ポータブル portable port(運ぶ)+able(できる)}"""
    img, d = base(ctx.number)
    bits = c["arg"].split()
    if len(bits) < 2:
        warn(f"{c['line']}行目: kata は「カタカナ 英語 パーツ」の順に書きます")
        bits += [""] * (3 - len(bits))
    kana, eng, spec = bits[0], bits[1], (" ".join(bits[2:]) if len(bits) > 2 else eng)
    parts = parse_parts(spec, ctx.root)
    ctx.katas.append({"kana": kana, "eng": eng, "parts": parts})
    n = len(ctx.katas)
    chip(d, f"知ってるカタカナ語 {n}", CX, 400, ACCENT, size=36, filled=True)
    f, lines, lh = fit_text(kana, CONTENT_W - 40, 200, 150, 80, max_lines=1, weight="black", where="（カタカナ語）")
    draw_lines(d, lines, f, lh, CX, 470, TEXT)
    d.text((CX, 730), "▼", font=font(56, "bold"), fill=LINE, anchor="mm")
    segs = split_colored(eng, parts)
    fe = colored_font(segs, CONTENT_W - 40, 130)
    draw_colored(d, segs, fe, CX, 860)
    fb, bl, blh = fit_text(breakdown_text(parts), CONTENT_W - 40, 150, 50, 34, max_lines=2, weight="medium", where="（分解）")
    draw_lines(d, bl, fb, blh, CX, 980, SUB)
    telop(d, c["text"])
    return img


def word_block(img, d, w, top, show_parts=True, word_size=140):
    segs = split_colored(w["word"], w["parts"])
    fe = colored_font(segs, CONTENT_W - 40, word_size)
    draw_colored(d, segs, fe, CX, top + 80)
    mean = w["meaning"].split("；")[0]
    fm, ml, mlh = fit_text(mean, CONTENT_W - 60, 120, 64, 40, max_lines=1, where="（意味）")
    draw_lines(d, ml, fm, mlh, CX, top + 170, TEXT)
    if w.get("eiken"):
        chip(d, "英検" + w["eiken"], CX, top + 300, ACCENT, size=34)
    if not show_parts:
        return
    parts = [p for p in w["parts"] if p["picto"] or p["type"] != "suffix"][:4]
    if not parts:
        return
    n = len(parts)
    cell = min(250, (CONTENT_W - 30 * (n - 1)) // n)
    gap = 30
    x = CX - (cell * n + gap * (n - 1)) / 2
    y = top + 380
    for p in parts:
        rounded(d, (x, y, x + cell, y + cell), 22, outline=LINE, width=4)
        paste_center(img, picto_image(p["picto"], int(cell * 0.72)), x + cell / 2, y + cell / 2)
        fm2 = font(44 if cell > 200 else 36, "black")
        d.text((x + cell / 2, y + cell + 44), p["morph"], font=fm2, fill=TYPE_COLOR[p["type"]], anchor="mm")
        fg, gl, glh = fit_text(p["gloss"] or TYPE_LABEL[p["type"]], cell + 20, 80, 34, 24, max_lines=2, weight="medium")
        draw_lines(d, gl, fg, glh, x + cell / 2, y + cell + 76, SUB)
        x += cell + gap


def scene_word(ctx, c):
    img, d = base(ctx.number)
    name = c["arg"].split()[0] if c["arg"] else ""
    # 前の場面（ペアや推理）ですでに出た語なら、同じ番号のまま使う
    prev = next((i for i, x in enumerate(ctx.words) if x["word"].lower() == name.lower()), None)
    if prev is None:
        w = find_word(name) or {"word": name, "meaning": "", "parts": [], "eiken": ""}
        ctx.words.append(w)
        prev = len(ctx.words) - 1
    w = ctx.words[prev]
    chip(d, f"受験単語 {prev + 1}", CX, 400, TYPE_COLOR["root"], size=36, filled=True)
    word_block(img, d, w, 440)
    telop(d, c["text"])
    return img


def scene_summary(ctx, c):
    """まとめ画面（語根＋カタカナ語＋受験単語）。3秒止める"""
    img, d = base(ctx.number)
    info = root_info(ctx.root) if ctx.root else {"gloss": "", "picto": None}
    gloss = getattr(ctx, "root_gloss", "") or info["gloss"]
    # 見出し: [絵] port ＝ 運ぶ
    pic = picto_image(info["picto"], 150)
    title_f = font(110, "black")
    tw = text_w(ctx.root, title_f)
    gf = font(64, "bold")
    gw = text_w("＝" + gloss, gf)
    total = (170 if pic else 0) + tw + 20 + gw
    x = CX - total / 2
    if pic:
        rounded(d, (x, 340, x + 150, 490), 18, outline=LINE, width=3)
        img.paste(pic, (int(x), 340), pic)
        x += 170
    d.text((x, 415), ctx.root, font=title_f, fill=TYPE_COLOR["root"], anchor="lm")
    d.text((x + tw + 20, 425), "＝" + gloss, font=gf, fill=TEXT, anchor="lm")

    y = 540

    def section(title, rows, y):
        d.text((LEFT + 10, y), title, font=font(40, "bold"), fill=ACCENT, anchor="lm")
        d.line((LEFT + 10 + text_w(title, font(40, "bold")) + 20, y, SAFE_RIGHT, y), fill=LINE, width=3)
        y += 34
        for segs, right in rows:
            fe = font(64, "black")
            word = "".join(s for s, _ in segs)
            while text_w(word, fe) > 470 and fe.size > 40:
                fe = font(fe.size - 4, "black")
            x = draw_segs(d, segs, fe, LEFT + 20, y + 44)
            fr = font(44, "bold")
            r = right
            while text_w(r, fr) > SAFE_RIGHT - max(x + 30, 560) and len(r) > 1:
                r = r[:-1]
            if r != right:
                r = r[:-1] + "…"
            d.text((SAFE_RIGHT, y + 46), r, font=fr, fill=SUB, anchor="rm")
            y += 92
        return y + 40

    rows = [(split_colored(k["eng"], k["parts"]), k["kana"]) for k in ctx.katas]
    if rows:
        y = section("カタカナ語", rows, y)
    rows = [(split_colored(w["word"], w["parts"]), w["meaning"].split("；")[0]) for w in ctx.words]
    if rows:
        y = section("受験単語", rows, y)
    if y > TELOP_BOX[1] - 10:
        warn("まとめ画面の行が多すぎて、テロップと重なります（6行までがおすすめ）")
    telop(d, c["text"])
    return img


# ---------------------------------------------------------------- 型② 雑学（意外な語源の話）
def get_word(ctx, c):
    name = c["arg"].split()[0] if c["arg"] else (ctx.words[-1]["word"] if ctx.words else "")
    if ctx.words and ctx.words[-1]["word"].lower() == name.lower():
        return ctx.words[-1]
    w = find_word(name) or {"word": name, "meaning": "", "parts": [], "eiken": ""}
    ctx.words.append(w)
    return w


def part_cells(img, d, parts, top, cell_max=250, plus=True):
    """語源パーツを、ピクトグラムの箱＋色つきの文字＋意味で横に並べる。下のはしの y を返す"""
    parts = parts[:4]
    if not parts:
        return top
    n = len(parts)
    gap = 70 if plus else 30
    cell = min(cell_max, (CONTENT_W - gap * (n - 1)) // n)
    x = CX - (cell * n + gap * (n - 1)) / 2
    bottom = top
    for i, p in enumerate(parts):
        rounded(d, (x, top, x + cell, top + cell), 22, outline=TYPE_COLOR[p["type"]], width=5)
        pic = picto_image(p.get("picto"), int(cell * 0.72), TYPE_COLOR[p["type"]])
        if pic is None:
            fs = font(min(64, int(cell * 0.5)), "black")
            d.text((x + cell / 2, top + cell / 2), p["morph"], font=fs, fill=TYPE_COLOR[p["type"]], anchor="mm")
        else:
            paste_center(img, pic, x + cell / 2, top + cell / 2)
        fm2 = font(48 if cell > 200 else 40, "black")
        d.text((x + cell / 2, top + cell + 46), p["morph"], font=fm2, fill=TYPE_COLOR[p["type"]], anchor="mm")
        fg, gl, glh = fit_text(p["gloss"] or TYPE_LABEL[p["type"]], cell + 40, 90, 38, 26, max_lines=2, weight="medium",
                               where="（パーツの意味）")
        bottom = max(bottom, draw_lines(d, gl, fg, glh, x + cell / 2, top + cell + 80, SUB))
        if plus and i < n - 1:
            d.text((x + cell + gap / 2, top + cell / 2), "＋", font=font(56, "black"), fill=SUB, anchor="mm")
        x += cell + gap
    return bottom


def scene_trivia(ctx, c):
    """{trivia danger} 単語を大きく出して「意外な語源」"""
    img, d = base(ctx.number)
    w = get_word(ctx, c)
    chip(d, "意外な語源", CX, 400, ACCENT, size=40, filled=True)
    f = colored_font([(w["word"], None)], CONTENT_W - 40, 190)
    d.text((CX, 600), w["word"], font=f, fill=TEXT, anchor="mm")
    fm, ml, mlh = fit_text(w["meaning"].split("；")[0], CONTENT_W - 60, 110, 72, 44, max_lines=1, where="（意味）")
    draw_lines(d, ml, fm, mlh, CX, 720, SUB)
    paste_center(img, chara(c["arg"].split()[1] if len(c["arg"].split()) > 1 else "think", 300), CX, 1030)
    telop(d, c["text"])
    return img


def scene_origin(ctx, c):
    """{origin danger} もとの意味（語源パーツとピクトグラム）"""
    img, d = base(ctx.number)
    w = get_word(ctx, c)
    chip(d, "もともとの意味は…", CX, 400, TYPE_COLOR["root"], size=40, filled=True)
    segs = split_colored(w["word"], w["parts"])
    fe = colored_font(segs, CONTENT_W - 40, 150)
    draw_colored(d, segs, fe, CX, 560)
    part_cells(img, d, w["parts"], 690, cell_max=300)
    telop(d, c["text"])
    return img


def scene_reveal(ctx, c):
    """{reveal danger} もとの意味 → 今の意味"""
    img, d = base(ctx.number)
    w = get_word(ctx, c)
    roots = [p for p in w["parts"] if p["type"] == "root"] or w["parts"]
    then = "＋".join(p["gloss"] for p in roots if p["gloss"]) or "？"
    segs = split_colored(w["word"], w["parts"])
    draw_colored(d, segs, colored_font(segs, CONTENT_W - 40, 120), CX, 380)
    # 昔
    rounded(d, (LEFT + 40, 470, SAFE_RIGHT - 40, 680), 28, outline=LINE, width=4)
    d.text((LEFT + 80, 520), "むかし", font=font(36, "bold"), fill=SUB, anchor="lm")
    fa, la, lha = fit_text(then, CONTENT_W - 160, 110, 76, 44, max_lines=1, where="（もとの意味）")
    draw_lines(d, la, fa, lha, CX, 560, TYPE_COLOR["root"])
    d.text((CX, 760), "▼", font=font(80, "black"), fill=ACCENT, anchor="mm")
    # 今
    rounded(d, (LEFT + 40, 840, SAFE_RIGHT - 40, 1110), 28, fill=ACCENT_SOFT, outline=ACCENT, width=5)
    d.text((LEFT + 80, 890), "いま", font=font(36, "bold"), fill=ACCENT, anchor="lm")
    fb, lb, lhb = fit_text(w["meaning"].split("；")[0], CONTENT_W - 160, 150, 110, 56, max_lines=1, weight="black",
                           where="（今の意味）")
    draw_lines(d, lb, fb, lhb, CX, 940, TEXT)
    if w.get("eiken"):
        chip(d, "英検" + w["eiken"], CX, 1170, ACCENT, size=32)
    telop(d, c["text"])
    return img


# ---------------------------------------------------------------- 型③ 推理（カウントダウン→分解→正解）
def scene_quiz(ctx, c):
    """{quiz interrupt} 単語だけ出して「意味わかる？」"""
    img, d = base(ctx.number)
    w = get_word(ctx, c)
    chip(d, "語源で推理", CX, 400, ACCENT, size=40, filled=True)
    f = colored_font([(w["word"], None)], CONTENT_W - 40, 180)
    d.text((CX, 620), w["word"], font=f, fill=TEXT, anchor="mm")
    d.text((CX, 780), "この意味、わかる？", font=font(72, "black"), fill=ACCENT, anchor="mm")
    paste_center(img, chara(c["arg"].split()[1] if len(c["arg"].split()) > 1 else "think", 280), CX, 1060)
    telop(d, c["text"])
    return img


def scene_count(ctx, c):
    """{count interrupt} 3・2・1 のカウントダウン（1秒ずつ数字が変わる）。3枚の絵を返す"""
    w = get_word(ctx, c)
    frames = []
    name = _cur["name"]
    for k in (3, 2, 1):
        if k != 3:   # 数字ごとに別の絵として調べる
            begin_frame(f"{name}（{k}）")
        img, d = base(ctx.number)
        f = colored_font([(w["word"], None)], CONTENT_W - 40, 130)
        d.text((CX, 440), w["word"], font=f, fill=TEXT, anchor="mm")
        r = 230
        d.ellipse((CX - r, 830 - r, CX + r, 830 + r), outline=ACCENT, width=14)
        # 残り時間の弧（数字が減るほど短く）
        d.arc((CX - r, 830 - r, CX + r, 830 + r), -90, -90 + 360 * k / 3, fill=ACCENT, width=28)
        d.text((CX, 830), str(k), font=font(300, "black"), fill=ACCENT, anchor="mm")
        telop(d, c["text"])
        frames.append(img)
    return frames


def scene_split(ctx, c):
    """{split interrupt} 分解してヒント"""
    img, d = base(ctx.number)
    w = get_word(ctx, c)
    chip(d, "分解すると…", CX, 400, TYPE_COLOR["root"], size=40, filled=True)
    segs = split_colored(w["word"], w["parts"])
    draw_colored(d, segs, colored_font(segs, CONTENT_W - 40, 150), CX, 560)
    part_cells(img, d, w["parts"], 690, cell_max=300)
    telop(d, c["text"])
    return img


def scene_answer(ctx, c):
    """{answer interrupt} 正解（意味・英検級・パーツ）"""
    img, d = base(ctx.number)
    w = get_word(ctx, c)
    chip(d, "正解", CX, 400, "#2E7D4F", size=44, filled=True)
    word_block(img, d, w, 440)
    telop(d, c["text"])
    return img


# ---------------------------------------------------------------- 型④ ペア（左右分割で比べる）
def pair_words(ctx, c):
    names = c["arg"].split()[:2]
    if len(names) < 2:
        warn(f"{c['line']}行目: pair は {{pair 単語1 単語2}} と2語書きます")
        names = (names + ["?", "?"])[:2]
    out = []
    for nm in names:
        w = next((x for x in ctx.words if x["word"].lower() == nm.lower()), None)
        if w is None:
            w = find_word(nm) or {"word": nm, "meaning": "", "parts": [], "eiken": ""}
            ctx.words.append(w)
        out.append(w)
    ctx.pair = out
    return out


PAIR_GAP = 90
HALF = (CONTENT_W - PAIR_GAP) // 2   # 左右それぞれの幅（385px）


def short_meaning(w):
    """「～より先に起こる，先行する」→「～より先に起こる」（せまい所用）"""
    return re.split(r"[；，,]", w["meaning"])[0].strip()


def pair_column(img, d, w, x0, top, highlight):
    cx = x0 + HALF / 2
    rounded(d, (x0, top, x0 + HALF, 1200), 28, outline=highlight, width=5)
    segs = split_colored(w["word"], w["parts"])
    draw_colored(d, segs, colored_font(segs, HALF - 40, 96, min_size=48), cx, top + 80)
    y = top + 160
    for p in w["parts"][:3]:
        pic = picto_image(p.get("picto"), 120, TYPE_COLOR[p["type"]])
        rounded(d, (cx - 70, y, cx + 70, y + 140), 18, outline=LINE, width=3)
        if pic is not None:
            paste_center(img, pic, cx, y + 70)
        else:
            d.text((cx, y + 70), p["morph"], font=font(48, "black"), fill=TYPE_COLOR[p["type"]], anchor="mm")
        label = f"{p['morph']}＝{p['gloss'] or TYPE_LABEL[p['type']]}"
        fl, ll, lhl = fit_text(label, HALF - 30, 60, 40, 26, max_lines=1, where="（ペアのパーツ）")
        draw_lines(d, ll, fl, lhl, cx, y + 150, TYPE_COLOR[p["type"]])
        y += 150 + lhl + 20
    rounded(d, (x0 + 20, 1060, x0 + HALF - 20, 1180), 20, fill=ACCENT_SOFT)
    fm, ml, mlh = fit_text(short_meaning(w), HALF - 70, 100, 52, 30, max_lines=2, weight="black", one_line_min=32,
                           where="（ペアの意味）")
    draw_lines(d, ml, fm, mlh, cx, 1120 - mlh * len(ml) / 2, TEXT)


def scene_pair(ctx, c):
    """{pair precede proceed} 左右に2語を並べて比べる"""
    img, d = base(ctx.number)
    a, b = pair_words(ctx, c)
    d.text((CX, 380), "似てる2語、どう違う？", font=font(56, "black"), fill=ACCENT, anchor="mm")
    pair_column(img, d, a, LEFT, 440, TYPE_COLOR["prefix"])
    pair_column(img, d, b, LEFT + HALF + PAIR_GAP, 440, TYPE_COLOR["prefix"])
    d.text((CX, 820), "vs", font=font(44, "black"), fill=SUB, anchor="mm")
    telop(d, c["text"])
    return img


def scene_pairsum(ctx, c):
    """{pairsum} 1行まとめ（3秒以上止める）"""
    img, d = base(ctx.number)
    pair = getattr(ctx, "pair", None) or (ctx.words[-2:] if len(ctx.words) >= 2 else [])
    chip(d, "まとめ", CX, 400, ACCENT, size=40, filled=True)
    y = 520
    for w in pair:
        segs = split_colored(w["word"], w["parts"])
        fe = colored_font(segs, 420, 84, min_size=48)
        x = draw_segs(d, segs, fe, LEFT + 30, y)
        fr, rl, rlh = fit_text(short_meaning(w), SAFE_RIGHT - max(x + 30, 520), 70, 46, 28, max_lines=1,
                               where="（まとめの意味）")
        d.text((SAFE_RIGHT - 10, y), rl[0], font=fr, fill=SUB, anchor="rm")
        y += 130
    d.line((LEFT + 20, y - 30, SAFE_RIGHT - 20, y - 30), fill=LINE, width=3)
    # 1行まとめは大きく（テロップの文をそのまま使う）
    f, lines, lh = fit_text(c["text"], CONTENT_W - 40, 1150 - y, 96, 52, max_lines=3, weight="black",
                            where="（1行まとめ）")
    draw_lines(d, lines, f, lh, CX, y + 20, TEXT)
    paste_center(img, chara("cheer", 240), CX, 1330)
    return img


def scene_end(ctx):
    img = Image.new("RGB", (W, H), ACCENT)
    d = CheckedDraw(ImageDraw.Draw(img))
    paste_center(img, chara("cheer", 360), CX, 640)
    d.text((CX, 960), "Rootsで英単語", font=font(110, "black"), fill="#FFFFFF", anchor="mm")
    d.line((CX - 300, 1060, CX + 300, 1060), fill="#FFFFFF", width=4)
    d.text((CX, 1150), "プロフのリンクから無料", font=font(64, "bold"), fill="#FFFFFF", anchor="mm")
    return img


SCENES = {"hook": scene_hook, "text": scene_text, "root": scene_root, "kata": scene_kata,
          "word": scene_word, "summary": scene_summary,
          "trivia": scene_trivia, "origin": scene_origin, "reveal": scene_reveal,
          "quiz": scene_quiz, "count": scene_count, "split": scene_split, "answer": scene_answer,
          "pair": scene_pair, "pairsum": scene_pairsum}

# 型ごとにふだん使う場面
COMMON = {"hook", "text", "root", "word"}
TYPE_SCENES = {
    1: COMMON | {"kata", "summary"},
    2: COMMON | {"trivia", "origin", "reveal", "summary"},
    3: COMMON | {"quiz", "count", "split", "answer", "summary"},
    4: COMMON | {"pair", "pairsum"},
}


# ---------------------------------------------------------------- 動画にする
def run_checks(report_path=None):
    """全カットの文字の位置を調べて、問題を一覧にする"""
    bad = 0
    for rec in CHECK_LOG:
        if not rec["items"]:
            continue
        probs = check_frame(rec)
        for pr in probs:
            warn(f"{rec['cut']}: {pr}")
            bad += 1
    n_items = sum(len(r["items"]) for r in CHECK_LOG)
    print(f"文字の位置チェック: {len([r for r in CHECK_LOG if r['items']])}カット・文字 {n_items}か所を調べて、問題 {bad}件")
    if report_path:
        with open(report_path, "w", encoding="utf-8") as fp:
            json.dump({"safe_area": {"top": SAFE_TOP, "bottom": SAFE_BOTTOM, "right": SAFE_RIGHT},
                       "cuts": [r for r in CHECK_LOG if r["items"]]}, fp, ensure_ascii=False, indent=1)
        print(f"文字の位置の一覧: {report_path}")
    return bad


def render(args):
    meta, cuts = parse_script(args.script)
    ctx = Ctx(meta, args.number, args.type)
    total = plan_timing(cuts, args.voice, args.sync)
    allowed = TYPE_SCENES.get(args.type, set(SCENES))
    frames = []
    for c in cuts:
        kind = c["kind"]
        if kind not in SCENES:
            warn(f"{c['line']}行目: 「{kind}」という場面はまだありません。ふつうのテロップで出します")
            kind = "text"
        elif kind not in allowed:
            warn(f"{c['line']}行目: 型{args.type}では「{kind}」はふだん使いません")
        begin_frame(f"{c['line']}行目（{kind}）")
        out = SCENES[kind](ctx, c)
        if isinstance(out, list):   # カウントダウンなど、1カットの中で絵が変わる場面
            frames += [(im, c["dur"] / len(out)) for im in out]
        else:
            frames.append((out, c["dur"]))
    begin_frame("エンドカード")
    frames.append((scene_end(ctx), END_CARD_SEC))
    _cur["items"] = None
    video_len = sum(d for _, d in frames)
    if not (30 <= video_len <= 45):
        warn(f"動画の長さが {video_len:.1f} 秒です（目安は30〜45秒）")
    run_checks(args.report)
    if args.check:   # 動画は作らず、チェックだけ
        print(f"チェックだけ: {video_len:.1f}秒・カット数 {len(frames)}・注意 {len(WARNINGS)}件")
        return

    if args.preview:
        os.makedirs(args.preview, exist_ok=True)
        for i, (im, _) in enumerate(frames):
            im.save(os.path.join(args.preview, f"cut{i + 1:02d}.png"))
        with open(os.path.join(args.preview, "timing.txt"), "w", encoding="utf-8") as fp:
            for c in cuts:
                extra = f"  声 {c['a0']:.2f}-{c['a1']:.2f}" if "a0" in c else ""
                extra += f"  ＋無音 {c['pad']:.2f}" if c.get("pad") else ""
                fp.write(f"{c['t0']:6.2f}〜{c['t0'] + c['dur']:6.2f}  {c['kind']:8s} {c['text'].replace(chr(10), ' / ')}{extra}\n")

    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg が見つかりません")
    tmpdir = tempfile.mkdtemp(prefix="roots_shorts_")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-"]
    if args.voice:
        track = build_voice_track(cuts, args.voice, os.path.join(tmpdir, "voice.wav"))
        cmd += ["-i", track, "-filter_complex", "[1:a]apad[a]", "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", args.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    fade_n = int(FADE_SEC * FPS)
    prev = None
    written = 0
    t_end = 0.0
    for im, dur in frames:
        t_end += dur
        cut_fade = fade_n if dur >= 0.9 else 0   # とても短いカットはフェードなしで切りかえる
        n = round(t_end * FPS) - written   # ずれがたまらないよう、終わりの時刻から数える
        raw = im.tobytes()
        for i in range(n):
            if prev is not None and i < cut_fade:
                proc.stdin.write(Image.blend(prev, im, (i + 1) / (cut_fade + 1)).tobytes())
            else:
                proc.stdin.write(raw)
        written += n
        prev = im
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg でエラーが出ました")
    shutil.rmtree(tmpdir, ignore_errors=True)
    size = os.path.getsize(args.out) / 1e6
    print(f"できました: {args.out}  {video_len:.1f}秒  {size:.1f}MB  カット数 {len(frames)}")
    if WARNINGS:
        print(f"注意 {len(WARNINGS)} 件（上の ⚠ を見てください）")


def main():
    ap = argparse.ArgumentParser(description="Rootsで英単語 ショート動画を作る")
    ap.add_argument("--script", required=True, help="台本ファイル（.txt）")
    ap.add_argument("--voice", help="録音ファイル（m4a / mp3 / wav）。なければ無音の仮動画")
    ap.add_argument("--type", type=int, default=1, choices=[1, 2, 3, 4], help="型 1=カタカナ語 2=雑学 3=推理 4=ペア")
    ap.add_argument("--number", type=int, default=1, help="左上の連番（Roots #001）")
    ap.add_argument("--out", required=True, help="出力する MP4")
    ap.add_argument("--crf", type=int, default=26, help="画質（大きいほどファイルが小さい）")
    ap.add_argument("--preview", help="各カットの静止画（PNG）と時間の表（timing.txt）を書き出すフォルダ（確認用）")
    ap.add_argument("--sync", default="chars", choices=["chars", "script", "mix"],
                    help="録音の分け方 chars=文字数の割合（ふつう） script=台本の目安秒数の割合 mix=両方の平均")
    ap.add_argument("--report", help="全部の文字の位置とチェック結果を書き出す JSON ファイル")
    ap.add_argument("--check", action="store_true", help="動画は作らず、文字のはみ出しチェックだけする")
    args = ap.parse_args()
    render(args)


if __name__ == "__main__":
    main()
