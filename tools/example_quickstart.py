# -*- coding: utf-8 -*-
"""最小可跑示例：打开 WAR，为一个条目爆破 pos1，打印明文头部。

用法:
    python example_quickstart.py <WAR路径> <条目名> [magic]

例:
    python example_quickstart.py J:/game/CHOSAIMIN_D.WAR TITLE.S25 "S25\\0"

这是给第一次接手的人看流程用的，不是工程脚本。
真正的批量破解用 crack_all.py，图像解码用 s25.py。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import warc_pack as WP

MAGICS = {
    "S25\0": b"S25\x00",
}


def crack(w, name, magic):
    s = w.find(name)
    if s is None:
        print("找不到条目:", name)
        return None
    raw = w.entry_raw(s)[8:]
    for c in range(64):
        try:
            plain = WP.decrypt_entry(raw, c)
        except Exception:
            continue
        if magic and plain[:len(magic)] != magic:
            continue
        # 尺寸校验：只认 magic 会误命中
        if len(plain) == s["size_orig"]:
            return c, plain
        print("  pos1=%d magic 命中但尺寸不符 (%d != %d)，继续" % (c, len(plain), s["size_orig"]))
    return None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    war_path, name = sys.argv[1], sys.argv[2]
    magic = MAGICS.get(sys.argv[3], b"") if len(sys.argv) > 3 else b""

    w = WP.War(war_path)
    print("条目总数:", len(w.slots))
    r = crack(w, name, magic)
    if r is None:
        print("爆破失败：大概率是哑块（纯色占位图 / dummy 音频 / 前缀影子条目），别在这上面耗时间")
        return 1
    pos1, plain = r
    print("pos1 =", pos1, " 明文长度 =", len(plain))
    print("头部 64 字节:", plain[:64])
    return 0


if __name__ == "__main__":
    sys.exit(main())
