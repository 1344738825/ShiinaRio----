# -*- coding: utf-8 -*-
"""_sys_pack.py Stage B v2 -- SYSTEM/EXBGM/EX 三包中文槽回封 D.WAR

v2 变更: EX.S25 (52MB) 跳过 fit_compress2 (二分搜索需反复压 52MB, 不可行),
改直接 zlib9 重压缩 + 表区重建 (SCN 的等长约束源于脚本内部偏移, S25 无此约束);
SYSTEM/EXBGM 仍走 fit 精确命中 (与 TITLE 先例同款)。
验收: 替换槽解码==输入PNG; 未动条目 raw 与备份逐字节全等。
"""
import os, sys, glob, struct, zlib, shutil
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import s25, warc_pack as WP
from fitlib import fit_compress2

GAME = r"J:/SR Game/超催眠術学園"
D_WAR = os.path.join(GAME, "CHOSAIMIN_D.WAR")
BAK = os.path.join(GAME, "CHOSAIMIN_D.WAR.bak_before_syscn_20261015")
OUT = os.path.join(HERE, "..", "work", "CHOSAIMIN_D.WAR.syscn")
CN_DIR = os.path.join(HERE, "..", "work", "sys_cn")

# (包名, pos1, 是否 fit 精确命中, fit max_pad)
TARGETS = [("SYSTEM.S25", 12, True, 60000), ("EXBGM.S25", 12, True, 60000),
           ("EX.S25", 2, True, 1500000)]

def log(*a):
    print(*a)
    sys.stdout.flush()

def main():
    only = sys.argv[1].upper() if len(sys.argv) > 1 else None
    targets = [t for t in TARGETS if only is None or t[0].split(".")[0] == only]
    if not os.path.exists(BAK):
        shutil.copy2(D_WAR, BAK)
        log("已备份:", BAK)
    else:
        log("备份已存在:", BAK)

    w = WP.War(BAK)                       # 从备份基线出发 (幂等)
    orig_raws = [bytes(w.entry_raw(s)) for s in w.slots]   # ★ 按槽位序号 (条目名有重复, 名字键会互相覆盖)
    total_bad = 0
    for name, pos1, use_fit, max_pad in targets:
        s = w.find(name)
        raw = w.entry_raw(s)[8:]
        plain = WP.decrypt_entry(raw, pos1)
        assert plain[:4] == b"S25\x00"
        ents = s25.parse(plain)
        (n_slots,) = struct.unpack_from("<I", plain, 4)
        raw_offs = struct.unpack_from("<%dI" % n_slots, plain, 8)
        slot_ids = [i for i, o in enumerate(raw_offs) if o]
        replace = {}
        for f in sorted(glob.glob(os.path.join(CN_DIR, "%s_*.png" % name.split(".")[0]))):
            slot = int(os.path.basename(f).rsplit("_", 1)[1][:-4])
            im = Image.open(f).convert("RGBA")
            arr = np.asarray(im).astype(np.uint8)
            e = ents[slot]
            assert (e.width, e.height) == im.size, (name, slot, (e.width, e.height), im.size)
            replace[slot] = (e.width, e.height, arr[:, :, [2, 1, 0, 3]].tobytes())
        log("%s: 替换 %d 槽 / 有效槽 %d, 原明文 %d" % (name, len(replace), len(slot_ids), len(plain)))
        new_plain = s25.encode_partial(plain, ents, replace, share=True, slot_ids=slot_ids)
        log("  重编码明文: %d (delta %+d)" % (len(new_plain), len(new_plain) - len(plain)))

        if use_fit:
            A = WP.essential_decrypt(raw, pos1)
            z0 = WP.ypk_mask(WP.saimin_crypt(A))
            r = fit_compress2(new_plain, len(z0), z0[:2], max_pad=max_pad, budget=5000)
            log("  fit:", repr(r))
            if not r.ok:
                log("  FIT FAIL:", r.reason)
                return 1
            assert zlib.decompress(r.z) == r.plain_full
            z = r.z
            plain_full = r.plain_full
        else:
            co = zlib.compressobj(9)
            z = co.compress(new_plain) + co.flush()
            plain_full = new_plain
            log("  直接 zlib9: %d (原 z %d)" % (len(z), len(raw) - 8))

        A_new = WP.saimin_crypt(WP.ypk_mask(z))
        raw_new = WP.essential_encrypt(A_new, pos1)
        assert len(raw_new) == len(raw), (name, len(raw_new), len(raw))
        head = WP.make_head(len(plain_full), w.entry_raw(s)[3])
        w.write_entry(s, head, raw_new)
        w.set_size_orig(s, len(plain_full))

        # 即时验: 替换槽解码一致
        plain2 = WP.decrypt_entry(raw_new, pos1)
        assert plain2[:4] == b"S25\x00"
        e2 = s25.parse(plain2)
        bad = 0
        for slot, (wd, ht, bgra) in replace.items():
            got = s25.decode_entry(plain2, e2[slot])
            if got != bgra:
                bad += 1
                log("  槽%d 解码不一致!" % slot)
        log("  替换槽复验: %d/%d 一致" % (len(replace) - bad, len(replace)))
        total_bad += bad

    old_len, new_len = w.save(OUT)
    log("表区 %d -> %d; 已写出 %s" % (old_len, new_len, OUT))

    # ---- 全库验收: 未动条目 raw 与备份逐字节全等 ----
    w2 = WP.War(OUT)
    diff = 0
    for idx, s in enumerate(w2.slots):
        nm = WP.W.safe_name(s["name_raw"])
        if nm in [t[0] for t in targets]:
            continue
        if bytes(w2.entry_raw(s)) != orig_raws[idx]:
            diff += 1
            log("未动条目被改! #%d %s" % (idx, nm))
    log("未动条目 raw 全等: %s" % ("OK" if diff == 0 else "FAIL %d" % diff))
    log("结论:", "PASS" if diff == 0 and total_bad == 0 else "FAIL")
    return 0 if diff == 0 and total_bad == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
