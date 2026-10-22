# 构建汉化补丁

当前维护与发行目标为 Steam Exanima 0.9.5.2f build 25733142，只生成一个 Steam 汉化发行包。在 Windows x64 上使用 Python 3.12、Pillow 12.3.0 和 Zig 0.14.1。常规构建使用随源码提供的文本索引，不需要游戏 EXE/RPK，也不会启动游戏、安装补丁或上传文件。

## 首次准备

在源码目录打开 PowerShell。以下命令只在本目录创建虚拟环境并安装构建依赖，不修改全局 Python：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -B -X utf8 tools\build.py --check-only
```

`requirements-build.txt` 固定 Pillow 12.3.0 和 ziglang 0.14.1。ziglang 包含本地编译器及头文件，不需要另装系统 SDK。字体原件、许可证及来源哈希已包含在 `assets/fonts/`；构建前会检查这些文件及 `data/versions.json` 的版本身份。

如果本机 Python 启动器没有 `py -3.12`，可将第一行替换为已安装的 Python 3.12 可执行文件路径，保留 `-m venv .venv`。

## 完整构建

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\build.py
```

构建按以下顺序执行，任何一步失败都会停止：

1. 检查 Python、Pillow、Zig、字体哈希、JSON 格式和版本配置中的 EXE/RPK 精确哈希。
2. 将 `data/catalog/` 的四份索引补充到 `build/catalog/`。仅复制缺失文件，保留已经重新提取或人工维护的现有索引。
3. 生成物品名、界面、教程、地图和动态对话词典。
4. 编译 `data/compatibility.json` 为外部兼容特征文件，从 `data/versions.json` 生成 `native/version_profiles.h`，再编译两个 DLL、生成字体图集并整理补丁目录。
5. 确认生成头文件与版本配置一致；验证 WinMM 代理导出、静态导入加载、系统函数转发，以及控制标记、段落、译文冲突、字体覆盖、完整译文输出和绘制状态；验证自动定位、整图地址移动、同名语境、生产初始化及拒绝时不写入口。
6. 打包并核对 ZIP 成员、清单哈希和解压结果，生成 SHA256 校验文件。

成功后得到：

- `dist/Exanima-zh-CN-0.9.5.2f-Steam.zip`
- `dist/Exanima-zh-CN-0.9.5.2f-Steam.zip.sha256`

`release/README.txt` 逐字节进入 ZIP，构建程序不会重写作者署名、文字或换行。ZIP 只包含运行补丁、生成字体、词典、说明和许可证；不会包含游戏 EXE/RPK、源码字体或编译器。

已有同名 ZIP 会先备份为带原哈希的 `-previous-*.zip`。构建产生的 `build/`、`dist/`、`.venv/` 和 `toolchain/` 是本地目录，不应上传为源码。生成结果通过自动测试不等于完成游戏内全部画面的实机验证；当前教程插图隐藏的限制仍然存在。

## 指定已有 Zig

优先顺序为命令行 `--zig`、进程环境变量 `EXANIMA_ZIG`、项目 `.venv`、当前 Python 环境、旧版项目工具链位置以及 `PATH`。可以传可执行文件或包含它的目录；编译器必须报告版本 `0.14.1`。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\build.py --zig 'D:\Tools\Zig\zig.exe'
```

`--zig` 仅传递给这次构建的子进程，不写入系统环境。也可临时设置当前 PowerShell 进程的变量：

```powershell
$env:EXANIMA_ZIG = 'D:\Tools\Zig\zig.exe'
.\.venv\Scripts\python.exe -B -X utf8 tools\build.py --check-only
```

使用 `--check-only` 只校验依赖和输入文件，并运行 `generate_version_profiles.py --check` 检查已保存的版本头文件；不生成词典、DLL、字体或 ZIP，也不会覆盖 `build/catalog`。如头文件过期，需要先显式运行 `python -B -X utf8 tools/generate_version_profiles.py` 更新它。完整构建则会在编译前自动生成。查看参数说明：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\build.py --help
```

## 重复构建与原资源

修改译文后重新运行完整构建即可。人工编辑源映射后，相关编译步骤会更新派生 JSON；请按维护文档选择正确的源文件，不只修改下一次会被重新生成的文件。

四份索引分别为 `sources.json`、`resource-sources.json`、`dialogue-sources.json` 和 `map-sources.json`。这些索引使用旧版 EXE 的规范地址；Steam build 25733142 的上下文地址由运行时版本配置映射，词典保持共用。重新提取原游戏资源是单独的可选流程，当前四个提取工具仍只接受旧版精确文件对，详见 [重新提取说明](EXTRACTING.md)。不要把游戏文件放入源码包或补丁 ZIP。

## 验证版本与 Steam 代理

Steam 目标与历史规范来源的 EXE/RPK 哈希、地址映射和验证边界见 [Steam 兼容说明](STEAM_COMPATIBILITY.md)。历史配置作为现有地址转换的基础保留，不单独生成旧版发行包。常规构建不需要 Steam；`verify_proxy.py` 会运行专用测试程序，验证新增 mixer 导出和系统函数转发，不启动游戏或 Steam。

如需额外核对本机 Steam 模块的 WinMM 导入，完整构建后显式传入 Steam 安装目录：

```powershell
python -B -X utf8 tools/verify_proxy.py --steam-dir "<Steam安装目录>"
```

`--steam-dir` 只读取导入表，不会加载 Steam 模块。代理报告保存在 `build/proxy-verification/`。核对游戏文件对使用独立的只读工具：

```powershell
python -B -X utf8 tools/verify_game_version.py --game-dir "<游戏目录>" --dictionary build/preview-package/ExanimaZh/translations/ui.utf8
```

这个检查验证精确文件身份、挂钩签名和上下文字符串，结果写入 `build/version-verification-<profile-id>.json`。它不执行游戏，也不能证明所有实际界面已正确绘制。

该入口支持从相同源码重新生成可用补丁；没有承诺 ZIP 或 DLL 的 SHA256 在不同目录、编译环境或构建时间下完全相同。发布时请使用本次输出的 `.sha256`，不要沿用旧包的校验值。

自动兼容的范围、验证方法与外部配置补救流程见 [自动兼容说明](AUTO_COMPATIBILITY.md)。
