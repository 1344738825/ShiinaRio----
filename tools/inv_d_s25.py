# -*- coding: utf-8 -*-
"""inv_d_s25.py v2 -- D 包 S25: 逐条目爆破 pos1 (0..63, 明文 S25\\0 校验) 再解码落盘"""
import sys, os, io
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import s25, warc_pack as WP
from PIL import Image

GAME = r"J:/SR Game/超催眠術学園"
D_WAR = os.path.join(GAME, "CHOSAIMIN_D.WAR")
OUTDIR = os.path.join(HERE, "..", "work", "s25_inv")
os.makedirs(OUTDIR, exist_ok=True)

w = WP.War(D_WAR)
for s in w.slots:
    nm = WP.W.safe_name(s["name_raw"])
    if not nm.upper().endswith(".S25"):
        continue
    raw = w.entry_raw(s)[8:]
    if s["size_comp"] < 8 + 108:
        print("%-14s 过小, 跳过" % nm)
        continue
    pos1 = None
    for c in range(64):
        try:
            plain = WP.decrypt_entry(raw, c)
        except Exception:
            continue
        if plain[:4] == b"S25\x00":
            pos1 = c
            break
    if pos1 is None:
        print("%-14s pos1 爆破失败" % nm)
        continue
    if len(plain) != s["size_orig"]:
        print("%-14s pos1=%d 但 size 不符 (%d != %d)" % (nm, pos1, len(plain), s["size_orig"]))
        continue
    ents = s25.parse(plain)
    base = os.path.splitext(nm)[0]
    n_ok = 0
    for i, e in enumerate(ents):
        if not e.width or not e.height:
            continue
        try:
            bgra = s25.decode_entry(plain, e)
            png = s25.to_png(e.width, e.height, bgra)
            Image.open(io.BytesIO(png)).save(os.path.join(OUTDIR, "%s_%03d.png" % (base, i)))
            n_ok += 1
        except Exception as ex:
            print("  %s slot%d 解码失败: %s" % (nm, i, ex))
    print("%-14s pos1=%-2d slots=%-3d 渲染=%d size=%d" % (nm, pos1, len(ents), n_ok, len(plain)))
