from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


RPK_ENTRY_SIZE = 32
RPK_NAME_SIZE = 16
RFI_MAGIC = 0x1D2D3DC6
RFI_RAW = 0x10000000
RFI_RLE = 0x50000000
RFI_CHANNELS = {
    0x01002008: 1,
    0x01004200: 1,
    0x01006208: 2,
    0x0100C600: 3,
    0x0100E608: 4,
}

# Ink widths measured from the game's main font for printable ASCII 0x21..0x7E.
# The executable's six advance tables correlate with this shape even though
# their stored values are smaller spacing deltas.
ADVANCE_REFERENCE = [
    6, 12, 22, 18, 36, 26, 4, 9, 9, 15, 23, 8, 12, 6, 16, 22, 11, 20, 19,
    22, 19, 20, 20, 20, 21, 6, 8, 21, 23, 21, 12, 31, 29, 21, 27, 27, 17, 17,
    29, 27, 5, 10, 23, 18, 33, 26, 34, 20, 34, 23, 19, 24, 26, 28, 37, 24, 25,
    26, 8, 20, 8, 22, 22, 10, 20, 21, 20, 21, 20, 14, 20, 18, 5, 10, 19, 4,
    31, 18, 22, 21, 21, 11, 15, 12, 19, 20, 33, 20, 21, 20, 10, 4, 10, 22,
]


@dataclass(frozen=True)
class RpkEntry:
    name: str
    offset: int
    size: int
    tail: bytes


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_rpk_index(path: Path) -> tuple[bytes, list[RpkEntry], int]:
    with path.open("rb") as stream:
        header = stream.read(8)
        if len(header) != 8:
            raise ValueError("RPK header is truncated")
        magic = header[:4]
        index_size = struct.unpack_from("<I", header, 4)[0]
        if index_size % RPK_ENTRY_SIZE:
            raise ValueError(f"Unexpected RPK index size: {index_size}")
        index = stream.read(index_size)
    entries: list[RpkEntry] = []
    for pos in range(0, index_size, RPK_ENTRY_SIZE):
        row = index[pos : pos + RPK_ENTRY_SIZE]
        name = row[:RPK_NAME_SIZE].rstrip(b"\0").decode("latin-1")
        offset, size = struct.unpack_from("<II", row, 16)
        entries.append(RpkEntry(name, offset, size, row[24:32]))
    return magic, entries, 8 + index_size


def extract_entry(path: Path, name: str) -> bytes:
    _, entries, data_start = read_rpk_index(path)
    match = next((entry for entry in entries if entry.name == name), None)
    if match is None:
        raise KeyError(f"RPK entry not found: {name}")
    with path.open("rb") as stream:
        stream.seek(data_start + match.offset)
        data = stream.read(match.size)
    if len(data) != match.size:
        raise ValueError(f"RPK entry is truncated: {name}")
    return data


def hash_entry(stream, data_start: int, entry: RpkEntry) -> str:
    digest = hashlib.sha256()
    stream.seek(data_start + entry.offset)
    remaining = entry.size
    while remaining:
        block = stream.read(min(1024 * 1024, remaining))
        if not block:
            raise ValueError(f"RPK entry is truncated: {entry.name}")
        digest.update(block)
        remaining -= len(block)
    return digest.hexdigest()


def rebuild_rpk(source: Path, target: Path, replacements: dict[str, bytes]) -> None:
    magic, entries, data_start = read_rpk_index(source)
    missing = set(replacements) - {entry.name for entry in entries}
    if missing:
        raise KeyError(f"RPK replacement entries not found: {sorted(missing)}")

    index = bytearray()
    next_offset = 0
    for entry in entries:
        size = len(replacements[entry.name]) if entry.name in replacements else entry.size
        encoded_name = entry.name.encode("latin-1")
        index += encoded_name.ljust(RPK_NAME_SIZE, b"\0")
        index += struct.pack("<II", next_offset, size)
        index += entry.tail
        next_offset += size

    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("wb") as dst:
        dst.write(magic)
        dst.write(struct.pack("<I", len(index)))
        dst.write(index)
        for entry in entries:
            if entry.name in replacements:
                dst.write(replacements[entry.name])
                continue
            src.seek(data_start + entry.offset)
            remaining = entry.size
            while remaining:
                block = src.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError(f"RPK entry is truncated: {entry.name}")
                dst.write(block)
                remaining -= len(block)


def read_rdb(data: bytes) -> tuple[int, list[tuple[int, int, bytes]]]:
    if len(data) < 8:
        raise ValueError("RDB header is truncated")
    magic, index_size = struct.unpack_from("<II", data, 0)
    if index_size % 16 or 8 + index_size > len(data):
        raise ValueError(f"Unexpected RDB index size: {index_size}")
    base = 8 + index_size
    rows: list[tuple[int, int, bytes]] = []
    for pos in range(8, base, 16):
        a, flags, offset, length = struct.unpack_from("<4I", data, pos)
        if offset + length > len(data) - base:
            raise ValueError(f"RDB row points outside its string pool: {pos:#x}")
        rows.append((a, flags, data[base + offset : base + offset + length]))
    return magic, rows


def rebuild_rdb(data: bytes, replacements: dict[bytes, bytes]) -> bytes:
    magic, rows = read_rdb(data)
    pool = bytearray()
    positions: dict[bytes, int] = {}
    index = bytearray()
    for a, flags, original in rows:
        value = replacements.get(original, original)
        if value not in positions:
            positions[value] = len(pool)
            pool += value
        index += struct.pack("<4I", a, flags, positions[value], len(value))
    return struct.pack("<II", magic, len(index)) + index + pool


def rfi_decode(data: bytes) -> tuple[list[int], int, bytes, bytes]:
    if len(data) < 32:
        raise ValueError("RFI header is truncated")
    header = list(struct.unpack_from("<8I", data, 0))
    if header[0] != RFI_MAGIC:
        raise ValueError("Not an RFI bitmap")
    channels = RFI_CHANNELS.get(header[4])
    if channels is None:
        raise ValueError(f"Unknown RFI pixel format: {header[4]:#x}")
    body = data[32:]
    if header[6] == RFI_RAW:
        decoded = body
    elif header[6] == RFI_RLE:
        decoded = bytearray()
        run_base = 64 if channels == 1 else 63
        pos = 0
        while pos < len(body) and len(decoded) < header[7]:
            control = body[pos]
            pos += 1
            if control < run_base:
                count = (control + 1) * channels
                decoded += body[pos : pos + count]
                pos += count
            else:
                pixel = body[pos : pos + channels]
                pos += channels
                decoded += pixel * (control - 61)
        decoded = bytes(decoded)
    else:
        raise ValueError(f"Unknown RFI storage mode: {header[6]:#x}")
    if len(decoded) != header[7]:
        raise ValueError(f"RFI decoded size mismatch: {len(decoded)} != {header[7]}")
    base_size = header[1] * header[2] * channels
    return header, channels, decoded[:base_size], decoded[base_size:]


def rfi_encode(header: list[int], channels: int, base_bottom_up: bytes, mips: bytes) -> bytes:
    decoded = base_bottom_up + mips
    run_base = 64 if channels == 1 else 63
    min_run = run_base - 61
    pixel_count = len(decoded) // channels
    output = bytearray()
    literals: list[bytes] = []

    def flush_literals() -> None:
        while literals:
            count = min(len(literals), run_base)
            output.append(count - 1)
            for pixel in literals[:count]:
                output.extend(pixel)
            del literals[:count]

    pos = 0
    while pos < pixel_count:
        start = pos * channels
        pixel = decoded[start : start + channels]
        end = pos + 1
        while end < pixel_count and end - pos < 194:
            other = decoded[end * channels : (end + 1) * channels]
            if other != pixel:
                break
            end += 1
        run_length = end - pos
        if run_length >= min_run:
            flush_literals()
            output.append(run_length + 61)
            output.extend(pixel)
            pos = end
        else:
            literals.append(pixel)
            pos += 1
            if len(literals) == run_base:
                flush_literals()
    flush_literals()
    new_header = header[:]
    new_header[6] = RFI_RLE
    new_header[7] = len(decoded)
    return struct.pack("<8I", *new_header) + bytes(output)


def rfi_to_image(data: bytes) -> Image.Image:
    header, channels, base_bottom_up, _ = rfi_decode(data)
    width, height = header[1], header[2]
    stride = width * channels
    rows = [base_bottom_up[pos : pos + stride] for pos in range(0, len(base_bottom_up), stride)]
    top_down = b"".join(reversed(rows))
    mode = {1: "L", 2: "LA", 3: "RGB", 4: "RGBA"}[channels]
    return Image.frombytes(mode, (width, height), top_down)


def patch_font_glyphs(
    data: bytes,
    glyphs: dict[int, str],
    font_path: Path,
    clear_high_slots: bool = False,
) -> bytes:
    if any(not 0 <= codepoint <= 0xFF for codepoint in glyphs):
        raise ValueError("Font codepoints must fit in one byte")
    header, channels, base_bottom_up, mips = rfi_decode(data)
    width, height = header[1], header[2]
    if width % 16 or height % 16 or channels not in (1, 2):
        raise ValueError(f"Unexpected font atlas: {width}x{height}, {channels} channel(s)")

    image = rfi_to_image(data)
    cell_width = width // 16
    cell_height = height // 16
    empty = 0 if channels == 1 else (0, 0)
    ink = 255 if channels == 1 else (255, 255)
    reference_codepoint = ord("W")
    reference_x = (reference_codepoint & 0x0F) * cell_width
    reference_y = (15 - (reference_codepoint >> 4)) * cell_height
    reference_bbox = image.crop(
        (reference_x, reference_y, reference_x + cell_width, reference_y + cell_height)
    ).getbbox()
    if reference_bbox is None:
        raise ValueError("Reference glyph W is empty")
    reference_bottom = reference_bbox[3]
    if clear_high_slots:
        for codepoint in range(0x80, 0x100):
            cell_x = (codepoint & 0x0F) * cell_width
            cell_y = (15 - (codepoint >> 4)) * cell_height
            image.paste(
                empty,
                (cell_x, cell_y, cell_x + cell_width, cell_y + cell_height),
            )

    font_size = max(10, int(min(cell_width, cell_height) * 0.72))
    font = ImageFont.truetype(str(font_path), font_size)
    draw = ImageDraw.Draw(image)
    for codepoint, character in glyphs.items():
        cell_x = (codepoint & 0x0F) * cell_width
        cell_y = (15 - (codepoint >> 4)) * cell_height
        image.paste(
            empty,
            (cell_x, cell_y, cell_x + cell_width, cell_y + cell_height),
        )
        bounds = draw.textbbox((0, 0), character, font=font)
        glyph_width = bounds[2] - bounds[0]
        glyph_height = bounds[3] - bounds[1]
        x = cell_x + (cell_width - glyph_width) // 2 - bounds[0]
        # Exanima samples glyphs using per-font baseline metrics. Aligning to
        # the cell centre puts CJK ink too high and the renderer clips its top.
        y = cell_y + reference_bottom - glyph_height - bounds[1]
        draw.text((x, y), character, font=font, fill=ink)

    top_down = image.tobytes()
    stride = header[1] * channels
    rows = [top_down[pos : pos + stride] for pos in range(0, len(top_down), stride)]
    patched_bottom_up = b"".join(reversed(rows))
    return rfi_encode(header, channels, patched_bottom_up, mips)


def patch_font_glyph(data: bytes, codepoint: int, character: str, font_path: Path) -> bytes:
    return patch_font_glyphs(data, {codepoint: character}, font_path)


EXE_STRING_PATTERN = re.compile(
    rb"\xff{8}(.{8})([\x20-\x7e\x80-\xff\r\n\t]{1,3000})\x00",
    re.S,
)


def patch_exe_string(data: bytearray, source: bytes, replacement: bytes) -> int:
    matches: list[tuple[int, int]] = []
    for match in EXE_STRING_PATTERN.finditer(data):
        declared = struct.unpack("<Q", match.group(1))[0]
        value = match.group(2)
        if declared == len(value) and value == source:
            capacity = ((declared + 1 + 7) // 8) * 8 - 1
            matches.append((match.start() + 16, capacity))
    if not matches:
        raise ValueError(f"EXE string not found: {source!r}")
    for offset, capacity in matches:
        if len(replacement) > capacity:
            raise ValueError(f"Replacement does not fit EXE string buffer: {len(replacement)} > {capacity}")
        struct.pack_into("<Q", data, offset - 8, len(replacement))
        data[offset : offset + capacity + 1] = replacement + bytes(capacity + 1 - len(replacement))
    return len(matches)


def embedded_rfi_blobs(data: bytes) -> list[tuple[int, int, int, int, int]]:
    magic = struct.pack("<I", RFI_MAGIC)
    blobs: list[tuple[int, int, int, int, int]] = []
    pos = -1
    while True:
        pos = data.find(magic, pos + 1)
        if pos < 0:
            return blobs
        if pos + 32 > len(data):
            continue
        header = struct.unpack_from("<8I", data, pos)
        width, height, pixel_format, storage, decoded_size = (
            header[1],
            header[2],
            header[4],
            header[6],
            header[7],
        )
        channels = RFI_CHANNELS.get(pixel_format)
        if channels is None or width % 16 or height % 16 or width > 4096 or height > 4096:
            continue
        body_pos = pos + 32
        if storage == RFI_RAW:
            body_length = decoded_size
        elif storage == RFI_RLE:
            cursor = body_pos
            produced = 0
            run_base = 64 if channels == 1 else 63
            try:
                while produced < decoded_size:
                    control = data[cursor]
                    cursor += 1
                    if control < run_base:
                        count = (control + 1) * channels
                        produced += count
                        cursor += count
                    else:
                        produced += (control - 61) * channels
                        cursor += channels
            except IndexError:
                continue
            if produced != decoded_size:
                continue
            body_length = cursor - body_pos
        else:
            continue
        blobs.append((pos, 32 + body_length, width, height, channels))


def patch_embedded_fonts(data: bytearray, glyphs: dict[int, str], font_path: Path) -> list[dict]:
    original = bytes(data)
    results: list[dict] = []
    for offset, allocated, width, height, channels in embedded_rfi_blobs(original):
        # The executable also embeds icons that happen to use the RFI container.
        # Its five text atlases are the 1:2 images from 128x256 through 512x1024.
        if channels not in (1, 2) or width < 128 or height != width * 2:
            continue
        patched = patch_font_glyphs(
            original[offset : offset + allocated],
            glyphs,
            font_path,
            clear_high_slots=True,
        )
        if len(patched) > allocated:
            results.append({
                "offset": offset,
                "width": width,
                "height": height,
                "channels": channels,
                "status": "too-large",
                "original_size": allocated,
                "patched_size": len(patched),
            })
            continue
        data[offset : offset + len(patched)] = patched
        if len(patched) < allocated:
            data[offset + len(patched) : offset + allocated] = bytes(allocated - len(patched))
        results.append({
            "offset": offset,
            "width": width,
            "height": height,
            "channels": channels,
            "status": "patched",
            "original_size": allocated,
            "patched_size": len(patched),
        })
    return results


def find_advance_tables(data: bytes, threshold: float = 0.60) -> list[tuple[int, float]]:
    reference_mean = sum(ADVANCE_REFERENCE) / len(ADVANCE_REFERENCE)
    reference_sd = (
        sum((value - reference_mean) ** 2 for value in ADVANCE_REFERENCE)
        / len(ADVANCE_REFERENCE)
    ) ** 0.5
    normalized_reference = [
        (value - reference_mean) / reference_sd for value in ADVANCE_REFERENCE
    ]

    zero_run = bytes(22 * 2)
    found: list[tuple[int, float]] = []
    previous = -99
    search_from = -1
    while True:
        search_from = data.find(zero_run, search_from + 1)
        if search_from < 0:
            return found
        if search_from % 2:
            continue
        offset = search_from - 0x0A * 2
        if offset < 0 or offset + 512 > len(data) or offset - previous < 64:
            continue
        table = struct.unpack_from("<256h", data, offset)
        if any(table[codepoint] for codepoint in range(1, 9)):
            continue
        printable = table[0x21:0x7F]
        if len(set(printable)) < 6 or max(printable) - min(printable) < 4:
            continue
        mean = sum(printable) / len(printable)
        sd = (sum((value - mean) ** 2 for value in printable) / len(printable)) ** 0.5
        if sd < 1e-9:
            continue
        correlation = sum(
            ((value - mean) / sd) * reference
            for value, reference in zip(printable, normalized_reference)
        ) / len(printable)
        if correlation > threshold:
            previous = offset
            found.append((offset, correlation))


def patch_advance_widths(
    data: bytearray,
    mappings: dict[int, int],
) -> list[dict]:
    results: list[dict] = []
    for offset, correlation in find_advance_tables(bytes(data)):
        table = list(struct.unpack_from("<256h", data, offset))
        for target, source in mappings.items():
            table[target] = table[source]
        struct.pack_into("<256h", data, offset, *table)
        results.append({
            "offset": offset,
            "correlation": round(correlation, 3),
            "values": {f"0x{target:02X}": table[target] for target in mappings},
        })
    return results


def command_inspect(args: argparse.Namespace) -> None:
    source = Path(args.rpk)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    font = extract_entry(source, args.font_entry)
    rfi_to_image(font).save(output)
    _, rows = read_rdb(extract_entry(source, "objstrings.rdb"))
    report = {
        "rpk": str(source),
        "sha256": sha256(source),
        "font_entry": args.font_entry,
        "font_png": str(output),
        "rdb_rows": len(rows),
        "first_strings": [row[2].decode("latin-1") for row in rows[:20]],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def command_build_test(args: argparse.Namespace) -> None:
    source = Path(args.rpk)
    target = Path(args.output)
    original_rdb = extract_entry(source, "objstrings.rdb")
    patched_rdb = rebuild_rdb(original_rdb, {b"Sword": bytes([args.codepoint])})
    original_font = extract_entry(source, args.font_entry)
    patched_font = patch_font_glyph(
        original_font,
        args.codepoint,
        args.character,
        Path(args.system_font),
    )
    rebuild_rpk(
        source,
        target,
        {
            "objstrings.rdb": patched_rdb,
            args.font_entry: patched_font,
        },
    )

    _, rows = read_rdb(patched_rdb)
    matches = sum(1 for _, _, value in rows if value == bytes([args.codepoint]))
    _, target_entries, _ = read_rpk_index(target)
    target_rdb = next(entry for entry in target_entries if entry.name == "objstrings.rdb")
    target_font = next(entry for entry in target_entries if entry.name == args.font_entry)
    verification_font = extract_entry(target, args.font_entry)
    verification_image = rfi_to_image(verification_font)
    cell_size = 64
    cell_x = (args.codepoint & 0x0F) * cell_size
    cell_y = (15 - (args.codepoint >> 4)) * cell_size
    glyph_pixels = verification_image.crop(
        (cell_x, cell_y, cell_x + cell_size, cell_y + cell_size)
    )
    print(json.dumps({
        "source_sha256": sha256(source),
        "output": str(target),
        "output_sha256": sha256(target),
        "translated_rows": matches,
        "translation": f"Sword -> {args.character}",
        "replacement_byte": f"0x{args.codepoint:02X}",
        "objstrings_size": target_rdb.size,
        "font_entry": args.font_entry,
        "font_size": target_font.size,
        "glyph_nonzero_pixels": sum(1 for value in glyph_pixels.tobytes() if value),
    }, ensure_ascii=False, indent=2))


def command_verify_test(args: argparse.Namespace) -> None:
    source = Path(args.source)
    patched = Path(args.patched)
    source_magic, source_entries, source_base = read_rpk_index(source)
    patched_magic, patched_entries, patched_base = read_rpk_index(patched)
    if source_magic != patched_magic:
        raise ValueError("RPK magic changed")
    if [entry.name for entry in source_entries] != [entry.name for entry in patched_entries]:
        raise ValueError("RPK entry names or order changed")
    if [entry.tail for entry in source_entries] != [entry.tail for entry in patched_entries]:
        raise ValueError("RPK entry metadata changed")

    allowed = {"objstrings.rdb", args.font_entry}
    unexpected: list[str] = []
    expected_changes: list[str] = []
    with source.open("rb") as source_stream, patched.open("rb") as patched_stream:
        for original, changed in zip(source_entries, patched_entries):
            original_hash = hash_entry(source_stream, source_base, original)
            changed_hash = hash_entry(patched_stream, patched_base, changed)
            if original_hash != changed_hash:
                if original.name in allowed:
                    expected_changes.append(original.name)
                else:
                    unexpected.append(original.name)
    if unexpected:
        raise ValueError(f"Unexpected changed RPK entries: {unexpected}")
    if set(expected_changes) != allowed:
        raise ValueError(f"Expected changed entries are missing: {allowed - set(expected_changes)}")

    _, source_rows = read_rdb(extract_entry(source, "objstrings.rdb"))
    _, rows = read_rdb(extract_entry(patched, "objstrings.rdb"))
    replacement = bytes([args.codepoint])
    if len(source_rows) != len(rows):
        raise ValueError("RDB row count changed")
    for row_number, (original_row, changed_row) in enumerate(zip(source_rows, rows)):
        original_a, original_flags, original_value = original_row
        changed_a, changed_flags, changed_value = changed_row
        expected_value = replacement if original_value == b"Sword" else original_value
        if (changed_a, changed_flags, changed_value) != (
            original_a,
            original_flags,
            expected_value,
        ):
            raise ValueError(f"Unexpected RDB change in row {row_number}")
    translated_rows = sum(1 for _, _, value in rows if value == replacement)
    if translated_rows != 5:
        raise ValueError(f"Expected 5 translated Sword rows, found {translated_rows}")

    original_font_data = extract_entry(source, args.font_entry)
    patched_font_data = extract_entry(patched, args.font_entry)
    image = rfi_to_image(patched_font_data)
    cell_size = 64
    cell_x = (args.codepoint & 0x0F) * cell_size
    cell_y = (15 - (args.codepoint >> 4)) * cell_size
    glyph = image.crop((cell_x, cell_y, cell_x + cell_size, cell_y + cell_size))
    nonzero = sum(1 for value in glyph.tobytes() if value)
    if nonzero < 100:
        raise ValueError(f"Patched glyph appears empty: {nonzero} nonzero pixels")
    original_image = rfi_to_image(original_font_data)
    original_image.paste(0, (cell_x, cell_y, cell_x + cell_size, cell_y + cell_size))
    comparison_image = image.copy()
    comparison_image.paste(0, (cell_x, cell_y, cell_x + cell_size, cell_y + cell_size))
    if original_image.tobytes() != comparison_image.tobytes():
        raise ValueError("Font pixels changed outside the selected glyph cell")
    _, _, _, original_mips = rfi_decode(original_font_data)
    _, _, _, patched_mips = rfi_decode(patched_font_data)
    if original_mips != patched_mips:
        raise ValueError("Font mipmaps changed")

    print(json.dumps({
        "verified": True,
        "entry_count": len(source_entries),
        "changed_entries": expected_changes,
        "unchanged_entries": len(source_entries) - len(expected_changes),
        "translated_rows": translated_rows,
        "glyph_nonzero_pixels": nonzero,
        "patched_sha256": sha256(patched),
    }, ensure_ascii=False, indent=2))


def command_build_menu_test(args: argparse.Namespace) -> None:
    source_exe = Path(args.exe)
    source_rpk = Path(args.rpk)
    output_exe = Path(args.output_exe)
    output_rpk = Path(args.output_rpk)
    font_path = Path(args.system_font)
    glyphs = {0xFD: "设", 0xFE: "置"}

    exe_data = bytearray(source_exe.read_bytes())
    string_matches = patch_exe_string(exe_data, b"SETTINGS", bytes([0xFD, 0xFE]))
    embedded_results = patch_embedded_fonts(exe_data, glyphs, font_path)
    patched_fonts = [item for item in embedded_results if item["status"] == "patched"]
    if not patched_fonts:
        raise ValueError("No embedded EXE font could be patched")
    output_exe.parent.mkdir(parents=True, exist_ok=True)
    output_exe.write_bytes(exe_data)

    replacements: dict[str, bytes] = {}
    for entry_name in ("fontbase24r.rfi", "titlefont.rfi"):
        original_font = extract_entry(source_rpk, entry_name)
        replacements[entry_name] = patch_font_glyphs(
            original_font,
            glyphs,
            font_path,
            clear_high_slots=True,
        )
    rebuild_rpk(source_rpk, output_rpk, replacements)

    verification_exe = output_exe.read_bytes()
    if b"SETTINGS\0" in verification_exe:
        raise ValueError("Plain SETTINGS string remains in the patched EXE")
    menu_bytes = bytes([0xFD, 0xFE])
    menu_hits = sum(
        1
        for match in EXE_STRING_PATTERN.finditer(verification_exe)
        if struct.unpack("<Q", match.group(1))[0] == len(match.group(2))
        and match.group(2) == menu_bytes
    )
    if menu_hits != string_matches:
        raise ValueError(f"Patched menu string count mismatch: {menu_hits} != {string_matches}")

    print(json.dumps({
        "source_exe_sha256": sha256(source_exe),
        "source_rpk_sha256": sha256(source_rpk),
        "output_exe": str(output_exe),
        "output_exe_sha256": sha256(output_exe),
        "output_rpk": str(output_rpk),
        "output_rpk_sha256": sha256(output_rpk),
        "menu_translation": "SETTINGS -> 设置",
        "menu_string_matches": string_matches,
        "embedded_fonts": embedded_results,
        "resource_fonts": sorted(replacements),
    }, ensure_ascii=False, indent=2))


def command_build_settings_test(args: argparse.Namespace) -> None:
    source_exe = Path(args.exe)
    source_rpk = Path(args.rpk)
    output_exe = Path(args.output_exe)
    output_rpk = Path(args.output_rpk)
    font_path = Path(args.system_font)
    glyphs = {0xFD: "音", 0xFE: "量"}

    original_exe = source_exe.read_bytes()
    exe_data = bytearray(original_exe)
    string_matches = patch_exe_string(exe_data, b"Audio volume: ", bytes([0xFD, 0xFE, 0x3A, 0x20]))
    embedded_results = patch_embedded_fonts(exe_data, glyphs, font_path)
    if sum(item["status"] == "patched" for item in embedded_results) != 5:
        raise ValueError("Expected to patch exactly five embedded text atlases")
    advance_results = patch_advance_widths(exe_data, {0xFD: ord("W"), 0xFE: ord("W")})
    if len(advance_results) != 6:
        raise ValueError(f"Expected six font advance tables, found {len(advance_results)}")
    if any(
        not result["values"][key]
        for result in advance_results
        for key in ("0xFD", "0xFE")
    ):
        raise ValueError("A patched Chinese glyph still has zero advance")
    output_exe.parent.mkdir(parents=True, exist_ok=True)
    output_exe.write_bytes(exe_data)

    font_name = "fontbase24r.rfi"
    original_font = extract_entry(source_rpk, font_name)
    patched_font = patch_font_glyphs(
        original_font,
        glyphs,
        font_path,
        clear_high_slots=True,
    )
    rebuild_rpk(source_rpk, output_rpk, {font_name: patched_font})

    verification_exe = output_exe.read_bytes()
    settings_count_before = original_exe.count(b"SETTINGS")
    settings_count_after = verification_exe.count(b"SETTINGS")
    if settings_count_after != settings_count_before:
        raise ValueError("Main-menu SETTINGS bytes changed")
    replacement = bytes([0xFD, 0xFE, 0x3A, 0x20])
    replacement_hits = sum(
        1
        for match in EXE_STRING_PATTERN.finditer(verification_exe)
        if struct.unpack("<Q", match.group(1))[0] == len(match.group(2))
        and match.group(2) == replacement
    )
    if replacement_hits != string_matches:
        raise ValueError(f"Patched settings label count mismatch: {replacement_hits} != {string_matches}")

    print(json.dumps({
        "source_exe_sha256": sha256(source_exe),
        "source_rpk_sha256": sha256(source_rpk),
        "output_exe": str(output_exe),
        "output_exe_sha256": sha256(output_exe),
        "output_rpk": str(output_rpk),
        "output_rpk_sha256": sha256(output_rpk),
        "translation": "Audio volume: -> 音量:",
        "label_matches": string_matches,
        "main_menu_settings_unchanged": True,
        "embedded_fonts_patched": len(embedded_results),
        "advance_tables": advance_results,
        "resource_fonts": [font_name],
    }, ensure_ascii=False, indent=2))


def command_inspect_exe_fonts(args: argparse.Namespace) -> None:
    exe_path = Path(args.exe)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    data = exe_path.read_bytes()
    outputs = []
    for index, (offset, length, width, height, channels) in enumerate(embedded_rfi_blobs(data)):
        if channels not in (1, 2) or width < 128 or height != width * 2:
            continue
        output = output_dir / f"font-{index}-{width}x{height}-0x{offset:X}.png"
        image = rfi_to_image(data[offset : offset + length])
        image.save(output)
        cell_width, cell_height = width // 16, height // 16
        bboxes = {}
        for codepoint in (ord("W"), 0xFD, 0xFE):
            cell_x = (codepoint & 0x0F) * cell_width
            cell_y = (15 - (codepoint >> 4)) * cell_height
            bboxes[f"0x{codepoint:02X}"] = image.crop(
                (cell_x, cell_y, cell_x + cell_width, cell_y + cell_height)
            ).getbbox()
        outputs.append({"path": str(output), "cell": [cell_width, cell_height], "bboxes": bboxes})
    print(json.dumps({"exe": str(exe_path), "fonts": outputs}, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exanima 0.9.5.2 Chinese localization test tools")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="extract and render the main font atlas")
    inspect.add_argument("--rpk", required=True)
    inspect.add_argument("--output", required=True)
    inspect.add_argument("--font-entry", default="fontbase24r.rfi")
    inspect.set_defaults(run=command_inspect)

    text_test = commands.add_parser("build-test", help="replace Sword with one custom Chinese glyph")
    text_test.add_argument("--rpk", required=True)
    text_test.add_argument("--output", required=True)
    text_test.add_argument("--codepoint", type=lambda value: int(value, 0), default=0xFE)
    text_test.add_argument("--character", default="剑")
    text_test.add_argument("--system-font", default=r"C:\Windows\Fonts\msyh.ttc")
    text_test.add_argument("--font-entry", default="fontbase24r.rfi")
    text_test.set_defaults(run=command_build_test)

    verify = commands.add_parser("verify-test", help="verify only the intended RPK entries changed")
    verify.add_argument("--source", required=True)
    verify.add_argument("--patched", required=True)
    verify.add_argument("--codepoint", type=lambda value: int(value, 0), default=0xFE)
    verify.add_argument("--font-entry", default="fontbase24r.rfi")
    verify.set_defaults(run=command_verify_test)

    menu_test = commands.add_parser("build-menu-test", help="build a SETTINGS -> 设置 test")
    menu_test.add_argument("--exe", required=True)
    menu_test.add_argument("--rpk", required=True)
    menu_test.add_argument("--output-exe", required=True)
    menu_test.add_argument("--output-rpk", required=True)
    menu_test.add_argument("--system-font", default=r"C:\Windows\Fonts\msyh.ttc")
    menu_test.set_defaults(run=command_build_menu_test)

    settings_test = commands.add_parser(
        "build-settings-test",
        help="build an inner settings Audio volume -> 音量 test",
    )
    settings_test.add_argument("--exe", required=True)
    settings_test.add_argument("--rpk", required=True)
    settings_test.add_argument("--output-exe", required=True)
    settings_test.add_argument("--output-rpk", required=True)
    settings_test.add_argument("--system-font", default=r"C:\Windows\Fonts\msyh.ttc")
    settings_test.set_defaults(run=command_build_settings_test)

    inspect_exe = commands.add_parser("inspect-exe-fonts", help="render embedded EXE font atlases")
    inspect_exe.add_argument("--exe", required=True)
    inspect_exe.add_argument("--output-dir", required=True)
    inspect_exe.set_defaults(run=command_inspect_exe_fonts)
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = build_parser().parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
