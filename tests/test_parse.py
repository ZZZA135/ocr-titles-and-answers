"""解析模块测试：把 OCR 出来的答案页文字切成结构化题目。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answerfinder.parse import parse_questions


def test_standard_single_choice():
    lines = [
        "1. 下列关于细胞膜的叙述，正确的是（ ）",
        "A. 细胞膜不具有选择透过性",
        "B. 细胞膜的基本支架是磷脂双分子层",
        "C. 细胞膜中不含蛋白质",
        "D. 细胞膜不能控制物质进出",
        "答案：B",
    ]
    qs = parse_questions(lines, source="page1.png")
    assert len(qs) == 1
    q = qs[0]
    assert q.qno == "1"
    assert q.stem.startswith("下列关于细胞膜的叙述")
    assert q.options["A"].startswith("细胞膜不具有选择透过性")
    assert q.answer_letter == "B"
    assert q.answer_text == "细胞膜的基本支架是磷脂双分子层"
    assert q.source == "page1.png"


def test_multiline_stem_is_merged():
    lines = [
        "1. 某患者出现发热、咳嗽伴胸痛三天，",
        "血常规示白细胞升高，最可能的诊断是（ ）",
        "A. 普通感冒",
        "B. 肺炎",
        "C. 支气管哮喘",
        "D. 肺结核",
        "【答案】B",
    ]
    qs = parse_questions(lines)
    assert len(qs) == 1
    assert "血常规示白细胞升高" in qs[0].stem
    assert qs[0].answer_letter == "B"
    assert qs[0].answer_text == "肺炎"


def test_option_wrapped_line_is_merged():
    lines = [
        "1. 关于心力衰竭的治疗，下列说法正确的是（ ）",
        "A. 所有患者都应立即使用利尿剂",
        "B. 血管紧张素转换酶抑制剂可改善预后，但需要监测",
        "肾功能和血钾",
        "C. 洋地黄适用于所有心衰患者",
        "D. β受体阻滞剂急性期首选",
        "答案：B",
    ]
    qs = parse_questions(lines)
    q = qs[0]
    assert "监测肾功能和血钾" in q.options["B"]
    assert q.answer_text.startswith("血管紧张素转换酶抑制剂")


def test_multi_answer_letters():
    lines = [
        "1. 下列属于脂溶性维生素的有（ ）",
        "A. 维生素A",
        "B. 维生素B1",
        "C. 维生素D",
        "D. 维生素C",
        "答案：AC",
    ]
    qs = parse_questions(lines)
    q = qs[0]
    assert q.answer_letter == "AC"
    assert "维生素A" in q.answer_text and "维生素D" in q.answer_text


def test_no_answer_marker_yields_none():
    lines = [
        "1. 正常成人安静状态下的心率范围是（ ）",
        "A. 40~60次/分",
        "B. 60~100次/分",
        "C. 100~120次/分",
        "D. 120~140次/分",
    ]
    qs = parse_questions(lines)
    assert qs[0].answer_letter is None
    assert qs[0].answer_text is None


def test_question_type_tag_is_stripped():
    lines = [
        "1、【单选题】下列哪项不是肝性脑病的诱因（ ）",
        "A. 上消化道出血",
        "B. 大量放腹水",
        "C. 高蛋白饮食",
        "D. 低钾血症",
        "正确答案：D",
    ]
    qs = parse_questions(lines)
    q = qs[0]
    assert q.stem.startswith("下列哪项不是肝性脑病的诱因")
    assert "单选题" not in q.stem
    assert q.qtype == "单选题"


def test_various_numbering_forms():
    lines = [
        "1、第一题题干内容（ ）",
        "A. 甲",
        "B. 乙",
        "答案：A",
        "2．第二题题干内容（ ）",
        "A. 甲",
        "B. 乙",
        "答案：B",
        "第3题 第三题题干内容（ ）",
        "A. 甲",
        "B. 乙",
        "答案：A",
    ]
    qs = parse_questions(lines)
    assert [q.qno for q in qs] == ["1", "2", "3"]
    assert len(qs) == 3


def test_fullwidth_option_letters_are_normalized():
    lines = [
        "1. 下列属于革兰阳性菌的是（ ）",
        "Ａ．金黄色葡萄球菌",
        "Ｂ．大肠埃希菌",
        "Ｃ．铜绿假单胞菌",
        "Ｄ．肺炎克雷伯菌",
        "答案：Ａ",
    ]
    qs = parse_questions(lines)
    q = qs[0]
    assert q.options["A"] == "金黄色葡萄球菌"
    assert q.answer_letter == "A"
    assert q.answer_text == "金黄色葡萄球菌"


def test_answer_inline_before_options():
    lines = [
        "1. 成人正常血pH范围是（答案：C）",
        "A. 7.15~7.25",
        "B. 7.25~7.35",
        "C. 7.35~7.45",
        "D. 7.45~7.55",
    ]
    qs = parse_questions(lines)
    q = qs[0]
    assert q.answer_letter == "C"
    assert q.answer_text == "7.35~7.45"
    assert "答案" not in q.stem


def test_multiple_questions_same_page():
    lines = [
        "1. 题目一（ ）",
        "A. 甲一",
        "B. 乙一",
        "C. 丙一",
        "D. 丁一",
        "答案：A",
        "2. 题目二（ ）",
        "A. 甲二",
        "B. 乙二",
        "C. 丙二",
        "D. 丁二",
        "答案：D",
    ]
    qs = parse_questions(lines)
    assert len(qs) == 2
    assert qs[0].answer_text == "甲一"
    assert qs[1].answer_text == "丁二"


def test_ocr_noise_blank_lines_and_page_noise_ignored():
    lines = [
        "学习平台 期末考试 复习资料",
        "",
        "1. 题目一（ ）",
        "A. 甲一",
        "B. 乙一",
        "答案：B",
        "   ",
        "第 1 页 共 5 页",
    ]
    qs = parse_questions(lines)
    assert len(qs) == 1
    assert qs[0].answer_letter == "B"
    assert "第" not in qs[0].stem or qs[0].stem.startswith("题目一")


def test_stem_without_options_still_parsed():
    lines = [
        "1. 简述心力衰竭的治疗原则。",
        "答案：见教材第三章",
    ]
    qs = parse_questions(lines)
    assert len(qs) == 1
    assert qs[0].stem.startswith("简述心力衰竭的治疗原则")
    assert qs[0].answer_letter is None
