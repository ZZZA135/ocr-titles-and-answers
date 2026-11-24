"""作业详情格式（小红书“作业详情”页）解析测试。

真实 OCR 形态（872×1920 手机截图）：
  20.（单选题，2.9分）
  一个男孩是血友病A(XR)的患者，其父母和祖父母
  的表型均正常。若没有新突变，其亲属中不可能
  接患本病的人是
  外祖父          <- 字母 A 整个丢了（被 ✗ 图标挤掉）
  B.
  姨表兄弟
  姑姑            <- 字母 C 丢了（前面有 ✓）
  D
  同胞兄弟
  E.
  舅父
  正确答案C我的答案：A得O AI讲解   <- 答案区粘成一行，还带“AI讲解”
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answerfinder.parse import parse_questions, suspicious_reason

# 小红书页面右侧有个“写笔记”浮层按钮，OCR 会把它粘进句子中间
Q_WRITE_NOTE = [
    "章节",
    "讨论",
    "10.[单选题]",
    "一个表型正常的男性，其父亲为白化病患者，该",
    "与一个基因型和表型均正常的女性结婚，婚写笔记",
    "育，其子女中有",
    "A.1/2可能为白化病携带者",
    "B.1/4概率为白化病患者",
    "C.全部子女的基因型及表现型都正常",
    "D.1/4概率为白化病携带者",
    "E.1/2概率为白化病携带者",
    "我的答案：E",
    "得分：5.0分",
]


def test_write_note_overlay_is_stripped_from_stem():
    """“写笔记”是页面浮层，不能留在题干里。"""
    qs = parse_questions(Q_WRITE_NOTE)
    assert len(qs) == 1
    assert "写笔记" not in qs[0].stem
    assert qs[0].stem.endswith("其子女中有")
    assert qs[0].answer_letter == "E"
    assert qs[0].answer_text == "1/2概率为白化病携带者"

# 第一张：字母缺失 + 选项文字被拆成“字母行 / 正文行”
Q20 = [
    "作业详情",
    "17 18 19 20 21 22 23",
    "20.（单选题，2.9分）",
    "一个男孩是血友病A(XR)的患者，其父母和祖父母",
    "的表型均正常。若没有新突变，其亲属中不可能",
    "接患本病的人是",
    "外祖父",
    "B.",
    "姨表兄弟",
    "姑姑",
    "D",
    "同胞兄弟",
    "E.",
    "舅父",
    "教师批阅",
    "正确答案C我的答案：A得O AI讲解",
    "答案解析：",
]

# 第二张：字母紧贴文字 + 答案区带“得2.9分”
Q32 = [
    "作业详情",
    "29 30 31 32 33 34 35",
    "32.（单选题，2.9分）",
    "一对表现型正常的夫妇连生了3个苯丙酮尿症患",
    "儿。他们生育表型正常孩子的",
    "A.25%",
    "B.50%",
    "C.75%",
    "D.100%",
    "E.O",
    "教师批阅",
    "正确答案C,我的答案：C得2.9分",
    "答案解析：",
    "AI讲解",
]


def test_score_in_parentheses_is_not_part_of_stem():
    q = parse_questions(Q20)[0]
    assert q.qno == "20"
    assert q.qtype == "单选题"
    assert not q.stem.startswith("，2.9分")
    assert q.stem.startswith("一个男孩是血友病A")


def test_stem_lines_join_across_wraps():
    q = parse_questions(Q20)[0]
    assert "其亲属中不可能接患本病的人是" in q.stem


def test_answer_marker_glued_in_one_line():
    """正确答案C我的答案：A得O 粘成一行时，必须取出正确答案 C，不能把“解析”当答案。"""
    q = parse_questions(Q20)[0]
    assert q.answer_letter == "C"
    assert q.answer_text == "姑姑"


def test_answer_text_comes_from_options_not_analysis():
    q = parse_questions(Q32)[0]
    assert q.answer_letter == "C"
    assert q.answer_text == "75%"
    assert "解析" not in (q.answer_text or "")


def test_letters_without_marker_still_make_options():
    """A/C 的字母被 ✗/✓ 图标挤掉、只剩正文行时，按顺序补回字母。"""
    q = parse_questions(Q20)[0]
    assert list(q.options) == ["A", "B", "C", "D", "E"]
    assert q.options["A"] == "外祖父"
    assert q.options["B"] == "姨表兄弟"
    assert q.options["C"] == "姑姑"
    assert q.options["D"] == "同胞兄弟"
    assert q.options["E"] == "舅父"


def test_glued_letters_and_short_values():
    q = parse_questions(Q32)[0]
    assert list(q.options) == ["A", "B", "C", "D", "E"]
    assert q.options == {"A": "25%", "B": "50%", "C": "75%", "D": "100%", "E": "0"}


def test_no_noise_in_options():
    """教师批阅 / AI讲解 / 答案解析 不能粘进选项。"""
    q20 = parse_questions(Q20)[0]
    q32 = parse_questions(Q32)[0]
    for q in (q20, q32):
        for v in q.options.values():
            assert "教师批阅" not in v
            assert "AI讲解" not in v
            assert "解析" not in v


def test_new_format_is_not_flagged_suspicious():
    for text in (Q20, Q32):
        q = parse_questions(text)[0]
        assert suspicious_reason(q) is None, suspicious_reason(q)


def test_score_paren_without_open_paren():
    """OCR 会把“（单选题，2.9分）”的左括号弄丢，变成“单选题，2.9分）”，也要剥掉。"""
    lines = [
        "33.单选题，2.9分）",
        "一个女性将常染色体上的某一突变基因传给她孙",
        "子的概率为",
        "A.1/2",
        "B.1/4",
        "C.1/8",
        "D.1/16",
        "E.O",
        "教师批阅",
        "正确答案B，我的答案：B得2.9分",
    ]
    q = parse_questions(lines)[0]
    assert q.qno == "33"
    assert q.stem.startswith("一个女性将常染色体上")
    assert "2.9" not in q.stem
    assert q.answer_letter == "B"


def test_aijiang_icon_variant_is_noise():
    """“AI讲解”图标有时被识成“A/讲解”，不能粘到最后一个选项后面。"""
    lines = [
        "19.（单选题，2.9分）",
        "与G6PD缺陷有关的疾病为",
        "胱氨酸尿症",
        "B.",
        "白化病",
        "蚕豆病",
        "血友病",
        "E.",
        "血红蛋白病",
        "教师批阅",
        "正确答案",
        "我的答案：C得2.9分",
        "答案解析：",
        "A/讲解",
        "C",
    ]
    q = parse_questions(lines)[0]
    assert q.options["E"] == "血红蛋白病"
    assert q.options["A"] == "胱氨酸尿症"
    assert q.answer_letter == "C"
    assert q.answer_text == "蚕豆病"


def test_percentage_answer_maps_by_exact_text():
    """答案文字是“75%”这类纯符号+数字时，归一化会把它抹成空，必须靠原文精确比对。"""
    from answerfinder.match import map_answer_to_user_options

    q = parse_questions(Q32)[0]
    shuffled = {"A": "100%", "B": "75%", "C": "0", "D": "50%", "E": "25%"}
    assert map_answer_to_user_options(q, shuffled) == ["B"]


def test_two_new_format_questions_in_one_image():
    text = Q32 + [
        "33.（单选题，2.9分）",
        "下一个题目的题干",
        "A.甲",
        "B.乙",
        "C.丙",
        "D.丁",
        "E.戊",
        "正确答案B,我的答案：B得2.9分",
    ]
    qs = parse_questions(text)
    assert [q.qno for q in qs] == ["32", "33"]
    assert qs[1].answer_letter == "B"
