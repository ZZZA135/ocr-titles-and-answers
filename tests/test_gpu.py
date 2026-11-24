"""GPU（DirectML）开关的测试：默认能用就用、关掉就纯 CPU、两者识别结果一致。"""
import pytest
from PIL import Image, ImageDraw, ImageFont

from answerfinder.ocr import BACKEND_CPU, BACKEND_GPU, OcrEngine, dml_available

FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"


def _make_image(tmp_path):
    img = Image.new("RGB", (900, 240), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 36)
    draw.text((30, 40), "染色体核型分析与C组染色体", fill="black", font=font)
    draw.text((30, 130), "A 性染色体  B 常染色体", fill="black", font=font)
    path = tmp_path / "gpu_sample.png"
    img.save(path)
    return path


def test_dml_flag_is_boolean():
    assert isinstance(dml_available(), bool)


def test_gpu_engine_reports_gpu_when_available(tmp_path):
    if not dml_available():
        pytest.skip("本机没有 DirectML 可用")
    engine = OcrEngine(use_gpu=True)
    assert engine.backend == "未初始化"
    engine.image_text(_make_image(tmp_path))
    assert engine.backend == BACKEND_GPU


def test_gpu_can_be_turned_off(tmp_path):
    engine = OcrEngine(use_gpu=False)
    assert engine.backend == "未初始化"
    engine.image_text(_make_image(tmp_path))
    assert engine.backend == BACKEND_CPU


def test_gpu_and_cpu_read_the_same_text(tmp_path):
    if not dml_available():
        pytest.skip("本机没有 DirectML 可用")
    path = _make_image(tmp_path)
    cpu_lines = OcrEngine(use_gpu=False).image_lines(path)
    gpu_lines = OcrEngine(use_gpu=True).image_lines(path)
    assert cpu_lines, "CPU 识别没有出任何文字"
    assert gpu_lines == cpu_lines


def test_exam_paper_text_survives_ocr(tmp_path):
    """试卷式排版（题号紧贴题型、字母紧贴文字）OCR 后要能切成题目。"""
    from answerfinder.parse import parse_questions

    img = Image.new("RGB", (1400, 420), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 34)
    draw.text((40, 30), "3【单选题】根据《ISCN》的规定B组和C组染色体为", fill="black", font=font)
    draw.text((80, 100), "A  性染色体", fill="black", font=font)
    draw.text((80, 170), "B  亚中着丝粒染色体", fill="black", font=font)
    draw.text((80, 240), "C  常染色体", fill="black", font=font)
    draw.text((80, 310), "D  中着丝粒染色体", fill="black", font=font)
    path = tmp_path / "exam_sample.png"
    img.save(path)

    lines = OcrEngine(use_gpu=False).image_lines(path)
    qs = parse_questions(lines)
    assert len(qs) == 1
    q = qs[0]
    assert q.qno == "3"
    assert "B组和C组染色体" in q.stem
    assert list(q.options) == ["A", "B", "C", "D"]
