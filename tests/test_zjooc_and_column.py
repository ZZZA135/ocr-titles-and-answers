"""两种新平台格式：

1) 浙江高校开放课程平台（zjooc）章节测试卷面：
    1.
    3.5分
    患者男性，56岁。……该医生的行为违背了下列原则中的（）
    A.有利原则
    B.公正原则
   —— 题号独占一行、分值单独一行，中间没有“【单选题】”标签。

2) 医学伦理学“第二章测试题”答案页（四栏卡片式）：
    第 1 题 （2.5分）        单选题
    违背尊重原则的是()
    A. 医师消毒观念不强,造成交叉感染
    B. 医师满足病人的一切保密要求  ✓
    正确答案：
    B
"""
import sys
from pathlib import Path

import pytest
from PIL import ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answerfinder.ocr import OcrEngine
from answerfinder.parse import parse_questions, suspicious_reason

# ---------------- zjooc：题号一行、分值一行 ----------------

ZJOOC = [
    "第二章测试题",
    "1.单选题(共36题)",
    "1.",
    "3.5分",
    "患者男性，56岁。因左小腿丹毒复发到某医院就诊，医生给他开了价格较",
    "昂贵的新抗生素，患者自费而要求改用上次发病时有效目便宜的青霉",
    "素。但是，医生却不耐烦地说：“是你说了算，还是我说了算？”",
    "A.有利原则",
    "B.公正原则",
    "C.尊重原则",
    "D.公益原则",
    "E.生命价值原则",
    "2.",
    "2.5分",
    "由“现代医学模式强调以病人为中心”引出的“诊治病人的医学伦理原",
    "则”错误的是(）",
    "A.对病人无伤",
    "B.尊重病人自主",
    "C.治疗服务公正",
    "D.对医院无利益损害",
    "E.对病人有利",
    "3.",
    "2.5分",
    "属于保密做法的是（)",
    "A.将患者的医疗信息告知患者及其家属",
    "B.医疗方案的实施应征得患者及其家属的同意",
    "C.告知患者不良预后",
    "D.对患者实施保护性医疗",
    "E.在医疗服务中用尊称、敬称",
]


def test_zjooc_bare_number_starts_question():
    qs = parse_questions(ZJOOC)
    assert [q.qno for q in qs] == ["1", "2", "3"]


def test_zjooc_score_line_is_not_part_of_stem():
    q = parse_questions(ZJOOC)[0]
    assert not q.stem.startswith("3.5分")
    assert q.stem.startswith("患者男性")
    assert "3.5分" not in q.stem


def test_zjooc_options_are_six():
    for q in parse_questions(ZJOOC):
        assert list(q.options) == ["A", "B", "C", "D", "E"], (q.qno, q.options)


def test_zjooc_question_without_number_still_splits():
    """第 4 题的题号整行被 OCR 漏掉，只剩“4.”后面的分值 —— 仍要当成新题。"""
    lines = ZJOOC + [
        "2.5分",
        "我国医学道德规范的基本内容是（）",
        "A.防病治病，救死扶伤",
        "B.全心全意为人民健康服务",
        "C.不伤害，有利，公正，自主",
        "D.救死扶伤，忠于职守",
        "E.实行医学人道主义",
    ]
    qs = parse_questions(lines)
    assert len(qs) == 4
    assert qs[3].stem.startswith("我国医学道德规范")
    assert list(qs[3].options) == ["A", "B", "C", "D", "E"]


# ---------------- 四栏答案页 ----------------

CH2 = [
    "第二章测试题",
    "医学伦理学  2026/8/9 21:21",
    "第1题（2.5分）",
    "单选题",
    "违背尊重原则的是()",
    "A. 医师消毒观念不强,造成交叉感染",
    "B. 医师满足病人的一切保密要求",
    "C. 医师业余时间给病人看病",
    "D. 医师拒收病人的财物",
    "E. 医师使某病人受益,但却损害了别的病人的利益",
    "正确答案：",
    "B",
    "第2题（2.5分）",
    "单选题",
    "根据伤害与医务人员主观意志的关系,伤害可以分为责任伤害与非责任伤害,下列()不属于医务人员的责任伤害",
    "A. 拒绝给病人提供必要的诊疗措施",
    "B. 因病人体质特殊导致的麻醉意外",
    "C. 滥施不必要的诊疗手段等所造成的故意伤害",
    "D. 粗心造成的开错刀",
    "E. 医务人员经过努力可以也应该降低其损伤程度",
    "正确答案：",
    "B",
]


def test_ch2_number_with_score_in_parens():
    qs = parse_questions(CH2)
    assert [q.qno for q in qs] == ["1", "2"]
    for q in qs:
        assert "2.5分" not in q.stem
        assert "单选题" not in q.stem


def test_ch2_answer_letter_is_on_the_line_after_marker():
    """“正确答案：”单独一行、字母在下一行时，这个字母是答案，不是选项。"""
    q = parse_questions(CH2)[0]
    assert q.answer_letter == "B"
    assert q.answer_text == "医师满足病人的一切保密要求"
    assert q.options["B"] == "医师满足病人的一切保密要求"
    assert len(q.options) == 5


def test_ch2_two_column_pages_do_not_mix():
    """一栏里的题不能被邻栏的题污染。"""
    qs = parse_questions(CH2)
    assert qs[1].options["E"] == "医务人员经过努力可以也应该降低其损伤程度"
    for q in qs:
        assert suspicious_reason(q) is None, suspicious_reason(q)


# ---------------- 版式：四栏切分 ----------------

def _box(x, y, w, h):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def _blocks_two_columns():
    """两栏：左栏两行、右栏两行；若不分栏，同一水平线上的左右两栏会被拼成一行。"""
    blk = []
    for i, text in enumerate(["左栏第一行", "左栏第二行"]):
        blk.append((_box(100, 100 + i * 60, 300, 30), text, 0.9))
    for i, text in enumerate(["右栏第一行", "右栏第二行"]):
        blk.append((_box(900, 100 + i * 60, 300, 30), text, 0.9))
    return blk


def test_to_lines_splits_two_columns():
    lines = OcrEngine._to_lines(_blocks_two_columns(), width=1400)
    assert lines == ["左栏第一行", "左栏第二行", "右栏第一行", "右栏第二行"], lines


def test_to_lines_keeps_single_column_together():
    """普通单栏：同一行里被大空白隔开的两段，仍按原有规则拆成两行（不改变旧行为）。"""
    blk = [
        (_box(100, 100, 80, 30), "A", 0.9),
        (_box(1200, 100, 120, 30), "3.5分", 0.9),
    ]
    lines = OcrEngine._to_lines(blk, width=1400)
    assert len(lines) == 2, lines


def test_narrow_sidebar_column_is_dropped():
    """左侧窄目录栏（<18% 宽、短文本）要被丢掉，正文完整保留。"""
    blk = []
    for i in range(6):
        blk.append((_box(20, 50 + i * 40, 150, 26), f"目录{i}", 0.9))
    for i in range(6):
        blk.append((_box(420, 50 + i * 40, 700, 26), f"正文第{i}行的内容文字", 0.9))
    lines = OcrEngine._to_lines(blk, width=1400)
    assert all("目录" not in ln for ln in lines), lines
    assert len(lines) == 6


# ---------------- 四栏答案页：选项字母被吃掉 ----------------

CH2_LOST_C = [
    "第34题（3.5分）",
    "单选题",
    "某女,40岁,企图自杀,服用大量巴比妥严重中毒,送来医院时呼吸已停,接诊医生",
    "马上对病人进行洗胃,无效。在没有其他对抗措施条件下,继而采用了当时还未推",
    "广的人工肾透析疗法进行治疗。对于接诊医生为抢救病人采用治疗性实验的做法,",
    "下面说法错误的是(）",
    "A.动机是好的,但得失结果一时难以下定论",
    "B.是符合医学道德的医学行为",
    "即使是抢救成功,也不合乎道德规范",
    "D.即使不幸造成死亡或伤残,也不能逆推动机不好",
    "E.本案例医生的选择是正确的",
    "正确答案：",
    "C",
]


def test_option_letter_lost_in_the_middle_is_recovered():
    """C 的字母整行丢了，正文要单独成 C，而不是并进 B。"""
    q = parse_questions(CH2_LOST_C)[0]
    assert list(q.options) == ["A", "B", "C", "D", "E"], q.options
    assert q.options["C"] == "即使是抢救成功,也不合乎道德规范"
    assert q.options["B"] == "是符合医学道德的医学行为"
    assert q.answer_letter == "C"
    assert q.answer_text == "即使是抢救成功,也不合乎道德规范"


# ---------------- 粘贴带圆圈选项的卷面文字 ----------------

CIRCLED_PASTE = [
    "1.",
    "3.5分",
    "患者男性，56岁。该医生的行为违背了下列原则中的（）",
    "○ A.有利原则",
    "○ B.公正原则",
    "◉ C.尊重原则",
    "○ D.公益原则",
    "○ E.生命价值原则",
]


def test_circled_option_markers_do_not_leak_into_stem():
    """用户从 zjooc 页面直接复制文字时，选项前的 ○ / ◉ 要剥掉。"""
    qs = parse_questions(CIRCLED_PASTE)
    assert len(qs) == 1, [q.stem for q in qs]
    q = qs[0]
    assert "○" not in q.stem and "◉" not in q.stem, q.stem
    assert q.stem == "患者男性,56岁。该医生的行为违背了下列原则中的()", q.stem
    assert sorted(q.options) == ["A", "B", "C", "D", "E"], q.options
    assert q.options["C"] == "尊重原则", q.options


# ---------------- 分值写在选项之后（超星整页答案卷） ----------------

SCORE_AFTER_OPTIONS = [
    "1【单选题】下列关于染色体组的说法正确的是",
    "A.甲说法",
    "B.乙说法",
    "C.丙说法",
    "D.丁说法",
    "E.戊说法",
    "2.5分",
    "2【单选题】父源第15号染色体有微缺失是",
    "A.甲说法",
    "B.乙说法",
    "C.丙说法",
    "D.丁说法",
    "E.戊说法",
    "2.5分",
]


def test_trailing_score_line_does_not_create_empty_question():
    """分值行在一题末尾时，不能凭空多出一个“空题干”的题。"""
    qs = parse_questions(SCORE_AFTER_OPTIONS)
    assert [q.qno for q in qs] == ["1", "2"], [(q.qno, q.stem) for q in qs]
    assert all(q.stem for q in qs)
    assert all(len(q.options) == 5 for q in qs)
    assert all(suspicious_reason(q) is None for q in qs), [suspicious_reason(q) for q in qs]


# ---------------- 长图分块：不能留下碎片块 ----------------

def test_tiles_never_leave_a_sliver():
    """18078 高的长图曾被切成最后一块只有 7px，OCR 直接崩。"""
    from PIL import Image, ImageDraw

    for h in (2607, 3001, 3007, 4021):
        img = Image.new("RGB", (400, h), "white")
        d = ImageDraw.Draw(img)
        for y in range(0, h, 120):
            d.line([(20, y), (380, y)], fill="black", width=6)

        tiles = list(OcrEngine._tiles(img))
        assert sum(t.size[1] for t in tiles) == h, (h, [t.size for t in tiles])
        assert all(t.size[1] >= 100 for t in tiles), (h, [t.size for t in tiles])


# ---------------- 真实 OCR：四栏页端到端 ----------------

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


def _font(size=28):
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    pytest.skip("本机没有中文字体，跳过四栏 OCR 测试")


def test_rendered_four_column_page_reads_column_by_column(tmp_path):
    """四栏并排时，同一水平线上的四道题号不能被拼成一行。"""
    from PIL import Image, ImageDraw

    font = _font(26)
    col_w, gap, pad = 470, 60, 30
    width = pad * 2 + col_w * 4 + gap * 3
    cards = []
    for col in range(4):
        for row in range(2):
            qno = col * 2 + row + 1
            cards.append((col, row, [
                f"第{qno}题（2.5分）",
                f"这是第{qno}题的题干内容",
                "A.甲选项内容",
                "B.乙选项内容",
                "C.丙选项内容",
            ]))
    line_h = 46
    img = Image.new("RGB", (width, pad * 2 + 2 * (line_h * 5 + 40)), "white")
    d = ImageDraw.Draw(img)
    for col, row, lines in cards:
        x = pad + col * (col_w + gap)
        y = pad + row * (line_h * 5 + 40)
        for k, ln in enumerate(lines):
            d.text((x, y + k * line_h), ln, font=font, fill="black")
    path = tmp_path / "four_col.png"
    img.save(path)

    lines = OcrEngine().image_lines(path)
    assert lines, "OCR 应识别出文字"
    # 任何一行里都不该同时出现两个不同题号（那就是把并排两栏拼成了一行）
    for ln in lines:
        assert not (("第1题" in ln or "第3题" in ln or "第5题" in ln or "第7题" in ln)
                    and ("第2题" in ln or "第4题" in ln or "第6题" in ln or "第8题" in ln)), ln

    qs = parse_questions(lines)
    assert [q.qno for q in qs] == ["1", "2", "3", "4", "5", "6", "7", "8"], [q.qno for q in qs]
    for q in qs:
        assert len(q.options) == 3, (q.qno, q.options)
        assert q.stem.startswith("这是第"), (q.qno, q.stem)

