# 超催眠術学園 AI汉化工程

这个仓库放的是《超催眠術学園》(ShiinaRio v2.50) 汉化工程的**文本资产、工具和方法论**。
不含游戏二进制、音频、图像资源。

工程状态：**已收尾（2026-10-15）**。脚本文本、编译脚本可见串、标题与系统 UI 图像三条线都做完了，验证过。

想直接看经验的，去读 `docs/方法论_ShiinaRio引擎汉化实战.md`。那份文档是写给接手同类引擎的人看的，
坑和方法都在里面，跟这个具体游戏关系不大。

## 目录

```
docs/
  方法论_ShiinaRio引擎汉化实战.md   面向他人的经验总结，建议先读这篇
  格式速查_WAR容器与S25图像包.md    纯技术规格：容器结构、S25 行编码、两条硬约束
  交接文档.md                       总交接文档：加密体系、工具链、踩坑清单、原版与汉化版差异清单
  排版崩字_*.md                     三篇取证：静态定案、运行时取证、反编译收口
  接手准备_未完成内容清点_20261015.md
  翻译进度交接_20261014.md

tools/
  文末有工具表，核心是 warc_pack / s25 / fitlib 加译文流水线
  example_quickstart.py            最小可跑示例：开 WAR、爆破 pos1、打印明文头
```

第一次上手的话，按这个顺序读：格式速查 → example_quickstart.py → 方法论。

`_x1` 这个后缀是为了避开另一位协作 AI 的 `cn_<ENTRY>_N.tsv` 命名，防止互相覆盖，没有别的含义。

## 完成到哪一步

| 面 | 状态 |
|---|---|
| 脚本文本（T 包 SCN，48501 行 / 112 条目） | 完成 |
| 编译脚本可见串（S 包 SRC_MAIN 14 对选项、START 4 条） | 完成 |
| UI 图像（D 包 TITLE 30 按钮 + SYSTEM/EXBGM/EX 115 槽） | 完成 |
| 显示层（EXE 的 charset / SJIS 解码边界 / 字体名） | 完成，见 `tools/patch_exe_cn.py` |
| 补丁形态 | 4 个文件覆盖 + 4 个新增文件，见交接文档 §33.2 |

没做的：MAP/EX 人物介绍卡的段落文本、OGGTBL/VOITBL 换路径解密（纯定性用途）。
这两项对玩家可见面没有影响，判断下来不值得投入。

HP 包（回想模式人物立绘，284 张 S25）后来补做了抽查：全是立绘、零文字，不需要汉化，但运行时要加载，不能删。

## 术语与口癖

完整版在私有工程目录的交接文档 §28，公开版只留几条不涉及成人内容的：

- 光ヶ丘様 → MRK 线「光丘大人」/ SKR 线「光丘」
- 茉莉花：`ですわ`→呢；佳澄的乱语段落用「窝 / 的说」；会长樱的乱语不造方言，只保留断续

硬约束一条：译文只能用 GBK 一级区字（首字节 ≤ 0xD7）。二级区字会落表错位显示成别的字，
真机上撞到过一次，排查了很久才发现是字库区的问题。各 patch 脚本里都内置了断言。

## 复现流程

```bash
# 环境用 venv Python，需要 numpy/scipy/PIL
# 工程路径：J:/SR Game/超催眠術学園/_汉化工程

python tools/_check_tsv.py work/cn_<ENTRY>_x1.tsv      # 译文自检
python tools/fill_cn.py work/cn_<ENTRY>_x1.tsv         # 回填 jsonl
python -u tools/trans_rebuild.py --strip-comments --apply   # 重建 WAR
python tools/_verify_entries.py                        # 必跑：查脚本最长行，不查会被打崩

python tools/_sys_cn.py      # UI 图像 Stage A：擦除重画
python tools/_sys_pack.py    # UI 图像 Stage B：fit 等长回封，必须全量跑
```

`_sys_pack.py` 有个坑：单包模式会吞掉其他包已部署的改动。跑过 `python _sys_pack.py EX` 之后必须再全量跑一次。

## 工具

| 脚本 | 用途 |
|---|---|
| `warc_pack.py` | WAR 容器读写、essential crypt 加解、表区重建 |
| `crack_all.py` | 全条目 pos1 批量破解 |
| `s25.py` | S25 图像包解码、编码、行共享重编码 |
| `fitlib.py` | `fit_compress2` 精确长度对齐，等长铁律靠它 |
| `export_todo.py` / `fill_cn.py` / `trans_rebuild.py` | 译文流水线 |
| `_check_tsv.py` | 译文自检：行覆盖、非 GBK、0x5C、竖线 |
| `_verify_entries.py` | 全条目体检 + 脚本最长行 |
| `_spot_check.py` | 按行号读 WAR 内明文，目验用 |
| `inv_d_s25.py` | S25 全槽解码落盘 |
| `_sys_cn.py` / `_sys_pack.py` | UI 图像汉化的 A/B 两段 |
| `_srcmain_patch.py` / `_start_patch.py` | 编译脚本内可见串的等字数替换 |
| `patch_exe_cn.py` | 显示层 EXE 补丁：18 字节 / 6 处，带原字节校验与 `--revert` |

## 上传时的注意

见交接文档 §31。不要传 `CHOSAIMIN_*.WAR`、`CHOSAIMIN.EXE`、`*.crash.dmp`、
`extracted_crack/`、`extracted/`、音视频资源。`.gitignore` 已经排掉了。

## 关于版权

`tools/` 下的脚本和 `docs/` 下的技术规格、方法论用 MIT 许可，见 LICENSE。

`tools/patch_exe_cn.py` 是对游戏主程序做字节修改的补丁脚本，里面只有偏移和字节值，不含任何游戏代码。
发它是因为"该改哪几处"才是真正费功夫的部分，而这部分靠方法描述很难传达。
**仅供技术研究，请支持正版。** 用它之前请确认你拥有该软件的合法副本。

公开版**不含译文**。译文是原作文本的演绎作品，权利归原著作权人，留档在私有工程目录里。

成人向术语表（性器官与性行为词汇）和成人剧情摘要同样已从公开版移除，
只保留技术内容：容器与图像格式、工具链、方法论。

仓库里也没有任何日文原文、游戏二进制、音频或图像资源。
权利人不希望相关内容出现在这里的话，提 issue 即可，我会移除。

## 三条遗留风险

1. GBK 二级区字永远不能进译文，会落表错位。
2. S25 条目尺寸一变，引擎就弹 `Not File Type` 或 `@gload`。改 D 包任何条目都必须 fit 等长回封。
3. `fitlib.HEX_MAX` 已经从 120000 放到 2000000（EX 的大缺口需要）。回滚旧版 fitlib 会让 EX 重封失败。
