# -*- coding: utf-8 -*-
"""
trans_rebuild.py -- 按译文回填重建 WAR.

流程 (保 L 路线, 见交接文档 §12):
  原始包取明文 -> 按行号把 jp(CP932) 换成 cn(GBK) -> fitlib 填回原压缩长度 L
  -> essential_encrypt(pos1 继承) -> 原地覆盖目标包条目 -> 重加密表区

硬约束:
  1. **行数严格不变** —— $LABEL/$JUMP 等命令可能按行定位, 改行数会破坏脚本
  2. 未翻译行保留**原始字节** (CP932), 不重新编码
  3. cn 必须先过 CP936(GBK) 可编码检查, 不可编码则拒绝回填该行
  4. 压缩长度必须精确 == 原 L, 且 zlib 头不变 -> pos1 继承 (§12.1)

用法:
  python trans_rebuild.py                    # 全部有译文的条目 -> trans/out/
  python trans_rebuild.py KYO1.TXT           # 指定条目
  python trans_rebuild.py --apply            # 备份后覆盖游戏目录
  python trans_rebuild.py --dry-run          # 只校验不输出
"""
import sys, os, json, struct, shutil, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import warc_pack as WP
import warc_extract as W
import fitlib
from trans_export import cp936_ok, classify, TXT_DIR, ORIG, TRANS

GAME = r"J:/SR Game/超催眠術学園"
OUTDIR = os.path.join(TRANS, "out")


def load_records(war, entry):
    """读 jsonl, 返回 {line_no: rec}"""
    stem = "%s__%s" % (war.replace(".WAR", ""), entry)
    p = os.path.join(TXT_DIR, stem + ".jsonl")
    if not os.path.exists(p):
        return None
    recs = {}
    for line in open(p, encoding="utf-8"):
        r = json.loads(line)
        recs[r["line"]] = r
    return recs


def build_plain(plain, recs, strip_comments=False):
    """按行回填. 返回 (new_plain, stats) 或抛 AssertionError.

    strip_comments=True: 把 comment(';' 开头) 行内容清空但**保留行**.
      引擎不解析 ';' 注释行, 所以安全; 目的是腾出压缩空间 ——
      实测中文译文的 zlib 压缩率比日文低 10~15% (明文短 155B 压缩后反而长 288B),
      全量翻译后压缩长度必然超过原 L, 必须腾挪空间.
      保留行(而非删除) => 行号不变 => 原文ID 不变.
    """
    orig = plain.split(b"\r\n")
    if len(orig) != len(recs):
        raise AssertionError("行数不符: 原始 %d vs jsonl %d" % (len(orig), len(recs)))
    out = []
    n_cn = n_skip = n_bad = n_cmt = 0
    bad_chars = {}
    for i, ob in enumerate(orig, 1):
        r = recs[i]
        # 行对齐校验: jsonl 里的 jp 必须与原始字节一致
        if r["jp"].encode("cp932", "replace") != ob:
            # 空白行 / 解码边界差异容差
            if r["jp"].strip() or ob.strip():
                raise AssertionError("第 %d 行错位: jp=%r" % (i, r["jp"][:40]))
        if strip_comments and r["kind"] == "comment":
            # 清空注释内容但**保留 1 字节 ';'**: 既是合法注释行(引擎忽略),
            # 又是 fitlib 的填充锚点. 若清成 b'' 则 _find_comment_line 找不到锚点,
            # fit 会退回尾部追加 -> 多出 2 行, 违反行数零变化.
            out.append(b";")
            n_cmt += max(0, len(ob) - 1)
            continue
        cn = (r.get("cn") or "").strip()
        if not cn or r["kind"] not in ("text", "name"):
            out.append(ob)
            n_skip += 1
            continue
        bad = [ch for ch in cn if not cp936_ok(ch)]
        if bad:
            for ch in bad:
                bad_chars["U+%04X %r" % (ord(ch), ch)] = bad_chars.get(
                    "U+%04X %r" % (ord(ch), ch), 0) + 1
            n_bad += 1
            out.append(ob)          # 拒绝该行, 保留原文
            continue
        nb = cn.encode("gbk")
        if b"\r" in nb or b"\n" in nb:
            raise AssertionError("第 %d 行译文含换行符, 会破坏行数" % i)
        out.append(nb)
        n_cn += 1
    if len(out) != len(orig):
        raise AssertionError("行数在回填后改变: %d -> %d" % (len(orig), len(out)))
    return b"\r\n".join(out), dict(cn=n_cn, skip=n_skip, bad=n_bad,
                                   bad_chars=bad_chars, lines=len(orig),
                                   freed=n_cmt)


def save_fixed_len(w, out_path):
    """重加密表区并写出, 但**强制表区字节数与原文件完全一致** (试 zlib level 1-9).

    为什么必须: size_orig 字段值变化 (91958->90800) 会让 zlib 输出长度漂移,
    表区少 1 字节 -> 文件总长少 1 字节. 交接文档 §8 记录"表区长度敏感,
    多写 1-3 字节游戏秒退", 少 1 字节同样有风险.
    level 1-9 的输出长度不同, 逐个试直到命中原长度.
    """
    orig_len = len(w.blob) - w.table_offset
    _diag = {}
    for lv in (9, 8, 7, 6, 5, 4, 3, 2, 1):
        region, C = WP.encrypt_table(bytes(w.table_plain), w.table_offset,
                                     w.version, X0=w.X[:8], level=lv)
        _diag[lv] = len(region)
        if len(region) == orig_len:
            blob = bytes(w.blob[:w.table_offset]) + region
            with open(out_path, "wb") as f:
                f.write(blob)
            return orig_len, len(region), lv
    # 回退: level 1-9 均无法命中时, 微调某条目 tm(时间戳)字段低字节,
    # 改变表区明文字节模式 -> 改变 zlib 压缩后长度, 力图精确命中原表区长度.
    # tm 仅元数据(游戏读取不使用), 不动 offset/size_comp/size_orig/flags.
    import struct as _s
    base = bytearray(w.table_plain)
    for slot in w.slots:
        p = slot["tpos"] + WP.ENTRY_NAME_SIZE + 12  # off,sc,so 各4字节后即 tm(Q)
        cur = _s.unpack_from("<Q", base, p)[0]
        for delta in (1, -1, 2, -2, 3, -3, 4, -4, 8, -8, 16, -16, 64, -64, 256, -256):
            tp = bytearray(base)
            _s.pack_into("<Q", tp, p, (cur + delta) & 0xFFFFFFFFFFFFFFFF)
            region, C = WP.encrypt_table(bytes(tp), w.table_offset,
                                         w.version, X0=w.X[:8], level=9)
            if len(region) == orig_len:
                blob = bytes(w.blob[:w.table_offset]) + region
                with open(out_path, "wb") as f:
                    f.write(blob)
                print("     [tm] %s tm %+d 命中表区 %d" % (slot["name_raw"], delta, orig_len))
                return orig_len, len(region), 9
    # 扩展回退 v2 (2026-10-14 追加): 上面 ±256 小步长覆盖面太窄, 全量翻译后
    # 表区长度常差 1~3 字节而卡死整个写入.
    #
    # 关键认识 (踩过坑): 单纯"随机化 tm"是**增大熵** => 压缩只会变长,
    # 对"需要变短"的场景完全无效 (实测 27000 轮 0 命中).
    # 有效手段是**降低熵**: 把若干槽的 tm 高 4 字节清零 ——
    #   全表清零: 2381 -> 2298 (可调幅度约 -83);
    #   清零 3 个槽即可 -4 字节.
    # 反向(需要变长)时则随机化 tm 提熵. 用随机子集直接实测长度.
    #
    # 性能: len(encrypt_table(p,..)[0]) == 8 + len(zlib.compress(p, level))
    # (essential_table 只做异或变换, 不改长度). 所以先用 zlib 快速判长
    # (~0.25ms/轮), 命中后再做一次完整加密 —— 否则每轮都跑 essential_table
    # 会慢上百倍 (实测 30000 轮要 30 分钟以上).
    # tm 仍为游戏不读的元数据, offset/size_comp/size_orig/flags 一律不动.
    import random as _r
    import zlib as _z

    def _len_fast(pb, lv):
        return 8 + len(_z.compress(pb, lv))

    rnd = _r.Random(0x5A17)
    nsl = len(w.slots)
    tms = [s["tpos"] + WP.ENTRY_NAME_SIZE + 12 for s in w.slots]
    b9 = _len_fast(bytes(base), 9)
    shrink = b9 > orig_len          # 需要变短 -> 清零高4字节; 否则随机化提熵
    for _try in range(300000):
        tp = bytearray(base)
        if shrink:
            m = 2 + rnd.randrange(29)          # 2..30 个槽
            for i in rnd.sample(range(nsl), m):
                cur = _s.unpack_from("<Q", tp, tms[i])[0]
                _s.pack_into("<Q", tp, tms[i], cur & 0xFFFFFFFF)
        else:
            for i in rnd.sample(range(nsl), 1 + rnd.randrange(20)):
                _s.pack_into("<Q", tp, tms[i], rnd.getrandbits(64))
        for lv in (9, 8, 7, 6, 5, 4):
            if _len_fast(bytes(tp), lv) != orig_len:
                continue
            region, C = WP.encrypt_table(bytes(tp), w.table_offset,
                                         w.version, X0=w.X[:8], level=lv)
            if len(region) == orig_len:
                blob = bytes(w.blob[:w.table_offset]) + region
                with open(out_path, "wb") as f:
                    f.write(blob)
                print("     [tm-%s] 第 %d 轮命中表区 %d (level=%d)"
                      % ("shrink" if shrink else "grow", _try + 1, orig_len, lv))
                return orig_len, len(region), lv
    print("     [diag] table_plain len=%d  各level区域长度=%s  目标=%d"
          % (len(w.table_plain), _diag, orig_len))
    return orig_len, None, None


def main(args):
    apply_ = "--apply" in args
    dry = "--dry-run" in args
    strip = "--strip-comments" in args or os.environ.get("TRANS_STRIP") == "1"
    names = [a for a in args if not a.startswith("-")]
    manifest = json.load(open(os.path.join(TRANS, "manifest.json"),
                              encoding="utf-8"))
    pos1map = WP.load_pos1()

    # 目标包 = 游戏目录当前包 (原地覆盖); 明文源 = 原始备份
    targets = {}
    for e in manifest["entries"]:
        if names and e["entry"] not in names:
            continue
        targets.setdefault(e["war"], []).append(e)
    if not targets:
        print("没有匹配的条目。先跑 trans_export.py, 并在 jsonl 里填 cn 字段。")
        return 1

    os.makedirs(OUTDIR, exist_ok=True)
    print("=" * 78)
    print("回填重建   模式: %s" % ("覆盖游戏目录" if apply_ else
                          ("仅校验" if dry else "输出到 trans/out/")))
    print("=" * 78)
    for wn, ents in targets.items():
        src = os.path.join(ORIG, wn)
        if not os.path.exists(src):
            src = os.path.join(GAME, wn)
        wo = WP.War(src)
        # 目标包基线: 优先用**原始备份**, 避免从"已被上次写入污染的游戏目录包"
        # 出发造成累积漂移 (实测表区 2377->2376, 文件少 1 字节).
        dst_orig = os.path.join(ORIG, wn)
        dst = dst_orig if os.path.exists(dst_orig) else os.path.join(GAME, wn)
        wt = WP.War(dst)
        total_cn = 0
        for e in ents:
            nm = e["entry"]
            recs = load_records(wn, nm)
            if recs is None:
                print("  - %-16s 无 jsonl, 跳过" % nm)
                continue
            n_cn = sum(1 for r in recs.values()
                       if (r.get("cn") or "").strip()
                       and r["kind"] in ("text", "name"))
            if n_cn == 0:
                print("  - %-16s 无译文, 跳过" % nm)
                continue
            plain = WP.decrypt_entry(wo.entry_raw(wo.find(nm))[8:], pos1map[nm])
            st = build_plain(plain, recs, strip_comments=strip)
            new_plain, info = st
            total_cn += info["cn"]
            # fit 回原 L
            s = wt.find(nm)
            raw_t = wt.entry_raw(s)[8:]
            z_orig = WP.ypk_mask(WP.saimin_crypt(
                WP.essential_decrypt(raw_t, pos1map[nm])))
            target, head2 = len(z_orig), z_orig[:2]
            r = fitlib.fit_compress2(new_plain, target, head2)
            if not r.ok:
                print("  ! %-16s fit 失败: %s" % (nm, r.reason))
                print("     (可试 --strip-comments 腾挪注释行空间; 或精简译文)")
                continue
            A_new = WP.saimin_crypt(WP.ypk_mask(r.z))
            raw_new = WP.essential_encrypt(A_new, pos1map[nm])
            if len(raw_new) != len(raw_t):
                print("  ! %-16s raw 长度变化 %d -> %d" %
                      (nm, len(raw_t), len(raw_new)))
                continue
            wt.write_entry(s, WP.make_head(len(r.plain_full),
                                           wt.entry_raw(s)[3]), raw_new)
            wt.set_size_orig(s, len(r.plain_full))
            print("  + %-16s 译文 %5d/%-5d 明文 %d->%d  L=%d(不变) fit:mem=%d pad=%dB%s"
                  % (nm, info["cn"], info["lines"], len(plain),
                     len(new_plain), target, r.mem, r.pad,
                     "  腾出注释 %dB" % info["freed"] if info["freed"] else ""))
        out_path = os.path.join(OUTDIR, wn)
        if dry:
            print("  (dry-run) 不写文件")
            continue
        olen, nlen, lv = save_fixed_len(wt, out_path)
        if nlen is None:
            print("  !! %s 表区长度无法固定 (原 %d), 已跳过写入" % (wn, olen))
            continue
        # 自校验
        w2 = WP.War(out_path)
        bad = []
        p1b = WP.load_pos1()
        for s3 in w2.slots:
            nm3 = W.safe_name(s3["name_raw"])
            if nm3 not in p1b or s3["size_comp"] < 8 + 108:
                continue
            try:
                g = WP.decrypt_entry(w2.entry_raw(s3)[8:], p1b[nm3])
                if len(g) != s3["size_orig"]:
                    bad.append(nm3)
            except Exception:
                bad.append(nm3)
        sz_ok = os.path.getsize(out_path) == os.path.getsize(dst)
        print("  => %s  (%d 字节, 与游戏目录%s, 表区 %d->%d level=%d)  条目异常 %d %s"
              % (os.path.basename(out_path), os.path.getsize(out_path),
                 "同大小" if sz_ok else "大小不同!!", olen, nlen, lv,
                 len(bad), bad[:3]))
        if apply_:
            # ⚠️ 写入目标永远是**游戏目录**, 绝不能是 ORIG 下的原始备份
            # (曾经因把基线路径当写入目标, 导致 original/ 被污染, 靠 2014 真原始 .bak 才恢复)
            game_dst = os.path.join(GAME, wn)
            assert os.path.realpath(game_dst) != os.path.realpath(dst), \
                "写入目标与基线相同, 拒绝"
            shutil.copy2(game_dst, game_dst + ".bak2")
            shutil.copy2(out_path, game_dst)
            print("     已覆盖游戏目录 (备份 %s.bak2)" % wn)
    print()
    print("合计回填译文行数: %d" % total_cn)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
