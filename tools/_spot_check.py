# -*- coding: utf-8 -*-
"""_spot_check.py -- 从重建后的 CHOSAIMIN_T.WAR 直接解出指定条目的明文行, 用于终检抽读.

用法: python _spot_check.py KYK02.TXT 100 200 300
      (条目名 行号...)
"""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import warc_extract as W
import warc_pack as WP

GAME = r"J:/SR Game/超催眠術学園"


def main():
    war = os.path.join(GAME, "CHOSAIMIN_T.WAR")
    want = sys.argv[1]
    lines = [int(x) for x in sys.argv[2:]]
    with open(war, "rb") as f:
        hdr = f.read(0x20)
        ver = W.parse_war_version(hdr)
        table_offset, table = W.read_table(f, ver, 0x20)
        ents = W.parse_entries(table, 0x20)
        hit = None
        for e in ents:
            nm = W.safe_name(e.get("name_raw", b""))
            if nm and nm.upper() == want.upper():
                hit = e
                break
        if hit is None:
            names = [W.safe_name(e.get("name_raw", b"")) for e in ents]
            print("未找到条目", want)
            print("样例:", [n for n in names if n][:20])
            return 1
        # essential crypt 条目: 取压缩+加密体, 用 pos1 解密
        f.seek(hit["offset"] + 8)
        blob = f.read(hit["size_comp"] - 8)
        pos1 = WP.load_pos1().get(want.upper())
        if pos1 is None:
            print("pos1 缺失:", want)
            return 1
        raw = WP.decrypt_entry(blob, pos1)
    if raw[:len(raw)] is None:
        return 1
    txt = raw.decode("gbk", "replace")
    rows = txt.split("\r\n")
    print("条目 %s  总行 %d" % (want, len(rows)))
    for n in lines:
        if 1 <= n <= len(rows):
            print("  L%-5d %s" % (n, rows[n - 1]))
        else:
            print("  L%-5d <越界>" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
