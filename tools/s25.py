# -*- coding: utf-8 -*-
"""s25.py -- 椎名里绪 S25 图像包 解码/编码 (依据 arc_unpacker
src/dec/shiina_rio/s25_image_archive_decoder.cc 规范实现).

容器:
  "S25\\0" | u32 file_count | u32 offsets[file_count] |
  每 offset 处: u32 width, u32 height, 8 字节跳空, u32 flags, 随后是
  height 个 u32 行偏移(相对该 entry 数据起点), 每行为 RLE-ish 编码.

行编码 (decode_row): u16 tmp -> method=tmp>>13, skip=(tmp>>11)&3, count=tmp&0x7FF
  (count==0 则再读 u32); method 2/3/4/5 见下; 其余(0,1)为填充(透明黑).
  flags & 0x80000000 -> incremental 模式, decode 时 repeat=共享该行偏移的条目数.

用法:
  python s25.py dump  <file.s25> <outdir>       全部解成 PNG
  python s25.py info  <file.s25>                列容器内图像清单
"""
import io, os, struct, sys, zlib


# ---------------------------------------------------------------- 容器读取
class S25Entry:
    __slots__ = ("width", "height", "flags", "data_off", "row_offs")

    def __init__(self, w, h, fl, off):
        self.width, self.height, self.flags, self.data_off = w, h, fl, off
        self.row_offs = None


def parse(buf):
    if buf[:4] != b"S25\x00":
        raise ValueError("不是 S25 文件 (头 %s)" % buf[:4].hex())
    p = 4
    (n,) = struct.unpack_from("<I", buf, p); p += 4
    raw_offs = list(struct.unpack_from("<%dI" % n, buf, p)); p += 4 * n
    offs = [o for o in raw_offs if o]
    ents = []
    for o in offs:
        w, h = struct.unpack_from("<II", buf, o)
        fl, = struct.unpack_from("<I", buf, o + 16)      # 跳 8 字节
        e = S25Entry(w, h, fl, o + 20)
        if w and h:
            ents.append(e)
    return ents


# ---------------------------------------------------------------- 行解码
def decode_row(inp, width, repeat):
    out = bytearray(width * 4)
    p = 0
    op = 0
    end = len(inp)
    left = width
    while op < width * 4:
        if p & 1:
            p += 1                       # 输入流按 2 字节对齐
        if p + 2 > end:
            break
        tmp = inp[p] | (inp[p + 1] << 8)
        p += 2
        method = tmp >> 13
        skip = (tmp >> 11) & 3
        p += skip
        count = tmp & 0x7FF
        if count == 0:
            count = inp[p] | (inp[p + 1] << 8) | (inp[p + 2] << 16) | (inp[p + 3] << 24)
            p += 4
        if count > left:
            count = left
        left -= count
        if method == 2:                  # RGB (plain=原值 / incremental=增量)
            if p + count * 3 > end:
                count = max(0, (end - p) // 3)
            for _ in range(repeat):
                for i in range(3, count * 3):
                    inp[p + i] = (inp[p + i] + inp[p + i - 3]) & 0xFF
            for i in range(count):
                # 存储 R,G,B → 输出 B,G,R,A=255 (文档 §30.2, 与 m4/m5 同序)
                out[op] = inp[p + 2]; out[op + 1] = inp[p + 1]; out[op + 2] = inp[p]
                out[op + 3] = 0xFF
                op += 4; p += 3
        elif method == 3:                # RGB 单色重复
            r, g, b = inp[p], inp[p + 1], inp[p + 2]; p += 3
            for i in range(count):
                out[op] = b; out[op + 1] = g; out[op + 2] = r
                out[op + 3] = 0xFF; op += 4
        elif method == 4:                # BGRA 增量
            if p + count * 4 > end:
                count = max(0, (end - p) // 4)
            for _ in range(repeat):
                for i in range(4, count * 4):
                    inp[p + i] = (inp[p + i] + inp[p + i - 4]) & 0xFF
            for i in range(count):
                out[op:op + 4] = inp[p + 1:p + 4] + inp[p:p + 1]
                op += 4; p += 4
        elif method == 5:                # BGRA 单色重复
            a, r, g, b = inp[p], inp[p + 1], inp[p + 2], inp[p + 3]; p += 4
            for i in range(count):
                out[op], out[op + 1], out[op + 2] = r, g, b
                out[op + 3] = a; op += 4
        else:                            # 0/1: 空(透明黑)
            op += count * 4
        if count == 0:
            break
    return bytes(out)


def _read_row_bytes(buf, row_off):
    """与 read_row 对齐: row_size 为 u16, 若行偏移为奇数则先跳 1 且 row_size-1."""
    pos = row_off
    sz = buf[pos] | (buf[pos + 1] << 8)
    pos += 2
    if row_off & 1:
        pos += 1
        sz -= 1
    return buf[pos:pos + sz]


def decode_entry(buf, e, rows_count=None):
    """rows_count: {绝对行偏移: 引用它的条目数} incremental 模式用.
    注意: row_offsets 表里的值是**绝对文件偏移**(直接 seek 用), 不是相对值."""
    # 行偏移表(数据紧跟在 20 字节条目头之后)
    offs = list(struct.unpack_from("<%dI" % e.height, buf, e.data_off))
    out = bytearray()
    for y in range(e.height):
        ro = offs[y]
        inp = bytearray(_read_row_bytes(buf, ro))
        rep = 0
        if e.flags & 0x80000000:
            rep = rows_count.get(ro, 0) if rows_count else 0
        out += decode_row(inp, e.width, rep)
    return bytes(out)


def build_rows_count(buf, ents):
    """统计每个绝对 row 偏移被多少条目引用 (incremental 的 repeat 依据)."""
    cnt = {}
    for e in ents:
        try:
            offs = struct.unpack_from("<%dI" % e.height, buf, e.data_off)
        except Exception:
            continue
        for o in offs:
            cnt[o] = cnt.get(o, 0) + 1
    return cnt


# ---------------------------------------------------------------- 图像 IO
def to_png(width, height, bgra):
    """缓冲区是 B,G,R,A 序 (与游戏解码器输出一致), 存 PNG 需交换成 R,G,B,A."""
    try:
        from PIL import Image
    except ImportError:
        return None
    im = Image.frombytes("RGBA", (width, height), bgra)
    r, g, b, a = im.split()
    im = Image.merge("RGBA", (b, g, r, a))
    b = io.BytesIO()
    im.save(b, format="PNG")
    return b.getvalue()


# ---------------------------------------------------------------- 编码(S25)
#
# ★ 语义更正 (2026-10-15, 实测定案):
#   plain 模式 (flags 无 0x80000000) 下 method 2/3/4/5 全部是**原值存储**:
#     method 2/3 = RGB 3字节/像素 (仅全不透明行可用, 解码器强制 A=0xFF)
#     method 4/5 = BGRA 4字节/像素 (存储序 A,B,G,R)
#   "增量累计"只在 incremental 模式 (repeat>0) 生效 —— 旧版编码器误按 delta
#   编码, 导致 5 张图往返不一致 + 体积膨胀 33% (只发 4/5, 原版大量用 2/3).
#
# ★ 原编码器 token 化策略 (2026-10-15 对 TITLE.S25 全量实测反推, 四项证据):
#   0. 像素三分类: 透明黑(0,0,0,0) / 半透明(0<a<FF) / 不透明(a=FF)
#   1. 透明黑: 任意 run 长度 -> m0 (2 字节, 与 count 无关, 最便宜)
#      —— 证据: 原文件 m0 count 分布 {1:64, 2:32, 3:32, 4:32, 5:32, 7:32},
#         短透明 run 也单独成 token, 未被变异段吸收.
#   2. 同色 run >= _RUN_MIN(=12): m3 (不透明) / m5 (半透明)
#      —— 证据: 原文件 4378 个 m3 token 的 count 最小为 12, 无一个 < 12;
#         短同色 run 不单独成 token, 吸收进变异段 (m2 段 4308/6620 含相邻同色对).
#   3. 变异段**类同质**: 全不透明 -> m2 (3 字节/px); 全半透明 -> m4 (4 字节/px);
#      扫描在 异类像素 / 长run(>=12) / 行尾 处断开.
#      —— 证据: 原文件 m4 count 分布 {1:163, 2:154, 3:29, 4:3, 7:29} 全部 <=7,
#         半透明像素被隔离成独立小 m4, 不吸收相邻不透明像素 (我早期版本吸收,
#         导致 m4 15299px vs 原版 773px, zlib 劣化 14KB).
#   为何要照抄: 短 run/异类像素单独成 token 会把行切成碎片, 既多头部字节,
#   又打碎 zlib 的跨行匹配 (带状图形近重复行) —— 实测重编码流 zlib-9
#   从 1614467 (碎片化) 降到 1463471 (仅阈值), 照抄全模型应回到 1448790 量级.
#
# ★ 两条硬约束:
#   (a) 每个 token 必须起始于行载荷内的偶数偏移 (解码器 if(pos&1) skip(1))
#       ⇒ method 2 (2+3n, n 奇则奇) 和 method 3 (恒 5) 后面要补 1 字节
#   (b) 行偏移表存绝对偏移; 本编码器一律产偶数行偏移 (不触发 read_row 的 skip)
_RUN_MIN = 12
_TRANSPARENT = b"\x00\x00\x00\x00"
_MAXC = 0x7FF


def _emit_tokens(tokens):
    """tokens: [(payload_bytes, need_pad_after_if_more)] 已含 u16 头.
    拼接时按运行偏移补奇偶 pad. 返回 bytes."""
    out = bytearray()
    for idx, (tok, odd_len) in enumerate(tokens):
        out += tok
        if odd_len and idx != len(tokens) - 1:
            if len(out) & 1:
                out += b"\x00"
    return bytes(out)


def _enc_row(rgba_row):
    """按原编码器策略 token 化 (见文件头四条规则注释).

    通道序 (本模块缓冲区一律 B,G,R,A):
      m2/m3 存 R,G,B  (解码器输出时换回 B,G,R 并强制 A=0xFF)
      m4/m5 存 A,B,G,R (解码器输出 B,G,R,A)
    """
    n = len(rgba_row) // 4
    px = [rgba_row[k * 4:k * 4 + 4] for k in range(n)]
    # 三分类: 0=透明黑 1=半透明 2=不透明
    cls = [0 if p == _TRANSPARENT else (2 if p[3] == 0xFF else 1) for p in px]
    # run_len[j] = px[j] 起最大同色 run 长度 (O(n) 倒扫)
    run_len = [1] * n
    for j in range(n - 2, -1, -1):
        if px[j] == px[j + 1]:
            run_len[j] = run_len[j + 1] + 1
    tokens = []          # (bytes, odd_len)
    i = 0
    while i < n:
        p = px[i]
        c0 = cls[i]
        rl = run_len[i]
        # —— 1) 透明黑: 任意长度 m0 ——
        if c0 == 0:
            c = rl
            while c > 0:
                k = min(c, _MAXC)
                tokens.append((struct.pack("<H", k), False))     # m0, 长2偶
                c -= k
            i += rl
            continue
        # —— 2) 长同色 run (>=12): m3/m5 ——
        if rl >= _RUN_MIN:
            m = 3 if c0 == 2 else 5
            c = rl
            while c > 0:
                k = min(c, _MAXC)
                hdr = struct.pack("<H", (m << 13) | k)
                if m == 3:
                    # 存 R,G,B = buf[2],buf[1],buf[0]; 长5奇
                    tokens.append((hdr + bytes((p[2], p[1], p[0])), True))
                else:
                    # 存 A,B,G,R = buf[3],buf[0..2]; 长6偶
                    tokens.append((hdr + p[3:4] + p[0:3], False))
                c -= k
            i += rl
            continue
        # —— 3) 同类变异段: 吃到异类像素 / 长 run / 行尾 ——
        j = i + 1
        while j < n and cls[j] == c0 and run_len[j] < _RUN_MIN:
            j += 1
        cnt = j - i
        c = cnt
        base = i
        while c > 0:
            k = min(c, _MAXC)
            hdr = struct.pack("<H", ((2 if c0 == 2 else 4) << 13) | k)
            if c0 == 2:
                body = b"".join(bytes((px[base + t][2], px[base + t][1],
                                       px[base + t][0])) for t in range(k))
                tokens.append((hdr + body, bool(k & 1)))     # 2+3k, k奇则奇
            else:
                body = b"".join(px[base + t][3:4] + px[base + t][0:3] for t in range(k))
                tokens.append((hdr + body, False))            # 2+4k 恒偶
            c -= k
            base += k
        i = j
    return _emit_tokens(tokens)


def _row_is_opaque(rgba_row):
    for i in range(3, len(rgba_row), 4):
        if rgba_row[i] != 0xFF:
            return False
    return True


def _pad_even(b):
    return b + (b"\x00" if len(b) & 1 else b"")


def _encode_entry(w, h, px, entry_start):
    """编码单个条目(plain 模式). entry_start = 该条目在容器中的绝对起始偏移.
    返回 bytes.

    ⚠️ 关键约束(来自 s25_image_archive_decoder.cc 的 read_row):
      (a) 每行格式 = u16 row_size + row_size 字节编码数据;
      (b) 行偏移表里存的是**绝对文件偏移**(直接 seek 用);
      (c) 若绝对行偏移为奇数, 解码器会多跳 1 字节并把 row_size 减 1.
    因此: 写绝对偏移 + 条目起点对齐偶数 + 每行补齐到偶数字节总长."""
    data_start = entry_start + 20 + 4 * h
    data = bytearray()
    offs = []
    for y in range(h):
        offs.append(data_start + len(data))     # 绝对偏移
        row = px[y * w * 4:(y + 1) * w * 4]
        payload = _enc_row(row)
        rowbytes = struct.pack("<H", len(payload)) + payload
        data += _pad_even(rowbytes)
    head = struct.pack("<II", w, h) + b"\x00" * 8 + struct.pack("<I", 0)
    return bytes(head) + struct.pack("<%dI" % h, *offs) + bytes(data)


def encode(images):
    """images: [(width, height, bytes(BGRA, width*height*4)), ...]
    返回 S25 字节. 所有条目一律用 plain 模式编码(flags=0, 解码器可无损还原):
      全不透明变异段用 method 2(RGB 3字节/像素), 否则 method 4(BGRA 4字节/像素);
      同色 run 用 m3/m5, 透明黑用 m0. 均为原值存储, 无 delta."""
    head_size = 4 + 4 + 4 * len(images)
    offs = []
    body = bytearray()
    for (w, h, px) in images:
        if len(body) & 1:                     # 条目起点对齐偶数
            body += b"\x00"
        offs.append(head_size + len(body))
        body += _encode_entry(w, h, px, head_size + len(body))
    out = bytearray(b"S25\x00")
    out += struct.pack("<I", len(images))
    out += struct.pack("<%dI" % len(images), *offs) + body
    while len(out) & 3:                       # 4 字节对齐
        out += b"\x00"
    return bytes(out)


def encode_partial(buf, ents, replace, share=True, slot_ids=None):
    """只重编码 replace={index: (w,h,bgra)} 里的条目, 其余从 buf 实时解码后重新编码.

    注意: 未修改条目也**必须重编码**, 不能原样拷贝字节区间 —— 原包里可能有
    奇数绝对行偏移的行(靠解码器的 skip 处理), 一旦前面条目长度变化就会错位。
    已验证重新编码是无损往返, 且能保证所有绝对行偏移为偶数。

    share=True (默认, 2026-10-15 新增): 跨条目行级去重 —— 原编码器就这么干
    (实测 TITLE.S25 有 582 行被其他条目引用, 如 #1 的 209 行指向 #2 区域,
    按钮簇 #3..#32 互相共享框架行). 字节完全相同的行只存一份, 后续条目的
    行偏移表直接引用先出现的位置. 安全性: 解码器对共享字节按共享方宽度解码,
    由往返保真性保证结果就是共享方自己的像素 (与宽度是否相同无关).
    未实现时不共享也能解码, 但压缩体积 +51507 字节 (超 YPK 槽位 11313).

    slot_ids (2026-10-15 新增, 真机报错修复): 槽位号映射表 — 第 i 个有效条目
    放回原文件的 slot_ids[i] 号槽. 引擎 (menu5.asm @GetChrRect) 按槽位号索引
    chr, 空槽在原版里是"优雅返回 OFF", 若把有效条目压实成连续 count 会令
    槽位号越界 → 引擎硬报错弹窗 (真机实测: TITLE.S25 103 槽被压成 33 后
    主界面弹 menu5.asm:@GetChrRect(OFF):46,50). None = 维持旧的紧凑布局.
    """
    rc = build_rows_count(buf, ents)
    n_slots = (max(slot_ids) + 1) if slot_ids else len(ents)
    imgs = []
    for i, e in enumerate(ents):
        if i in replace:
            imgs.append(replace[i])
        else:
            imgs.append((e.width, e.height, decode_entry(buf, e, rc)))
    # 预编码所有行
    all_rows = []
    for (w, h, px) in imgs:
        rows = []
        for y in range(h):
            rows.append(_enc_row(px[y * w * 4:(y + 1) * w * 4]))
        all_rows.append(rows)
    # 组装: 头部 + 槽位偏移表占位 (count=n_slots, 空槽 offset=0),
    # 然后逐有效条目 (头 + 行偏移表 + 去重后的行)
    head_size = 4 + 4 + 4 * n_slots
    out = bytearray(b"S25\x00") + struct.pack("<I", n_slots)
    out += b"\x00" * (4 * n_slots)            # 槽位偏移表占位 (零=空槽)
    row_index = {}                            # row_bytes -> 绝对偏移 (先出现者拥有)
    shared_rows = 0
    saved_bytes = 0
    for i, (w, h, px) in enumerate(imgs):
        if len(out) & 1:
            out += b"\x00"                    # 条目起点对齐偶数
        slot = slot_ids[i] if slot_ids else i
        struct.pack_into("<I", out, 8 + 4 * slot, len(out))
        # ★ 条目头 8 字节 + flags 必须从原文件照抄 (2026-10-15 真机取证):
        #   原版这 8 字节非零, 是跨条目行共享组的元数据 (同组 3 按钮同值,
        #   第二个 u32 按组递增/步长=行数) —— 引擎靠它建 chr 表; 写死零
        #   会导致引擎排版崩坏 (真机: 只剩一个按钮能画, 面板位置错乱)
        e0 = ents[i]
        o0 = e0.data_off - 20                 # 原条目起点
        meta = bytes(buf[o0 + 8:o0 + 16])     # 8 字节组元数据
        flags0 = struct.unpack_from("<I", buf, o0 + 16)[0]
        out += struct.pack("<II", w, h) + meta + struct.pack("<I", flags0)
        row_tab_pos = len(out)
        out += b"\x00" * (4 * h)              # 行偏移表占位
        for y in range(h):
            rb = all_rows[i][y]
            if share and rb in row_index:
                abs_off = row_index[rb]
                shared_rows += 1
                saved_bytes += 2 + len(rb) + (len(rb) & 1)
            else:
                if len(out) & 1:
                    out += b"\x00"
                abs_off = len(out)
                out += struct.pack("<H", len(rb)) + rb
                if len(out) & 1:
                    out += b"\x00"            # 行总长补齐偶数 (行偏移恒偶)
                if share:
                    row_index[rb] = abs_off
            struct.pack_into("<I", out, row_tab_pos + 4 * y, abs_off)
    while len(out) & 3:
        out += b"\x00"
    if share:
        print("[encode_partial] 行共享: %d 行被引用, 省 %d 字节" %
              (shared_rows, saved_bytes))
    return bytes(out)


# ---------------------------------------------------------------- CLI
def main():
    if len(sys.argv) < 3:
        print(__doc__); return 1
    cmd, path = sys.argv[1], sys.argv[2]
    buf = open(path, "rb").read()
    ents = parse(buf)
    if cmd == "info":
        for i, e in enumerate(ents):
            print("  #%-3d %4dx%-4d flags=%08x data_off=%d" %
                  (i, e.width, e.height, e.flags, e.data_off))
        print("共 %d 张图" % len(ents))
        return 0
    outdir = sys.argv[3]
    os.makedirs(outdir, exist_ok=True)
    rc = build_rows_count(buf, ents)
    for i, e in enumerate(ents):
        if (i + 1) % 25 == 0 or i < 3:
            print("  解码 #%d %dx%d ..." % (i, e.width, e.height))
        px = decode_entry(buf, e, rc)
        png = to_png(e.width, e.height, px)
        if png is None:
            open(os.path.join(outdir, "%03d_%dx%d.bgra" % (i, e.width, e.height)),
                 "wb").write(px)
        else:
            open(os.path.join(outdir, "%03d_%dx%d.png" % (i, e.width, e.height)),
                 "wb").write(png)
    print("输出 %d 张到 %s" % (len(ents), outdir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
