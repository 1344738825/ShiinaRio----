# -*- coding: utf-8 -*-
"""_sys_cn.py Stage A -- SYSTEM/EXBGM/EX 按钮词中文重渲染 (只出 PNG, 不回封)

清单来自触表目验 (2026-10-15, 全部槽位逐张核实):
  SYSTEM 032-034 いいえ/035-037 はい/039 ゲームを終します/040 タイトルに戻ります/
  041 初期設定に戻します/047-049 セーブ/050-052 ロード/053-055 オプション/056-058 タイトル/
  059-061 終わる/062-064 閉じる/065-067 ヘルプ/071-073,078-081 戻る/102-104 システム/
  105-107 テキスト/108-110 サウンド/111-113 初期設定に戻す/150-161 自分で選択+各自動選択/
  162-167 口内を自動選択/168-170 既読/171-173 全て/174-176 解除/177-179 継続/
  180-182 装飾なし/183-185 影つき/186-188 縁取り/478-480 ノーマル/481-483 クイック/484-487 オート
  EXBGM 007-008 戻る/012-014 ボーカル;  EX 002-004 戻る(横)/014-016 戻る(竖)/017-019 CG鑑賞(竖)/020-022 シーン鑑賞(竖)
样式: 近白字(254,253,252) + 黑投影(alpha .6, 偏移2,2) —— TITLE 真机验证过的同款
"""
import os, sys, glob
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.interpolate import PchipInterpolator
from scipy.ndimage import binary_dilation

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.join(HERE, "..", "work", "s25_inv")
OUT = os.path.join(HERE, "..", "work", "sys_cn")
os.makedirs(OUT, exist_ok=True)

FONT_PATH = r"C:\Windows\Fonts\msyhbd.ttc"
GLYPH_RGB = (254, 253, 252)
SHADOW_ALPHA, SDY, SDX = 0.6, 2, 2

R = lambda *sl: [(f, t) for f, t in sl]  # noqa

# (slot, 中文)  -- 三风格连号直接展开
def trip(a, b, c=None):
    c = c if c is not None else b
    return [(a, b), (a + 1, c), (a + 2, c)]

JOBS = {
    "SYSTEM": (
        trip(32, "否") + trip(35, "是")
        + [(39, "结束游戏"), (40, "返回标题"), (41, "恢复初始设置")]
        + [(47, "存档"), (48, "存档"), (49, "存档")]
        + trip(50, "读档") + trip(53, "选项设置") + trip(56, "标题画面")
        + trip(59, "结束") + trip(62, "关闭") + trip(65, "帮助")
        + trip(71, "返回") + [(78, "返回"), (79, "返回"), (80, "返回"), (81, "返回")]
        + trip(102, "系统") + trip(105, "文本") + trip(108, "音效")
        + trip(111, "恢复初始设置")
        + trip(150, "自行选择") + trip(153, "自动选择射在里面") + trip(156, "自动选择射在身上")
        + trip(159, "自行选择") + trip(162, "自动选择射在口中") + trip(165, "自动选择射在口中")
        + trip(168, "已读") + trip(171, "全部") + trip(174, "解除") + trip(177, "继续")
        + trip(180, "无装饰") + trip(183, "带阴影") + trip(186, "描边")
        + trip(478, "普通") + trip(481, "快速") + trip(484, "自动") + [(487, "自动")]
    ),
    "EXBGM": [(7, "返回"), (8, "返回"), (12, "人声"), (13, "人声"), (14, "人声")],
    "EX": [(2, "返回"), (3, "返回"), (4, "返回"),
           (14, "返回"), (15, "返回"), (16, "返回"),
           (17, "CG鉴赏"), (18, "CG鉴赏"), (19, "CG鉴赏"),
           (20, "场景鉴赏"), (21, "场景鉴赏"), (22, "场景鉴赏")],
}
VERTICAL = {("EX", i) for i in (14, 15, 16, 17, 18, 19, 20, 21, 22)}


def rebuild_bg(a, t_dev=8, t_dark=6):
    """泛化版擦除 v2: 带域全域化 (小按钮字占比高, 原带域阈值漏字);
    行内锚点枯竭时用上下最近干净行纵向插值兜底 (按钮底是垂直渐变, 纵向插值安全)"""
    h, w = a.shape[:2]
    t0, t1 = int(h * 0.056), int(h * 0.24)
    b0, b1 = int(h * 0.83), int(h * 0.945)
    vals = a[:, :, :3].mean(axis=2)
    alpha = a[:, :, 3]
    band_top = vals[t0:t1].mean(axis=0)
    band_bot = vals[b0:b1].mean(axis=0)
    tt = np.clip((np.arange(h) - t0) / float(b0 - t0), 0, 1)[:, None]
    ref = band_top[None, :] * (1 - tt) + band_bot[None, :] * tt
    dev = np.abs(vals - ref)
    dark = ref - vals
    band = np.zeros(vals.shape, bool)
    band[1:h - 1, :] = True                      # 全域化 (原: 只盖中段)
    op = alpha >= 100                            # 含半透明阴影边缘 (alpha~153), 否则残迹
    txt = ((dev > 25) & band & op) | ((dev > t_dev) & band & op) | ((dark > t_dark) & band & op)
    txt = binary_dilation(txt, iterations=1) & band & op
    free = (~txt) & (dev <= t_dev) & (alpha >= 250) & band
    new = a.copy()
    clean_rows = np.nonzero((~txt).all(axis=1) & (alpha >= 250).all(axis=1))[0]
    for y in np.nonzero(txt.any(axis=1))[0]:
        fx = np.nonzero(free[y])[0]
        tx = np.nonzero(txt[y])[0]
        if len(fx) >= 8:
            for c in range(3):
                pch = PchipInterpolator(fx, a[y, fx, c].astype(np.float64))
                new[y, tx, c] = np.round(np.clip(pch(tx), 0, 255))
            new[y, tx, 3] = 255                  # 擦除区 alpha 归实底 (半透明残影根除)
            continue
        # 锚点枯竭行: 纵向插值兜底
        up = clean_rows[clean_rows < y]
        dn = clean_rows[clean_rows > y]
        if len(up) == 0 or len(dn) == 0:
            continue
        yu, yd = up[-1], dn[0]
        t = (y - yu) / float(yd - yu)
        for c in range(3):
            col = a[yu, :, c].astype(np.float64) * (1 - t) + a[yd, :, c].astype(np.float64) * t
            new[y, tx, c] = np.round(np.clip(col[tx], 0, 255))
    return new, txt


def rebuild_vtxt(a):
    """竖排标签专用擦除: 文字占满全高, 水平参考带失效 → 白字直接按亮度阈值判定
    (气泡深底均匀, 白字亮度远高于底), 横向 PCHIP 锚点取字两侧底色"""
    h, w = a.shape[:2]
    vals = a[:, :, :3].mean(axis=2)
    alpha = a[:, :, 3]
    op = alpha >= 100
    base = np.median(vals[op])
    txt = (vals > base + 25) & op
    txt = binary_dilation(txt, iterations=2)
    free = (~txt) & op
    new = a.copy()
    for y in np.nonzero(txt.any(axis=1))[0]:
        fx = np.nonzero(free[y])[0]
        tx = np.nonzero(txt[y])[0]
        if len(fx) < 8 or len(tx) == 0:
            continue
        for c in range(3):
            pch = PchipInterpolator(fx, a[y, fx, c].astype(np.float64))
            new[y, tx, c] = np.round(np.clip(pch(tx), 0, 255))
        new[y, tx, 3] = 255
    return new, txt


def draw_text(w, h, text, vertical, fsize):
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(FONT_PATH, fsize)
    if vertical:
        n = len(text)
        step = h / (n + 0.6)
        for k, ch in enumerate(text):
            d.text((w / 2.0, step * (k + 0.8)), ch, font=font, fill=255, anchor="mm")
    else:
        d.text((w / 2.0, h / 2.0), text, font=font, fill=255, anchor="mm")
    return np.asarray(im) > 128


def draw_outline_text(w, h, text, fsize):
    """消息条样式: 黑字 + 白描边 (原版 039-041 实测风格)"""
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(FONT_PATH, fsize)
    d.text((w / 2.0, h / 2.0), text, font=font, fill=255, anchor="mm")
    return np.asarray(im) > 128


def process(base, slot, text):
    src = os.path.join(INV, "%s_%03d.png" % (base, slot))
    rgba = np.asarray(Image.open(src).convert("RGBA")).astype(np.int32)
    h, w = rgba.shape[:2]
    vertical = (base, slot) in VERTICAL
    transparent = rgba[:, :, 3].mean() < 200      # 按钮底 alpha 恒 255; 消息条 <200
    out = rgba.astype(np.float64).copy()
    if transparent:
        # 消息条 (黑字白描边): 整幅清透明后重画
        out[:, :, :] = 0
        fsize = max(12, int(min(h * 0.72, w * 0.9 / max(len(text), 1))))
        m = draw_text(w, h, text, False, fsize)
        ring = binary_dilation(m, iterations=2) & ~m          # 白描边
        out[ring, :3] = 245
        out[m, :3] = 22                                        # 黑色主体
        out[m | ring, 3] = 255                                 # ★ 别忘 alpha
        txt_zone = m | ring
    else:
        if vertical:
            bg, txt_zone = rebuild_vtxt(rgba)   # 竖排: 文字占满全高, 水平带插值失效
        else:
            bg, txt_zone = rebuild_bg(rgba)
            bg, t2 = rebuild_bg(bg, t_dev=5, t_dark=4)   # 二遍低阈: bronze 亮底低对比残片
            txt_zone = txt_zone | t2
        out = bg.astype(np.float64)
        if vertical:
            fsize = max(10, int(min(w * 0.5, h / (len(text) + 0.6) * 0.85)))
        else:
            fsize = max(12, int(min(h * 0.55, w * 0.9 / max(len(text), 1))))
        m = draw_text(w, h, text, vertical, fsize)
    shadow = np.roll(np.roll(m, SDY, axis=0), SDX, axis=1) & ~m
    out[shadow, :3] *= (1.0 - SHADOW_ALPHA)
    out[m, :3] = GLYPH_RGB
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")
    dst = os.path.join(OUT, "%s_%03d.png" % (base, slot))
    img.save(dst)
    return dst, w, h, transparent, vertical


def main():
    n = 0
    fails = []
    for base, jobs in JOBS.items():
        for slot, text in jobs:
            try:
                dst, w, h, tr, vt = process(base, slot, text)
                n += 1
                print("%-7s #%-3d %3dx%-3d %s%s -> %s" % (base, slot, w, h,
                      "透" if tr else "  ", "竖" if vt else "  ", text))
            except Exception as e:
                fails.append((base, slot, text, str(e)))
                print("%-7s #%-3d FAIL %s: %s" % (base, slot, text, e))
    print("\n完成 %d 张, 失败 %d" % (n, len(fails)))
    # 拼验收触表
    files = sorted(glob.glob(os.path.join(OUT, "*.png")))
    TW, TH, COLS = 200, 120, 7
    rows = (len(files) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * TW, rows * TH), (40, 44, 52))
    d = ImageDraw.Draw(sheet)
    for i, f in enumerate(files):
        x, y = (i % COLS) * TW, (i // COLS) * TH
        im = Image.open(f).convert("RGBA")
        im.thumbnail((TW - 8, TH - 22))
        bg = Image.new("RGBA", (TW - 8, TH - 22), (70, 74, 84, 255))
        bg.paste(im, ((TW - 8 - im.width) // 2, (TH - 22 - im.height) // 2), im)
        sheet.paste(bg.convert("RGB"), (x + 4, y + 18))
        d.text((x + 6, y + 3), os.path.basename(f), fill=(255, 220, 120))
    sp = os.path.join(OUT, "_check.png")
    sheet.save(sp)
    print("验收触表:", sp)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
