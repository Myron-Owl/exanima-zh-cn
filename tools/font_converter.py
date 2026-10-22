"""Create ZHF1 fonts independently of the game, native build and catalog indexes."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import queue
import re
import struct
import sys
import tempfile
import threading
from datetime import datetime, timezone

from build_font_atlas import build
from font_cmap import cmap_glyph

VERSION = '1.0.0'
ROOT = Path(__file__).resolve().parents[1]
RESOURCES = Path(getattr(sys, '_MEIPASS', ROOT))
HEADER = struct.Struct('<4s5I')
GLYPH = struct.Struct('<6I3i')
FIELDS = ('codepoint', 'page', 'x', 'y', 'width', 'height',
          'bearing_x', 'bearing_y', 'advance_64')
MAX_BYTES = 64 * 1024 * 1024


def read_limited(path, limit=MAX_BYTES):
    with Path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f'文件过大（上限 {limit // 1024 // 1024} MiB）：{Path(path).name}')
    return data


def valid_codepoint(cp):
    return isinstance(cp, int) and not isinstance(cp, bool) and 32 <= cp <= 0x10FFFF and not 0xD800 <= cp <= 0xDFFF


def name_characters():
    chars = {bytes([i]).decode('cp1252', errors='ignore') for i in range(32, 256)}
    return {c for c in chars if c and (c.isprintable() or c.isspace())}


def text_characters(text):
    text = re.sub(r'\[/?[^\]]+\]', '', text)
    return {c for c in text if c not in '\r\n\t' and valid_codepoint(ord(c))}


def default_characters():
    frozen = RESOURCES / 'font-tool-charset.json'
    if frozen.is_file():
        record = json.loads(read_limited(frozen).decode('utf-8'))
        values = record.get('codepoints', [])
        if record.get('schema') != 1 or not values or not all(valid_codepoint(cp) for cp in values):
            raise ValueError('内置字符表无效，请重新下载完整工具。')
        return set(map(chr, values)) | name_characters()
    # Read committed translation files directly: no generated catalog or DLL required.
    from stage_preview import INPUTS
    chars = name_characters()
    for name in INPUTS:
        data = json.loads(read_limited(ROOT / 'translations' / name).decode('utf-8'))
        for row in data['entries']:
            chars.update(text_characters(row['zh']))
    return chars


def read_zhf(data):
    if len(data) < HEADER.size:
        raise ValueError('ui.zhf 文件头不完整。')
    magic, size, side, pages, count, reserved = HEADER.unpack_from(data)
    if (magic != b'ZHF1' or reserved or not 1 <= size <= 128 or not 64 <= side <= 4096
            or not 1 <= pages <= 64 or not 1 <= count <= 65536):
        raise ValueError('不是受支持的 ZHF1 字体。')
    expected = HEADER.size + count * GLYPH.size + pages * side * side
    if len(data) != expected or expected > MAX_BYTES:
        raise ValueError('ui.zhf 的长度或分页信息错误。')
    result, previous = set(), -1
    for i in range(count):
        cp, page, x, y, width, height, bx, by, advance = GLYPH.unpack_from(data, HEADER.size + i * GLYPH.size)
        if (not valid_codepoint(cp) or cp <= previous or page >= pages or x >= side or y >= side
                or width > side - x or height > side - y or not 0 <= advance <= 32768
                or not -128 <= bx <= 128 or not -128 <= by <= 128):
            raise ValueError('ui.zhf 字形记录无效。')
        result.add(chr(cp))
        previous = cp
    return result


def unescape_translation(text):
    def replace(match):
        value = match.group(1)
        return chr(int(value[1:], 16)) if value.startswith('x') else {'r': '\r', 'n': '\n', 't': '\t', '\\': '\\'}[value]
    if re.search(r'\\(?![rnt\\]|x[0-9a-fA-F]{2})', text):
        raise ValueError('词典中文列含有无法识别的转义。')
    return re.sub(r'\\(x[0-9a-fA-F]{2}|[rnt\\])', replace, text)


def load_characters(source=None):
    if source is None:
        chars = default_characters()
    elif Path(source).suffix.lower() == '.zhf':
        chars = read_zhf(read_limited(source)) | name_characters()
    elif Path(source).suffix.lower() == '.utf8':
        chars, rows = name_characters(), 0
        for number, line in enumerate(read_limited(source, 16 * 1024 * 1024).decode('utf-8-sig').split('\n'), 1):
            line = line.removesuffix('\r')
            if not line or line.startswith('#'):
                continue
            fields = line.split('\t')
            if len(fields) not in (2, 3) or not fields[0] or not fields[1]:
                raise ValueError(f'词典第 {number} 行格式错误，应为原文、制表符、中文。')
            chars.update(text_characters(unescape_translation(fields[1])))
            rows += 1
        if not rows:
            raise ValueError('词典中没有译文。')
    else:
        raise ValueError('字符来源只能选择原 ui.zhf 或汉化词典 ui.utf8。')
    if not chars or len(chars) > 65536:
        raise ValueError('所需字符数量超出运行时限制。')
    return chars


def checked_font(path):
    """Validate the SFNT/cmap boundaries used by the existing atlas builder."""
    data = read_limited(path)
    try:
        if len(data) < 12 or data[:4] not in (b'\x00\x01\x00\x00', b'OTTO', b'true'):
            raise ValueError('请选择单个 TTF/OTF 字体；不支持 TTC、WOFF 或图片字体。')
        u16 = lambda pos: struct.unpack_from('>H', data, pos)[0]
        u32 = lambda pos: struct.unpack_from('>I', data, pos)[0]
        count = u16(4)
        if not 1 <= count <= 256 or 12 + 16 * count > len(data):
            raise ValueError('字体表目录无效。')
        tables = {}
        for i in range(count):
            pos = 12 + 16 * i
            tag, offset, length = data[pos:pos+4], u32(pos+8), u32(pos+12)
            if offset > len(data) or length > len(data) - offset or tag in tables:
                raise ValueError('字体表越界或重复。')
            tables[tag] = (offset, length)
        cmap, length = tables[b'cmap']
        maxp, maxp_length = tables[b'maxp']
        if maxp_length < 6 or not u16(maxp+4) or length < 4 or u16(cmap) != 0:
            raise ValueError('字体的 cmap/maxp 表无效。')
        glyph_count, records = u16(maxp+4), u16(cmap+2)
        if not 1 <= records <= 1024 or 4 + 8 * records > length:
            raise ValueError('字体的 cmap 索引无效。')
        supported = False
        for i in range(records):
            record = cmap + 4 + 8 * i
            if not (u16(record) == 0 or (u16(record) == 3 and u16(record+2) in (1, 10))):
                continue
            relative = u32(record+4)
            if relative > length - 2:
                raise ValueError('字体的 cmap 子表越界。')
            table = cmap + relative
            kind = u16(table)
            if kind not in (4, 12):
                continue
            supported = True
            if kind == 12:
                if relative + 16 > length:
                    raise ValueError('字体的 format 12 子表不完整。')
                size, groups = u32(table+4), u32(table+12)
                if size < 16 or size > length - relative or groups > 65536 or 16 + 12 * groups > size:
                    raise ValueError('字体的 format 12 分组错误。')
                previous = -1
                for j in range(groups):
                    first, last, glyph = struct.unpack_from('>III', data, table+16+12*j)
                    if first <= previous or first > last or last > 0x10FFFF or glyph + last - first >= glyph_count:
                        raise ValueError('字体的 format 12 字形范围错误。')
                    previous = last
            else:
                if relative + 16 > length:
                    raise ValueError('字体的 format 4 子表不完整。')
                size, segments = u16(table+2), u16(table+6)//2
                if u16(table+6) % 2 or not segments or 16 + 8 * segments > size or size > length - relative:
                    raise ValueError('字体的 format 4 分段错误。')
                ends = table+14
                starts = ends+2*segments+2
                ranges = starts+4*segments
                previous = -1
                for j in range(segments):
                    first, last, distance = u16(starts+2*j), u16(ends+2*j), u16(ranges+2*j)
                    if first <= previous or first > last:
                        raise ValueError('字体的 format 4 字符范围错误。')
                    if distance and (distance % 2 or ranges+2*j+distance+2*(last-first)+2 > table+size):
                        raise ValueError('字体的 format 4 字形偏移越界。')
                    previous = last
        if not supported:
            raise ValueError('字体缺少受支持的 Unicode cmap（format 4/12）。')
        return data, glyph_count
    except (struct.error, KeyError, IndexError) as error:
        raise ValueError('字体数据不完整或缺少必要的 Unicode 字形表。') from error


def convert(font_path, characters, fallback_path=None):
    font_path = Path(font_path)
    fallback_path = Path(fallback_path) if fallback_path else RESOURCES / 'assets/fonts/NotoSerifLatin.ttf'
    primary, primary_count = checked_font(font_path)
    fallback, fallback_count = checked_font(fallback_path)
    missing, fallback_chars = [], []
    for char in sorted(characters):
        glyph = cmap_glyph(primary, ord(char))
        if glyph >= primary_count:
            raise ValueError(f'主字体字形编号无效：U+{ord(char):04X}')
        if not glyph:
            glyph = cmap_glyph(fallback, ord(char))
            if glyph >= fallback_count:
                raise ValueError(f'备用字体字形编号无效：U+{ord(char):04X}')
            (fallback_chars if glyph else missing).append(char)
    if missing:
        shown = ' '.join(f'{c} (U+{ord(c):04X})' for c in missing[:24])
        raise ValueError(f'缺少 {len(missing)} 个字形，已停止生成。\n{shown}\n请选择覆盖完整的中文字体，或指定合适的备用字体。')
    with tempfile.TemporaryDirectory(prefix='exanima-font-') as temporary:
        folder = Path(temporary)
        meta = build(characters, 32, 2048, folder, font_path=font_path, fallback_path=fallback_path,
                     license_name='Custom font: consult its own license')
        blob = bytearray(HEADER.pack(b'ZHF1', 32, 2048, meta['page_count'], len(meta['glyphs']), 0))
        for glyph in meta['glyphs']:
            blob.extend(GLYPH.pack(*(glyph[key] for key in FIELDS)))
        for i in range(meta['page_count']):
            blob.extend((folder / f'page-{i:03}.a8').read_bytes()[12:])
    if len(blob) > MAX_BYTES or read_zhf(blob) != characters:
        raise ValueError('输出未通过运行时格式校验。')
    return bytes(blob), {'tool_version': VERSION, 'glyphs': len(characters), 'pages': meta['page_count'],
                         'pixel_size': 32, 'page_size': 2048, 'bytes': len(blob),
                         'fallback_glyphs': len(fallback_chars), 'font_sha256': hashlib.sha256(primary).hexdigest(),
                         'sha256': hashlib.sha256(blob).hexdigest()}


def save_font(output, blob, *, overwrite=False, inputs=()):
    output = Path(output).resolve()
    if output.suffix.lower() != '.zhf':
        raise ValueError('输出文件必须以 .zhf 结尾。')
    if output in {Path(path).resolve() for path in inputs if path is not None}:
        raise ValueError('输出路径不能与输入字体或字符来源相同，请另选位置。')
    backup = None
    if output.exists():
        if not overwrite:
            raise FileExistsError('输出文件已存在。请选择新文件名，或确认备份后覆盖。')
        previous = read_limited(output)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = output.with_name(output.name + f'.bak-{stamp}')
        with backup.open('xb') as stream:
            stream.write(previous)
    # Keep the old output intact until all bytes have been written and flushed.
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix='.zhf-', suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(blob)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        if overwrite:
            os.replace(temporary, output)
        else:
            # Windows rename refuses to overwrite a file created by another process.
            if os.name == 'nt':
                os.rename(temporary, output)
            else:
                os.link(temporary, output)
                temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def launch_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from PIL import Image, ImageDraw, ImageFont, ImageTk

    root = tk.Tk()
    root.title(f'Exanima 字体转换工具 {VERSION}')
    root.geometry('800x590')
    root.minsize(720, 560)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    frame.columnconfigure(1, weight=1)
    ttk.Label(frame, text='将字体转换为 ui.zhf', font=('Microsoft YaHei UI', 17, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
    ttk.Label(frame, text='只生成字体文件。游戏、词典和汉化模块由你自行保留。').grid(row=1, column=0, columnspan=3, sticky='w', pady=(6, 18))
    font, source, output = tk.StringVar(), tk.StringVar(), tk.StringVar()
    busy, messages = False, queue.Queue()
    controls = []

    def browse(kind):
        if kind == 'font':
            chosen = filedialog.askopenfilename(title='选择中文字体', filetypes=[('字体文件', '*.ttf *.otf'), ('所有文件', '*.*')])
            if chosen:
                font.set(chosen)
                if not output.get():
                    output.set(str(Path(chosen).with_name(Path(chosen).stem + '-ui.zhf')))
                preview()
        elif kind == 'source':
            chosen = filedialog.askopenfilename(title='选择原字体或当前汉化词典', filetypes=[('汉化字符来源', '*.zhf *.utf8'), ('所有文件', '*.*')])
            if chosen:
                source.set(chosen)
        else:
            chosen = filedialog.asksaveasfilename(title='保存转换后的字体', initialfile='ui.zhf', defaultextension='.zhf', filetypes=[('Exanima 字体', '*.zhf')])
            if chosen:
                output.set(chosen)

    for row, (label, value, kind) in enumerate((('字体文件', font, 'font'), ('字符来源（可选）', source, 'source'), ('输出文件', output, 'output')), 2):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=6)
        entry = ttk.Entry(frame, textvariable=value)
        entry.grid(row=row, column=1, sticky='ew', pady=6)
        button = ttk.Button(frame, text='选择…', command=lambda kind=kind: browse(kind))
        button.grid(row=row, column=2, padx=(8, 0), pady=6)
        controls.extend((entry, button))
    ttk.Label(frame, text='字符来源留空：使用随工具附带的当前译文字符。\n词典更新后，建议选择汉化包的 ExanimaZh\\translations\\ui.utf8。', wraplength=700).grid(row=5, column=0, columnspan=3, sticky='w', pady=(4, 12))
    canvas = ttk.Label(frame, text='选择字体后显示样例。转换固定使用 32px，与现有汉化格式一致。', anchor='center')
    canvas.grid(row=6, column=0, columnspan=3, sticky='ew', pady=8)

    def preview():
        try:
            checked_font(font.get())
            image = Image.new('RGB', (700, 112), '#191a1c')
            draw = ImageDraw.Draw(image)
            face = ImageFont.truetype(font.get(), 32)
            draw.text((16, 10), '设置  操作  装备  技能  异能', font=face, fill='#dacdac')
            draw.text((16, 60), '羊皮纸上的文字  Exanima 100%', font=face, fill='#dacdac')
            canvas.picture = ImageTk.PhotoImage(image)
            canvas.configure(image=canvas.picture, text='')
        except (OSError, ValueError) as error:
            canvas.configure(image='', text=str(error))

    status = tk.StringVar(value='请选择有完整简体中文字形的字体。')
    ttk.Label(frame, textvariable=status, wraplength=700).grid(row=8, column=0, columnspan=3, sticky='w', pady=12)
    progress = ttk.Progressbar(frame, mode='indeterminate')
    progress.grid(row=9, column=0, columnspan=3, sticky='ew')
    ttk.Label(frame, text='生成后退出游戏，备份并替换 ExanimaZh\\fonts\\ui.zhf，再启动检查排版。\n样例仅供参考；重新分发字体时请附上该字体的实际许可证。', wraplength=700).grid(row=10, column=0, columnspan=3, sticky='w', pady=(14, 0))

    def poll():
        nonlocal busy
        try:
            success, result = messages.get_nowait()
        except queue.Empty:
            if busy:
                root.after(100, poll)
            return
        busy = False
        progress.stop()
        for control in controls:
            control.configure(state='normal')
        if success:
            report, backup, destination = result
            status.set(f'已生成：{report["glyphs"]} 字，{report["pages"]} 页，备用字体补充 {report["fallback_glyphs"]} 字。')
            detail = f'已保存：\n{destination}' + (f'\n\n原文件已备份：\n{backup}' if backup else '')
            messagebox.showinfo('转换完成', detail)
        else:
            status.set('生成失败，原输出文件保留。')
            messagebox.showerror('无法生成字体', result)

    def start():
        nonlocal busy
        if not font.get() or not output.get():
            messagebox.showerror('缺少文件', '请选择字体文件与输出位置。')
            return
        selected_font, selected_source, destination = Path(font.get()), Path(source.get()) if source.get() else None, Path(output.get())
        overwrite = destination.exists()
        if overwrite and not messagebox.askyesno('备份后覆盖', '输出文件已存在。是否保存带时间的备份后覆盖？'):
            return
        busy = True
        status.set('正在检查缺字并生成图集，请稍候…')
        for control in controls:
            control.configure(state='disabled')
        progress.start()

        def worker():
            try:
                blob, report = convert(selected_font, load_characters(selected_source))
                backup = save_font(destination, blob, overwrite=overwrite, inputs=(selected_font, selected_source))
                messages.put((True, (report, backup, destination)))
            except Exception as error:
                messages.put((False, str(error)))
        threading.Thread(target=worker, daemon=True).start()
        root.after(100, poll)

    generate = ttk.Button(frame, text='生成 ui.zhf', command=start)
    generate.grid(row=7, column=0, columnspan=3, sticky='ew', pady=(12, 0))
    controls.append(generate)
    root.protocol('WM_DELETE_WINDOW', lambda: None if busy else root.destroy())
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Exanima TTF/OTF → ui.zhf；无参数启动中文界面。')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('--font', type=Path, help='中文 TTF/OTF 字体')
    parser.add_argument('--source', type=Path, help='可选：原 ui.zhf 或当前词典 ui.utf8')
    parser.add_argument('--fallback', type=Path, help='可选：备用字体；默认 Noto Serif（西文）')
    parser.add_argument('--output', type=Path, help='输出 .zhf 文件')
    parser.add_argument('--overwrite', action='store_true', help='先自动备份，再覆盖已有输出')
    args = parser.parse_args(argv)
    if not any((args.font, args.source, args.fallback, args.output, args.overwrite)):
        launch_gui()
        return 0
    if not args.font or not args.output:
        parser.error('命令行转换需要同时提供 --font 和 --output。')
    try:
        blob, report = convert(args.font, load_characters(args.source), args.fallback)
        backup = save_font(args.output, blob, overwrite=args.overwrite, inputs=(args.font, args.source, args.fallback))
        print(json.dumps({**report, 'output': str(args.output), 'backup': str(backup) if backup else None}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, struct.error) as error:
        print(f'转换失败：{error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
