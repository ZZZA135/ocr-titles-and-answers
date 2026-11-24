"""第十章 单基因病“章节测试”卷面（字母带圆圈、选项是英文缩写/符号）解析测试。

真实 OCR 行（2372×12466 整屏截图，已 GPU 识别）：
  A AD / B XR / C XD ...            <- 纯英文缩写的选项
  A -a/aa / B aa/aa / ...           <- 基因型符号
  A HbLepore / B地中海贫血 / ...
  E PKU                             <- 不含中文的选项
  暂时保存 / 提交                    <- 页面底部按钮，不能粘进选项
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answerfinder.parse import parse_questions, suspicious_reason

# 第9题：选项全是英文缩写，之前整题被并进题干、一个选项都没认出来
Q9 = [
    "9【单选题】苯丙酮尿症属于",
    "A AD",
    "B XR",
    "C XD",
    "D AR",
    "E Y连锁遗传病",
]

# 第12题：基因型写法带减号和斜杠
Q12 = [
    "12【单选题】HbH病的基因型为",
    "A -a/aa",
    "B aa/aa",
    "C --/aa或-a/-a",
    "D --/--",
    "E --/-a",
]

# 第14题：选项里有英文基因名
Q14 = [
    "14【单选题】属于凝血障碍的分子病为",
    "A HbLepore",
    "B地中海贫血",
    "C家族性高胆固醇血症",
    "D镰状细胞贫血",
    "E血友病A",
]

# 第8题：E 只有 "PKU"，之前被并进 D
Q8 = [
    "8【单选题】具有精神发育迟缓白内障肝硬化征候群的遗传病是",
    "A白化病",
    "B尿黑酸尿症",
    "C GPD缺乏症",
    "D半乳糖血症",
    "E PKU",
]

# 第20题：底部“暂时保存 / 提交”粘进了 E
Q20 = [
    "20【单选题】β珠蛋白位于人类第几号染色体上",
    "A 6",
    "B 16",
    "C 11",
    "D 22",
    "E 14",
    "暂时保存",
    "提交",
    "上一节",
    "下一节",
]


def test_ascii_only_options_are_recognized():
    q = parse_questions(Q9)[0]
    assert q.stem == "苯丙酮尿症属于"
    assert q.options == {"A": "AD", "B": "XR", "C": "XD", "D": "AR", "E": "Y连锁遗传病"}


def test_genotype_symbols_are_options():
    q = parse_questions(Q12)[0]
    assert q.stem == "HbH病的基因型为"
    assert q.options == {"A": "-a/aa", "B": "aa/aa", "C": "--/aa或-a/-a", "D": "--/--", "E": "--/-a"}


def test_gene_name_options_are_recognized():
    q = parse_questions(Q14)[0]
    assert q.stem == "属于凝血障碍的分子病为"
    assert q.options == {"A": "HbLepore", "B": "地中海贫血", "C": "家族性高胆固醇血症",
                         "D": "镰状细胞贫血", "E": "血友病A"}


def test_ascii_tail_option_not_merged_into_previous():
    q = parse_questions(Q8)[0]
    assert q.options["D"] == "半乳糖血症"
    assert q.options["E"] == "PKU"


def test_footer_buttons_do_not_glue_to_options():
    q = parse_questions(Q20)[0]
    assert q.options["E"] == "14"
    for v in q.options.values():
        assert "提交" not in v and "暂时保存" not in v


def test_full_chapter_page_parses_all_questions():
    lines = []
    for block in (Q8, Q9, Q12, Q14, Q20):
        lines.extend(block)
    qs = parse_questions(lines)
    assert len(qs) == 5
    for q in qs:
        assert len(q.options) == 5, (q.qno, q.options)
        assert suspicious_reason(q) is None, suspicious_reason(q)
