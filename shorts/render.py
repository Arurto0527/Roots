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
    while True:
        f = font(sz, weight)
        lines = wrap(s, f, max_w)
        lh = int(sz * spacing)
        widest = max((text_w(l, f) for l in lines), default=0)
        if (len(lines) <= max_lines and lh * len(lines) <= max_h and widest <= max_w) or sz <= min_size:
            if len(lines) > max_lines or lh * len(lines) > max_h or widest > max_w:
                warn(f"文字が枠に入りきりません{where}: 「{s}」")
            return f, lines, lh
        sz -= 4


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


def draw_colored(d, segs, f, cx, cy, default=TEXT):
    total = sum(text_w(s, f) for s, _ in segs)
    x = cx - total / 2
    for s, t in segs:
        d.text((x, cy), s, font=f, fill=TYPE_COLOR.get(t, default), anchor="lm")
        x += text_w(s, f)


def colored_font(segs, max_w, size, min_size=40):
    word = "".join(s for s, _ in segs)
    sz = size
    while sz > min_size and text_w(word, font(sz, "black")) > max_w:
        sz -= 4
    if text_w(word, font(sz, "black")) > max_w:
        warn(f"英単語が横にはみ出します: {word}")
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


def plan_timing(cuts, voice):
    """各カットの長さを決める。録音があれば、録音の長さを文字数に比例して配分する"""
    if voice:
        total = ffprobe_duration(voice)
        chars = [count_chars(c["text"]) for c in cuts]
        s = sum(chars)
        t = 0.0
        for c, n in zip(cuts, chars):
            c["dur"] = total * n / s
            c["t0"] = t
            t += c["dur"]
        return total
    for i, c in enumerate(cuts):
        nxt = cuts[i + 1]["start"] if i + 1 < len(cuts) else c["end"]
        c["dur"] = max(0.5, nxt - c["start"])
    for c in cuts:
        if c["kind"] in ("summary", "pairsum") and c["dur"] < 3.0:
            warn(f"{c['line']}行目のまとめ画面が3秒より短いので、3秒にのばしました")
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
    d = ImageDraw.Draw(img)
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
    w = find_word(name) or {"word": name, "meaning": "", "parts": [], "eiken": ""}
    ctx.words.append(w)
    chip(d, f"受験単語 {len(ctx.words)}", CX, 400, TYPE_COLOR["root"], size=36, filled=True)
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
            x = LEFT + 20
            for s, t in segs:
                d.text((x, y + 44), s, font=fe, fill=TYPE_COLOR.get(t, TEXT), anchor="lm")
                x += text_w(s, fe)
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


def scene_end(ctx):
    img = Image.new("RGB", (W, H), ACCENT)
    d = ImageDraw.Draw(img)
    paste_center(img, chara("cheer", 360), CX, 640)
    d.text((CX, 960), "Rootsで英単語", font=font(110, "black"), fill="#FFFFFF", anchor="mm")
    d.line((CX - 300, 1060, CX + 300, 1060), fill="#FFFFFF", width=4)
    d.text((CX, 1150), "プロフのリンクから無料", font=font(64, "bold"), fill="#FFFFFF", anchor="mm")
    return img


SCENES = {"hook": scene_hook, "text": scene_text, "root": scene_root, "kata": scene_kata,
          "word": scene_word, "summary": scene_summary}

# 型ごとに使える場面（2晩目以降に増やす）
TYPE_SCENES = {
    1: {"hook", "text", "root", "kata", "word", "summary"},
    2: {"hook", "text", "root", "word", "summary"},
    3: {"hook", "text", "root", "word", "summary"},
    4: {"hook", "text", "root", "word", "summary"},
}


# ---------------------------------------------------------------- 動画にする
def render(args):
    meta, cuts = parse_script(args.script)
    ctx = Ctx(meta, args.number, args.type)
    total = plan_timing(cuts, args.voice)
    allowed = TYPE_SCENES.get(args.type, set(SCENES))
    frames = []
    for c in cuts:
        kind = c["kind"]
        if kind not in SCENES:
            warn(f"{c['line']}行目: 「{kind}」という場面はまだありません。ふつうのテロップで出します")
            kind = "text"
        elif kind not in allowed:
            warn(f"{c['line']}行目: 型{args.type}では「{kind}」はふだん使いません")
        frames.append((SCENES[kind](ctx, c), c["dur"]))
    frames.append((scene_end(ctx), END_CARD_SEC))
    video_len = sum(d for _, d in frames)
    if not (30 <= video_len <= 45):
        warn(f"動画の長さが {video_len:.1f} 秒です（目安は30〜45秒）")

    if args.preview:
        os.makedirs(args.preview, exist_ok=True)
        for i, (im, _) in enumerate(frames):
            im.save(os.path.join(args.preview, f"cut{i + 1:02d}.png"))

    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg が見つかりません")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-"]
    if args.voice:
        cmd += ["-i", args.voice, "-filter_complex", "[1:a]apad[a]", "-map", "0:v", "-map", "[a]"]
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
        n = round(t_end * FPS) - written   # ずれがたまらないよう、終わりの時刻から数える
        raw = im.tobytes()
        for i in range(n):
            if prev is not None and i < fade_n:
                proc.stdin.write(Image.blend(prev, im, (i + 1) / (fade_n + 1)).tobytes())
            else:
                proc.stdin.write(raw)
        written += n
        prev = im
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg でエラーが出ました")
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
    ap.add_argument("--preview", help="各カットの静止画（PNG）を書き出すフォルダ（確認用）")
    args = ap.parse_args()
    render(args)


if __name__ == "__main__":
    main()
