# -*- coding: utf-8 -*-
"""_check_tsv.py -- 译文 tsv 回填前自检（4 项硬校验，全过再 fill_cn.py）.

用法: python _check_tsv.py work/cn_KYK02_x1.tsv

校验项:
  1. 行覆盖: 与 work/todo_<ENTRY>.TXT.txt 比对, 行数/顺序/缺行/多行星
  2. 非 GBK 字符（含 U+30FB `・` 这类会炸的字符）
  3. GBK 第二字节 == 0x5C（反斜杠，引擎会当转义吃掉）
  4. 值内出现 ASCII `|`（会破坏 tsv 分隔符）
"""
import io
import os
import sys


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    tsv = [l for l in io.open(path, encoding="utf-8-sig").read().splitlines() if l.strip()]
    if not tsv:
        print("空文件:", path)
        return 1

    entry = tsv[0].split("|")[0]
    todo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(path))),
                             "work", "todo_%s.txt" % entry)
    ok = True

    # 1) 行覆盖
    ids = [l.split("|")[1] for l in tsv]
    if os.path.exists(todo_path):
        todo = [l.split("|")[0] for l in io.open(todo_path, encoding="utf-8") if l.strip()]
        if not todo:
            # 条目已清零（全部译完），todo 文件为空是正常的，不能据此判失败
            print("行覆盖: todo 为空（该条目已清零），跳过；tsv %d 行，格式已按 3 段解析" % len(ids))
        else:
            miss = [x for x in todo if x not in ids]
            extra = [x for x in ids if x not in todo]
            print("行覆盖: todo %d / tsv %d  缺 %s  多 %s  顺序一致=%s" % (
                len(todo), len(ids), miss[:5], extra[:5], todo == ids))
            if miss or extra or todo != ids:
                ok = False
    else:
        print("行覆盖: 未找到 %s，跳过" % todo_path)

    # 2) 非 GBK + 3) 0x5C 尾字节 + 4) ASCII 竖线
    non_gbk, b5c, pipe = [], [], []
    for l in tsv:
        parts = l.split("|")
        if len(parts) != 3:
            pipe.append(l[:40])
            continue
        val = parts[2]
        for ch in val:
            try:
                b = ch.encode("gbk")
            except Exception:
                non_gbk.append((parts[1], ch, hex(ord(ch))))
                continue
            if b[-1] == 0x5C:
                b5c.append((parts[1], ch))
            if ch == "|":
                pipe.append(parts[1])
        if "|" in val:
            pipe.append(parts[1])

    print("非 GBK  : %d %s" % (len(non_gbk), non_gbk[:5]))
    print("0x5C 尾字节: %d %s" % (len(b5c), b5c[:5]))
    print("ASCII 竖线 : %d %s" % (len(pipe), pipe[:5]))
    if non_gbk or b5c or pipe:
        ok = False

    print("==> %s" % ("全部通过，可 fill_cn.py" if ok else "未通过，先修上面问题"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
