"""图片工具：尺寸解析 + LLM 送入前压缩。"""

import io
import struct

from PIL import Image


def compress_for_llm(data: bytes, *, max_long_side: int = 1280,
                     quality: int = 85) -> tuple[bytes, str]:
    """将图片缩放到长边 ≤ max_long_side 并转为 JPEG。

    返回 (压缩后字节, 新文件名)。
    如果原图已经足够小（长边 ≤ 阈值且 < 200KB），则不做处理。
    """
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")  # 去 alpha，JPEG 不支持

    w, h = img.size
    long_side = max(w, h)

    # 如果已经够小，跳过压缩
    if long_side <= max_long_side and len(data) < 200 * 1024:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue(), "image.jpg"

    # 等比缩放
    if long_side > max_long_side:
        scale = max_long_side / long_side
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue(), "image.jpg"


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
