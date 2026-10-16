# -*- coding: utf-8 -*-
"""_start_patch.py -- START.SCN 玩家可见系统串中文等长替换 + 回封

范围定案 (probe_start/probe_ctx 取证):
  - 只翻 4 条玩家可见串; 引擎内部错误串 (コマンドエラー等) 正常流程不可见, 不动
  - 字符集表 (あいうえお…/标点表) 是字体数据, 绝不能动
  - 等字数原则: ASCII 段保留原文逐字节配平, 居中零偏移
  - 基于游戏目录现行 S.WAR (含 START 成果 + SRC_MAIN 14 对), 重跑会因原文消失而断言失败 (幂等守卫)
"""
import sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import warc_pack as WP
from fitlib import fit_compress2

GAME = r"J:/SR Game/超催眠術学園"
S_WAR = os.path.join(GAME, "CHOSAIMIN_S.WAR")
OUT = os.path.join(HERE, "..", "work", "CHOSAIMIN_S.WAR.startcn")

# (日文全文, 中文全文) —— 日文段与中文段字数严格相等, ASCII 段原样保留
PAIRS = [
    ("このソフトウェアは、High Color(32768色又は65536色)必須、True Color(16777216色)推奨です。現在のモードのまま続けますか？",
     "本软件要求的色深为：High Color(32768色或者65536色)必需，True Color(16777216色)为推荐的设置。是否要维持当前模式继续呢？"),
    ("CD/DVD-ROMドライブにゲームディスクを挿入して下さい",
     "CD/DVD-ROM驱动器当中，请放入游戏光盘之后再继续操作"),
    ("エラー：インストールが正しく行われていません",
     "错误：游戏未能正确地完成安装，请重新安装程序"),
    ("「これぐらい？」",
     "「这种程度吗？」"),
]

def main():
    # ---- 字库区守卫 + 等字数守卫 ----
    for jp, cn in PAIRS:
        assert len(jp) == len(cn), "字数不等: %r %d != %d" % (jp[:12], len(jp), len(cn))
        for ch in cn:
            if ord(ch) > 0x7F:
                fb = ch.encode("gbk")[0]
                assert fb <= 0xD7, "一级区外汉字 %s (0x%02X)" % (ch, fb)
    print("守卫 OK: %d 对" % len(PAIRS))

    w = WP.War(S_WAR)
    s = w.find("START.SCN")
    p = WP.load_pos1()["START.SCN"]
    raw = w.entry_raw(s)[8:]
    plain = WP.decrypt_entry(raw, p)
    print("START.SCN 解密:", len(plain), "字节")
    assert len(plain) == s["size_orig"]

    # ---- 等长替换 ----
    buf = bytearray(plain)
    total = 0
    for jp, cn in PAIRS:
        jb = jp.encode("cp932")
        cb = cn.encode("gbk")
        assert len(jb) == len(cb), "字节不等: %r %d != %d" % (jp[:12], len(jb), len(cb))
        n = 0
        st = 0
        while True:
            i = buf.find(jb, st)
            if i < 0:
                break
            buf[i:i + len(cb)] = cb
            st = i + len(cb)
            n += 1
        assert n == 1, "命中数异常 (%d): %r" % (n, jp[:12])
        total += n
        print("  OK %r..." % jp[:14])
    print("替换总数:", total)
    assert len(buf) == len(plain)
    for jp, _ in PAIRS:
        assert jp.encode("cp932") not in buf, "残留: " + jp[:12]
    print("零残留 OK")

    # ---- fit + 回封 ----
    A = WP.essential_decrypt(raw, p)
    z0 = WP.ypk_mask(WP.saimin_crypt(A))
    target, head2 = len(z0), z0[:2]
    print("目标 zlib: len=%d head=%s" % (target, head2.hex()))
    r = fit_compress2(bytes(buf), target, head2, budget=3000)
    print(repr(r))
    if not r.ok:
        print("fit 失败:", r.reason)
        return 1
    import zlib
    back = zlib.decompress(r.z)
    assert back == r.plain_full
    # 语义校验 (fitlib keep_lines: hex 填充插入在 ';' 注释行行尾, 可能多处):
    # 行数不变; 非注释行逐字节全等; 注释行只允许原内容前缀延长
    lb = bytes(buf).split(b"\r\n")
    lr = back.split(b"\r\n")
    assert len(lb) == len(lr), "行数变化! %d -> %d" % (len(lb), len(lr))
    for k, (a, b) in enumerate(zip(lb, lr)):
        if a.startswith(b";"):
            assert b.startswith(a), "注释行内容被改 @行%d" % k
        else:
            assert a == b, "非注释行被改 @行%d: %r -> %r" % (k, a[:40], b[:40])
    print("行级校验 OK: %d 行, 注释行填充 %dB" % (len(lb), len(back) - len(buf)))

    A_new = WP.saimin_crypt(WP.ypk_mask(r.z))
    raw_new = WP.essential_encrypt(A_new, p)
    assert len(raw_new) == len(raw)
    head = WP.make_head(len(r.plain_full), w.entry_raw(s)[3])
    w.write_entry(s, head, raw_new)
    w.set_size_orig(s, len(r.plain_full))
    old_len, new_len = w.save(OUT)
    print("表区 %d -> %d; 已写出 %s" % (old_len, new_len, OUT))

    # ---- 复验 ----
    w2 = WP.War(OUT)
    s2 = w2.find("START.SCN")
    got = WP.decrypt_entry(w2.entry_raw(s2)[8:], p)
    ok = got == r.plain_full
    print("复验解密:", "一致" if ok else "不一致!!")
    txt = got.decode("gbk", errors="replace")
    for _, cn in PAIRS:
        assert cn in txt, "中文缺失: " + cn[:12]
    print("中文全量入包 OK")
    print("结论:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
