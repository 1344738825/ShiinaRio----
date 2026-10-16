# -*- coding: utf-8 -*-
"""_srcmain_patch.py -- SRC_MAIN.SCN 分支选项中文等长替换 + 回封 S.WAR (Task: 选项汉化)

约束 (来自字节取证):
  - 选项块前缀含疑似文件内偏移引用 (84 c0 1d 00 00 类) → 必须**等长替换**
  - SJIS/GBK 都是 2 字节/汉字 → 中文字符数 == 日文字符数时字节数天然相等, 不足补全角空格
  - 替换顺序: 先长后短 (体にかける 是 体にかけてしまう 的前缀)
  - 压缩长度漂移用 fit_compress2 尾部 hex 填充精确命中 (编译字节码无行概念, 尾部追加安全)
  - 基于游戏目录现行 S.WAR 回封 (保留 START.SCN 标题栏中文化成果), 先备份
"""
import sys, os, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import warc_pack as WP
from fitlib import fit_compress2

GAME = r"J:/SR Game/超催眠術学園"
S_WAR = os.path.join(GAME, "CHOSAIMIN_S.WAR")
BAK = os.path.join(GAME, "CHOSAIMIN_S.WAR.bak_before_srcmain_20261015")
OUT = os.path.join(HERE, "..", "work", "CHOSAIMIN_S.WAR.srcmain")
POS1_SRCMAIN = 61

# (日文原文, 中文译文) —— 字数与原文严格相等 (居中引擎按整串宽度算, 补空格必偏 ±半格, 真机实测)
# 先长后短排序，防止短串是长串的前缀造成部分替换
#
# 完整工程里这里一共 14 对，其中 10 对是成人向选项，公开版不收录（见 README「关于版权」）。
# 留下这 4 对中性的，脚本照样能完整演示「等字数替换 → 零残留断言 → fit 回封」这条链，
# 顺序无关，删掉那 10 条不影响其余条目的替换结果。
PAIRS = [
    ("自分本位な愛を貫くことしかできない", "只能把以自我为本位的爱贯彻到底而已"),
    ("誰か一人しか選べない世界の変革",   "一场只能选择其中一人的世界变革"),
    ("携帯端末をポケットにしまう",       "把手机重新放回到口袋里面去"),
    ("アプリを起動させる",              "把应用程序启动起来"),
]

def pad_to(src_jp, cn):
    # 等字数, 零补齐: 偏移根治
    assert len(cn) == len(src_jp), "字数不等: %s(%d) -> %s(%d)" % (src_jp, len(src_jp), cn, len(cn))
    return cn

def main():
    # ---- 0. 备份现行 S.WAR ----
    if not os.path.exists(BAK):
        shutil.copy2(S_WAR, BAK)
        print("已备份:", BAK)
    else:
        print("备份已存在:", BAK)

    # ---- 1. 解密 (基于备份版: 未做 srcmain 替换的原 JP 选项版, 幂等重跑) ----
    w = WP.War(BAK)
    s = w.find("SRC_MAIN.SCN")
    raw = w.entry_raw(s)[8:]
    plain = WP.decrypt_entry(raw, POS1_SRCMAIN)
    print("SRC_MAIN.SCN 解密:", len(plain), "字节")
    assert len(plain) == s["size_orig"]

    # ---- 2. 等长替换 ----
    # 字库区守卫: 引擎仅覆盖 GB2312 一级区 (首字节 <= 0xD7); 二级字落表错位, 真机上会显示成别的字
    for jp, cn in PAIRS:
        for ch in pad_to(jp, cn):
            fb = ch.encode("gbk")[0]
            assert fb <= 0xD7, "二级字库区汉字 %s (0x%02X) 在: %s" % (ch, fb, cn)
    buf = bytearray(plain)
    total = 0
    for jp, cn in PAIRS:
        jb = jp.encode("cp932")
        cb = pad_to(jp, cn).encode("gbk")
        assert len(jb) == len(cb), "等长失败: %s %d != %d" % (jp, len(jb), len(cb))
        n = 0
        start = 0
        while True:
            i = buf.find(jb, start)
            if i < 0:
                break
            buf[i:i + len(cb)] = cb
            start = i + len(cb)
            n += 1
        assert n > 0, "未找到: " + jp
        total += n
        print("  %-18s x%-3d -> %s" % (jp, n, pad_to(jp, cn)))
    print("替换实例总数:", total)
    assert len(buf) == len(plain), "总长变化!"
    # 残留检查: PAIRS 内原文串应零残留
    for jp, _ in PAIRS:
        assert bytes(jp, "cp932") not in buf, "残留: " + jp
    print("零残留 OK")

    # ---- 3. fit 精确命中压缩长度 ----
    z_orig_len = len(raw)              # size_comp - 8 头
    # 原 zlib 头: 从现行条目反解
    A = WP.essential_decrypt(raw, POS1_SRCMAIN)
    z0 = WP.ypk_mask(WP.saimin_crypt(A))
    target, head2 = len(z0), z0[:2]
    print("目标 zlib: len=%d head=%s" % (target, head2.hex()))
    r = fit_compress2(bytes(buf), target, head2, budget=3000)
    print(repr(r))
    if not r.ok:
        print("fit 失败:", r.reason)
        return 1
    assert zlib_ok(r.z, r.plain_full, bytes(buf))

    # ---- 4. 加密回封 ----
    A_new = WP.saimin_crypt(WP.ypk_mask(r.z))
    raw_new = WP.essential_encrypt(A_new, POS1_SRCMAIN)
    assert len(raw_new) == len(raw)
    assert WP.essential_decrypt(raw_new, POS1_SRCMAIN) == A_new
    head = WP.make_head(len(r.plain_full), w.entry_raw(s)[3])
    w.write_entry(s, head, raw_new)
    w.set_size_orig(s, len(r.plain_full))
    old_len, new_len = w.save(OUT)
    print("表区 %d -> %d; 已写出 %s" % (old_len, new_len, OUT))

    # ---- 5. 复验 ----
    w2 = WP.War(OUT)
    s2 = w2.find("SRC_MAIN.SCN")
    got = WP.decrypt_entry(w2.entry_raw(s2)[8:], POS1_SRCMAIN)
    ok = got == r.plain_full
    print("复验解密:", "一致" if ok else "不一致!!")
    txt = got.decode("gbk", errors="replace")
    for _, cn in PAIRS:
        assert cn.strip() in txt, "中文缺失: " + cn
    print("中文全量入包 OK")
    # 其余条目抽查
    pos1 = WP.load_pos1()
    bad = 0
    for s3 in w2.slots:
        nm = WP.W.safe_name(s3["name_raw"])
        if nm == "SRC_MAIN.SCN" or nm not in pos1 or s3["size_comp"] < 8 + 108:
            continue
        try:
            g = WP.decrypt_entry(w2.entry_raw(s3)[8:], pos1[nm])
            if len(g) != s3["size_orig"]:
                bad += 1
        except Exception:
            bad += 1
    print("其余条目抽查异常:", bad)
    print("结论:", "PASS" if ok and bad == 0 else "FAIL")
    return 0 if ok else 1

def zlib_ok(z, full, plain_new):
    import zlib
    back = zlib.decompress(z)
    return back[:len(plain_new)] == plain_new and back == full

if __name__ == "__main__":
    sys.exit(main())
