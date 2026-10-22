# Exanima 字体转换工具

本工具把单个 TTF/OTF 字体转换为本汉化补丁使用的 `ZHF1` 格式 `ui.zhf`。只生成字体文件，不需要游戏原文件、文本提取索引、Zig 或编译 DLL，也不改动作者的 README、正式汉化 ZIP 或游戏安装。

## Windows 图形界面

下载 `Exanima-Font-Tool-1.0.0-Windows-x64.zip`，完整解压，双击 `ExanimaFontTool.exe`。适用于 Windows x64；独立版不需要安装 Python、系统字体或编译器。未提供其他系统的可执行版本。

1. 在“字体文件”中选择包含完整简体中文字形的 `.ttf` 或 `.otf`。
2. “字符来源”可以留空，使用构建工具时附带的译文字符。若正在使用的汉化词典更新过，建议选择当前汉化包里的 `ExanimaZh/translations/ui.utf8`。也可选择原 `ExanimaZh/fonts/ui.zhf`，沿用其字符集合。
3. 选择新输出位置，点击“生成 ui.zhf”。生成时会检查缺字；缺字就报出字符并停止，不用方框代替。少量主字体缺失的西文由内置 Noto Serif 补齐。
4. 退出游戏，备份原 `ExanimaZh/fonts/ui.zhf`，再把生成文件改名为 `ui.zhf` 并覆盖到这个位置。重启游戏，检查设置、操作、技能说明和羊皮纸等画面。

样例预览不等于实机排版。不同字体的字宽、基线和笔画不同，可能引起换行或截断。工具固定使用与现有汉化一致的 32px、2048×2048 A8 图集，不需要修改汉化 DLL。

输出默认拒绝覆盖已有文件。界面确认覆盖后会先保存 `文件名.zhf.bak-时间`；输出与输入字体、字符来源相同则拒绝操作。工具不自动安装字体到游戏。失败时不会替换原输出；生成过程中的临时文件会自动清理。

只支持单个 SFNT TTF/OTF；不支持 TTC 字体合集、WOFF 网页字体、图片字体。可变字体使用默认字重/轴值；暂不提供字重、字号、描边和粗细调节。内置字符集合不会自动联网更新；新词典加入新字符后应重新转换。

## 从源码运行

需要 Python 3.12 和 Pillow 12.3.0。直接下载源码即可运行，不必先完整构建汉化包，也不需要替换 `assets/fonts/NotoSerifSC.ttf` 或修改 `provenance.json`。

在源码根目录打开 PowerShell，使用本项目虚拟环境：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install Pillow==12.3.0
.\.venv\Scripts\python.exe -B -X utf8 tools\font_converter.py
```

命令行转换例子：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\font_converter.py --font "D:\Fonts\中文字体.ttf" --output "D:\Output\ui.zhf"
```

指定最新词典或原字体作为字符来源：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\font_converter.py --font "D:\Fonts\中文字体.ttf" --source "D:\ExanimaZh\translations\ui.utf8" --output "D:\Output\ui.zhf"
```

`--source` 也接受原 `.zhf`。`--fallback` 可指定额外的 TTF/OTF 备用字体；未指定时使用随源码提供的 Noto Serif 西文字体。命令行需要覆盖已有输出时显式加 `--overwrite`，仍会自动备份。输出目录必须已存在。命令行成功输出 JSON 摘要及 SHA256；失败返回非零退出码。独立 EXE 是无控制台的界面版本，脚本方式更适合批量转换。

## 构建独立 EXE

这组依赖单独列在 `requirements-font-tool.txt`，不会加入常规汉化构建或 CI。所有依赖仅安装到项目虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-font-tool.txt
.\.venv\Scripts\python.exe -B -X utf8 tools\build_font_tool.py
```

构建使用 Windows x64、Python 3.12、Pillow 12.3.0、PyInstaller 6.16.0，以及 Python 自带的 Tk。临时构建材料放在 `build/font-tool/`，交付 ZIP 和 SHA256 放在 `dist/`。ZIP 含 EXE、使用说明、构建信息及运行库/备用字体许可证；不含游戏文件、中文字体原件或汉化 DLL。已有同名 ZIP 时拒绝覆盖，需要先自行保存旧版本。

验证源码功能：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 tools\verify_font_converter.py
```

已完整构建汉化时，可另加 `--reference build/preview-package/ExanimaZh/fonts/ui.zhf`，用原字体逐字节核对转换输出；加 `--gui` 验证窗口选择与转换流程。自动验证不代替新字体的游戏内排版检查。

## 字体授权

转换不会改变字体许可证，也不代表字体允许再分发。自行分享生成的 `ui.zhf` 时，应核对所选字体是否允许修改/转换和再分发，并按其条款附上许可证。工具不会把任意自选字体标记为 OFL。内置备用字体 Noto Serif 使用 SIL OFL 1.1，许可证随独立工具保存于 `licenses/NotoSerifLatin-OFL.txt`。

Tcl/Tk 许可证原件保存在 `release/font-tool-Tcl-license.terms`、`release/font-tool-Tk-license.terms`，分别来自 [Tcl 8.6.12](https://github.com/tcltk/tcl/blob/core-8-6-12/license.terms) 与 [Tk 8.6.12](https://github.com/tcltk/tk/blob/core-8-6-12/license.terms)。Python、Pillow（包含其第三方组件说明）和 PyInstaller 的许可证从构建环境复制进独立工具 ZIP。它们与自选字体的许可证分别适用。
