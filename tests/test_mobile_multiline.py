"""手机“作业详情”页的三种失败形态（真实 OCR 行）。

1) 题干以英文字母开头（`a珠蛋白…`、`ArchibaldGarrod(1857-1936)…`）被当成选项 A；
2) 选项字母只剩 "A." / "B." 这种空壳，正文跟在后面 → 正文错配到最后一个字母；
3) 连续多行正文各是一道选项，但字母整行丢了（C、D 没有字母）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answerfinder.parse import parse_questions, suspicious_reason

# _17_ 第13题：题干首行以 Archibald 开头，被当成选项 A
Q13 = [
    "作业详情",
    "10 11 12 13 14 15 16",
    "13.（单选题，2.8分）",
    "ArchibaldGarrod(1857-1936)曾深入研究和报道",
    "的黑尿酸尿症疾病，患者缺乏",
    "A.苯丙氨酸羟化酶",
    "B.酶氨酸酶",
    "C.溶酶体酶",
    "D.黑尿酸氧化酶",
    "E.半乳糖激酶",
    "教师批阅",
    "正确答案D我的答案：D得2.8分",
    "答案解析：",
    "AI讲解",
]

# _5_ 第1题：题干首行以 “a珠蛋白…” 开头（α 被识成小写 a）
Q1 = [
    "作业详情",
    "1",
    "2",
    "3",
    "4",
    "5",
    "1（单选题，2.8分）",
    "a珠蛋白位于人类第几号染色体",
    "A.6",
    "B.11",
    "C.14",
    "D.16",
    "E.22",
    "教师批阅",
    "正确答案",
    "我的答案：D得2.8分",
    "答案解析：",
    "AI讲解",
]

# (5) 第21题：只有 B./E. 两个字母行，中间三行正文各是一个选项（A 的字母丢了）
Q21 = [
    "作业详情",
    "18",
    "20 21 22 23 24",
    "21.（单选题，2.9分）",
    "具有精神发育迟缓、白内障、肝硬化征候群的遗",
    "传病是",
    "PKU",
    "B.",
    "GPD缺乏症",
    "半乳糖血症",
    "尿黑酸尿症",
    "E.",
    "白化病",
    "教师批阅",
    "正确答案C我的答案：C得2.9分",
    "AI讲解",
    "答案解析：",
]

# (16) 第29题：A./B./E. 三个字母行，正文五行，C、D 的字母丢了
Q29 = [
    "作业详情",
    "26 27 28 29 30 31 32",
    "29.（单选题，2.9分）",
    "某男性患者，8岁，精神发育迟缓皮肤、毛发和虹",
    "膜色素减退，头发呈赤褐色癫痫，湿疹，特殊的",
    "鼠样臭味尿。最可能的诊断是",
    "A.",
    "眼皮肤白化病川型",
    "B.",
    "典型的苯丙酮尿症",
    "Duchenne型肌营养不良",
    "家族性高胆固醇血症",
    "E.",
    "尿黑酸血症",
    "教师批阅",
    "正确答案B，我的答案：B得2.9 AI讲解",
    "答案解析：",
    "B",
]


def test_stem_starting_with_latin_letter_is_not_option_a():
    q = parse_questions(Q13)[0]
    assert q.stem.startswith("ArchibaldGarrod")
    assert "患者缺乏" in q.stem
    assert q.options["A"] == "苯丙氨酸羟化酶"
    assert q.options["D"] == "黑尿酸氧化酶"
    assert q.answer_letter == "D"


def test_stem_starting_with_lowercase_greek_is_not_option_a():
    q = parse_questions(Q1)[0]
    assert q.stem == "a珠蛋白位于人类第几号染色体"
    assert q.options == {"A": "6", "B": "11", "C": "14", "D": "16", "E": "22"}


def test_consecutive_bodies_fill_letters_in_order():
    q = parse_questions(Q21)[0]
    assert q.stem == "具有精神发育迟缓、白内障、肝硬化征候群的遗传病是"
    assert q.options == {"A": "PKU", "B": "GPD缺乏症", "C": "半乳糖血症",
                         "D": "尿黑酸尿症", "E": "白化病"}
    assert q.answer_letter == "C"
    assert q.answer_text == "半乳糖血症"


def test_letter_only_markers_use_two_line_layout():
    q = parse_questions(Q29)[0]
    assert q.options == {"A": "眼皮肤白化病川型", "B": "典型的苯丙酮尿症",
                         "C": "Duchenne型肌营养不良", "D": "家族性高胆固醇血症",
                         "E": "尿黑酸血症"}
    assert q.answer_letter == "B"
    assert q.answer_text == "典型的苯丙酮尿症"
    assert suspicious_reason(q) is None


def test_trailing_analysis_letter_not_turned_into_option():
    for text in (Q21, Q29):
        q = parse_questions(text)[0]
        assert len(q.options) == 5
