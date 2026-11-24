"""OCR 封装：图片 -> 按阅读顺序排好的文字行。

用 RapidOCR（PP-OCR 中文模型，纯本地推理，不联网、不上传图片）。
有可用显卡时走 DirectML（Windows 通用 GPU 接口，NVIDIA/AMD/Intel 都支持），
实测比纯 CPU 快约 2.8 倍、识别结果完全一致；不可用时自动退回 CPU。
长截图（小红书/学习通的整页长图）会自动按“空白行”切块识别，避免缩得太小认不出字。
"""
from __future__ import annotations

import re
import sys
import threading
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

_CJK = r"[\u4e00-\u9fff]"
_MIN_WIDTH = 1400          # 实测 1400 比 1600/1800 更稳（再大反而会把相邻两行选项粘成一行）
_MAX_WIDTH = 2600
_TILE_MAX = 1300           # 单块最高像素（再高会被检测模型压缩，字就糊了）
_TILE_MIN = 700            # 单个分块的最小高度，避免切得过碎
_TILE_TAIL_MIN = 120       # 收尾不足这个高度就并进上一块（碎片块会让识别直接失败）
_DARK_THRESHOLD = 200      # 灰度低于此值算“有字”
_BLANK_ROW_MAX_DARK = 1    # 一行里暗点少于这个数就当空白行

# 多栏版式（如四栏卡片式答案页）：按横向覆盖空隙切栏
_COL_BINS = 400            # 横向切成多少格来统计覆盖度
_COL_GUTTER_FRAC = 0.02    # 栏缝至少占页宽 2%
_COL_LOW_FRAC = 0.03       # 覆盖度低于最大覆盖度的 3% 算“这一竖线没字”

BACKEND_GPU = "GPU (DirectML)"
BACKEND_CPU = "CPU"


def dml_available() -> bool:
    """本机能不能用 DirectML 跑 GPU 推理（需要 onnxruntime-directml，且系统为 Win10+）。"""
    if sys.platform != "win32":
        return False
    try:
        import onnxruntime as ort
        return "DmlExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


def _session_providers(engine) -> set:
    """读引擎内部真正生效的执行提供程序，确认 GPU 没被静默回退成 CPU。"""
    found = set()
    for name in ("text_det", "text_cls", "text_rec"):
        obj = getattr(engine, name, None)
        for holder in (obj, getattr(obj, "session", None), getattr(obj, "infer", None)):
            if holder is None:
                continue
            inner = getattr(holder, "session", None) or holder
            getter = getattr(inner, "get_providers", None)
            if callable(getter):
                try:
                    found.update(getter())
                except Exception:
                    pass
    return found


class OcrEngine:
    """懒加载的 RapidOCR 封装（首次调用约 1~2 秒）。"""

    def __init__(self, use_gpu: Optional[bool] = None):
        self._engine = None
        self._lock = threading.Lock()
        self.want_gpu = dml_available() if use_gpu is None else bool(use_gpu)
        self.backend = "未初始化"

    def _create(self):
        from rapidocr_onnxruntime import RapidOCR

        if self.want_gpu and dml_available():
            try:
                engine = RapidOCR(det_use_dml=True, rec_use_dml=True, cls_use_dml=True)
                if "DmlExecutionProvider" in _session_providers(engine):
                    self.backend = BACKEND_GPU
                    return engine
            except Exception:
                pass
        self.backend = BACKEND_CPU
        return RapidOCR()

    def _ensure_engine(self):
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    self._engine = self._create()
        return self._engine

    @staticmethod
    def _prepare_image(src):
        from PIL import Image, ImageOps

        if isinstance(src, (str, Path)):
            img = Image.open(str(src))
        elif isinstance(src, Image.Image):
            img = src
        else:
            img = Image.fromarray(src)
        img = ImageOps.exif_transpose(img).convert("RGB")
        w, h = img.size
        if w < _MIN_WIDTH:
            scale = _MIN_WIDTH / w
        elif w > _MAX_WIDTH:
            scale = _MAX_WIDTH / w
        else:
            scale = 1.0
        if scale != 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        return img

    @staticmethod
    def _tiles(img) -> Iterator:
        """把超长图沿空白行切成互不重叠的块，保证文字行不会被切断。"""
        import numpy as np

        w, h = img.size
        if h <= _TILE_MAX:
            yield img
            return
        gray = np.asarray(img.convert("L"))
        dark_per_row = (gray < _DARK_THRESHOLD).sum(axis=1)
        pos = 0
        while pos < h:
            if h - pos <= _TILE_MAX:
                yield img.crop((0, pos, w, h))
                return
            lo, hi = pos + _TILE_MIN, min(pos + _TILE_MAX, h)
            window = dark_per_row[lo:hi]
            blank = np.flatnonzero(window <= _BLANK_ROW_MAX_DARK)
            cut = lo + int(blank[-1]) if blank.size else lo + int(np.argmin(window))
            cut = max(cut, pos + _TILE_MIN // 2)
            # 剩下的尾巴太短就并进这一块，别切出几像素的碎片（OCR 会直接报错）
            if h - cut < _TILE_TAIL_MIN:
                cut = h
            yield img.crop((0, pos, w, cut))
            pos = cut

    def _raw_blocks(self, path_or_array) -> List[Tuple]:
        """整图识别（不分块）——调试用。"""
        import numpy as np

        engine = self._ensure_engine()
        img = self._prepare_image(path_or_array)
        result, _ = engine(np.asarray(img))
        return result or []

    @staticmethod
    def _to_items(blocks, y_offset: float = 0.0) -> List[dict]:
        items = []
        for box, text, score in blocks:
            if not text or not str(text).strip():
                continue
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            items.append({
                "text": str(text).strip(),
                "cy": y_offset + sum(ys) / len(ys),
                "x": min(xs),
                "x2": max(xs),
                "h": max(ys) - min(ys),
            })
        return items

    @staticmethod
    def _rows_to_lines(items: List[dict]) -> List[str]:
        """把文字块按行拼接（同一行的多块拼成一行，行内大空白继续分栏）。"""
        if not items:
            return []
        items.sort(key=lambda d: (d["cy"], d["x"]))
        median_h = sorted(d["h"] for d in items)[len(items) // 2] or 20
        rows: List[List[dict]] = []
        for it in items:
            if rows and abs(it["cy"] - rows[-1][0]["cy"]) <= median_h * 0.6:
                rows[-1].append(it)
            else:
                rows.append([it])
        lines = []
        gutter = median_h * 2.5      # 同一行里超过这个宽度的空白，视为分栏而不是同一句话
        for row in rows:
            row.sort(key=lambda d: d["x"])
            segments: List[List[dict]] = [[row[0]]]
            for prev, it in zip(row, row[1:]):
                if it["x"] - prev["x2"] > gutter:
                    segments.append([it])
                else:
                    segments[-1].append(it)
            for seg in segments:
                text = ""
                for i, it in enumerate(seg):
                    if i and _needs_space(seg[i - 1]["text"], it["text"]):
                        text += " "
                    text += it["text"]
                lines.append(text.strip())
        return [re.sub(r"[ \t]+", " ", ln) for ln in lines if ln.strip()]

    @staticmethod
    def _lines_from_items(items: List[dict], width: Optional[int] = None) -> List[str]:
        """整页文字块 → 文字行。多栏版式先按纵向栏带切开，再逐栏自上而下拼行。"""
        if not items:
            return []
        bands = _column_bands(items, width) if width else []
        if len(bands) > 1 and _balanced_bands(items, bands, width):
            grouped: List[List[dict]] = [[] for _ in bands]
            for it in items:
                grouped[_band_index(it, bands)].append(it)
            out: List[str] = []
            for band_items in grouped:
                out.extend(OcrEngine._rows_to_lines(band_items))
            return out
        if width:
            items = _drop_side_columns(items, width)
        if not items:
            return []
        return OcrEngine._rows_to_lines(items)

    @staticmethod
    def _to_lines(blocks, width: Optional[int] = None) -> List[str]:
        return OcrEngine._lines_from_items(OcrEngine._to_items(blocks), width)

    def image_lines(self, path_or_array) -> List[str]:
        """返回按阅读顺序排列的文字行（长图按块识别后顺序拼接）。"""
        import numpy as np

        engine = self._ensure_engine()
        img = self._prepare_image(path_or_array)
        items: List[dict] = []
        pos = 0
        for tile in self._tiles(img):
            result, _ = engine(np.asarray(tile))
            if result:
                items.extend(self._to_items(result, y_offset=pos))
            pos += tile.size[1]
        return self._lines_from_items(items, width=img.size[0])

    def image_text(self, path_or_array) -> str:
        return "\n".join(self.image_lines(path_or_array))


def _column_bands(items: List[dict], width: int) -> List[Tuple[int, int]]:
    """按文字框的横向覆盖空隙，把整页切成若干竖栏。

    真栏之间有一段“几乎没有字框覆盖”的竖条；栏内的每一根竖线都会被大量
    行覆盖，所以用“相对最大覆盖度”判空白，比按绝对像素更稳。
    """
    if not items or not width:
        return []
    bins = _COL_BINS
    cover = [0] * bins
    for it in items:
        b0 = int(it["x"] / width * bins)
        b1 = int(it["x2"] / width * bins)
        for b in range(max(0, b0), min(bins - 1, b1) + 1):
            cover[b] += 1
    thr = max(1, int(max(cover) * _COL_LOW_FRAC))
    runs: List[Tuple[int, int]] = []
    start = None
    for b in range(bins):
        if cover[b] <= thr:
            if start is None:
                start = b
        elif start is not None:
            runs.append((start, b - 1))
            start = None
    if start is not None:
        runs.append((start, bins - 1))
    minb = max(2, int(bins * _COL_GUTTER_FRAC))
    cuts = [(a, b) for a, b in runs if (b - a + 1) >= minb and a > 0 and b < bins - 1]
    if not cuts:
        return []
    edges = [0]
    for a, b in cuts:
        edges.append(int(a / bins * width))
        edges.append(int((b + 1) / bins * width))
    edges.append(width)
    bands = [(edges[i], edges[i + 1]) for i in range(0, len(edges) - 1, 2)]
    return [bd for bd in bands if bd[1] > bd[0]]


def _band_index(it: dict, bands: List[Tuple[int, int]]) -> int:
    """按“和哪一栏重叠最多”归类（长行可能跨过栏缝，按中心点会掉进缝里）。"""
    best, best_ov = 0, -1
    for idx, (x0, x1) in enumerate(bands):
        ov = min(it["x2"], x1) - max(it["x"], x0)
        if ov > best_ov:
            best, best_ov = idx, ov
    return best


def _balanced_bands(items: List[dict], bands: List[Tuple[int, int]], width: int) -> bool:
    """判断切出来的“栏”到底是不是并排的文字栏。

    四栏答案页每栏文字量相当；而“正文 + 右侧悬浮面板”这类版式，第二栏
    只有寥寥几行，交给 _drop_side_columns 处理更安全。
    最边上的窄条如果只是三五个字的目录/按钮短词，也当侧栏处理。
    """
    counts: List[int] = []
    max_lens: List[int] = []
    for x0, x1 in bands:
        band = [it for it in items if x0 <= (it["x"] + it["x2"]) / 2 < x1]
        counts.append(len(band))
        max_lens.append(max((len(it["text"]) for it in band), default=0))
    if not counts or min(counts) == 0:
        return False
    if min(counts) < max(counts) * 0.25:
        return False
    if not all(x1 - x0 >= width * 0.08 for x0, x1 in bands):
        return False
    longest = max(max_lens) or 1
    first_w = bands[0][1] - bands[0][0]
    last_w = bands[-1][1] - bands[-1][0]
    # 侧栏特征：贴着页边、很窄、而且全是短词（目录条目、悬浮按钮）
    if first_w < width * 0.18 and max_lens[0] < longest * 0.5:
        return False
    if last_w < width * 0.12 and max_lens[-1] < longest * 0.5:
        return False
    return True


def _needs_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return not (re.match(_CJK, left[-1]) or re.match(_CJK, right[0]))


def _drop_side_columns(items: List[dict], width: int) -> List[dict]:
    """丢掉落在大面积侧栏里的小段文字（左侧目录、右侧悬浮块）。

    只在“确实存在侧栏”时才动手：侧栏候选块至少 4 段，且画面中段有正文。
    手机/平板截图（宽度小于 1400）一律不动，那里的独立字母块就是选项本身。
    这样手机窄截图、单栏页面里的短选项（如 "A 4"）不会被误删。
    """
    if width < 1400:
        return items
    candidates = [it for it in items
                  if (it["x2"] <= width * 0.18 or it["x"] >= width * 0.80)
                  and len(it["text"]) <= 30]
    if len(candidates) < 4 or len(candidates) >= len(items):
        return items
    others = [it for it in items if not any(it is c for c in candidates)]
    # 真侧栏的标志：正文整体右移（绝大多数文字都从画面 20% 之后开始）。
    # 单栏长图（手机页放大到 1400 宽）里，选项本身也在最左边，这里就会失败，不做任何删除。
    if sum(1 for it in others if it["x"] >= width * 0.20) < len(others) * 0.75:
        return items
    if not any(width * 0.20 <= it["x"] <= width * 0.70 for it in items):
        return items
    return others
