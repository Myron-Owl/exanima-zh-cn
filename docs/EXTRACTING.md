# 重新提取游戏原文索引

常规编译使用仓库内的 `data/catalog/`，无需每次读取游戏。仅在核对原文或重新审核提取结果时运行这些工具。导出仅写入 `build/catalog/`，目录不存在时自动创建，不覆盖 `data/catalog/` 或人工译文。

## 本地游戏校验

四个工具都要求显式传入 `--game-dir`，不设默认游戏目录，不自动搜索安装位置。游戏目录只读，任何工具开始导出前都必须找到以下两个原版文件，并校验 SHA256：

| 文件 | Exanima 0.9.5.2 原版 SHA256 |
| --- | --- |
| `Exanima.exe` | `97a83509f1e230349126817adb8576a7725bceda120023f1173bb463b46cba6a` |
| `Resource.rpk` | `e32dbf99663d648848a1dff3c777fc9a5a32d17c20576a7df69cfd60b39b751a` |

优先使用正式文件名。如果文件缺失或哈希不符，则尝试同目录下的 `Exanima.exe.exanima-zh-original` 或 `Resource.rpk.exanima-zh-original`。备份必须通过同样的原版哈希校验，选中备份时会显示提示。任一文件没有合格候选便停止，不输出索引；Python 优化模式不会跳过版本校验。

## 用法

在源码目录运行，将 `<游戏目录>` 替换为本机实际路径：

```powershell
python -B -X utf8 tools/export_catalog.py --game-dir "<游戏目录>"
python -B -X utf8 tools/export_resource_text.py --game-dir "<游戏目录>"
python -B -X utf8 tools/export_dialogue.py --game-dir "<游戏目录>"
python -B -X utf8 tools/export_maps.py --game-dir "<游戏目录>"
```

四个工具均支持 `--help`，查看帮助无需游戏文件或图像依赖。实际导出会加载共用工具库，需要 Pillow；依赖环境参见 [构建说明](BUILD.md)。

| 工具 | `build/catalog/` 内的输出 |
| --- | --- |
| `export_catalog.py` | `sources.json`、`exe-review.txt` |
| `export_resource_text.py` | `resource-sources.json`、`resource-review.txt`、手册 `.fds` 临时副本 |
| `export_dialogue.py` | `dialogue-sources.json`、`dialogue-review.txt` |
| `export_maps.py` | `map-sources.json`、`map-review.txt`、`map-indexes.json` |

导出结果包含游戏原文，部分工具还会提取手册资源，不应上传整个 `build/`。扫描候选可能包含脚本、内部标识或不可见文本，不能将每一条候选都直接当作玩家正文。审核后按 [译文维护说明](TRANSLATING.md) 更新需要维护的内容。

`tools/exanima_zh.py` 中保留了早期直接修改 EXE、RPK 或原版字体的实验命令；这些命令不属于当前发行流程，不要用于回写游戏。正式汉化构建及打包使用 [构建说明](BUILD.md) 中的入口。
