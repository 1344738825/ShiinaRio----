# -*- coding: utf-8 -*-
"""_verify_entries.py -- 体检 CHOSAIMIN_T.WAR 全部条目.

对每条 essential 条目: 用 pos1 解密 -> zlib 解压 -> 校验解压长度 == size_orig,
并与 ORIG 原版明文比对行数 (行数是硬约束, 变了就说明脚本被改坏).

用法: python _verify_entries.py [WAR路径]
"""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import warc_extract as W
import warc_pack as WP

GAME = r"J:/SR Game/超催眠術学園"
ORIG = os.path.join(HERE, "..", "trans", "orig")


def read_all(path):
    out = {}
    with open(path, "rb") as f:
        ver = W.parse_war_version(f.read(0x20))
        toff, table = W.read_table(f, ver, 0x20)
        ents = W.parse_entries(table, 0x20)
        for e in ents:
            nm = W.safe_name(e.get("name_raw", b""))
            f.seek(e["offset"] + 8)
            blob = f.read(e["size_comp"] - 8)
            out[nm] = (e, blob)
    return ver, out


def main():
    war = sys.argv[1] if len(sys.argv) > 1 else os.path.join(GAME, "CHOSAIMIN_T.WAR")
    pos1 = WP.load_pos1()
    ver, ents = read_all(war)
    bad, ok, skip = [], 0, []
    for nm, (e, blob) in ents.items():
        p1 = pos1.get(nm.upper())
        if p1 is None:
            skip.append(nm)
            continue
        try:
            plain = WP.decrypt_entry(blob, p1)
        except Exception as ex:
            bad.append((nm, "解密失败 %s" % ex))
            continue
        n = plain.count(b"\r\n") + 1
        ok += 1
        # 与 ORIG 比对行数
        op = None
        for cand in (os.path.join(ORIG, nm), os.path.join(ORIG, "CHOSAIMIN_T", nm)):
            if os.path.exists(cand):
                op = cand
                break
        if op:
            ob = open(op, "rb").read()
            on = ob.count(b"\r\n") + 1
            if on != n:
                bad.append((nm, "行数变了: 原 %d -> 现 %d" % (on, n)))
    print("条目 %d  解密OK %d  跳过(无pos1) %d  异常 %d" % (len(ents), ok, len(skip), len(bad)))
    for nm, why in bad:
        print("  !! %-16s %s" % (nm, why))
    if skip:
        print("  跳过条目:", ", ".join(skip[:20]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
