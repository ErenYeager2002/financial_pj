"""Bounded PDF compression; original bytes are never changed."""
from __future__ import annotations

import io
from pathlib import Path

import fitz
from PIL import Image

LIMIT_BYTES = 8_000_000


class CompressionError(ValueError):
    pass


def validate(data: bytes, pages: int) -> None:
    with fitz.open(stream=data, filetype="pdf") as doc:
        if len(doc) != pages:
            raise CompressionError("压缩结果页数不一致。")
        for page in doc:
            scale = min(0.2, 1200 / max(page.rect.width, page.rect.height))
            page.get_pixmap(matrix=fitz.Matrix(scale, scale))


def compressed_images(source: bytes, quality: int, side: int | None) -> bytes:
    with fitz.open(stream=source, filetype="pdf") as doc:
        seen = set()
        for page in doc:
            for info in page.get_images(full=True):
                xref, mask = info[:2]
                if xref in seen or mask:
                    continue
                seen.add(xref)
                image = doc.extract_image(xref)
                if not image:
                    continue
                with Image.open(io.BytesIO(image["image"])) as opened:
                    if opened.mode == "1":
                        continue
                    rgb = opened.convert("RGB")
                    if side:
                        rgb.thumbnail((side, side), Image.Resampling.LANCZOS)
                    buffer = io.BytesIO()
                    rgb.save(buffer, format="JPEG", quality=quality, optimize=True)
                    encoded = buffer.getvalue()
                    if len(encoded) < len(image["image"]):
                        page.replace_image(xref, stream=encoded)
        return doc.tobytes(garbage=4, deflate=True)


def rasterized(source: bytes, dpi: int) -> bytes:
    with fitz.open(stream=source, filetype="pdf") as original, fitz.open() as result:
        for page in original:
            # Cap unusually large page dimensions as well as resolution.
            scale = min(dpi / 72, 2400 / max(page.rect.width, page.rect.height))
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            output_page = result.new_page(width=page.rect.width, height=page.rect.height)
            output_page.insert_image(output_page.rect, stream=pix.tobytes("jpeg", jpg_quality=70))
        return result.tobytes(garbage=4, deflate=True)


def compress_pdf(source: Path, target: Path, progress=lambda message: None) -> dict:
    if source.resolve() == target.resolve() or target.exists():
        raise CompressionError("输出必须使用新的副本路径。")
    raw = source.read_bytes()
    try:
        with fitz.open(stream=raw, filetype="pdf") as doc:
            if doc.needs_pass:
                raise CompressionError("PDF 需要密码，请先解除密码后再上传。")
            if not len(doc):
                raise CompressionError("PDF 没有可处理的页面。")
            if doc.get_sigflags() > 0 and len(raw) >= LIMIT_BYTES:
                raise CompressionError("PDF 含签名，压缩会使签名失效，请上传未签名副本。")
            pages = len(doc)
            if len(raw) < LIMIT_BYTES:
                candidate, mode = raw, "无需压缩"
            else:
                candidate, mode = doc.tobytes(garbage=4, deflate=True), "无损整理"
        if len(candidate) >= LIMIT_BYTES:
            for quality, side in [(95, None), (88, None), (80, 2400), (72, 1800), (60, 1400), (50, 1000)]:
                progress("正在优化图片质量和分辨率")
                attempt = compressed_images(raw, quality, side)
                if len(attempt) < len(candidate):
                    candidate, mode = attempt, "图片压缩"
                if len(candidate) < LIMIT_BYTES:
                    break
        warnings = []
        if len(candidate) >= LIMIT_BYTES:
            for dpi in [120, 96, 72, 50, 36]:
                progress("正在生成适合上传的页面副本")
                candidate = rasterized(raw, dpi)
                mode = "页面图像压缩"
                if len(candidate) < LIMIT_BYTES:
                    warnings.append("文件采用页面图像压缩，文字不可直接选取，链接及表单交互不保留；请使用原件进行编辑。")
                    break
        if len(candidate) >= LIMIT_BYTES:
            raise CompressionError("保留全部页面后仍无法压缩至 8MB 内，请拆分为多个 PDF。")
        progress("正在核对页数、文件大小和页面可读性")
        validate(candidate, pages)
        target.write_bytes(candidate)
        return {"original_bytes": len(raw), "output_bytes": len(candidate), "pages": pages,
                "mode": mode, "warnings": warnings}
    except CompressionError:
        raise
    except Exception as exc:
        raise CompressionError("PDF 无法读取或压缩，请检查文件是否完整。") from exc
