"""版式测试：同一水平行里被大块空白隔开的两栏（左侧目录 + 正文）要拆成两行。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answerfinder.ocr import OcrEngine


def _box(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def test_two_columns_on_same_row_become_two_lines():
    blocks = [
        (_box(10, 100, 260, 140), "8.1染色体畸变发生的原因", 0.9),
        (_box(530, 102, 1600, 142), "1【单选题】为了发现更多更细微的染色体结构异常,可采用", 0.9),
    ]
    lines = OcrEngine._to_lines(blocks)
    assert lines == ["8.1染色体畸变发生的原因", "1【单选题】为了发现更多更细微的染色体结构异常,可采用"]


def test_nearby_pieces_on_same_row_still_join():
    blocks = [
        (_box(80, 100, 110, 140), "A", 0.9),
        (_box(130, 100, 400, 140), "性染色体", 0.9),
    ]
    lines = OcrEngine._to_lines(blocks)
    assert lines == ["A性染色体"]


def test_option_letter_and_body_stay_one_line_for_exam_layout():
    blocks = [
        (_box(530, 100, 1600, 145), "3【单选题】根据《ISCN》的规定B组和C组染色体为", 0.9),
        (_box(600, 180, 640, 220), "A", 0.9),
        (_box(660, 180, 1600, 220), "性染色体", 0.9),
        (_box(600, 260, 640, 300), "B", 0.9),
        (_box(660, 260, 1600, 300), "亚中着丝粒染色体", 0.9),
    ]
    lines = OcrEngine._to_lines(blocks)
    assert lines[0].startswith("3【单选题】")
    assert lines[1] == "A性染色体"
    assert lines[2] == "B亚中着丝粒染色体"


# ---------------- 左侧目录栏：只有确有大面积侧栏时才丢 ----------------

def test_left_sidebar_column_is_dropped():
    blocks = [(_box(20, 100 + i * 60, 280, 140 + i * 60), f"8.{i}章节测试", 0.9) for i in range(6)]
    blocks.append((_box(560, 100, 1800, 140), "1【单选题】为了发现更多更细微的染色体结构异常,可采用", 0.9))
    blocks.append((_box(600, 180, 640, 220), "A", 0.9))
    blocks.append((_box(660, 180, 1800, 220), "C显带", 0.9))
    lines = OcrEngine._to_lines(blocks, width=2000)
    assert lines == ["1【单选题】为了发现更多更细微的染色体结构异常,可采用", "A C显带"]


def test_narrow_mobile_screenshot_keeps_short_options():
    blocks = [(_box(40, 100 + i * 60, 300, 140 + i * 60), f"{L} 选项文字", 0.9)
              for i, L in enumerate("ABCDE")]
    lines = OcrEngine._to_lines(blocks, width=1080)
    assert len(lines) == 5


def test_single_column_with_short_options_is_kept():
    blocks = [(_box(60, 100 + i * 60, 260, 140 + i * 60), f"{L} 4", 0.9)
              for i, L in enumerate("ABCDE")]
    lines = OcrEngine._to_lines(blocks, width=1800)
    assert len(lines) == 5


def test_mobile_width_never_drops_short_left_blocks():
    """手机截图（1080 宽）里的独立字母块不能被当成侧栏丢掉。"""
    blocks = [(_box(50, 100 + i * 60, 90, 140 + i * 60), L, 0.9) for i, L in enumerate("BCDE")]
    blocks.append((_box(500, 100, 1040, 140), "染色体核型分析", 0.9))
    lines = OcrEngine._to_lines(blocks, width=1080)
    assert sorted(lines) == sorted(["B", "C", "D", "E", "染色体核型分析"])


def test_single_column_page_keeps_short_left_options_at_1400_width():
    """手机长图会被放大到 1400 宽：整页只有一栏时，靠左的短选项不能被当成目录删掉。"""
    blocks = [(_box(84, 100 + i * 60, 240, 140 + i * 60), f"{L}.{v}", 0.9)
              for i, (L, v) in enumerate(zip("ABCDE", ["C组", "E组", "A组", "D组", "F组"]))]
    blocks.append((_box(84, 520, 900, 560), "人类染色体中按着丝粒位置可分为几组", 0.9))
    blocks.append((_box(1240, 30, 1356, 70), "讨论", 0.9))
    blocks.append((_box(600, 470, 720, 510), "写笔记", 0.9))
    lines = OcrEngine._to_lines(blocks, width=1400)
    assert len(lines) == 8
    assert any("C组" in ln for ln in lines)
