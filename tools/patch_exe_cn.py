# -*- coding: utf-8 -*-
"""
ShiinaRio 引擎汉化 · EXE 显示层补丁（终版，6 处共 18 字节）

这是 CHOSAIMIN.EXE（ShiinaRio v2.50）从原版到汉化版的**全部**差异，
由 原版(1592c0457f0782dc360fd139f1c8bc1a) 与 汉化版(a70efcc539882fa057210d2e94c26834)
逐字节 diff 得到，不含任何推测。

改动清单：
  1) 0x3815d  80 -> 86     CreateFont 的 charset：128(Shift-JIS) -> 134(GBK)
  2) 0x29c13  9f -> fe     SJIS 解码器边界 1
  3) 0x3a9ae  9f -> fe     SJIS 解码器边界 2
  4) 0x3ab83  9f -> fe     SJIS 解码器边界 3
  5) 0x3bb0f  9f -> fe     SJIS 解码器边界 4（RVA 0x3bb00 那个把 GBK 0xA1-0xDF
                            引导字节误判为单字节的缺陷就在这里）
  6) 0xc1f7c  13 字节      字体名 ＭＳ ゴシック(Shift-JIS) -> MSGothicCNJP2(ASCII)

为什么必须改：引擎内部自己解析 Shift-JIS 字节流，UIF 之类的运行时注入管不到
这段逻辑；不改的话 GBK 双字节会被拆错，表现为崩字/乱码。

用法：
  python patch_exe_cn.py <EXE路径>              # 打补丁（自动备份 .bak_orig）
  python patch_exe_cn.py <EXE路径> --revert     # 还原
  python patch_exe_cn.py <EXE路径> --check      # 只检查当前是原版还是已汉化

安全设计：每处改动前都校验原字节，版本对不上会直接报错退出，不会写坏文件。
"""
import sys, os, shutil, hashlib

# (文件偏移, 原版字节, 汉化字节, 说明)
PATCHES = [
    (0x3815d, bytes.fromhex("80"), bytes.fromhex("86"), "charset 128 -> 134 (GBK)"),
    (0x29c13, bytes.fromhex("9f"), bytes.fromhex("fe"), "SJIS 解码边界 #1"),
    (0x3a9ae, bytes.fromhex("9f"), bytes.fromhex("fe"), "SJIS 解码边界 #2"),
    (0x3ab83, bytes.fromhex("9f"), bytes.fromhex("fe"), "SJIS 解码边界 #3"),
    (0x3bb0f, bytes.fromhex("9f"), bytes.fromhex("fe"), "SJIS 解码边界 #4 (RVA 0x3bb00)"),
    (0xc1f7c,
     bytes.fromhex("82 6c 82 72 20 83 53 83 56 83 62 83 4e"),  # ＭＳ ゴシック
     b"MSGothicCNJP2",
     "字体名 -> MSGothicCNJP2"),
]

ORIG_MD5 = "1592c0457f0782dc360fd139f1c8bc1a"   # 原版
CN_MD5 = "a70efcc539882fa057210d2e94c26834"     # 打完补丁后


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    exe = args[0]
    revert = "--revert" in sys.argv
    check = "--check" in sys.argv

    if check:
        m = md5(exe)
        print("md5 =", m)
        print("状态 =", "已汉化" if m == CN_MD5 else ("原版" if m == ORIG_MD5 else "未知版本"))
        return

    bak = exe + ".bak_orig"
    if revert:
        if not os.path.exists(bak):
            sys.exit("没有备份: " + bak)
        shutil.copy(bak, exe)
        print("已还原, md5 =", md5(exe))
        return

    if not os.path.exists(bak):
        shutil.copy(exe, bak)
        print("已备份 ->", bak)

    b = bytearray(open(exe, "rb").read())
    done = 0
    for off, old, new, note in PATCHES:
        cur = bytes(b[off:off + len(old)])
        if cur == new:
            print("  跳过(已是新值) 0x%x  %s" % (off, note))
            continue
        if cur != old:
            sys.exit("偏移 0x%x 原字节不符: 期望 %s 实际 %s —— 版本不匹配，已中止\n  (%s)"
                     % (off, old.hex(" "), cur.hex(" "), note))
        b[off:off + len(new)] = new
        print("  已改 0x%-8x %s" % (off, note))
        done += 1

    open(exe, "wb").write(bytes(b))
    m = md5(exe)
    print("\n写入完成, 本次改动 %d 处, md5 = %s" % (done, m))
    print("校验:", "PASS 与汉化版一致" if m == CN_MD5 else
          ("注意: 与记录的汉化版 md5 不一致（可能版本不同）" if m != ORIG_MD5 else "仍是原版?"))


if __name__ == "__main__":
    main()
