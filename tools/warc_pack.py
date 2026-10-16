# -*- coding: utf-8 -*-
"""
warc_pack.py -- ShiinaRio WARC 1.7 重封 (加密方向) + 原地热补丁.

为什么可以绕开 pos1 的浮点偏差:
  essential crypt 循环里, 首字节之后 p1 = 输出字节 % 64, 与初始 pos1 无关.
  所以真正决定结果的只是 CK[pos1] 这一个字节.
  而 pos1 = f(L, a, b), 其中 a,b 只依赖 A[0],A[1].
  => 只要保证 (1) 压缩后长度 L 不变 (2) zlib 头两字节不变,
     pos1 就自动继承原值, 无需预测浮点.

策略 (原地热补丁):
  - 条目数据原地覆盖 (长度不变 => 后续条目偏移全部不变)
  - 表区整体重新加密 (表在文件尾, 变动不影响条目)
  - header / table_offset / 未知字段 全部保持原样

用法:
  python warc_pack.py selftest          # 加密方向自测 (enc(dec(x)) == x)
  python warc_pack.py info CHOSAIMIN_T.WAR 01_A.TXT
  python warc_pack.py patch CHOSAIMIN_T.WAR 01_A.TXT <newfile> <out.WAR>
"""
import sys, os, struct, zlib, math, json, pickle, random

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import saimin_full as SF
import warc_extract as W
from crack_all import K, LOGO, _region_crc, RB, RW, RH

GAME = r"J:/SR Game/超催眠術学園"
ORIG = os.path.join(GAME, "_汉化工程", "project", "original")
CK = SF.CRYPT_KEY
KLEN = len(CK)
ENTRY_NAME_SIZE = 0x20
MAX_ENTRIES = 16384
TABLE_M = (ENTRY_NAME_SIZE + 0x18) * MAX_ENTRIES     # 917504
TABLE_OFFSET_XOR = 0xF182AD82
FILE_HEAD_XOR = 0x82AD82
YPK_MAGIC = 0x4B5059        # "YPK" little-endian 3 bytes


def rotl8(x, n=1):
    x &= 0xFF
    return ((x << n) | (x >> (8 - n))) & 0xFF


# --------------------------------------------------------------------------
# essential crypt (条目)
# --------------------------------------------------------------------------
def _entry_ctx(buf):
    """计算 crypt 循环所需的一切. buf 可以是 raw 或 A (两者在 0..0x81, 44..107 一致)."""
    L = len(buf)
    keys, flags = SF.get_helper_keys(buf, _region_crc)
    lcg = SF.LCG(L)
    v1 = lcg.next_u32()
    idx = int(v1 * (len(LOGO) / 4294967296.0))
    ad1 = SF.get_key_pos_addend1(SF.u32(v1 + LOGO[idx])) & 0x0FFFFFFF
    a = SF.s8(buf[0] ^ (L & 0xFF))
    b = SF.s8(buf[1] ^ ((L // 2) & 0xFF))
    tmp = SF.get_lcg_xor(float(a)) * 100000000.0
    lcg.reset(SF.u32(v1) ^ SF.u32(int(tmp)))
    tok = 0.0
    if a or b:
        tok = math.acos(a / math.sqrt(a * a + b * b)) / math.pi * 180.0
    if b < 0:
        tok = 360.0 - tok
    ad2 = SF.get_key_pos_addend2(tok, lcg)
    end = min(L, 1024)
    start = 0x80 if end > 0x80 else 0
    return dict(L=L, keys=keys, lcg=lcg, ad1=ad1, ad2=ad2, a=a, b=b,
                tok=tok, v1=v1, start=start, end=end,
                computed=(ad1 + ad2) % KLEN)


def essential_decrypt(raw, pos1):
    """raw -> A (essential 解密). pos1 只需落在正确等价类里即可."""
    c = _entry_ctx(raw)
    d = bytearray(raw)
    for i in range(10):
        off = 4 + 4 * i
        struct.pack_into("<I", d, off, struct.unpack_from("<I", d, off)[0] ^ c["keys"][i])
    lcg, start, end = c["lcg"], c["start"], c["end"]
    p1, p2 = pos1 % KLEN, 0
    i = start + 2
    while i < end:
        r = lcg.next_u32() // 16777216
        x = SF.rotr8(d[i] ^ r, 1)
        x ^= CK[p1] ^ CK[p2]
        d[i] = x
        p1 = x % KLEN
        p2 = (p2 + 1) % KLEN
        i += 1
    return bytes(d)


def essential_encrypt(A, pos1):
    """A -> raw (essential 加密, essential_decrypt 的严格逆)."""
    c = _entry_ctx(A)
    out = bytearray(A)
    lcg, start, end = c["lcg"], c["start"], c["end"]
    p1, p2 = pos1 % KLEN, 0
    i = start + 2
    while i < end:
        p = A[i]
        r = lcg.next_u32() // 16777216
        out[i] = rotl8(p ^ CK[p1] ^ CK[p2], 1) ^ r
        p1 = p % KLEN
        p2 = (p2 + 1) % KLEN
        i += 1
    for i in range(10):
        off = 4 + 4 * i
        struct.pack_into("<I", out, off,
                         struct.unpack_from("<I", out, off)[0] ^ c["keys"][i])
    return bytes(out)


# --------------------------------------------------------------------------
# SaiminCrypt (对合) / YPK
# --------------------------------------------------------------------------
def saimin_crypt(data):
    L = len(data)
    if L < 0x200:
        return bytes(data)
    o = bytearray(data)
    nwin = (L & 0x7E) | 1
    for j in range(nwin):
        o[j] ^= K[j % 0x40]
    struct.pack_into("<I", o, 0x104,
                     struct.unpack_from("<I", o, 0x104)[0] ^ L)
    return bytes(o)


def ypk_mask(data):
    n = len(data) // 4
    w = struct.unpack("<%dI" % n, bytes(data[:n * 4]))
    out = bytearray(struct.pack("<%dI" % n, *[x ^ 0xB4B2B4B2 for x in w]))
    out += bytearray(b ^ 0xB2 for b in data[n * 4:])
    return bytes(out)


def ypk_compress(plain, level=9):
    return ypk_mask(zlib.compress(plain, level))


def ypk_decompress(data):
    return zlib.decompress(ypk_mask(data))


def decrypt_entry(raw, pos1):
    return ypk_decompress(saimin_crypt(essential_decrypt(raw, pos1)))


def encrypt_entry(plain, pos1, level=9):
    """plain -> raw. 要求 len(zlib.compress(plain)) == L_original."""
    return essential_encrypt(saimin_crypt(ypk_compress(plain, level)), pos1)


def make_head(size_orig, crypt_flag=1):
    low24 = (YPK_MAGIC ^ FILE_HEAD_XOR ^ size_orig) & 0xFFFFFF
    return struct.pack("<I", low24 | (crypt_flag << 24)) + struct.pack("<I", size_orig)


# --------------------------------------------------------------------------
# 表
# --------------------------------------------------------------------------
def essential_table(data, inverse=False, X0=None):
    """表的 essential crypt. inverse=True 时 data 是 X, 返回 F."""
    L = len(data)
    out = bytearray(data)
    src = X0 if (inverse and X0 is not None) else data
    a = SF.s8(src[0] ^ (L & 0xFF))
    b = SF.s8(src[1] ^ ((L // 2) & 0xFF))
    lcg = SF.LCG(L)
    tmp = SF.get_lcg_xor(float(a)) * 100000000.0
    lcg.reset(SF.u32(lcg.value ^ int(tmp)))
    tok = 0.0
    if a or b:
        tok = math.acos(a / math.sqrt(a * a + b * b)) / math.pi * 180.0
    if b < 0:
        tok = 360.0 - tok
    ad2 = SF.get_key_pos_addend2(tok, lcg)
    p1, p2 = ad2 % KLEN, 0
    for i in range(2, min(L, 1024)):
        r = lcg.next_u32() // 16777216
        if inverse:
            p = data[i]
            out[i] = rotl8(p ^ CK[p1] ^ CK[p2], 1) ^ r
            p1 = p % KLEN
        else:
            x = SF.rotr8(out[i] ^ r, 1)
            x ^= CK[p1] ^ CK[p2]
            out[i] = x
            p1 = x % KLEN
        p2 = (p2 + 1) % KLEN
    return bytes(out)


def decrypt_table(region, table_offset, version=170):
    data = region + b"\x00" * max(0, TABLE_M - len(region))
    data = data[:TABLE_M]
    X = essential_table(data)
    Y = bytearray(X)
    n = len(Y) // 4
    for i, w in enumerate(struct.unpack_from("<%dI" % n, bytes(Y[:n * 4]))):
        struct.pack_into("<I", Y, i * 4, w ^ table_offset)
    key = version ^ 0xFF
    for i in range(8, len(Y)):
        Y[i] ^= key
    return X, Y, zlib.decompress(bytes(Y[8:]))


def encrypt_table(plain, table_offset, version=170, X0=None, level=9):
    """plain -> 表区字节 (写到 table_offset 处). X0 = 原表的前 8 字节 (保持 a,b 不变)."""
    C = zlib.compress(plain, level)
    key = version ^ 0xFF
    X = bytearray(TABLE_M)
    if X0 is not None:
        X[0:8] = X0[0:8]
    for i in range(8, 8 + len(C)):
        X[i] = C[i - 8] ^ key ^ ((table_offset >> (8 * (i % 4))) & 0xFF)
    for i in range(8 + len(C), TABLE_M):
        X[i] = key ^ ((table_offset >> (8 * (i % 4))) & 0xFF)
    F = essential_table(bytes(X), inverse=True, X0=X0)
    # 严格写 8+len(C) 字节: 与原版表区长度一致 (不要 4 字节对齐补齐,
    # 否则文件会平白多出 1~3 字节)
    return F[:8 + len(C)], C


# --------------------------------------------------------------------------
# WAR 读写
# --------------------------------------------------------------------------
class War:
    def __init__(self, path):
        self.path = path
        self.blob = bytearray(open(path, "rb").read())
        self.version = W.parse_war_version(bytes(self.blob[:8]))
        self.table_offset = struct.unpack_from("<I", self.blob, 8)[0] ^ TABLE_OFFSET_XOR
        region = bytes(self.blob[self.table_offset:])
        self.X, self.Y, self.table_plain = decrypt_table(region, self.table_offset,
                                                         self.version)
        self.table_plain = bytearray(self.table_plain)
        self.slots = []
        pos = 0
        while pos + ENTRY_NAME_SIZE + 0x18 <= len(self.table_plain):
            chunk = bytes(self.table_plain[pos:pos + ENTRY_NAME_SIZE])
            zero = chunk.find(b"\x00")
            name = chunk if zero < 0 else chunk[:zero]
            off, sc, so, tm, fl = struct.unpack_from("<IIIQI", self.table_plain,
                                                     pos + ENTRY_NAME_SIZE)
            self.slots.append(dict(name_raw=name, tpos=pos, offset=off,
                                   size_comp=sc, size_orig=so, time=tm, flags=fl))
            pos += ENTRY_NAME_SIZE + 0x18

    def find(self, name):
        for s in self.slots:
            if W.safe_name(s["name_raw"]) == name:
                return s
        return None

    def entry_raw(self, s):
        return bytes(self.blob[s["offset"]:s["offset"] + s["size_comp"]])

    def write_entry(self, s, head, raw):
        self.blob[s["offset"]:s["offset"] + len(head) + len(raw)] = head + raw

    def set_size_orig(self, s, so):
        struct.pack_into("<I", self.table_plain, s["tpos"] + ENTRY_NAME_SIZE + 8, so)

    def set_size_comp(self, s, sc):
        struct.pack_into("<I", self.table_plain, s["tpos"] + ENTRY_NAME_SIZE + 4, sc)

    def save(self, out_path):
        region, _ = encrypt_table(bytes(self.table_plain), self.table_offset,
                                  self.version, X0=self.X[:8])
        old_len = len(self.blob) - self.table_offset
        del self.blob[self.table_offset:]
        self.blob += region
        with open(out_path, "wb") as f:
            f.write(bytes(self.blob))
        return old_len, len(region)


# --------------------------------------------------------------------------
# pos1 清单
# --------------------------------------------------------------------------
def load_pos1():
    p = os.path.join(HERE, "pos1_rows.pkl")
    if not os.path.exists(p):
        return {}
    rows = pickle.load(open(p, "rb"))
    return {r["name"]: min(r["hits"]) for r in rows if r["hits"]}


# --------------------------------------------------------------------------
# 长度对齐: 让 zlib 输出长度和头部与原版一致
# --------------------------------------------------------------------------
def fit_compress(plain, target_len, want_head2, tail_marker=b"\r\n;"):
    """找 zlib 参数 + 填充, 使 len(z)==target_len 且 z[0:2]==want_head2."""
    rnd = random.Random(12345)
    # 先试纯 level
    for level in (9, 6, 1):
        z = zlib.compress(plain, level)
        if z[0:2] == want_head2 and len(z) == target_len:
            return z, level, 0, plain
    # 用不可压缩填充微调 (脚本文件里 ';' 开头是注释行, 安全)
    pad_chars = []
    for i in range(900):
        pad_chars.append(b"%02X" % rnd.randrange(256))
    for level in (9, 6, 1):
        base = zlib.compress(plain, level)
        if base[0:2] != want_head2:
            continue
        prev = len(base)
        if prev > target_len:
            continue
        for k in range(1, len(pad_chars) + 1):
            full = plain + tail_marker + b"".join(pad_chars[:k]) + b"\r\n"
            z = zlib.compress(full, level)
            if len(z) == target_len:
                return z, level, k, full
            if len(z) > target_len:
                break
    return None, None, None, None


# --------------------------------------------------------------------------
def selftest():
    """加密方向自测: essential_encrypt(essential_decrypt(raw)) == raw"""
    pos1 = load_pos1()
    ok = fail = skip = 0
    for war in ("CHOSAIMIN_S.WAR", "CHOSAIMIN_T.WAR"):
        w = War(os.path.join(ORIG, war))
        for s in w.slots:
            nm = W.safe_name(s["name_raw"])
            if nm not in pos1 or s["size_comp"] < 8 + 108:
                skip += 1
                continue
            raw = w.entry_raw(s)[8:]
            A = essential_decrypt(raw, pos1[nm])
            raw2 = essential_encrypt(A, pos1[nm])
            if raw2 == raw:
                ok += 1
            else:
                fail += 1
                if fail <= 3:
                    d = [i for i in range(len(raw)) if raw2[i] != raw[i]]
                    print("  FAIL %s 首差 @%d/%d" % (nm, d[0], len(d)))
    print("essential 往返: ok=%d fail=%d skip=%d" % (ok, fail, skip))

    # 表往返
    for war in ("CHOSAIMIN_S.WAR", "CHOSAIMIN_T.WAR"):
        w = War(os.path.join(ORIG, war))
        region = bytes(w.blob[w.table_offset:])
        new_region, C = encrypt_table(bytes(w.table_plain), w.table_offset,
                                      w.version, X0=w.X[:8])
        w2v = W.parse_war_version(bytes(w.blob[:8]))
        X2, Y2, plain2 = decrypt_table(bytes(new_region), w.table_offset, w2v)
        if plain2 == bytes(w.table_plain):
            print("表往返 %s: OK (原 %d 字节 -> 新 %d 字节)" %
                  (war, len(region), len(new_region)))
        else:
            print("表往返 %s: FAIL (plain %d vs %d)" %
                  (war, len(bytes(w.table_plain)), len(plain2)))
    return ok, fail


def info(war, name):
    pos1 = load_pos1()
    w = War(os.path.join(ORIG, war))
    s = w.find(name)
    if s is None:
        print("未找到", name)
        return
    raw = w.entry_raw(s)[8:]
    head = w.entry_raw(s)[:8]
    print("条目: %s  offset=0x%X size_comp=%d size_orig=%d flags=0x%08X" %
          (name, s["offset"], s["size_comp"], s["size_orig"], s["flags"]))
    print("head:", head.hex(" "), " L(data)=%d" % len(raw))
    if name not in pos1:
        print("无 pos1 真值, 无法重封")
        return
    A = essential_decrypt(raw, pos1[name])
    plain = ypk_decompress(saimin_crypt(A))
    print("pos1=%d  解压=%d 字节 (size_orig=%d) %s" %
          (pos1[name], len(plain), s["size_orig"],
           "OK" if len(plain) == s["size_orig"] else "MISMATCH"))
    z = ypk_mask(saimin_crypt(A))
    print("原 zlib 头: %s  压缩长度=%d" % (z[:4].hex(" "), len(z)))
    for level in (9, 6, 1):
        zz = zlib.compress(plain, level)
        print("   python level=%d -> len=%d head=%s" % (level, len(zz), zz[:2].hex()))


def patch(war, name, newfile, out_path):
    pos1 = load_pos1()
    w = War(os.path.join(ORIG, war))
    s = w.find(name)
    if s is None:
        print("未找到", name)
        return 1
    if name not in pos1:
        print("无 pos1 真值")
        return 1
    raw = w.entry_raw(s)[8:]
    A = essential_decrypt(raw, pos1[name])
    z_orig = ypk_mask(saimin_crypt(A))
    target = len(z_orig)
    want_head2 = z_orig[:2]
    plain_new = open(newfile, "rb").read()
    print("目标压缩长度=%d  zlib 头=%s  新明文=%d 字节 (原 %d)" %
          (target, want_head2.hex(), len(plain_new), s["size_orig"]))
    z, level, k, plain_full = fit_compress(plain_new, target, want_head2)
    if z is None:
        print("无法对齐压缩长度")
        return 1
    print("对齐成功: level=%d 填充=%d 段 -> 压缩长度=%d 头=%s  明文 %d->%d" %
          (level, k, len(z), z[:2].hex(), len(plain_new), len(plain_full)))
    A_new = saimin_crypt(ypk_mask(z))
    raw_new = essential_encrypt(A_new, pos1[name])
    if len(raw_new) != len(raw):
        print("raw 长度不符")
        return 1
    head = make_head(len(plain_full), w.entry_raw(s)[3])
    w.write_entry(s, head, raw_new)
    w.set_size_orig(s, len(plain_full))
    old_len, new_len = w.save(out_path)
    print("表区: %d -> %d 字节" % (old_len, new_len))
    print("已写出:", out_path)
    # 立即复验
    w2 = War(out_path)
    s2 = w2.find(name)
    got = decrypt_entry(w2.entry_raw(s2)[8:], pos1[name])
    print("复验解压=%d 字节, 与目标 %s" %
          (len(got), "一致" if got == plain_full else "不一致!!"))
    # 其余条目随机抽查, 确认没被破坏
    bad = []
    for s3 in w2.slots:
        nm3 = W.safe_name(s3["name_raw"])
        if nm3 == name or nm3 not in pos1 or s3["size_comp"] < 8 + 108:
            continue
        try:
            g = decrypt_entry(w2.entry_raw(s3)[8:], pos1[nm3])
            if len(g) != s3["size_orig"]:
                bad.append(nm3)
        except Exception:
            bad.append(nm3)
    print("其余条目抽查: %d 个, 异常 %d 个 %s" %
          (sum(1 for s3 in w2.slots
               if W.safe_name(s3["name_raw"]) in pos1
               and s3["size_comp"] >= 8 + 108) - 1, len(bad), bad[:5]))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "selftest":
        selftest()
    elif cmd == "info":
        info(sys.argv[2], sys.argv[3])
    elif cmd == "patch":
        sys.exit(patch(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]))
    else:
        print(__doc__)
