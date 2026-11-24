"""真实学习平台答案页格式（超星/学习通式）的解析测试。

实际看到的排版：
    21.[单选题]
    X染色体属于
    A.C组
    B.E组
    C.A组
    D.D组
    E.F组
    我的答案：A
    得分：4.4分
长截图里还混着"写笔记"悬浮按钮、"我的得分"误识别、"章节测试"标题。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answerfinder.match import split_question
from answerfinder.parse import parse_questions, suspicious_reason


PLATFORM_PAGE = [
    "21.[单选题]",
    "X染色体属于",
    "A.C组",
    "B.E组",
    "C.A组",
    "D.D组",
    "E.F组",
    "我的答案：A",
    "得分：4.4分",
]


def test_platform_format_with_my_answer():
    qs = parse_questions(PLATFORM_PAGE, source="p.png")
    assert len(qs) == 1
    q = qs[0]
    assert q.qno == "21"
    assert q.qtype == "单选题"
    assert q.stem == "X染色体属于"
    assert len(q.options) == 5
    assert q.answer_letter == "A"
    assert q.answer_text == "C组"


def test_score_line_does_not_pollute_last_option():
    qs = parse_questions([
        "1.[单选题]",
        "第20号染色体属于",
        "A.A组", "B.B组", "C.C组", "D.D组", "E.F组",
        "我的答案：E",
        "我的得分：4.3分",
    ])
    q = qs[0]
    assert q.options["E"] == "F组"
    assert q.answer_text == "F组"


def test_write_note_button_noise_is_stripped():
    qs = parse_questions([
        "22.[单选题]",
        "染色质和染色体是",
        "A.同一物质在细胞的不同时期的两种不同的",
        "形式写笔记",
        "B.同一物质在细胞的同一时期的不同表现",
        "我的答案：A写笔记",
        "得分：4.4分",
    ])
    q = qs[0]
    assert q.options["A"] == "同一物质在细胞的不同时期的两种不同的形式"
    assert q.answer_letter == "A"
    assert "写笔记" not in q.stem


def test_correct_answer_beats_my_answer():
    qs = parse_questions([
        "3.[单选题]",
        "下列属于常染色体的是",
        "A.第1号染色体",
        "B.X染色体",
        "C.Y染色体",
        "D.线粒体DNA",
        "我的答案：B",
        "正确答案：A",
    ])
    q = qs[0]
    assert q.answer_letter == "A"
    assert q.answer_text == "第1号染色体"


def test_correct_and_mine_on_same_line():
    qs = parse_questions([
        "4.[单选题]",
        "人类正常染色体数目是",
        "A.23条", "B.46条", "C.92条", "D.44条",
        "我的答案：B  正确答案：C",
    ])
    q = qs[0]
    assert q.answer_letter == "C"
    assert q.answer_text == "92条"


def test_judgement_question_with_chinese_answer():
    qs = parse_questions([
        "5.[判断题]",
        "染色质和染色体是同一物质在不同时期的不同形态。",
        "我的答案：对",
    ])
    q = qs[0]
    assert q.qtype == "判断题"
    assert q.answer_letter is None
    assert q.answer_text == "对"


def test_section_heading_is_not_question():
    qs = parse_questions([
        "章节讨论",
        "7.4 章节测试",
        "21.[单选题]",
        "X染色体属于",
        "A.C组", "B.E组", "C.A组", "D.D组", "E.F组",
        "我的答案：A",
        "得分：4.4分",
        "上一节下一节",
    ])
    assert len(qs) == 1
    assert qs[0].qno == "21"


def test_page_header_score_is_noise():
    qs = parse_questions([
        "第八章 人类染色体",
        "本次得分：100",
        "1.[单选题]",
        "根据《ISCN》的规定第1~22号染色体为",
        "A.近端着丝粒染色体",
        "B.中着丝粒染色体",
        "C.性染色体",
        "D.常染色体",
        "E.亚中着丝粒染色体",
        "我的答案：D",
        "得分：4.3分",
    ])
    q = qs[0]
    assert q.stem == "根据《ISCN》的规定第1~22号染色体为"
    assert q.answer_text == "常染色体"


def test_multiple_questions_with_platform_layout():
    qs = parse_questions(PLATFORM_PAGE + [
        "22.[单选题]",
        "染色质和染色体是",
        "A.甲", "B.乙", "C.丙", "D.丁", "E.戊",
        "我的答案：B",
        "得分：4.3分",
    ])
    assert [q.qno for q in qs] == ["21", "22"]
    assert qs[1].answer_text == "乙"


def test_ocr_x_glitch_is_normalized():
    qs = parse_questions([
        "18.[单选题]",
        "根据《ISCN》的标准，人类C组染色体数目为",
        "A.7对+Y染色体",
        "B.7对",
        "C.6对",
        "D.6对+×染色体",
        "E.7对+×染色体",
        "我的答案：E",
    ])
    q = qs[0]
    assert q.options["E"] == "7对+X染色体"
    assert q.answer_text == "7对+X染色体"


def test_suspicious_reason_flags_missing_options():
    qs = parse_questions(["1.[单选题]", "题干内容在这里怎么样", "A.甲", "B.乙", "C.丙", "我的答案：A"])
    assert suspicious_reason(qs[0]) == "只认出 3 个选项"


def test_suspicious_reason_flags_merged_option():
    merged = "螺旋化程度低，有转录活性的染色质" + "螺旋化程度低，无转录活性的染色质"
    qs = parse_questions(["1.[单选题]", "题干内容在这里怎么样", "A.甲", "B.乙", "C.丙", "D.丁",
                          "E." + merged, "我的答案：E"])
    assert "文字过长" in (suspicious_reason(qs[0]) or "")


def test_normal_question_has_no_warning():
    qs = parse_questions(PLATFORM_PAGE)
    assert suspicious_reason(qs[0]) is None


# ---------------- 试卷格式（mooc1.chaoxing.com 答题页） ----------------

EXAM_PAGE = [
    "3【单选题】根据《ISCN》的规定B组和C组染色体为",
    "A性染色体",
    "B亚中着丝粒染色体",
    "C近端着丝粒染色体",
    "D中着丝粒染色体",
    "E常染色体",
]


def test_exam_paper_question_number_without_punctuation():
    qs = parse_questions(EXAM_PAGE)
    assert len(qs) == 1
    q = qs[0]
    assert q.qno == "3"
    assert q.qtype == "单选题"
    assert q.stem == "根据《ISCN》的规定B组和C组染色体为"


def test_exam_paper_options_glued_to_letter():
    q = parse_questions(EXAM_PAGE)[0]
    assert list(q.options) == ["A", "B", "C", "D", "E"]
    assert q.options["A"] == "性染色体"
    assert q.options["B"] == "亚中着丝粒染色体"
    assert q.options["E"] == "常染色体"


def test_exam_paper_option_with_letter_and_digit():
    q = parse_questions([
        "5【单选题】人类正常染色体的类型数为",
        "A 4",
        "B 3",
        "C）5",
        "D 2",
        "E1",
    ])[0]
    assert q.options == {"A": "4", "B": "3", "C": "5", "D": "2", "E": "1"}
    assert q.stem == "人类正常染色体的类型数为"


def test_exam_text_can_be_split_for_query():
    stem, opts = split_question("\n".join(EXAM_PAGE))
    assert "B组和C组染色体" in stem
    assert opts["B"] == "亚中着丝粒染色体"
    assert len(opts) == 5


def test_two_exam_questions_in_one_screenshot():
    text = EXAM_PAGE + [
        "4【单选题】经检测发现某女性的体细胞核中有2个X小体，表明该女性的体细胞中X染色体数目",
        "A 1",
        "B 2",
        "C 4",
        "D 3",
        "E 5",
    ]
    qs = parse_questions(text)
    assert [q.qno for q in qs] == ["3", "4"]
    assert qs[1].options["D"] == "3"


# ---------- 题号被 OCR 拆到单独一行 / 粘在上一行末尾时，不能漏题 ----------

def test_question_number_alone_on_its_own_line():
    """题号和【单选题】被识别成两行，第二行还带着题干，这道题不能丢。"""
    text = [
        "1【单选题】第一题题干",
        "A 1", "B 2", "C 3", "D 4", "E 5",
        "2",
        "【单选题】第二题题干",
        "A 1", "B 2", "C 3", "D 4", "E 5",
    ]
    qs = parse_questions(text)
    assert [q.qno for q in qs] == ["1", "2"]
    assert qs[1].stem == "第二题题干"
    assert len(qs[1].options) == 5


def test_question_number_glued_to_end_of_previous_line():
    """上一题的选项行末尾粘着下一题的题号时，要在这里断行。"""
    text = [
        "1【单选题】第一题题干",
        "A 1", "B 2", "C 3", "D 4",
        "E A组2【单选题】第二题题干",
        "A 1", "B 2", "C 3", "D 4", "E 5",
    ]
    qs = parse_questions(text)
    assert [q.qno for q in qs] == ["1", "2"]
    assert qs[0].options["E"] == "A组"
    assert qs[1].stem == "第二题题干"


def test_question_number_glued_after_answer_marker():
    """学习通式：'我的答案：A21.[单选题]下一题' 也要能断开。"""
    text = [
        "21.[单选题]",
        "X染色体属于",
        "A.C组", "B.E组", "C.A组", "D.D组", "E.F组",
        "我的答案：A22.[单选题]",
        "染色质和染色体是",
        "A.同一物质在细胞的不同时期的两种形式", "B.不同物质", "C.两者结构不同", "D.不同物质不同时期",
    ]
    qs = parse_questions(text)
    assert [q.qno for q in qs] == ["21", "22"]
    assert qs[1].stem.startswith("染色质和染色体是")
