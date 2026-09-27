# 译文维护说明

本目录用于维护 Exanima **0.9.5.2** 的简体中文汉化。日常修改从 [`translations/`](../translations/) 中的编辑源开始，再运行构建生成词典、字体和覆盖包。不要直接把生成文件当作唯一编辑源，否则下次构建会覆盖修改。

源码结构与维护入口见 [源码使用说明](SOURCE_GUIDE.md)。本说明不替代作者的 README、署名或制作时间，也不为源码和译文另行指定许可证。

## 从哪里修改译文

编辑前先在 `translations/` 中搜索现有英文或中文。同一句话可能同时出现在编辑源和生成结果中；先通过下表找到它的来源，再修改来源文件。

### 直接编辑并参与构建的文件

| 文件 | 内容 | 注意事项 |
|---|---|---|
| [`ui.json`](../translations/ui.json) | 设置、操作及部分通用界面文字 | 文件中的旧设置页元数据不是当前发行进度；其中的译文仍参与完整构建，不能当作历史样例移除。 |
| [`runtime_ui.json`](../translations/runtime_ui.json) | 经游戏画面或运行时记录确认的补漏词条 | 用于已经确认的完整源文；修改中文即可，保留匹配原文及来源信息。 |

这两个文件不经过 `compile_*.py` 重新生成。普通译文修改应只调整对应条目的 `zh`。

### 编辑源与生成结果

下表左栏是维护入口，右栏是构建时重新生成的文件。生成结果保留英文、中文及来源信息，适合查阅；修改应回到左栏。

| 编辑源，位于 `translations/` | 生成工具，位于 `tools/` | 生成结果，位于 `translations/` |
|---|---|---|
| `ui_core.json` | `compile_core.py` | `ui-expanded.json` |
| `skills_terms.json` | `compile_core.py` | `skills.json` |
| `arena_terms.json` | `compile_core.py` | `arena.json` |
| `content_by_id.json` | `compile_core.py` | `content.json` |
| `item_descriptions_by_id.json` | `compile_core.py` | `item-descriptions.json` |
| `powers_terms.json` | `compile_core.py` | `powers.json` |
| `narrator_by_id.json` | `compile_core.py` | `narrator.json` |
| `manual_terms.json` | `compile_core.py` | `manual.json` |
| `item_names.json` | `compile_item_names.py` | `items.json` |
| `ui_supplement_terms.json` | `compile_ui_supplement.py` | `ui-supplement.json` |
| `manual_terms.json` 与 `manual_controller_terms.json` | `compile_controller_manual.py` | `manual-controller.json` |
| `maps_by_id.json` | `compile_maps.py` | `maps.json`，含已知性别变量的展开文本 |
| `dialogue_by_offset.json` | `compile_runtime.py` | `dialogue.json` |
| `item_grammar.json`、`message_templates.json`、`item_names.json`，以及生成的 `item-descriptions.json` | `compile_runtime.py` | `runtime_generated.json` |

`*_terms.json` 和 `item_names.json` 通常采用“英文原文 → 中文译文”映射。`*_by_id.json` 与 `dialogue_by_offset.json` 采用“原始记录标识或位置 → 中文译文”映射；可以在对应的生成结果中查找该条的完整英文。不要为了调整译文更改记录标识或位置。

`manual_terms.json` 按章节保存替换段落。修改其中的中文即可；英文段落必须继续与该版本原文精确匹配。手柄教程复用相同段落，再应用 `manual_controller_terms.json` 中的差异译文，因此修改通用教程段落后也要检查手柄教程。

部分重复原文会合并为一个运行时词条。若同一英文在多个来源中的中文不一致，构建可能报告语境冲突；应先核对实际含义，不能只为消除报错而任选一个译法。

## 动态文本的维护位置

物品说明、角色姓名、竞技场消息和教程按键在游戏运行时才会组合成完整句子。它们不能只靠逐字替换解决。

- **物品名称：**编辑 `item_names.json`。运行时会为已知物品名称处理当前版本支持的单个轻重或材质前缀。
- **品质、磨损及前缀：**编辑 `item_grammar.json`。中文名称和说明应保持术语一致，例如同一物品的标签和同伴拾物对白不应使用两套译法。
- **消息句式：**编辑 `message_templates.json`。保留 `{n0}`、`{s0}`、`{r1}`、`{m0}`、`{i0}` 等占位符及其标号；分别用于数字、姓名、段位、比赛类型、物品名称。不同标号承载不同值，不要相互替换。
- **比赛类型名称：**目前13种比赛类型的中文仍位于 [`compile_runtime.py`](../tools/compile_runtime.py) 的 `match_types` 映射中。若修改“决斗”“淘汰”等译名，需要修改这里，并核对其他界面中的同类用词；直接改 `runtime_generated.json` 会在构建时丢失。
- **角色姓名：**保留 `{Actor[0].Name}` 等原始占位符。玩家自定义姓名由运行时保留，不能在译文里固定写成一个名字。
- **教程按键：**保留 `[inpt4]` 等按键标记。运行时会从游戏展开后的完整章节中读取实际绑定，不能把标记直接改成 `Shift`、`Q` 等固定按键。

添加一种从未支持过的动态句式属于匹配规则改动。需要先记录游戏实际输出，再修改相应规则并增加验证；不要把猜测的拼接结果标记为已实机确认。

## 术语表的作用

[`glossary.json`](../translations/glossary.json) 是人工维护的名称与术语约定。修改人名、地点名或异能名时，先查阅并更新术语表，再同步修改涉及的实际译文。

**构建不会自动把术语表中的修改传播到其他文件。** 仅修改 `glossary.json` 不会改变游戏内显示。也不应全局替换英文匹配键来统一名称。

## 必须保留的匹配信息

源文匹配使用当前版本的实际字节与上下文。普通翻译编辑只改中文措辞，保留下列信息：

- 英文键、`en`、`id`、`offset`、`source_ids` 和已有的上下文地址。大小写、空格、句号均可能影响匹配。
- 换行与制表符，包括 JSON 中的 `\r\n`、`\r`、`\n`、`\t`。不要让编辑器自动把原有段落分隔统一成另一种形式。
- 颜色、对齐、字体、图片和按键标记，例如 `[tcol=FFE399]`、`[/tcol]`、`[algn=2]`、`[scrp=i]`、`[rimg=...]`、`[inpt4]`。
- 物品生成标记，例如 `@WEAR75:`、`[sq]`、`[pq]`、`[sc]`、`\u0010`；以及角色、地图和消息中的花括号占位符。
- 原文中的特殊单字节字符。不要用编辑器的“智能标点”把它们自动替换成外观相近但字节不同的符号。

JSON 文件使用 UTF-8 保存，并保持语法有效：字符串内的双引号和反斜杠需要转义，键不能重复。编译器会检查多种控制符与换行一致性；出现错误时，应修正具体条目，不能跳过校验。

特殊装饰标题按既定要求保留英文。不要通过新增标题绘制挂接或修改游戏图像，把它们顺手改成中文。

## 构建与验证

维护环境为 **Windows x64、Python 3.12、Pillow 12.3.0、Zig 0.14.1**。依赖和编译器使用本项目的本地环境，具体准备方法以构建说明为准，不需要为修改译文安装全局开发环境。

在源码目录根目录运行：

```text
python -X utf8 tools/build.py
```

一键构建负责按依赖顺序生成译文、字体、原生模块、验证结果及发行包。不要手动挑几个生成文件复制过去，导致词典、字体或模块来自不同版本。

**新增中文字也必须重新生成字体。** 只把新译文复制到运行时词典，已有字形图集可能没有这些字符，造成整句回退或显示异常。即使只是调整用词，也建议执行完整构建以同时检查字形覆盖。

构建完成后检查输出与验证报告，确认没有译文冲突、缺字、控制符变化或原生输出测试失败。若修改的是测试中已经固定的中文措辞，相关预期值也可能需要同步；先确认新译文和实际输出正确，再修改预期，不要单纯为通过测试而改断言。

构建和自动测试通过，不等于每个游戏画面都已验证。对本次修改涉及的界面做定点实机检查，尤其是长段落、滚动、物品说明、带姓名的消息和自定义按键教程。记录触发位置及观察结果，避免把“能加载”写成“显示无误”。

构建产物位于本地 `build/` 和 `dist/`。构建过程不自动安装到游戏，也不自动发布；测试安装前应退出游戏，并保留上一版补丁。发行时继续使用独立覆盖包，原版 EXE/RPK 和存档不放进包中。

## 文本索引与原版资源

[`data/catalog/`](../data/catalog/) 保存四份当前版本的文字匹配索引：`sources.json`、`resource-sources.json`、`dialogue-sources.json`、`map-sources.json`。它们包含编译需要的英文文本、记录标识与位置，**不包含游戏二进制资源**。

日常修改已收录译文并重建补丁，不需要把原版游戏资源复制进源码目录。索引应视为只读，不要为了让新译文通过构建而伪造源记录。

若要重新提取原文、调查未识别内容，或适配另一个游戏版本，则需要另外提供合法取得、哈希匹配的原版游戏文件，并使用提取工具重新核对格式。其他版本不能直接沿用本版本的偏移和绘制入口。不要把游戏 EXE/RPK、提取出的完整二进制资源、存档或运行日志加入待上传源码。

## 已知交付边界

当前维护链针对已校验的 Exanima 0.9.5.2。特殊装饰标题保留英文；教程插图目前隐藏但保留排版占位；未知或不受支持的动态文本回退原文。修订译文不应把这些边界描述成已经解决，也不应把提取范围内的覆盖率当作所有未来内容的保证。
