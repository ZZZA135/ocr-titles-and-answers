"""匹配模块测试：题干乱序、选项乱序、OCR 误差下仍要命中正确题目。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answerfinder.parse import Question
from answerfinder.match import normalize_text, split_question, find_matches, map_answer_to_user_options


def q(qno, stem, options, letter, atext, source="p1.png"):
    return Question(qno=qno, stem=stem, options=options,
                    answer_letter=letter, answer_text=atext, source=source)


BANK = [
    q("1", "下列关于细胞膜的叙述，正确的是（ ）",
      {"A": "细胞膜不具有选择透过性", "B": "细胞膜的基本支架是磷脂双分子层",
       "C": "细胞膜中不含蛋白质", "D": "细胞膜不能控制物质进出"}, "B", "细胞膜的基本支架是磷脂双分子层"),
    q("2", "成人正常血pH范围是（ ）",
      {"A": "7.15~7.25", "B": "7.25~7.35", "C": "7.35~7.45", "D": "7.45~7.55"}, "C", "7.35~7.45"),
    q("3", "肝性脑病患者禁用肥皂水灌肠的原因是（ ）",
      {"A": "防止腹泻", "B": "减少氨的吸收", "C": "避免电解质紊乱", "D": "防止腹胀"}, "B", "减少氨的吸收"),
]


def test_normalize_strips_punctuation_space_and_numbering():
    assert normalize_text("1. 下列关于 细胞膜 的叙述，正确的是（ ）") == normalize_text(
        "下列关于细胞膜的叙述正确的是")


def test_split_question_with_options():
    stem, opts = split_question("成人正常血pH范围是（ ）\nA.7.15~7.25\nB.7.25~7.35\nC.7.35~7.45\nD.7.45~7.55")
    assert "正常血pH范围" in stem
    assert opts["A"] == "7.15~7.25"
    assert opts["C"] == "7.35~7.45"


def test_identical_stem_hits_top1():
    hits = find_matches("下列关于细胞膜的叙述，正确的是（ ）", BANK)
    assert hits, "应至少命中一条"
    assert hits[0].question.qno == "1"
    assert hits[0].score > 0.95


def test_question_number_difference_ignored():
    hits = find_matches("7. 成人正常血pH范围是（ ）", BANK)
    assert hits[0].question.qno == "2"


def test_shuffled_options_still_hits_and_maps_letter():
    # 用户卷面上选项被打乱：正确答案文字落在 C
    user_text = ("成人正常血pH范围是（ ）\n"
                 "A. 7.25~7.35\nB. 7.15~7.25\nC. 7.35~7.45\nD. 7.45~7.55")
    hits = find_matches(user_text, BANK)
    assert hits[0].question.qno == "2"
    letter = map_answer_to_user_options(hits[0].question, hits[0].user_options)
    assert letter == ["C"]


def test_shuffled_options_second_case():
    user_text = ("肝性脑病患者禁用肥皂水灌肠的原因是（ ）\n"
                 "A. 避免电解质紊乱\n"
                 "B. 防止腹胀\n"
                 "C. 减少氨的吸收\n"
                 "D. 防止腹泻")
    hits = find_matches(user_text, BANK)
    assert hits[0].question.qno == "3"
    assert map_answer_to_user_options(hits[0].question, hits[0].user_options) == ["C"]


def test_typo_tolerance():
    hits = find_matches("下列关于细胞摸的叙述，正确的是（ ）", BANK)
    assert hits[0].question.qno == "1"
    assert hits[0].score > 0.8


def test_similar_questions_disambiguated_by_options():
    stem = "肝性脑病患者禁用肥皂水灌肠的原因是（ ）"
    user_text = stem + "\nA. 减少氨的吸收\nB. 防止腹泻\nC. 避免电解质紊乱\nD. 防止腹胀"
    hits = find_matches(user_text, BANK)
    assert hits[0].question.qno == "3"


def test_unrelated_text_yields_no_confidence_hit():
    hits = find_matches("今天天气不错，我们一起去打篮球吧", BANK)
    assert not hits or hits[0].score < 0.45


def test_short_stem_still_matches_when_unique():
    hits = find_matches("肝性脑病患者禁用肥皂水灌肠的原因", BANK)
    assert hits[0].question.qno == "3"


def test_map_returns_none_without_user_options():
    hits = find_matches("成人正常血pH范围是（ ）", BANK)
    assert map_answer_to_user_options(hits[0].question, {}) is None


def test_multi_answer_maps_multiple_letters():
    bank = [q("9", "下列属于脂溶性维生素的有（ ）",
              {"A": "维生素A", "B": "维生素B1", "C": "维生素D", "D": "维生素C"},
              "AC", "维生素A；维生素D")]
    user_text = ("下列属于脂溶性维生素的有（ ）\n"
                 "A. 维生素C\nB. 维生素D\nC. 维生素B1\nD. 维生素A")
    hits = find_matches(user_text, bank)
    assert map_answer_to_user_options(hits[0].question, hits[0].user_options) == ["B", "D"]


# ---------- 答案是纯数字/纯字母时也要能换算字母 ----------

def test_normalize_keeps_pure_number():
    """纯数字本身就是答案或选项，不能被当成“题号”吃掉。"""
    assert normalize_text("3") == "3"
    assert normalize_text("23") == "23"


def test_normalize_still_strips_leading_question_number():
    assert normalize_text("21. 题干内容") == "题干内容"
    assert normalize_text("3【单选题】题干") == "题干"


def test_numeric_answer_maps_to_user_letter():
    """答案是“3”、卷面选项是 1/2/4/3/5，应算出 D。"""
    key = q("4", "某女性的体细胞中X染色体数目",
            {"A": "1", "B": "2", "C": "4", "D": "3", "E": "5"}, "D", "3")
    user = {"A": "1", "B": "2", "C": "4", "D": "3", "E": "5"}
    assert map_answer_to_user_options(key, user) == ["D"]


def test_numeric_options_still_match_question():
    key = q("5", "人类正常染色体的类型数为",
            {"A": "4", "B": "3", "C": "5", "D": "2", "E": "1"}, "B", "3")
    user = {"A": "1", "B": "2", "C": "4", "D": "3", "E": "5"}
    hits = find_matches("人类正常染色体的类型数为\nA 1\nB 2\nC 4\nD 3\nE 5", [key])
    assert hits and hits[0].score > 0.7
    assert map_answer_to_user_options(key, user) == ["D"]


# ---------- 两个选项只差一个字符时，要选“完全匹配”的那个，而不是字母靠前的 ----------

def test_exact_match_wins_over_one_char_difference_even_if_earlier_letter():
    """A 与答案只差一个标点（归一化后同分），D 与答案逐字相同 → 必须选 D。"""
    key = q("7", "常染色质是间期细胞核中",
            {"A": "螺旋化程度低，有转录活性的染色质", "B": "螺旋化程度高，无转录活性的染色质",
             "C": "螺旋化程度低，无转录活性的染色质", "D": "螺旋化程度低,有转录活性的染色质"},
            "D", "螺旋化程度低,有转录活性的染色质")
    user = {"A": "螺旋化程度低，有转录活性的染色质", "B": "螺旋化程度高，无转录活性的染色质",
            "C": "螺旋化程度低，无转录活性的染色质", "D": "螺旋化程度低,有转录活性的染色质"}
    assert map_answer_to_user_options(key, user) == ["D"]


def test_exact_match_wins_on_latin_case_difference():
    """A 是大小写/全半角差异，D 完全一致 → 选 D。"""
    key = q("8", "SRY基因位于",
            {"A": "Yp11.31", "B": "Yq11.2", "C": "Xp11.31", "D": "Yp11．31"}, "D", "Yp11.31")
    user = {"A": "Yp11.3l", "B": "Yq11.2", "C": "Xp11.31", "D": "Yp11.31"}
    assert map_answer_to_user_options(key, user) == ["D"]
