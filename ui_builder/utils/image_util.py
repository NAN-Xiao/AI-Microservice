"""图片工具：从原始字节流中读取图片宽高（不依赖 Pillow）。"""

import struct


def get_image_size(data: bytes) -> tuple[int, int] | None:
    """从 PNG / JPEG / WebP / BMP 字节流中解析宽高，失败返回 None。"""
    if not data or len(data) < 26:
        return None

    # PNG: 固定头 8 字节 + IHDR chunk 中 offset 16-23 存 w/h
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        w, h = struct.unpack('>II', data[16:24])
        return w, h

    # JPEG: 找 SOFn marker（0xC0-0xC2）
    if data[:2] == b'\xff\xd8':
        idx = 2
        while idx < len(data) - 9:
            if data[idx] != 0xFF:
                break
            marker = data[idx + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack('>HH', data[idx + 5:idx + 9])
                return w, h
            if marker == 0xD9:
                break
            if 0xD0 <= marker <= 0xD8 or marker == 0x01:
                idx += 2
            else:
                seg_len = struct.unpack('>H', data[idx + 2:idx + 4])[0]
                idx += 2 + seg_len
        return None

    # WebP: RIFF....WEBP
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        chunk = data[12:16]
        if chunk == b'VP8 ' and len(data) >= 30:
            w = struct.unpack('<H', data[26:28])[0] & 0x3FFF
            h = struct.unpack('<H', data[28:30])[0] & 0x3FFF
            return w, h
        if chunk == b'VP8L' and len(data) >= 25:
            bits = struct.unpack('<I', data[21:25])[0]
            w = (bits & 0x3FFF) + 1
            h = ((bits >> 14) & 0x3FFF) + 1
            return w, h
        if chunk == b'VP8X' and len(data) >= 30:
            w = int.from_bytes(data[24:27], 'little') + 1
            h = int.from_bytes(data[27:30], 'little') + 1
            return w, h
        return None

    # BMP: offset 18-25 存 w/h（signed int）
    if data[:2] == b'BM' and len(data) >= 26:
        w, h = struct.unpack('<ii', data[18:26])
        return w, abs(h)

    return None
