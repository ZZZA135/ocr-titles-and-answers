"""界面冒烟测试：能开窗、能查题、无命中给提示。

注意：Tk 在同一进程里销毁后重建偶尔会失败（Tcl 库路径丢失），
所以整个模块共用一个窗口实例，正是正式程序的用法（一次启动一个窗口）。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from answerfinder.parse import Question


Q1 = Question(qno="1", stem="下列关于细胞膜的叙述，正确的是（ ）",
              options={"A": "细胞膜不具有选择透过性", "B": "细胞膜的基本支架是磷脂双分子层",
                       "C": "细胞膜中不含蛋白质", "D": "细胞膜不能控制物质进出"},
              answer_letter="B", answer_text="细胞膜的基本支架是磷脂双分子层", source="p1.png")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    from answerfinder import gui

    db = tmp_path_factory.mktemp("db") / "answers.db"
    original = gui.DB_PATH
    gui.DB_PATH = db
    try:
        instance = gui.App()
    except Exception as exc:
        gui.DB_PATH = original
        pytest.skip(f"没有可用的图形界面：{exc}")
    yield instance
    instance.store.close()
    instance.destroy()
    gui.DB_PATH = original


def test_app_opens_and_answers(app):
    app.store.add_questions([Q1])
    app._refresh_count()
    app.query_text.delete("1.0", "end")
    app.query_text.insert("1.0", "下列关于细胞膜的叙述，正确的是（ ）")
    app.do_search()
    app.update()
    body = app.result.get("1.0", "end")
    assert "磷脂" in body
    assert "第 1 题" in body


def test_app_reports_no_hit_with_hint(app):
    app.query_text.delete("1.0", "end")
    app.query_text.insert("1.0", "完全无关的一句话用来测试兜底")
    app.do_search()
    app.update()
    body = app.result.get("1.0", "end")
    assert "没有找到" in body


# ---------- 整屏截图（带左侧目录、右侧悬浮块）要能自动挑出题目 ----------

EXAM_Q = Question(qno="3", stem="根据《ISCN》的规定B组和C组染色体为",
                  options={"A": "性染色体", "B": "亚中着丝粒染色体", "C": "近端着丝粒染色体",
                           "D": "中着丝粒染色体", "E": "常染色体"},
                  answer_letter="B", answer_text="亚中着丝粒染色体", source="exam.png")

EXAM_LINES = [
    "返 回 课 程", "章 节 详 情", "目录", "讨论", "笔记", "标注",
    "6.5 章节测试", "7 人类染色体", "7.4 章节测试",
    "3【单选题】根据《ISCN》的规定B组和C组染色体为",
    "A性染色体",
    "B亚中着丝粒染色体",
    "C近端着丝粒染色体",
    "D中着丝粒染色体",
    "E常染色体",
    "可以向我提出任何问题",
]


def test_exam_screenshot_strips_sidebar_noise(app):
    app.store.add_questions([EXAM_Q])
    app._apply_ocr_text("exam.png", EXAM_LINES)
    body = app.query_text.get("1.0", "end")
    assert "目录" not in body and "返 回" not in body
    assert "B组和C组染色体为" in body
    assert "B. 亚中着丝粒染色体" in body


def test_exam_screenshot_query_finds_answer(app):
    app.store.add_questions([EXAM_Q])
    app._apply_ocr_text("exam.png", EXAM_LINES)
    app.do_search()
    app.update()
    body = app.result.get("1.0", "end")
    assert "亚中着丝粒染色体" in body


# ---------- 多道题：必须一次给出全部答案 ----------

EXAM_Q2 = Question(qno="2", stem="第20号染色体属于",
                   options={"A": "D组", "B": "E组", "C": "C组", "D": "F组", "E": "A组"},
                   answer_letter="D", answer_text="F组", source="exam.png")

MULTI_LINES = [
    "目录", "讨论", "笔记",
    "3【单选题】根据《ISCN》的规定B组和C组染色体为",
    "A性染色体",
    "B亚中着丝粒染色体",
    "C近端着丝粒染色体",
    "D中着丝粒染色体",
    "E常染色体",
    "2【单选题】第20号染色体属于",
    "A D组",
    "B E组",
    "C C组",
    "D F组",
    "E A组",
]


def test_multi_question_screenshot_shows_every_answer(app):
    app.store.add_questions([EXAM_Q, EXAM_Q2])
    app._apply_ocr_text("exam.png", MULTI_LINES)
    app.do_search()
    app.update()
    body = app.result.get("1.0", "end")
    assert "亚中着丝粒染色体" in body
    assert "F组" in body
    assert "2 道题" in body


def test_multi_question_paste_shows_every_answer(app):
    paste = (
        "1．下列关于细胞膜的叙述，正确的是（ ）\n"
        "A．细胞膜不具有选择透过性\n"
        "B．细胞膜的基本支架是磷脂双分子层\n"
        "C．细胞膜中不含蛋白质\n"
        "D．细胞膜不能控制物质进出\n"
        "\n"
        "3【单选题】根据《ISCN》的规定B组和C组染色体为\n"
        "A性染色体\n"
        "B亚中着丝粒染色体\n"
        "C近端着丝粒染色体\n"
        "D中着丝粒染色体\n"
        "E常染色体\n"
    )
    app.query_text.delete("1.0", "end")
    app.query_text.insert("1.0", paste)
    app.do_search()
    app.update()
    body = app.result.get("1.0", "end")
    assert "磷脂双分子层" in body
    assert "亚中着丝粒染色体" in body
    assert "2 道题" in body


# ---------- 答案库：搜索、清空 ----------

def test_library_search_hits_option_text_and_multiple_keywords(app):
    app.store.delete_all()
    app.store.add_questions([Q1])
    app.refresh_library()
    base = len(app.tree.get_children())
    assert base == 1

    app.lib_kw.set("选择透过性")      # 只出现在 A 选项里
    app.refresh_library()
    assert len(app.tree.get_children()) == 1

    app.lib_kw.set("细胞膜 磷脂")     # 两个词都要命中
    app.refresh_library()
    assert len(app.tree.get_children()) == 1
    assert "命中 1 题" in app.lib_hint.get()

    app.lib_kw.set("细胞膜 完全没有")
    app.refresh_library()
    assert app.tree.get_children() == ()

    app.lib_kw.set("")
    app.refresh_library()
    assert len(app.tree.get_children()) == 1


def test_clear_library_empties_it_after_confirm(app, monkeypatch):
    from answerfinder import gui

    app.store.add_questions([Q1])
    app.refresh_library()
    assert app.tree.get_children()

    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    app.clear_library()
    assert app.store.count() == 0
    assert app.tree.get_children() == ()


def test_clear_library_keeps_data_when_not_confirmed(app, monkeypatch):
    from answerfinder import gui

    app.store.add_questions([Q1])
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    app.clear_library()
    assert app.store.count() >= 1


# ---------- 导入核对：当场改、当场删、再入库 ----------

def _review_pair():
    a = Question(qno="24", stem="在机体内,酶的正常数量大大超过机体所必需的数量",
                 options={"A": "100%", "B": "75%", "C": "50%"}, answer_letter="C",
                 answer_text="50%", source="a.jpg")
    b = Question(qno="25", stem="酶缺陷所引起的病理改变一般因为",
                 options={"A": "底物堆积", "B": "产物缺乏"}, answer_letter="D",
                 answer_text="", source="a.jpg")
    return [a, b]


def test_review_dialog_fix_and_drop(app):
    from answerfinder import gui

    confirmed = []
    dlg = gui.ReviewDialog(app, _review_pair(), on_confirm=confirmed.append)
    dlg.update()
    assert len(dlg.tree.get_children()) == 2
    assert "⚠" in dlg.tree.item("1", "values")[5]     # 缺选项的题会被标出来

    # 当场改第 2 题：补上 D 选项并选 D
    dlg._apply(1, "25", "酶缺陷所引起的病理改变一般因为",
               {"A": "底物堆积", "B": "产物缺乏", "C": "中间产物堆积", "D": "以上全部"}, "D")
    assert dlg.items[1].answer_letter == "D"
    assert dlg.items[1].answer_text == "以上全部"
    assert "⚠" not in dlg.tree.item("1", "values")[5]

    # 当场删掉第 1 题
    dlg.tree.selection_set("0")
    dlg.drop_selected()
    assert len(dlg.items) == 1

    dlg.confirm()
    assert confirmed and len(confirmed[0]) == 1
    assert confirmed[0][0].qno == "25"


def test_review_dialog_cancel_imports_nothing(app):
    from answerfinder import gui

    confirmed = []
    dlg = gui.ReviewDialog(app, _review_pair(), on_confirm=confirmed.append)
    dlg.update()
    dlg._cancel()
    assert confirmed == [[]]


def test_commit_import_writes_edited_questions(app):
    app.store.delete_all()
    fixed = Question(qno="25", stem="酶缺陷所引起的病理改变一般因为",
                     options={"A": "底物堆积", "B": "产物缺乏", "C": "中间产物堆积", "D": "以上全部"},
                     answer_letter="D", answer_text="以上全部", source="a.jpg")
    app._commit_import([fixed])
    assert app.store.count() == 1


def test_import_review_queue_opens_review_not_library(app, monkeypatch):
    """识别线程只交结果，不直接写库；主线程收到后弹核对窗口。"""
    opened = {}
    monkeypatch.setattr(app, "_open_review", lambda qs: opened.setdefault("qs", qs))
    app.store.delete_all()
    app.queue.put(("import_review", _review_pair(), 0))
    app._poll_queue()
    assert len(opened["qs"]) == 2
    assert app.store.count() == 0          # 还没点入库，库里不能有东西
    assert app._importing is True or app.start_btn.cget("state") != "disabled"
