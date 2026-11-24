"""超长截图（小红书/学习通长图）分块识别的测试。"""
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answerfinder.ocr import OcrEngine
from answerfinder.parse import parse_questions

FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"


def _font(size=44):
    if not Path(FONT_PATH).exists():
        pytest.skip("本机没有中文字体")
    return ImageFont.truetype(FONT_PATH, size)


def _tall_image(path, blocks, width=980, pad=24, gap=30):
    font = _font()
    lines = []
    for block in blocks:
        for ln in block:
            lines.append(ln)
        lines.append("")
    heights = []
    for ln in lines:
        heights.append(24 if not ln else font.getbbox(ln)[3] - font.getbbox(ln)[1] + gap)
    img = Image.new("RGB", (width, pad * 2 + sum(heights)), "white")
    d = ImageDraw.Draw(img)
    y = pad
    for ln, h in zip(lines, heights):
        if ln:
            d.text((pad, y), ln, font=font, fill="black")
        y += h
    img.save(path)
    return path


BLOCK_A = [
    "1.[单选题]",
    "X染色体属于",
    "A.C组",
    "B.E组",
    "C.A组",
    "D.D组",
    "E.F组",
    "我的答案：A",
    "得分：4.4分",
]
BLOCK_B = [
    "2.[单选题]",
    "常染色质是间期细胞核中",
    "A.螺旋化程度高，无转录活性的染色质",
    "B.螺旋化程度高，有转录活性的染色质",
    "C.螺旋化程度低，有转录活性的染色质",
    "D.螺旋化程度低，无转录活性的染色质",
    "我的答案：C",
    "得分：4.4分",
]
BLOCK_C = [
    "3.[单选题]",
    "SRY基因位于",
    "A.Xp11.2",
    "B.Xq11.2",
    "C.Yq11.31",
    "D.Yp11.31",
    "我的答案：D",
    "得分：4.4分",
]


def test_tall_image_is_split_without_duplicating_lines(tmp_path):
    img = _tall_image(tmp_path / "tall.png", [BLOCK_A, BLOCK_B, BLOCK_C])
    assert Image.open(img).size[1] > 1300, "这张图应高到触发分块"
    engine = OcrEngine()
    lines = engine.image_lines(img)
    qs = parse_questions(lines, source=str(img))
    assert len(qs) == 3, f"应解析出 3 题，实际 {len(qs)} 题：{lines}"
    assert [q.qno for q in qs] == ["1", "2", "3"]
    assert qs[0].answer_text == "C组"
    assert qs[1].answer_letter == "C"
    assert "有转录活性" in (qs[1].answer_text or "")
    assert qs[2].answer_text == "Yp11.31"


def test_seam_does_not_duplicate_option_letters(tmp_path):
    img = _tall_image(tmp_path / "tall2.png", [BLOCK_A, BLOCK_B, BLOCK_C])
    lines = OcrEngine().image_lines(img)
    joined = "\n".join(lines)
    assert joined.count("3.[单选题]") == 1
