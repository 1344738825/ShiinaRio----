# -*- coding: utf-8 -*-
"""
fitlib.py -- 压缩长度对齐库 (Phase 3 回填流水线基础设施).

背景 (见交接文档 §12):
  保 L 路线下, 翻译后明文必然变短 (中文约为日文 0.62 长),
  必须把压缩输出精确"填回"原长度 L, 且 zlib 头保持 78da,
  才能继承原 pos1 (pos1 = f(L, a, b), a/b 只依赖 L 与 zlib 头).

手段 (两段式):
  1. memLevel 1..9 粗调 —— 输出长度差数千字节, 由短到长
  2. 尾部 ';' 注释行填充细调 —— 脚本注释行引擎忽略, 1:1 抬升明文,
     明文总长变了也没关系 (size_orig 会同步更新, head 里重算)

搜索策略: 填充量 k 与压缩长度近似单调 -> 二分查找 (O(log n) 次压缩),
        回退线性扫描兜底. 固定 seed 保证可重复.

本模块不修改任何解包/压缩核心, 只在 zlib 之上做参数搜索.
"""
import zlib

DEFAULT_SEED = 20261013
TAIL_MARK = b"\r\n;"      # 追加的注释行开头
TAIL_END = b"\r\n"        # 注释行结尾
HEX_MAX = 2000000          # 填充池上限 (明文字节) —— 20261015 放开: D 包大条目 (EX.S25) 缺口达 28 万 z 字节


class FitResult(object):
    __slots__ = ("ok", "z", "mem", "pad", "plain_full", "tries", "reason", "base_len")

    def __init__(self, ok, z=None, mem=None, pad=None, plain_full=None,
                 tries=0, reason="", base_len=0):
        self.ok = ok
        self.z = z
        self.mem = mem
        self.pad = pad              # 明文字节数 (hex 段长度)
        self.plain_full = plain_full
        self.tries = tries
        self.reason = reason
        self.base_len = base_len    # 未填充时该 memLevel 的压缩长度

    def __repr__(self):
        if not self.ok:
            return "<FitResult FAIL %s>" % self.reason
        return "<FitResult OK mem=%d pad=%dB L=%d tries=%d>" % (
            self.mem, self.pad, len(self.z), self.tries)


def _pool(seed, n_hex):
    """不可压缩填充池: 随机 hex 文本. 固定 seed -> 可重复."""
    import random
    rnd = random.Random(seed)
    return [b"%02X" % rnd.randrange(256) for _ in range(n_hex)]


def _compress(plain, mem, level=9, strategy=0):
    co = zlib.compressobj(level, 8, 15, mem, strategy)
    return co.compress(plain) + co.flush()


def _build_tail(plain, k, pool):
    """k=0 -> 原明文; k>0 -> 明文 + '\\r\\n;' + hex*k + '\\r\\n'  (会多出 2 行)"""
    if k <= 0:
        return plain
    return plain + TAIL_MARK + b"".join(pool[:k]) + TAIL_END


def _find_comment_line(plain):
    """最后一个 ';' 注释行的下标; 没有则 -1."""
    lines = plain.split(b"\r\n")
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith(b";"):
            return i
    return -1


def _build_inline(plain, k, pool, ci):
    """把 hex 追加到第 ci 个注释行末尾 -> **行数零变化**."""
    if k <= 0:
        return plain
    ls = plain.split(b"\r\n")
    ls[ci] = ls[ci] + b"".join(pool[:k])
    return b"\r\n".join(ls)


def _build(plain, k, pool):
    if k <= 0:
        return plain
    return plain + TAIL_MARK + b"".join(pool[:k]) + TAIL_END


def fit_compress2(plain, target_len, want_head2=b"\x78\xda", max_pad=60000,
                  seed=DEFAULT_SEED, strategy=0, keep_lines=True, budget=60000):
    """把 plain 压缩成长度精确 == target_len 且头 == want_head2 的 zlib 流.

    keep_lines=True (默认): 填充写进已有的 ';' 注释行末尾, **明文行数零变化**
    (满足 rebuild 硬约束: 改行数会破坏 $LABEL/$JUMP).
    找不到注释行时才回退到尾部追加 (会多出 2 行).

    搜索难点: hex 填充每字符对约 +2.1 字节压缩输出, **离散跳变会整段跳过 target**
    (实测 k=9->30847, k=10->30846, k=11->30850, 目标 30848 被跳过).
    解法: 穷举 (锚点注释行 x seed 变体 x 窄 k 区间) 的受控搜索, 带尝试预算.

    返回 FitResult. 失败时 ok=False 且 reason 说明原因.
    """
    tries = 0
    n_hex = min(max_pad, HEX_MAX) // 2
    if want_head2 is not None:
        z0 = _compress(plain, 9, 9, strategy)
        tries += 1
        if z0[0:2] != want_head2:
            return FitResult(False, tries=tries, reason="zlib 头 %s != %s" %
                             (z0[:2].hex(), want_head2.hex()))
    # 候选锚点: 注释行, 从后往前 (最多 24 个). 空列表 -> 回退尾部追加.
    # 单行填充上限: 原版脚本最长行仅 435B, 之前把全部填充塞进一行会造出
    # 数 KB 的单行(实测最多 5861B), 疑似撑爆引擎的行缓冲导致回放崩溃.
    # 改为分摊到多个 ';' 注释行, 每行最多 PER_LINE_HEX 个 hex 字符(+512B),
    # 行数依旧零变化, 仍满足 rebuild 硬约束.
    MAX_ANCHORS = 96          # 最多用多少个注释行做锚点
    SPREAD_ORDERS = 8         # 环形旋转变体数(给搜索提供多样性)
    PER_LINE_HEX = 256        # 每行最多追加的 hex 字符数 -> 每行 +512 字节

    lines = plain.split(b"\r\n")
    anchors = ([i for i in range(len(lines) - 1, -1, -1)
                if lines[i].startswith(b";")][:MAX_ANCHORS] if keep_lines else [])
    if anchors:
        orders = [anchors[o:] + anchors[:o]
                  for o in range(min(SPREAD_ORDERS, len(anchors)))]
    else:
        orders = [None]

    def build(p, k, pool, order):
        """k<=0 -> 原明文; 否则把 hex 填充**分摊**到 order 里的多个注释行."""
        if k <= 0:
            return p
        if not order:
            return p + TAIL_MARK + b"".join(pool[:k]) + TAIL_END
        n = len(order)
        cap = max(1, -(-k // n))                 # ceil(k/n)
        ls = p.split(b"\r\n")
        rest = k
        for j in range(n):
            if rest <= 0:
                break
            take = min(cap, rest, PER_LINE_HEX)
            if take <= 0:                        # 容量不足 -> 退化, 允许超上限
                take = min(rest, cap)
            s = k - rest
            ls[order[j]] = ls[order[j]] + b"".join(pool[s:s + take])
            rest -= take
        if rest > 0:                             # 兜底: 剩余全塞最后一行
            ls[order[-1]] = ls[order[-1]] + b"".join(pool[k - rest:k])
        return b"\r\n".join(ls)

    def sweep(mem, k_lo, k_hi, pool, cands):
        """在 (锚点 x k) 网格里找精确命中. 返回 FitResult 或 None."""
        nonlocal tries
        for ci in cands:
            for k in range(max(1, k_lo), min(n_hex, k_hi) + 1):
                if tries > budget:
                    return None
                full = build(plain, k, pool, ci)
                z = _compress(full, mem, 9, strategy)
                tries += 1
                if len(z) == target_len:
                    return FitResult(True, z, mem, k * 2, full, tries,
                                     "", len(_compress(plain, mem, 9, strategy)))
            if tries > budget:
                return None
        return None

    for mem in range(9, 0, -1):          # mem 9(最短) -> 1(最长)
        base = _compress(plain, mem, 9, strategy)
        tries += 1
        if want_head2 is not None and base[0:2] != want_head2:
            continue
        if len(base) == target_len:
            return FitResult(True, base, mem, 0, plain, tries, "", len(base))
        if len(base) > target_len:
            continue                      # 太长 -> 继续降 memLevel
        need = target_len - len(base)
        pool = _pool(seed, n_hex)
        cands = orders
        a0 = orders[0]
        k_est = max(1, int(need / 2.1))
        # 大缺口: 先用二分把 k 定位到 ballpark (省掉线性扫大片区域)
        # 2026-10-14 修正: 原阈值 need>800 太高 —— 实测每 k 单位(2 hex 字符)只抬升
        # 约 1.78 字节(而非 2.1), need=782 时 k_est=372 而真实命中在 k=440,
        # 偏差 68 远超 ±16 窗口 -> 明明可达却报"无法命中". 改为 always 二分.
        if need > 50:
            lo, hi = 1, n_hex
            while lo <= hi:
                mid = (lo + hi) // 2
                z = _compress(build(plain, mid, pool, a0), mem, 9, strategy)
                tries += 1
                if len(z) == target_len:
                    full = build(plain, mid, pool, a0)
                    return FitResult(True, z, mem, mid * 2, full, tries, "",
                                     len(base))
                if len(z) < target_len:
                    lo = mid + 1
                else:
                    hi = mid - 1
            k_est = max(1, lo)
        # 细扫: 先窄区间 (±6) 扫全部锚点, 再放宽 (±16/±48), 最后换 seed 变体
        for span in (6, 16, 48):
            r = sweep(mem, k_est - span, k_est + span, pool, cands)
            if r:
                return r
            if tries > budget:
                break
        for si in range(1, 9):
            if tries > budget:
                break
            pool = _pool(seed + si * 7919, n_hex)
            r = sweep(mem, k_est - 16, k_est + 16, pool, cands)
            if r:
                return r
    return FitResult(False, tries=tries,
                     reason="无法命中 %d (tries=%d, 锚点=%d)" %
                            (target_len, tries, len(anchors)))


def fit_report(plain, target_len, want_head2=b"\x78\xda", max_pad=60000):
    """诊断: 返回每个 memLevel 的基础压缩长度与缺口, 不实际搜索."""
    rows = []
    for mem in range(9, 0, -1):
        base = _compress(plain, mem, 9, 0)
        rows.append(dict(mem=mem, base=len(base),
                         head=base[:2].hex(),
                         need=target_len - len(base),
                         ok_head=(want_head2 is None or base[:2] == want_head2)))
    return rows


if __name__ == "__main__":
    # 自检: 用真实的 KYO1 明文做一次保 L 对齐
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import warc_pack as WP
    GAME = r"J:/SR Game/超催眠術学園"
    w = WP.War(os.path.join(GAME, "CHOSAIMIN_T.WAR"))
    s = w.find("KYO1.TXT")
    pos1 = WP.load_pos1()["KYO1.TXT"]
    plain = WP.decrypt_entry(w.entry_raw(s)[8:], pos1)
    z = WP.ypk_mask(WP.saimin_crypt(WP.essential_decrypt(w.entry_raw(s)[8:], pos1)))
    target, head2 = len(z), z[:2]
    print("KYO1 目标 L=%d 头=%s 明文=%d" % (target, head2.hex(), len(plain)))
    print("\n各 memLevel 基础长度:")
    for r in fit_report(plain, target, head2):
        print("   mem=%d base=%d need=%+d head=%s %s"
              % (r["mem"], r["base"], r["need"], r["head"],
                 "" if r["ok_head"] else "(头不符)"))
    for cut in (0, 2000, 20000, 40000):
        p2 = plain[:len(plain) - cut] if cut else plain
        r = fit_compress2(p2, target, head2)
        print("\n截断 %5d -> 明文 %6d : %r" % (cut, len(p2), r))
        if r.ok:
            assert len(r.z) == target and r.z[:2] == head2
            print("   复验: 长度/头 均正确")
