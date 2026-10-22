# Steam 版本兼容与维护

后续维护、测试和发包目标为 Steam Exanima 0.9.5.2f build 25733142，发行 `Exanima-zh-CN-0.9.5.2f-Steam.zip`，增加经完整函数特征校验的未知小版本兼容路径。旧版地址、索引及已完成的版本配置保留为当前实现的基础，不承诺继续适配旧独立发行版本，也不单独生成旧版发行包。

版本身份保存在 `data/versions.json`。Steam 目标由完整 EXE/RPK 的 SHA256 文件对确定；显示为“0.9.5.2f”或拥有相同文件名不足以证明兼容。下表同时保留规范提取来源，便于审核地址转换。

| 配置 | Exanima.exe SHA256 | Resource.rpk SHA256 |
| --- | --- | --- |
| 历史规范来源：旧版 0.9.5.2 | `97a83509f1e230349126817adb8576a7725bceda120023f1173bb463b46cba6a` | `e32dbf99663d648848a1dff3c777fc9a5a32d17c20576a7df69cfd60b39b751a` |
| Steam build 25441985 | `bd892a1f4bfde2603668f8f62d5e55fa40737353a9dc5bebb23f00cd03e10992` | `62b968ded239090fc580c0c299f71c1d1bc4b7220285beceae66f748d36342ca` |
| Steam build 25701113 | `56e69278996acecf3b77b0679dc89c7ce54030d64aacdfa867656859111ab20b` | `7624c0b88003d2b52a9088ec2275265019ff6d083ee0f97d5dd65ab12f1dba34` |
| Steam build 25733142（当前） | `f651658e4ef708932743c880f7b22c00ba4df52f2536c1c1c82a2e4dad3e3f4c` | `7624c0b88003d2b52a9088ec2275265019ff6d083ee0f97d5dd65ab12f1dba34` |

Steam build 编号说明本次核对的构建来源，实际匹配仍以哈希为准。Steam 更新后，即使版本字符串没变，也要重新审核，不应把新哈希直接加入允许列表。

生成补丁的 `ExanimaZh/version.json` 会记录 `supported_versions`，其中保留每个配置的精确 `id`、`exe_sha256` 和 `rpk_sha256`；`runtime_revision` 标记为 `steam-build25733142-preview`。`steam_visual_verified` 初始为 `false`，不能因为完成构建就改成已实机验证。发行说明仍从 `release/README.txt` 原样复制。

## 配置、编译与运行时

每个配置包含 EXE/RPK 哈希、11 处挂钩的位置和字节签名、9 个引擎布局地址，以及上下文词条的旧址到本版地址映射。`tools/generate_version_profiles.py` 将配置生成到 `native/version_profiles.h`；此头文件由工具维护，不能手工修改来绕过检查。

```powershell
python -B -X utf8 tools/generate_version_profiles.py
python -B -X utf8 tools/generate_version_profiles.py --check
```

第一条只按配置更新生成头；第二条只检查一致性，头文件缺失或过期时返回失败。`tools/build_native.py` 在编译前生成头文件；完整构建的验证阶段再执行 `--check`。`tools/build.py --check-only` 也检查头文件，但不会改写它。

离线版本验证工具按 EXE/RPK 双哈希选取配置，并检查挂钩、布局和上下文文本。运行时先根据实际 EXE 哈希选取已知地址配置；未知哈希进入完整结构检测，详见 [自动兼容](AUTO_COMPATIBILITY.md)。安装前再核对挂钩签名；不能把这一点描述为运行时也校验了整个 RPK。未知 EXE 未通过结构检测、或挂钩签名不符时，不能继续安装任何挂钩。

## 共用词典与规范地址

`data/catalog/` 和词典第三列的 `source_rva` 使用旧版 EXE 地址。Steam 配置把这 9 条带上下文限制的地址转换为本版地址，原文和中文共用一份词典。普通非上下文词条继续按原文字节匹配。

| 原文 | 旧版 source_rva | Steam build 25733142 地址 |
| --- | --- | --- |
| Back：移动操作 | `0x305150` | `0x3072a8` |
| Counter：技能 | `0x3151f0` | `0x317868` |
| Counter：另一技能表 | `0x3368a0` | `0x338fa0` |
| Crush：伤害属性 | `0x30e310` | `0x310798` |
| Ward：盾技 | `0x3152d0` | `0x317948` |
| Ward：另一技能表 | `0x336980` | `0x339080` |
| Weight：物品界面 | `0x30dc50` | `0x3100d8` |
| Weight：另一物品界面 | `0x30de48` | `0x3102d0` |
| Unknown 身世说明 | `0x3102c8` | `0x3127b8` |

这些映射核对了完整原文字节、64 位长度前缀及引用位置的上下文，不能改成“寻找第一个相同英文”。两个 Back 分别属于移动操作和文件浏览器；技能名也可能和异能资源中的同名词含义不同。`Shield` 本身不是当前词典中的地址限定项，不应因为出现相近名称而增加未经核对的范围。英文装饰标题仍维持原样。

四个导出工具目前仍仅接受旧版精确文件对，详见 [原文提取](EXTRACTING.md)。不要把 Steam 原始偏移写入旧版规范索引。

## 资源差异的验证范围

历史规范资源包与 Steam build 25441985 均有 243 个同名、同顺序条目，其中 207 个逐字节相同，36 个不同。`objstrings.rdb`、`charroles.rdb`、两份手册、四个异能资源和旁白资源全部相同。按活动 RDB 索引提取的 123 条地图记录、117 条去重原文也全部一致，既有地图词典没有因这次资源差异新增缺译。

`exanima08.rfc` 和 `exanima67.rfc` 的 24 条地图文本物理偏移变化，但 ID 和原文字节未变。标题字体则有实际像素和 mip 层差异，不能用整包哈希不同推断“只有压缩方式不同”。这些结论支持复用已核对的原文词典，不代替游戏画面测试。

## 手动检查

Steam EXE 没有导入 `timeGetTime`；`timeBeginPeriod` 也只在高精度等待计时器不可用时走到。只在计时函数里启动汉化会导致已安装补丁却始终显示英文。代理现在仅在宿主名为 `Exanima.exe` 时创建初始化线程，线程在 Windows 完成 DLL 初始化回调后加载汉化模块；DLL 入口本身不等待线程、不读取词典、不安装挂钩。所有 WinMM 导出只负责系统转发，运行时仍以精确 EXE 哈希决定是否安装挂钩。

`verify_proxy.py` 增加不调用任何 WinMM 函数的启动测试：使用名为 `Exanima.exe` 的测试宿主验证自动加载，同时确认未知哈希被拒绝。可用 `--startup-baseline <旧代理DLL>` 复现只有计时调用才能初始化的旧故障。词典加载失败时，运行时直接返回，确保不安装任何文字挂钩。

```powershell
python -B -X utf8 tools/verify_game_version.py --game-dir "<游戏目录>" --dictionary build/preview-package/ExanimaZh/translations/ui.utf8
python -B -X utf8 tools/verify_proxy.py --steam-dir "<Steam安装目录>"
```

游戏目录与 Steam 安装目录由维护者显式指定。第一个工具只读游戏文件，不启动游戏或加载本地模块；第二个工具读取 Steam 导入表，并运行专用验证宿主测试代理的静态导入和系统转发，不执行 Steam 模块。版本报告写入 `build/version-verification-<profile-id>.json`；代理报告写入 `build/proxy-verification/`。

省略 `--dictionary` 时，版本检查工具会在默认构建词典存在时使用它，否则报告词典检查跳过。未生成词典前的检查不能作为 9 条上下文译文已装入发行包的证明。需要选择原文件备份时可显式传入 `--allow-original-backups`；它不会放宽文件哈希。

完整验证仍需实际打开游戏检查：操作设置的 Back、物品 Weight/Crush、技能 Counter/Ward、同名异能、Unknown 身世说明、手册与羊皮纸，并确认英文装饰标题未被替换。自动测试、加载成功和实际绘制成功应分别记录。

## 2026-10-04 更新核对

Steam build 25701113 的 11 个文字入口与 5 个绘制辅助函数，完整函数体在忽略外部地址位移后与 build 25441985 一致；9 个引擎布局地址、9 条上下文词条的原文和新地址均已重新核对。同名词条借助引用表上下文唯一对应。资源包仍为同名同序 243 项，仅 `arenao5.rfc`、`arenao5.rft`、`humanoid.rsq` 三项改变；更新的地图文件不含活动文本。常用 EXE 英文键仍有 549 条原文字节匹配，其中 500 条具备完整长度前缀。详细证据在原工程本地 `build/steam-update-20261004/static-audit.json`，游戏二进制不随源码分发。

本次已通过 Steam 正常启动，在新鲜日志中确认完整 EXE 哈希、新版本配置、2,612 条词典记录及 11 个文字入口成功安装。游戏版本标签为 `V 0.9.5.2e`，因此发行名使用 0.9.5.2e。界面显示仍待用户实机核对，未据加载日志标记为视觉验证完成。

最终包再次安装并通过 Steam 启动后，日志确认 `steam-0.9.5.2e-build25701113`、`Unicode texture upload: OK` 及中文标签绘制提交成功；这证明实际加载与绘制路径已运行，但不代替界面截图或用户的显示确认。

## 2026-10-06：0.9.5.2f 核对

Steam build 25733142 与上一版相比，Resource.rpk 完整 SHA256 相同。11 个文字入口、5 个绘制辅助函数的完整函数体，在只忽略外部地址位移后一致；非 RIP 字段偏移、栈参数和局部跳转保留核对。5 个辅助函数的入口移动了 `+0x60`；4 个全局数据字段与 9 条上下文词条地址不变。上下文词条的完整原文、长度前缀及引用表语境均通过核对；549 个既有普通原文仍可匹配，其中 500 个具有完整长度前缀。详细证据在本地原工程 `build/steam-update-20261006/static-audit.json`，原始游戏文件不分发。

当前版本地址由生成头编译到 DLL 内，增加版本配置仍需重建模块和覆盖包。不能以“小更新”或单一入口签名相同为由放行未知 EXE。外置版本配置能减少以后重新编译，但仍需逐版核对，并需要独立设计、解析与回退测试；本次沿用已验证的构建机制。

本次完整构建、代理导出与自动初始化、词典字体、排版和 4 份版本配置模拟绘制检查通过。最终包已备份安装到本机 Steam 游戏目录，实际启动日志确认 f 版完整 EXE 哈希、当前版本配置、2,612 条词典记录、11 个文字入口、字体纹理上传和中文标签绘制提交成功。尚未据此宣称所有界面完成视觉验收。README 与人工校对表均保持原样。

自动兼容的范围、验证方法与外部配置补救流程见 [自动兼容说明](AUTO_COMPATIBILITY.md)。
