# -*- coding: utf-8 -*-
"""导出指定条目的未译行 (line|kind|jp)。

用法:
  python tools/export_todo.py KRM02.TXT [更多条目...]   # 导出 todo
  python tools/export_todo.py --status                  # 全局剩余结算表
输出: work/todo_<entry>.txt
过滤: 已有 cn / 纯符号数字 / 命令行 / 注释行(kind=command,comment)
排除: work/identical_cn.txt 登记的「中日同形」行 (entry|line)
注意: H 行一律导出并按精翻口径处理(中性化只作露骨兜底)
"""
import json, os, re, sys, glob

jpch = re.compile(r'[぀-ヿ一-鿿]')
SKIP_KIND = {'command', 'comment'}

IDENT = set()
_p = 'work/identical_cn.txt'
if os.path.exists(_p):
    for ln in open(_p, encoding='utf-8'):
        ln = ln.strip()
        if ln and not ln.startswith('#'):
            IDENT.add(ln)


def load(entry):
    p = f'trans/text/CHOSAIMIN_T__{entry}.jsonl'
    if not os.path.exists(p):
        print(f'!! 找不到 {p}')
        return []
    out = []
    for raw in open(p, encoding='utf-8'):
        raw = raw.strip()
        if not raw:
            continue
        out.append(json.loads(raw))
    return out


def todo_rows(entry, recs=None):
    """返回该条目的未译行 [(line, kind, jp)]"""
    if recs is None:
        recs = load(entry)
    rows = []
    for r in recs:
        jp = r.get('jp', '')
        if not jpch.search(jp):
            continue
        if r.get('kind') in SKIP_KIND:
            continue
        cn = r.get('cn')
        if f'{entry}|{r["line"]}' in IDENT:      # 已登记为中日同形 -> 视为完成
            continue
        if cn and cn != jp and '需要审核' not in cn:
            continue
        if r.get('kind') == 'name' and cn:       # 人名标签 cn 已填 -> 完成
            continue
        rows.append((r['line'], r.get('kind'), jp))
    rows.sort()
    return rows


def main(entries):
    for e in entries:
        rows = todo_rows(e)
        path = f'work/todo_{e}.txt'
        with open(path, 'w', encoding='utf-8') as f:
            for l, k, j in rows:
                f.write(f"{l}|{k}|{j}\n")
        print(f'{e}: 未译 {len(rows)} 行 -> {path}')


def status():
    rows = []
    tot_all = 0
    files = sorted(glob.glob('trans/text/*.jsonl'))
    for p in files:
        e = os.path.basename(p)[len('CHOSAIMIN_T__'):-6]
        recs = load(e)
        tot = sum(1 for r in recs
                  if jpch.search(r.get('jp') or '')
                  and r.get('kind') not in SKIP_KIND)
        rm = len(todo_rows(e, recs))
        tot_all += tot
        if rm:
            rows.append((rm, tot, e))
    rows.sort(reverse=True)
    print(f'应译合计 {tot_all} 行 | 剩余 {sum(r[0] for r in rows)} 行 '
          f'| 未完成条目 {len(rows)} | 已清零 {len(files) - len(rows)}')
    print('--- 剩余明细 ---')
    for rm, tt, e in rows:
        print(f'{e:18s} {rm:5d}/{tt:5d}')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--status':
        status()
    else:
        main(a)
