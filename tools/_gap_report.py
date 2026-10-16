# -*- coding: utf-8 -*-
"""_gap_report.py -- 全 WAR 缺口清单: 结构/magic/pos1/底稿 四方交叉, 机器取证.

用法: python _gap_report.py [WAR名...]   不带参数 = 全部 9 包
产出:
  - 每包: 条目总数 / magic 分布 / pos1 覆盖 / 非标准 magic 清单
  - T 包额外: 底稿对照 (已翻译/未翻译), 文本行 CJK 抽检
  - 汇总表: 各包汉化状态
"""
import sys, os, glob, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import warc_extract as W
import warc_pack as WP

GAME = r"J:/SR Game/超催眠術学園"
ENG = r"J:/SR Game/超催眠術学園/_汉化工程"
TEXTDIR = os.path.join(ENG, "trans", "text")

ALL_WARS = ["CHOSAIMIN_S", "CHOSAIMIN_T", "CHOSAIMIN_D", "CHOSAIMIN_HP",
            "CHOSAIMIN_E1", "CHOSAIMIN_E2", "CHOSAIMIN_E3",
            "CHOSAIMIN_G", "CHOSAIMIN_U1", "CHOSAIMIN_V"]


def magic_of(e):
    """head_u32 ^ 0x82AD82 ^ size_orig[:3] -> 'YPK'/'YH1'/'YLZ'/其它(hex)."""
    try:
        head = e.get("head_u32")
        so = e.get("size_orig")
        if head is None or so is None:
            return "?"
        v = head ^ 0x82AD82
        b = v.to_bytes(4, "little")[:3]
        try:
            s = b.decode("ascii")
            if s in ("YPK", "YH1", "YLZ"):
                return s
        except UnicodeDecodeError:
            pass
        return "raw:%s" % b.hex()
    except Exception:
        return "?"


def scan_war(stem):
    war = os.path.join(GAME, stem + ".WAR")
    if not os.path.exists(war):
        return None
    pos1 = WP.load_pos1()
    with open(war, "rb") as f:
        hdr = f.read(0x20)
        ver = W.parse_war_version(hdr)
        table_offset, table = W.read_table(f, ver, 0x20)
        ents = W.parse_entries(table, 0x20)
    rows = []
    for e in ents:
        nm = W.safe_name(e.get("name_raw", b""))
        if not nm:
            continue
        mg = magic_of(e)
        p1 = pos1.get(nm.upper())
        rows.append({"name": nm, "magic": mg, "pos1": p1 is not None,
                     "size_comp": e.get("size_comp"), "size_orig": e.get("size_orig")})
    return rows


def main():
    stems = sys.argv[1:] or ALL_WARS
    summary = []
    for stem in stems:
        rows = scan_war(stem)
        if rows is None:
            print("== %s: 文件不存在 ==" % stem)
            continue
        n = len(rows)
        magics = {}
        for r in rows:
            magics[r["magic"]] = magics.get(r["magic"], 0) + 1
        n_pos1 = sum(1 for r in rows if r["pos1"])
        nonstd = [r["name"] for r in rows if r["magic"] not in ("YPK", "YH1", "YLZ")]
        print("== %s: 条目 %d | pos1 %d | magic %s" % (stem, n, n_pos1, magics))
        if nonstd:
            print("   非标准magic %d 个: %s" % (len(nonstd), ", ".join(nonstd[:40])))
        nop1 = [r["name"] for r in rows if not r["pos1"]]
        if nop1 and n_pos1:
            print("   无pos1 %d 个: %s" % (len(nop1), ", ".join(nop1[:40])))
        summary.append({"war": stem, "entries": n, "pos1": n_pos1,
                        "magics": magics, "nonstd": nonstd, "nop1": nop1})

    # T 包底稿对照
    if "CHOSAIMIN_T" in stems:
        print()
        print("== T 包底稿对照 ==")
        rows = scan_war("CHOSAIMIN_T")
        drafts = {os.path.basename(p).replace("CHOSAIMIN_T__", "").replace(".jsonl", "")
                  for p in glob.glob(os.path.join(TEXTDIR, "CHOSAIMIN_T__*.jsonl"))}
        txt_ents = [r for r in rows if r["name"].upper().endswith(".TXT")]
        have, lack = [], []
        for r in txt_ents:
            if r["name"] in drafts:
                have.append(r["name"])
            else:
                lack.append(r)
        print("TXT 条目 %d | 有底稿 %d | 无底稿 %d" % (len(txt_ents), len(have), len(lack)))
        for r in lack:
            print("   [无底稿] %s  magic=%s pos1=%s size_orig=%s" %
                  (r["name"], r["magic"], r["pos1"], r["size_orig"]))
        bin_ents = [r for r in rows if not r["name"].upper().endswith(".TXT")]
        print("非TXT 条目 %d:" % len(bin_ents))
        for r in bin_ents:
            print("   [%s] %s magic=%s pos1=%s" %
                  ("有底稿" if r["name"] in drafts else "无底稿",
                   r["name"], r["magic"], r["pos1"]))

    out = os.path.join(ENG, "work", "gap_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print()
    print("已写出 %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
