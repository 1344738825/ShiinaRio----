# -*- coding: utf-8 -*-
"""
crack_all.py - ShiinaRio WARC 1.7 全量条目解密 + 提取 (最终可用版).

用法: python crack_all.py [WAR 文件名...]

流水线 (native 0x4740EC 与 au warc_archive_decoder.cc 双重确认):
    essential -> SaiminCrypt(0x202) -> YPK(zlib)
输出: _汉化工程/extracted_crack/<WAR>/<条目名>
"""
import sys, os, struct, zlib, math

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import saimin_full as SF
import warc_extract as W
from PIL import Image

GAME = r"J:/SR Game/超催眠術学園"
OUT = os.path.join(GAME, "_汉化工程", "extracted_crack")
K = open(os.path.join(HERE, "saimin_keyprobe.bin"), "rb").read()   # VM keystream
LOGO = open(os.path.join(HERE, "reference", "exe_logo.jpg"), "rb").read()
_region = Image.open(os.path.join(HERE, "reference", "exe_image.png")).convert("RGBA")
RB, RW, RH = _region.tobytes("raw", "BGRA"), *_region.size

_CRC_CACHE = {}


def _region_crc(flags, base_color):
    k = (flags, base_color)
    if k not in _CRC_CACHE:
        _CRC_CACHE[k] = SF.region_crc32(RB, RW, RH, flags, base_color)
    return _CRC_CACHE[k]


def essential(data, pos1_delta=0):
    """essential crypt: helper4 (10 keys) + 逐字节 crypt 循环."""
    L = len(data)
    d = bytearray(data)
    keys, flags = SF.get_helper_keys(data, _region_crc)
    for i in range(10):
        off = 4 + 4 * i
        struct.pack_into("<I", d, off, struct.unpack_from("<I", d, off)[0] ^ keys[i])

    lcg = SF.LCG(L)
    v1 = lcg.next_u32()
    idx = int(v1 * (len(LOGO) / 4294967296.0))
    ad1 = SF.get_key_pos_addend1(SF.u32(v1 + LOGO[idx])) & 0x0FFFFFFF
    a = SF.s8(data[0] ^ (L & 0xFF))
    b = SF.s8(data[1] ^ ((L // 2) & 0xFF))
    tmp = SF.get_lcg_xor(float(a)) * 100000000.0
    lcg.reset(SF.u32(v1) ^ SF.u32(int(tmp)))
    tok = 0.0
    if a or b:
        tok = math.acos(a / math.sqrt(a * a + b * b)) / math.pi * 180.0
    if b < 0:
        tok = 360.0 - tok
    ad2 = SF.get_key_pos_addend2(tok, lcg)

    ck = SF.CRYPT_KEY
    klen = len(ck)
    end = min(L, 1024)
    start = 0x80 if end > 0x80 else 0
    p1 = (ad1 + ad2 + pos1_delta) % klen
    p2 = 0
    i = start + 2
    while i < end:
        r = lcg.next_u32() // 16777216
        x = SF.rotr8(d[i] ^ r, 1)
        x ^= ck[p1] ^ ck[p2]
        d[i] = x
        p1 = x % klen
        p2 = (p2 + 1) % klen
        i += 1
    return bytes(d), (ad1 + ad2) % klen


def saimin_crypt(data):
    """SaiminCrypt (ExtraCrypt 0x202): 仅 length >= 0x200 生效."""
    L = len(data)
    if L < 0x200:
        return data
    d = bytearray(data)
    nwin = (L & 0x7E) | 1
    for j in range(nwin):
        d[j] ^= K[j % 0x40]
    struct.pack_into("<I", d, 0x104, struct.unpack_from("<I", d, 0x104)[0] ^ L)
    return bytes(d)


def decrypt_entry(raw, size_orig):
    """返回 (解压后数据, 使用的 delta) 或 (None, None)"""
    for delta in (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5):
        try:
            d, _ = essential(raw, delta)
            out = SF.ypk_decompress(saimin_crypt(d))
            if len(out) == size_orig:
                return out, delta
        except Exception:
            pass
    return None, None


def main(wars):
    os.makedirs(OUT, exist_ok=True)
    total = ok = 0
    failed = []
    for war in wars:
        path = os.path.join(GAME, war)
        if not os.path.exists(path):
            print("跳过 (不存在):", war)
            continue
        odir = os.path.join(OUT, war.replace(".WAR", ""))
        os.makedirs(odir, exist_ok=True)
        f = open(path, "rb")
        wv = W.parse_war_version(f.read(8))
        _, table = W.read_table(f, wv, 0x20)
        ents = W.parse_entries(table, 0x20)
        nok = 0
        for e in ents:
            name = W.safe_name(e["name_raw"])
            if e["size_comp"] < 8:
                continue
            f.seek(e["offset"])
            head = f.read(8)
            raw = f.read(e["size_comp"] - 8)
            h = struct.unpack_from("<I", head, 0)[0]
            so = struct.unpack_from("<I", head, 4)[0]
            tmp = h ^ 0x82AD82 ^ so
            magic = bytes([tmp & 0xFF, (tmp >> 8) & 0xFF, (tmp >> 16) & 0xFF])
            if magic != b"YPK":
                failed.append((war, name, "magic=" + magic.decode("latin1")))
                continue
            total += 1
            out, delta = decrypt_entry(raw, so)
            if out is None:
                failed.append((war, name, "解密失败"))
                continue
            open(os.path.join(odir, name), "wb").write(out)
            ok += 1
            nok += 1
        f.close()
        print("%-18s %3d/%3d" % (war, nok, len(ents)))
    print()
    print("YPK 条目 %d  成功 %d  失败 %d" % (total, ok, len(failed)))
    if failed:
        print("失败清单:")
        for w, n, r in failed:
            print("   %-18s %-16s %s" % (w, n, r))
    print("输出目录:", OUT)


if __name__ == "__main__":
    args = sys.argv[1:] or ["CHOSAIMIN_S.WAR", "CHOSAIMIN_T.WAR"]
    main(args)
