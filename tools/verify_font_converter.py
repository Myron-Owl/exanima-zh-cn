"""Regression checks for standalone font output, source inputs and safe failures."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import font_converter as converter

ROOT = converter.ROOT
REFERENCE = None
FROZEN = None
GUI = False


class ConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='exanima-font-test-')
        cls.folder = Path(cls.temporary.name) / '中文 空格&路径'
        cls.folder.mkdir()
        cls.primary = ROOT / 'assets/fonts/NotoSerifSC.ttf'
        cls.latin = ROOT / 'assets/fonts/NotoSerifLatin.ttf'
        cls.chars = converter.name_characters() | set('设置操作羊皮纸祖母绿')
        cls.blob, cls.report = converter.convert(cls.primary, cls.chars)
        cls.template = cls.folder / '原字体.zhf'
        cls.template.write_bytes(cls.blob)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_default_covers_selected_release_and_approved_terminology(self):
        chars = converter.load_characters()
        self.assertTrue(set('祖母绿') <= chars)
        # A fresh source archive has only committed translation files.
        with mock.patch.object(converter, 'ROOT', ROOT), mock.patch('stage_preview.select', side_effect=AssertionError('must not need catalog')):
            self.assertEqual(chars, converter.default_characters())
        if REFERENCE:
            self.assertTrue(converter.read_zhf(REFERENCE.read_bytes()) <= chars)

    def test_runtime_format_and_baseline_metrics(self):
        self.assertEqual(converter.read_zhf(self.blob), self.chars)
        magic, size, side, pages, count, reserved = struct.unpack_from('<4s5I', self.blob)
        self.assertEqual((magic, size, side, reserved), (b'ZHF1', 32, 2048, 0))
        self.assertEqual(len(self.blob), 24 + 36 * count + pages * side * side)
        self.assertEqual(self.report['sha256'], hashlib.sha256(self.blob).hexdigest())
        # Baseline bearings should put normal Chinese glyphs above the baseline.
        records = [struct.unpack_from('<6I3i', self.blob, 24 + i*36) for i in range(count)]
        self.assertTrue(any(row[0] == ord('设') and row[7] < 0 for row in records))

    def test_original_font_is_byte_identical(self):
        if not REFERENCE:
            self.skipTest('No previously built patch font supplied')
        chars = converter.read_zhf(REFERENCE.read_bytes())
        blob, _ = converter.convert(self.primary, chars)
        self.assertEqual(blob, REFERENCE.read_bytes())

    def test_dictionary_scopes_escapes_and_tags(self):
        dictionary = self.folder / '词典.ui.utf8'
        dictionary.write_text('# comment\nSet\t设置\\n羊皮纸\\t[red]祖母绿[/red]\\\\\\x41\t305150\n', encoding='utf-8')
        chars = converter.load_characters(dictionary)
        self.assertTrue(set('设置羊皮纸祖母绿\\A') <= chars)
        self.assertNotIn('\n', chars)
        self.assertNotIn('\t', chars)
        self.assertEqual(chars, converter.text_characters('设置\n羊皮纸\t[red]祖母绿[/red]\\A') | converter.name_characters())

    def test_malformed_dictionary_rejected(self):
        dictionary = self.folder / '错误.utf8'
        for content in ('', 'one column\n', 'a\tb\tc\td\n', 'a\tbad\\q\n', 'a\t\n'):
            dictionary.write_text(content, encoding='utf-8')
            with self.assertRaises(ValueError):
                converter.load_characters(dictionary)

    def test_zhf_truncation_and_unsafe_glyphs_rejected(self):
        for data in (b'', self.blob[:23], self.blob[:-1], b'xxxx' + self.blob[4:]):
            with self.assertRaises(ValueError):
                converter.read_zhf(data)
        for position, value in ((12, 65), (16, 65537), (24, 0xD800), (28, 64), (32, 2048), (48, 129)):
            broken = bytearray(self.blob)
            struct.pack_into('<I', broken, position, value)
            with self.assertRaises(ValueError):
                converter.read_zhf(broken)

    def test_multi_page_template_supported(self):
        data = bytearray(struct.pack('<4s5I', b'ZHF1', 32, 64, 2, 2, 0))
        data += struct.pack('<6I3i', ord('A'), 0, 2, 2, 15, 20, 0, -20, 1024)
        data += struct.pack('<6I3i', ord('中'), 1, 2, 2, 30, 30, 0, -30, 2048)
        data += bytes(2*64*64)
        self.assertEqual(converter.read_zhf(data), set('A中'))

    def test_missing_chinese_does_not_write_output(self):
        output = self.folder / '缺字输出.zhf'
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(ROOT/'tools/font_converter.py'),
                                 '--font', str(self.latin), '--source', str(self.template), '--output', str(output)],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('缺少', result.stderr)
        self.assertFalse(output.exists())

    def test_custom_fallback_can_supply_chinese(self):
        blob, report = converter.convert(self.latin, self.chars, self.primary)
        self.assertEqual(converter.read_zhf(blob), self.chars)
        self.assertGreater(report['fallback_glyphs'], 0)

    def test_bad_font_cmap_does_not_read_outside_table(self):
        invalid = self.folder / '损坏字体.ttf'
        samples = [b'', b'not a font', b'ttcf' + bytes(100), b'\x00\x01\x00\x00'+bytes(32)]
        font = bytearray(self.primary.read_bytes())
        for i in range(struct.unpack_from('>H', font, 4)[0]):
            position = 12 + 16*i
            if font[position:position+4] == b'cmap':
                cmap = struct.unpack_from('>I', font, position+8)[0]
                struct.pack_into('>I', font, cmap+8, 0xFFFFFFFF)
                break
        samples.append(font)
        for sample in samples:
            invalid.write_bytes(sample)
            with self.assertRaises(ValueError):
                converter.checked_font(invalid)

    def test_cli_unicode_paths_and_template(self):
        output = self.folder / '新字体 & 输出.zhf'
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(ROOT/'tools/font_converter.py'),
                                 '--font', str(self.primary), '--source', str(self.template), '--output', str(output)],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_bytes(), self.blob)
        self.assertEqual(json.loads(result.stdout)['sha256'], self.report['sha256'])

    def test_overwrite_backup_and_input_guard(self):
        output = self.folder / '覆盖测试.zhf'
        output.write_bytes(b'keep original')
        with self.assertRaises(FileExistsError):
            converter.save_font(output, self.blob)
        self.assertEqual(output.read_bytes(), b'keep original')
        backup = converter.save_font(output, self.blob, overwrite=True)
        self.assertEqual(backup.read_bytes(), b'keep original')
        self.assertEqual(output.read_bytes(), self.blob)
        with self.assertRaises(ValueError):
            converter.save_font(self.template, self.blob, overwrite=True, inputs=(self.template,))
        with self.assertRaises(ValueError):
            converter.save_font(self.folder/'wrong.ttf', self.blob)

    def test_packaged_executable_with_and_without_source(self):
        if not FROZEN:
            self.skipTest('No packaged executable supplied')
        for name, source in (('模板转换', self.template), ('内置字符', None)):
            output = self.folder / (name + '.zhf')
            command = [str(FROZEN), '--font', str(self.primary), '--output', str(output)]
            if source:
                command += ['--source', str(source)]
            environment = {key: value for key, value in os.environ.items() if key not in ('PYTHONHOME', 'PYTHONPATH')}
            environment['PATH'] = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32')
            result = subprocess.run(command, timeout=120, cwd=self.folder, env=environment)
            self.assertEqual(result.returncode, 0)
            expected = self.blob if source else converter.convert(self.primary, converter.default_characters())[0]
            self.assertEqual(output.read_bytes(), expected)

    def test_gui_select_preview_convert(self):
        if not GUI:
            self.skipTest('GUI test not requested')
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        actual_tk, events, failures = tk.Tk, [], []
        output = self.folder / '界面生成.zhf'

        def factory():
            root = actual_tk()

            def select_and_convert():
                try:
                    frame = root.winfo_children()[0]
                    buttons = [child for child in frame.winfo_children() if isinstance(child, ttk.Button)]
                    entries = [child for child in frame.winfo_children() if isinstance(child, ttk.Entry)]
                    buttons[0].invoke()
                    buttons[1].invoke()
                    entries[2].delete(0, 'end')
                    entries[2].insert(0, str(output))
                    root.update_idletasks()
                    buttons[-1].invoke()
                    self.assertEqual(str(buttons[-1]['state']), 'disabled')
                    deadline = time.monotonic() + 30

                    def finish():
                        if events or time.monotonic() > deadline:
                            if not events:
                                failures.append('GUI worker timeout')
                            root.destroy()
                        else:
                            root.after(100, finish)
                    root.after(100, finish)
                except Exception as error:
                    failures.append(str(error))
                    root.destroy()
            root.after(100, select_and_convert)
            return root

        with mock.patch.object(tk, 'Tk', factory), mock.patch.object(filedialog, 'askopenfilename', side_effect=[str(self.primary), str(self.template)]), \
                mock.patch.object(messagebox, 'showinfo', side_effect=lambda *args: events.append('success')), \
                mock.patch.object(messagebox, 'showerror', side_effect=lambda *args: failures.append(str(args))):
            converter.launch_gui()
        self.assertFalse(failures, failures)
        self.assertEqual(events, ['success'])
        self.assertEqual(output.read_bytes(), self.blob)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, help='Previously built ui.zhf for exact byte comparison')
    parser.add_argument('--frozen', type=Path, help='Packaged Windows EXE to exercise')
    parser.add_argument('--gui', action='store_true', help='Exercise actual Tk window, selection and conversion')
    args = parser.parse_args()
    REFERENCE = args.reference.resolve() if args.reference else None
    FROZEN = args.frozen.resolve() if args.frozen else None
    GUI = args.gui
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ConverterTests))
    raise SystemExit(0 if result.wasSuccessful() else 1)
