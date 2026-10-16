# -*- coding: utf-8 -*-
"""fill_cn.py -- 把翻译写回 jsonl. 用法: fill_cn.py <tsv文件> [更多 tsv...]
tsv 每行: <entry>|<line>|<cn>  (cn 内不得含 | ; 用真实 tab 分隔不行就用 | )
校验: GBK 可编码、第二字节非 0x5C、行数不变。"""
import sys, os, json, glob
if len(sys.argv) < 2:
    raise SystemExit('用法: fill_cn.py <tsv文件> [更多 tsv...]')
data = {}
for tsv in sys.argv[1:]:
    for line in open(tsv, encoding='utf-8-sig'):
        line = line.rstrip('\n')
        if not line: continue
        e, l, cn = line.split('|', 2)
        data[(e, int(l))] = cn
# 校验
for (e, l), cn in sorted(data.items()):
    try:
        cn.encode('gbk')            # 严格: 有不可编码字符直接报错
    except UnicodeEncodeError as ex:
        raise SystemExit(f'非 GBK 字符 {ex.object[ex.start]!r} (U+{ord(ex.object[ex.start]):04X}) in {e}:{l}')
    for ch in cn:
        b = ch.encode('gbk')
        if len(b) == 2 and b[1] == 0x5c:
            raise SystemExit(f'0x5C 字符 {ch!r} in {e}:{l}')
# 写回
files = {}
for (e, l), cn in data.items():
    files.setdefault(e, []).append((l, cn))
for e, items in files.items():
    path = f'trans/text/CHOSAIMIN_T__{e}.jsonl'
    lines = open(path, encoding='utf-8-sig').read().splitlines()
    for l, cn in items:
        r = json.loads(lines[l-1])
        assert r['line'] == l, (e, l)
        assert r['kind'] in ('text','name')
        r['cn'] = cn
        lines[l-1] = json.dumps(r, ensure_ascii=False)
    open(path, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines) + '\n')
    print(f'{e}: 回填 {len(items)} 行')
print('OK')
