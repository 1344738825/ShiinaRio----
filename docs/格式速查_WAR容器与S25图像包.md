# 格式速查：WAR 容器与 S25 图像包

这份是纯技术规格，不含任何游戏内容。写它纯粹是因为这两层格式没有公开文档，
只能从 `arc_unpacker` 的 C++ 解码器（`src/dec/shiina_rio/`）和我们自己的逆向结果拼出来。
如果你在做同引擎的游戏，这份应该能直接省掉几天的解析工作。

---

## 1. WAR 容器

```
表区：条目记录（含 name_raw、size_comp、size_orig、offset 等）
条目区：每条目前 8 字节头 + 加密载荷
```

要点：

- 条目**可以重名**，同一资源常有大小两份（小号那份往往是哑块或影子）。按槽位序号索引，别按名字。
- 表区长度允许增长（我们这次 1089 → 1090），但**没动过的条目必须逐字节全等**，这是验收的硬标准。
- 每条目有独立的 `pos1`（0..63）参与解密。爆破方式：

```python
for c in range(64):
    try: plain = decrypt_entry(raw, c)
    except Exception: continue
    if plain[:4] == b"S25\x00":  # 用目标格式的 magic 校验
        pos1 = c; break
```

  只有 magic 不够，要再加尺寸校验（`len(plain) == size_orig`），否则会误命中。

- 加密链路：`essential_decrypt(raw, pos1)` → `ypk_mask` → `saimin_crypt`，
  写回时反向：`saimin_crypt(ypk_mask(z))` → `essential_encrypt(..., pos1)`。
  具体实现见 `tools/warc_pack.py`。

---

## 2. S25 图像包

```
"S25\0"
u32 file_count
u32 offsets[file_count]           # 为 0 的槽位跳过
每个 offset 处:
    u32 width; u32 height; 8 字节跳空; u32 flags;
    u32 row_offsets[height]       # 绝对文件偏移，直接 seek 用
    行数据: [u16 row_size][row_size 字节载荷]
```

行载荷 token：`u16 tmp` → `method = tmp >> 13`，`skip = (tmp >> 11) & 3`，`count = tmp & 0x7FF`
（**count 为 0 时再读一个 u32**）。

| method | 含义 | 载荷 | 存储序 |
|---|---|---|---|
| 0 / 1 | 空（透明黑），跳过 count 像素 | — | — |
| 2 | RGB 增量，周期 3 累计 | 3×count | R,G,B → 输出 B,G,R,A=255 |
| 3 | RGB 单色重复 | 3 字节 | 同色 count 次 |
| 4 | BGRA 增量，周期 4 累计 | 4×count | **A,B,G,R** → 输出 B,G,R,A |
| 5 | 单色重复 | 4 字节 | **A,B,G,R**，同色 count 次 |

`flags & 0x80000000` 表示 incremental 模式，此时 `decode_row` 的 repeat
等于共享同一行偏移的条目数（按绝对偏移计数）。

### 两条硬约束，写编码器时最容易错

1. `read_row` 按**绝对行偏移的奇偶**决定是否跳过 1 字节（`row_size--`）。
   所以编码时必须保证**所有绝对行偏移是偶数**，否则解出来整行错位。
2. `decode_row` 在每个 token 前执行 `if (pos & 1) skip(1)`，
   也就是说 token 必须起始于**行载荷内**的偶数偏移。
   method 4/5 的 token 长度恒为偶数，天然满足；method 2/3 需要补位。

我们第一次写编码器时错的三件事，都在这两条附近：
行偏移写成了相对值（应为绝对）、漏写 `u16 row_size` 前缀、
method 4 的通道序写成 B,G,R,A（应为 A,B,G,R）。

### 行共享

多个条目可以共享同一行数据（incremental 模式下按绝对行偏移计数）。
重编码时如果保留共享，体积能省很多：这次 SYSTEM 包 14865 行被引用，省了 4260644 字节。
`tools/s25.py` 的 `encode_partial(..., share=True)` 就是干这个的。

---

## 3. SCN 编译脚本

编译后的脚本，内部是 VM 字节码加绝对偏移。改文本必须保证**明文长度逐字节不变**，
否则偏移整体错位。长度对齐用 `tools/fitlib.py` 的 `fit_compress2`，原理见方法论 §2。

UI 相关的可见串（选项文本、错误提示）散落在字节码里，可以用假名正则扫描定位，
然后做等长替换。注意字数必须和原文一致，引擎按整串宽度算居中，补空格会让显示偏移。

---

## 4. 怎么确认你手上是不是同一套格式

拿一个条目解密后看前 4 字节：

- `S25\0` → 图像包，按第 2 节解析
- 明文里能读到脚本 opcode 结构 → SCN，按第 3 节
- 全是可读日文文本 → `.TXT`，直接按行处理，最省事

如果 64 个 pos1 全解不动，大概率是哑块（纯色占位图、dummy 音频、前缀影子条目），别在上面耗时间。
我们这次 48 个条目里 11 个解不出，全是哑块。
