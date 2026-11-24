"""OCR 全链路测试：渲染一张中文题目图 -> 识别 -> 解析 -> 匹配答案。

这条测试验证的是真实使用路径：图片进，答案文字出。
"""
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answerfinder.ocr import OcrEngine
from answerfinder.parse import parse_questions
from answerfinder.match import find_matches

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


def _font(size=34):
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    pytest.skip("本机没有中文字体，跳过 OCR 渲染测试")


def _make_image(path, lines, size=34, width=1100):
    font = _font(size)
    pad, gap = 30, 14
    heights = []
    for ln in lines:
        heights.append(font.getbbox(ln)[3] - font.getbbox(ln)[1] + 2 * gap)
    img = Image.new("RGB", (width, pad * 2 + sum(heights)), "white")
    d = ImageDraw.Draw(img)
    y = pad
    for ln, h in zip(lines, heights):
        d.text((pad, y), ln, font=font, fill="black")
        y += h
    img.save(path)
    return path


def test_ocr_pipeline_reads_question_and_answer(tmp_path):
    lines = [
        "1. 下列关于细胞膜的叙述，正确的是（ ）",
        "A. 细胞膜不具有选择透过性",
        "B. 细胞膜的基本支架是磷脂双分子层",
        "C. 细胞膜中不含蛋白质",
        "D. 细胞膜不能控制物质进出",
        "答案：B",
    ]
    img = _make_image(tmp_path / "q1.png", lines)

    engine = OcrEngine()
    text_lines = engine.image_lines(img)
    assert text_lines, "OCR 应识别出文字"

    qs = parse_questions(text_lines, source="q1.png")
    assert len(qs) == 1
    q = qs[0]
    assert len(q.options) == 4
    assert "细胞膜" in q.stem
    assert q.answer_letter == "B"
    assert "磷脂" in (q.answer_text or "")


def test_ocr_pipeline_matches_shuffled_option_question(tmp_path):
    # 答案页里答案是“磷脂双分子层”；用户卷面上这个选项排在 C
    lines = [
        "1. 下列关于细胞膜的叙述，正确的是（ ）",
        "A. 细胞膜不具有选择透过性",
        "B. 细胞膜的基本支架是磷脂双分子层",
        "C. 细胞膜中不含蛋白质",
        "D. 细胞膜不能控制物质进出",
        "答案：B",
    ]
    img = _make_image(tmp_path / "q2.png", lines)
    engine = OcrEngine()
    qs = parse_questions(engine.image_lines(img))
    user_text = ("下列关于细胞膜的叙述，正确的是（ ）\n"
                 "A. 细胞膜中不含蛋白质\n"
                 "B. 细胞膜不能控制物质进出\n"
                 "C. 细胞膜的基本支架是磷脂双分子层\n"
                 "D. 细胞膜不具有选择透过性")
    hits = find_matches(user_text, qs)
    assert hits and hits[0].question.qno == "1"
