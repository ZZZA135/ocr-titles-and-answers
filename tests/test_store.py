"""答案库（SQLite）测试：导入、去重、查询、修改、删除、持久化。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answerfinder.parse import Question
from answerfinder.store import AnswerStore


def make(qno, stem, opts, letter, atext, source="p1.png"):
    return Question(qno=qno, stem=stem, options=opts, answer_letter=letter,
                    answer_text=atext, source=source)


Q1 = make("1", "下列关于细胞膜的叙述，正确的是（ ）",
          {"A": "细胞膜不具有选择透过性", "B": "细胞膜的基本支架是磷脂双分子层",
           "C": "细胞膜中不含蛋白质", "D": "细胞膜不能控制物质进出"},
          "B", "细胞膜的基本支架是磷脂双分子层")
Q2 = make("2", "成人正常血pH范围是（ ）",
          {"A": "7.15~7.25", "B": "7.25~7.35", "C": "7.35~7.45", "D": "7.45~7.55"},
          "C", "7.35~7.45")


@pytest.fixture
def store(tmp_path):
    s = AnswerStore(tmp_path / "answers.db")
    yield s
    s.close()


def test_add_and_count(store):
    added, skipped = store.add_questions([Q1, Q2])
    assert added == 2 and skipped == 0
    assert store.count() == 2


def test_duplicate_is_skipped(store):
    store.add_questions([Q1])
    added, skipped = store.add_questions([Q1])
    assert added == 0 and skipped == 1
    assert store.count() == 1


def test_near_duplicate_from_second_ocr_pass_is_skipped(store):
    store.add_questions([Q1])
    same = make("1", "下列关于细胞膜的叙述, 正确的是", Q1.options, "B", "细胞膜的基本支架是磷脂双分子层")
    added, skipped = store.add_questions([same])
    assert added == 0 and skipped == 1


def test_different_question_is_not_deduped(store):
    store.add_questions([Q1])
    other = make("2", "关于细胞膜功能特性的说法，错误的是（ ）",
                 {"A": "具有选择透过性", "B": "可进行信息交流",
                  "C": "不能控制物质进出", "D": "具有一定的流动性"}, "C", "不能控制物质进出")
    added, skipped = store.add_questions([other])
    assert added == 1 and skipped == 0


def test_search_returns_answer_text(store):
    store.add_questions([Q1, Q2])
    hits = store.search("1. 下列关于细胞膜的叙述，正确的是（ ）", top_n=2)
    assert hits[0].question.answer_text == "细胞膜的基本支架是磷脂双分子层"


def test_search_with_user_options_maps_letter(store):
    store.add_questions([Q2])
    query = "成人正常血pH范围是（ ）\nA. 7.25~7.35\nB. 7.15~7.25\nC. 7.35~7.45\nD. 7.45~7.55"
    hits = store.search(query)
    assert hits[0].question.answer_text == "7.35~7.45"


def test_list_questions_sorted_by_id(store):
    store.add_questions([Q1, Q2])
    rows = store.list_questions()
    assert [r[1].qno for r in rows] == ["1", "2"]


def test_update_changes_answer(store):
    store.add_questions([Q1])
    qid = store.list_questions()[0][0]
    store.update_question(qid, Q1.stem, Q1.options, "D")
    row = store.get_question(qid)
    assert row.answer_letter == "D"
    assert row.answer_text == "细胞膜不能控制物质进出"


def test_delete(store):
    store.add_questions([Q1, Q2])
    qid = store.list_questions()[0][0]
    store.delete_question(qid)
    assert store.count() == 1


def test_persistence(tmp_path):
    db = tmp_path / "answers.db"
    s1 = AnswerStore(db)
    s1.add_questions([Q1])
    s1.close()
    s2 = AnswerStore(db)
    assert s2.count() == 1
    assert s2.list_questions()[0][1].answer_letter == "B"
    s2.close()


def test_source_kept(store):
    store.add_questions([Q1])
    row = store.list_questions()[0][1]
    assert row.source == "p1.png"


# ---------- 题干相同但选项不同：不能当重复丢掉 ----------

def test_same_stem_with_different_options_is_kept(store):
    """同一题干在不同章节/版本里配了不同选项，必须各存一条，否则查不到正确答案。"""
    a = make("1", "下列关于染色体组的叙述，正确的是（ ）",
             {"A": "正常人体细胞有2个染色体组", "B": "单倍体只含1个染色体组",
              "C": "染色体组内没有同源染色体", "D": "二倍体生物只有2个染色体组"},
             "C", "染色体组内没有同源染色体")
    b = make("1", "下列关于染色体组的叙述，正确的是（ ）",
             {"A": "一个染色体组包含全部遗传信息", "B": "四倍体含有4个染色体组",
              "C": "染色体组之间没有同源关系", "D": "单倍体一定不含等位基因"},
             "A", "一个染色体组包含全部遗传信息")
    added, skipped = store.add_questions([a, b])
    assert added == 2 and skipped == 0

    # 用 b 的选项去查，要能命中 b 的答案（而不是被 b 挡掉只剩 a）
    hits = store.search("下列关于染色体组的叙述，正确的是（ ）\n"
                        "A. 一个染色体组包含全部遗传信息\nB. 四倍体含有4个染色体组\n"
                        "C. 染色体组之间没有同源关系\nD. 单倍体一定不含等位基因", top_n=3)
    assert hits and hits[0].question.answer_text == "一个染色体组包含全部遗传信息"


def test_same_stem_and_options_still_dedupe(store):
    """选项也相同的重复导入，仍然要判重。"""
    dup = make("1", Q1.stem, dict(Q1.options), "B", Q1.answer_text)
    added, skipped = store.add_questions([Q1, dup])
    assert added == 1 and skipped == 1


def test_same_stem_slightly_different_options_dedupe(store):
    """选项只有 OCR 小差异（一半以上完全相同）时仍判重，避免重复刷库。"""
    noisy = make("1", Q1.stem,
                 {"A": "细胞膜不具有选择透过性", "B": "细胞膜的基本支架是磷脂双分子层",
                  "C": "细胞膜中不含有蛋白质", "D": "细胞膜不能控制物质进出"}, "B", Q1.answer_text)
    added, skipped = store.add_questions([Q1, noisy])
    assert added == 1 and skipped == 1


def test_duplicate_with_answer_fills_missing_answer(store):
    """库里那条没答案、这次导入的带答案 → 判重的同时把答案补上。"""
    no_answer = make("1", Q1.stem, dict(Q1.options), None, None)
    assert store.add_questions([no_answer])[0] == 1
    assert store.list_questions()[0][1].answer_letter is None

    added, skipped = store.add_questions([Q1])
    assert (added, skipped) == (0, 1)
    row = store.list_questions()[0][1]
    assert row.answer_letter == "B"
    assert row.answer_text == "细胞膜的基本支架是磷脂双分子层"
    assert store.count() == 1


# ---------- 同一张图重复导入：选项有 OCR 小差异也要判重 ----------

def test_ocr_noise_across_options_still_dedupes(store):
    """同一道题两次识别的选项各有一两个字不同，仍要判成重复，不能刷出一堆副本。"""
    base = make("24", "在机体内，酶的正常数量大大超过维持机体新陈代谢所必需的数量",
                {"A": "100%", "B": "75%", "C": "50%", "D": "5%", "E": "1%"}, "C", "50%")
    noisy = make("24", "在机体内,酶的正常数量大大超过维持机体新陈代谢所必需的数量",
                 {"A": "100%", "B": "75%", "C": "50%", "D": "5%", "E": "l%"},
                 "C", "50%")
    assert store.add_questions([base]) == (1, 0)
    assert store.add_questions([noisy]) == (0, 1)
    assert store.count() == 1


def test_three_of_five_options_noisy_still_dedupe(store):
    """五个选项里有三个各差一个 OCR 字符，也要认成同一题。"""
    base = make("21", "具有精神发育迟缓、白内障、肝硬化征候群的遗传病是",
                {"A": "PKU", "B": "GPD缺乏症", "C": "半乳糖血症", "D": "尿黑酸尿症", "E": "白化病"},
                "C", "半乳糖血症")
    noisy = make("21", "具有精神发育迟缓,白内障,肝硬化征候群的遗传病是",
                 {"A": "PKU", "B": "GPD缺之症", "C": "半乳糖血症", "D": "尿黑酸尿", "E": "白化病E"},
                 "C", "半乳糖血症")
    assert store.add_questions([base]) == (1, 0)
    assert store.add_questions([noisy]) == (0, 1)


def test_genotype_question_with_noisy_options_dedupes(store):
    """基因型选项全是符号，OCR 丢一个减号也算同一题。"""
    a = make("4", "血红蛋白Barts胎儿水肿综合征的基因型为",
             {"A": "--/a-", "B": "--/aa或-a/-a", "C": "-a/aa", "D": "--/-a", "E": "aa/aa"}, "A", "--/a-")
    b = make("4", "血红蛋白Barts胎儿水肿综合征的基因型为",
             {"A": "--/a-", "B": "--/aa或-a/-a", "C": "-a/aa", "D": "--/--", "E": "aa/aa"}, "A", "--/a-")
    added, skipped = store.add_questions([a, b])
    assert (added, skipped) == (1, 1)


# ---------- 答案库搜索 ----------

def test_search_matches_option_text(store):
    """关键词只出现在选项里，也要能搜到。"""
    store.add_questions([Q1, Q2])
    rows = store.list_questions(keyword="选择透过性")
    assert [q.stem for _, q in rows] == [Q1.stem]


def test_search_requires_all_keywords(store):
    """空格分隔的多个关键词要同时满足。"""
    store.add_questions([Q1, Q2])
    rows = store.list_questions(keyword="细胞膜 磷脂")
    assert [q.stem for _, q in rows] == [Q1.stem]
    assert store.list_questions(keyword="细胞膜 pH") == []


def test_search_ignores_case(store):
    store.add_questions([Q2])
    assert store.list_questions(keyword="PH") or store.list_questions(keyword="ph")


def test_clear_all(store):
    store.add_questions([Q1, Q2])
    removed = store.delete_all()
    assert removed == 2
    assert store.count() == 0
    assert store.list_questions() == []