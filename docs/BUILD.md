# 构建汉化补丁

在 Windows x64 上使用 Python 3.12、Pillow 12.3.0 和 Zig 0.14.1。常规构建使用随源码提供的文本索引，不需要游戏 EXE/RPK，也不会启动游戏、安装补丁或上传文件。

## 首次准备

在源码目录打开 PowerShell。以下命令只在本目录创建虚拟环境并安装构建依赖，不修改全局 Python：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -B -X utf8 tools\build.py --check-only
```

`requirements-build.txt` 固定 Pillow 12.3.0 和 ziglang 0.14.1。ziglang 包含本地编译器及头文件，不需要另装系统 SDK。字体原件、许可证及来源哈希已包含在 `assets/fonts/`；构建前会检查这些文件。

如果本机 Python 启动器没有 `py -3.12`，可将第一行替换为已安装的 Python 3.12 可执行文件路径，保留 `-m venv .venv`。

## 完整构建

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\build.py
```

构建按以下顺序执行，任何一步失败都会停止：

1. 检查 Python、Pillow、Zig、字体哈希和 JSON 格式。
2. 将 `data/catalog/` 的四份索引补充到 `build/catalog/`。仅复制缺失文件，保留已经重新提取或人工维护的现有索引。
3. 生成物品名、界面、教程、地图和动态对话词典。
4. 编译两个 DLL，生成字体图集，再整理补丁目录。
5. 验证控制标记、段落、译文冲突与收录范围，以及字体覆盖、完整译文输出和绘制状态。
6. 打包并核对 ZIP 成员、清单哈希和解压结果，生成 SHA256 校验文件。

成功后得到：

- `dist/Exanima-zh-CN-0.9.5.2.zip`
- `dist/Exanima-zh-CN-0.9.5.2.zip.sha256`

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

使用 `--check-only` 只校验依赖和输入文件，不生成词典、DLL、字体或 ZIP；它也不会覆盖 `build/catalog`。查看参数说明：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\build.py --help
```

## 重复构建与原资源

修改译文后重新运行完整构建即可。人工编辑源映射后，相关编译步骤会更新派生 JSON；请按维护文档选择正确的源文件，不只修改下一次会被重新生成的文件。

四份索引分别为 `sources.json`、`resource-sources.json`、`dialogue-sources.json` 和 `map-sources.json`。重新提取原游戏资源是单独的可选流程，不属于默认构建；需要维护者自己的、哈希匹配的 0.9.5.2 游戏文件。不要把这些游戏文件放入源码包或补丁 ZIP。

该入口支持从相同源码重新生成可用补丁；没有承诺 ZIP 或 DLL 的 SHA256 在不同目录、编译环境或构建时间下完全相同。发布时请使用本次输出的 `.sha256`，不要沿用旧包的校验值。
