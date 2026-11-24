"""答案速查 · 桌面界面（tkinter）。

三个页签：
  查答案   —— 粘贴题干或识别/粘贴截图，直接给出正确选项文字 + 在你卷面上的字母
  答案库   —— 浏览、搜索、编辑、删除、导出已识别的题目
  导入答案 —— 批量导入答案图片，自动 OCR、切题、去重入库
"""
from __future__ import annotations

import csv
import json
import os
import queue
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk
from typing import List, Optional, Tuple

from .match import find_matches, map_answer_to_user_options
from .ocr import BACKEND_GPU, OcrEngine, dml_available
from .parse import OPTION_LETTERS, Question, parse_questions, suspicious_reason
from .store import AnswerStore

APP_DIR = Path(__file__).resolve().parent.parent
DB_PATH = APP_DIR / "data" / "answers.db"
SETTINGS_PATH = APP_DIR / "data" / "设置.json"


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _pick_font() -> str:
    try:
        families = set(tkfont.families())
    except Exception:
        return "Segoe UI"
    for f in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"):
        if f in families:
            return f
    return "Segoe UI"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("答案速查 · 题目乱序也能找到答案")
        self.geometry("1060x720")
        self.minsize(900, 600)
        self.option_add("*Font", (UI_FONT, 10))
        self.store = AnswerStore(DB_PATH)
        settings = load_settings()
        self.settings = settings
        self.ocr = OcrEngine(use_gpu=settings.get("use_gpu"))
        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.import_files: List[str] = []
        self.current_hits: list = []
        self._ocr_note: str = ""

        self._build()
        self._refresh_count()
        self.after(80, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI
    def _build(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("TNotebook.Tab", padding=(16, 7))

        header = ttk.Frame(self, padding=(14, 10, 14, 0))
        header.pack(fill="x")
        ttk.Label(header, text="答案速查", font=(UI_FONT, 15, "bold")).pack(side="left")
        self.count_var = tk.StringVar(value="答案库：0 题")
        ttk.Label(header, textvariable=self.count_var, foreground="#666").pack(side="left", padx=12)
        ttk.Label(
            header,
            text="题目顺序不同、选项顺序不同都没关系：按题干内容找题，答案换算成文字再对到你卷面上的字母。",
            foreground="#888",
        ).pack(side="left", padx=6)

        self.engine_var = tk.StringVar(value="识别引擎：待启动")
        ttk.Label(header, textvariable=self.engine_var, foreground="#666").pack(side="right", padx=(8, 0))
        self.gpu_var = tk.BooleanVar(value=self.ocr.want_gpu)
        gpu_chk = ttk.Checkbutton(
            header, text="显卡加速", variable=self.gpu_var, command=self._toggle_gpu,
            state=("disabled" if not dml_available() else "normal"))
        gpu_chk.pack(side="right")
        if not dml_available():
            gpu_chk.configure(text="显卡加速（本机不可用）")

        self.nb = ttk.Notebook(self, padding=(10, 6))
        self.nb.pack(fill="both", expand=True)
        self._build_query_tab()
        self._build_library_tab()
        self._build_import_tab()

    # ---- 查答案
    def _build_query_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="查答案")

        top = ttk.LabelFrame(tab, text="把题目贴在这里（含选项更好）", padding=8)
        top.pack(fill="both", expand=False)

        self.query_text = tk.Text(top, height=7, wrap="word", font=(UI_FONT, 11),
                                  relief="solid", borderwidth=1, undo=True)
        self.query_text.pack(fill="both", expand=True)
        self.query_text.bind("<Control-Return>", lambda e: (self.do_search(), "break")[1])

        btns = ttk.Frame(top)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="查答案（Ctrl+Enter）", command=self.do_search).pack(side="left")
        ttk.Button(btns, text="识别题目截图…", command=self.query_from_file).pack(side="left", padx=6)
        ttk.Button(btns, text="粘贴截图查（Ctrl+V）", command=self.query_from_clipboard).pack(side="left")
        ttk.Button(btns, text="清空", command=lambda: (self.query_text.delete("1.0", "end"),
                                                       self._clear_result())).pack(side="left", padx=6)

        res = ttk.LabelFrame(tab, text="查询结果", padding=8)
        res.pack(fill="both", expand=True, pady=(10, 0))
        self.result = tk.Text(res, wrap="word", font=(UI_FONT, 11), relief="flat",
                              background="#fbfbfb", padx=12, pady=10, cursor="arrow")
        sb = ttk.Scrollbar(res, orient="vertical", command=self.result.yview)
        self.result.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.result.pack(side="left", fill="both", expand=True)
        self.result.tag_configure("hint", foreground="#888")
        self.result.tag_configure("label", foreground="#555")
        self.result.tag_configure("answer", font=(UI_FONT, 20, "bold"), foreground="#b3261e")
        self.result.tag_configure("answer2", font=(UI_FONT, 13, "bold"), foreground="#b3261e")
        self.result.tag_configure("meta", foreground="#5a7a6a")
        self.result.tag_configure("warn", foreground="#a15c00")
        self.result.tag_configure("opt", font=(UI_FONT, 11))
        self.result.tag_configure("optcorrect", font=(UI_FONT, 11, "bold"), foreground="#1a7f37")
        self.result.configure(state="disabled")
        self._set_result_text(
            "这里显示答案。\n\n"
            "用法：把题目（连同 A/B/C/D 选项）粘到上面，按 Ctrl+Enter；\n"
            "或者直接截个题目的图，点“粘贴截图查”。\n"
            "一次贴多道题、或截一张含多道题的整屏图，会逐题把答案都列出来。\n"
            "答案会给两样东西：正确选项的文字内容，以及它在你所贴选项里的字母。\n"
            "从学习通/超星复制下来的整段（含“我的答案：A”“得分：4.3分”）可以直接贴，会自动去掉这些噪声。",
            "hint")

    # ---- 答案库
    def _build_library_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="答案库")

        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        ttk.Label(bar, text="搜索：").pack(side="left")
        self.lib_kw = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self.lib_kw, width=30)
        ent.pack(side="left")
        ent.bind("<Return>", lambda e: self.refresh_library())
        ttk.Button(bar, text="筛选", command=self.refresh_library).pack(side="left", padx=6)
        ttk.Button(bar, text="显示全部", command=lambda: (self.lib_kw.set(""), self.refresh_library())).pack(side="left")
        ttk.Button(bar, text="导出 CSV", command=self.export_csv).pack(side="right")
        ttk.Button(bar, text="清空答案库", command=self.clear_library).pack(side="right", padx=6)
        ttk.Button(bar, text="删除所选", command=self.delete_selected).pack(side="right", padx=6)
        ttk.Button(bar, text="编辑所选", command=self.edit_selected).pack(side="right")

        self.lib_hint = tk.StringVar(value="搜索时可用空格分隔多个词（例如：染色体 组），题干、选项、答案里任意一处命中即可；双击一行可直接改这题。")
        ttk.Label(tab, textvariable=self.lib_hint, foreground="#777").pack(fill="x", pady=(4, 0))

        cols = ("qno", "stem", "answer", "qtype", "source")
        self.tree = ttk.Treeview(tab, columns=cols, show="headings", selectmode="extended")
        for col, title, width in (("qno", "题号", 60), ("stem", "题干", 480),
                                  ("answer", "答案", 240), ("qtype", "题型", 80),
                                  ("source", "来源", 140)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w", stretch=(col == "stem"))
        vsb = ttk.Scrollbar(tab, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True, pady=(8, 0))
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

    # ---- 导入
    def _build_import_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="导入答案")

        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        ttk.Button(bar, text="选择图片…", command=self.choose_files).pack(side="left")
        ttk.Button(bar, text="选择文件夹…", command=self.choose_folder).pack(side="left", padx=6)
        ttk.Button(bar, text="清空列表", command=self.clear_import_list).pack(side="left")
        self.dedupe_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="自动跳过重复题目", variable=self.dedupe_var).pack(side="left", padx=12)
        self.start_btn = ttk.Button(bar, text="开始识别并入库", command=self.start_import)
        self.start_btn.pack(side="right")

        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, pady=(8, 0))
        left = ttk.LabelFrame(body, text="待识别图片", padding=6)
        left.pack(side="left", fill="both", expand=False)
        self.file_list = tk.Listbox(left, width=46, height=18, activestyle="none")
        self.file_list.pack(fill="both", expand=True)

        right = ttk.LabelFrame(body, text="识别日志", padding=6)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.log = tk.Text(right, height=18, wrap="word", font=(UI_FONT, 10),
                           relief="flat", background="#fbfbfb")
        lsb = ttk.Scrollbar(right, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("ok", foreground="#1a7f37")
        self.log.tag_configure("warn", foreground="#a15c00")
        self.log.tag_configure("err", foreground="#b3261e")

        self.progress = ttk.Progressbar(tab, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 0))
        self.import_hint = tk.StringVar(value="支持学习通/超星式页面（“21.[单选题] … 我的答案：A / 得分”）；整页长截图会自动分块识别，一张 800×16000 的长图约 20~40 秒。同一页重复导入不会产生重复题。")
        ttk.Label(tab, textvariable=self.import_hint, foreground="#777").pack(fill="x", pady=(4, 0))

    # --------------------------------------------------------------- 查询
    def _toggle_gpu(self):
        """切换显卡加速：重建 OCR 引擎，并把选择记到 data\\设置.json。"""
        want = bool(self.gpu_var.get())
        self.ocr = OcrEngine(use_gpu=want)
        self.engine_var.set("识别引擎：待启动")
        self.settings["use_gpu"] = want
        save_settings(self.settings)

    def _update_engine_label(self):
        backend = self.ocr.backend
        text = "识别引擎：" + ("CPU（纯处理器）" if backend == "CPU" else backend)
        self.engine_var.set(text)

    def _apply_ocr_text(self, source: str, lines: List[str]) -> None:
        """把截图的 OCR 结果填进查询框。

        整屏截图里常混着左侧目录、右侧“AI 助教”悬浮块，直接把全部文字丢去查会被稀释。
        这里先按题目切分：切出几道题就把几道题都写进查询框，下面的查询会逐题给答案。
        """
        raw = "\n".join(lines or [])
        text = raw
        self._ocr_note = ""
        try:
            questions = parse_questions(lines or [], source=source)
        except Exception:
            questions = []
        if questions:
            text = "\n\n".join(self._question_to_text(q) for q in questions)
        self.query_text.delete("1.0", "end")
        self.query_text.insert("1.0", text)

    @staticmethod
    def _question_to_text(q: Question) -> str:
        """把一道题写回可再次解析的文本（保留题号和题型）。"""
        head = f"{q.qno}．" if q.qno else ""
        if q.qtype:
            head += f"【{q.qtype}】"
        parts = [head + q.stem]
        parts.extend(f"{k}. {v}" for k, v in q.options.items() if v)
        return "\n".join(parts)

    @staticmethod
    def _question_probe(q: Question) -> str:
        return q.stem + "\n" + "\n".join(f"{k}. {v}" for k, v in q.options.items() if v)

    def _render_multi_answers(self, questions: List[Question]):
        """一次贴/截多道题：每道题各给一份答案，而不是只挑一道。"""
        entries = []
        for q in questions:
            try:
                hits = self.store.search(self._question_probe(q), top_n=1)
            except Exception:
                hits = []
            entries.append((q, hits[0] if hits else None))
        self.current_hits = [h for _, h in entries if h is not None]

        found = sum(1 for _, h in entries if h is not None)
        self._start_write()
        w = self.result.insert
        w("end", f"共 {len(entries)} 道题，下面逐题给答案", "label")
        w("end", f"（查到 {found} 题；题目顺序、选项顺序不同都不影响，答案按文字换算到你这里的选项）\n", "hint")
        for i, (q, h) in enumerate(entries, start=1):
            w("end", f"\n{i}. 第 {q.qno or '?'} 题  {q.stem[:42]}\n", "label")
            if h is None:
                w("end", "   答案库里没有找到这道题 —— 确认对应的答案图片已导入，"
                        "或到「答案库」里核对题干。\n", "warn")
                continue
            pct = int(round(h.score * 100))
            w("end", "   正确答案  ", "label")
            w("end", f"{h.question.answer_display}\n", "answer2")
            mapped = map_answer_to_user_options(h.question, h.user_options)
            if mapped:
                w("end", f"   在你贴的选项里对应：{'、'.join(mapped)}", "optcorrect")
            elif h.user_options:
                w("end", "   你贴的选项里没找到完全对应的说法，以上面的答案文字为准。", "warn")
            w("end", f"   相似度 {pct}%\n", "meta")
            if pct < 60:
                w("end", "   ⚠ 相似度偏低，先核对题干是不是同一道题。\n", "warn")
        w("end", "\n")
        self._end_write()

    def do_search(self):
        text = self.query_text.get("1.0", "end").strip()
        if not text:
            self._set_result_text("先粘贴题目或识别一张截图吧。", "hint")
            return
        questions: List[Question] = []
        try:
            questions = parse_questions(text.splitlines())
        except Exception:
            questions = []
        if len(questions) >= 2:
            self._render_multi_answers(questions)
            return
        try:
            hits = self.store.search(text, top_n=3)
        except Exception as exc:
            self._set_result_text(f"查询出错：{exc}", "warn")
            return
        self.current_hits = hits
        if not hits:
            self._render_no_hit(text)
            return
        self._render_hits(text, hits)

    def _start_write(self):
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")

    def _end_write(self):
        self.result.configure(state="disabled")

    def _render_hits(self, query: str, hits):
        top = hits[0]
        q: Question = top.question
        percent = int(round(top.score * 100))
        self._start_write()
        w = self.result.insert

        w("end", f"匹配到：第 {q.qno or '?'} 题", "label")
        w("end", f"    相似度 {percent}%\n", "meta")
        if percent < 80:
            w("end", "⚠ 相似度不高，先核对题干是否为同一道题；不对就在下面候选里挑。\n", "warn")

        w("end", "\n正确答案  ", "label")
        w("end", f"{q.answer_display}\n", "answer")

        mapped = map_answer_to_user_options(q, top.user_options)
        if mapped:
            w("end", "在你贴的选项里对应：", "label")
            w("end", f"  {'、'.join(mapped)}  \n", "answer")
        elif top.user_options:
            w("end", "你贴的选项里没找到完全对应的说法，以上面的答案文字为准。\n", "warn")
        else:
            w("end", "（把 A/B/C/D 选项一起贴进来，我还能算出它在你卷面上是第几个字母）\n", "meta")

        if q.options:
            w("end", "\n原图里的完整选项：\n", "label")
            correct_letters = set(q.answer_letter or "")
            for letter in sorted(q.options):
                mark = "✔ " if letter in correct_letters else "   "
                tag = "optcorrect" if letter in correct_letters else "opt"
                w("end", f"{mark}{letter}. {q.options[letter]}\n", tag)

        if q.source:
            w("end", f"\n来源：{Path(q.source).name}", "meta")
            if Path(q.source).exists():
                w("end", "    ", "meta")
                self.result.window_create("end", window=self._make_link(q.source))
                self.result.insert("end", "\n")
            else:
                w("end", "\n", "meta")

        others = [h for h in hits[1:] if h.score >= 0.45]
        if others:
            w("end", "\n其他可能：\n", "label")
            for i, h in enumerate(others, start=1):
                w("end", f"  {i}. 第 {h.question.qno or '?'} 题（{int(h.score*100)}%）"
                        f" {h.question.stem[:46]}\n", "meta")
        if self._ocr_note:
            w("end", "\n" + self._ocr_note + "\n", "warn")
            self._ocr_note = ""
        w("end", "\n")
        self._end_write()

    def _render_no_hit(self, query: str):
        self._start_write()
        w = self.result.insert
        w("end", "答案库里没有找到足够相似的题目。\n\n", "warn")
        # 关键词兜底：拿最长的中文片段去库里做包含搜索
        tokens = re.findall(r"[\u4e00-\u9fff]{3,}", query)
        token = max(tokens, key=len) if tokens else query[:8]
        rows = self.store.list_questions(keyword=token)[:12]
        if rows:
            w("end", f"不过有 {len(rows)} 条题目包含“{token}”，看看是不是这道：\n", "label")
            for _, q in rows:
                w("end", f"  第 {q.qno} 题  {q.stem[:40]}  →  {q.answer_display[:40]}\n", "meta")
            w("end", "\n把题干多贴几句再查会更准。\n", "hint")
        else:
            w("end", "要么题干贴得太短，要么这些答案图片还没导入。\n", "hint")
            w("end", "先到「导入答案」页把答案图片导进来，再来查。\n", "hint")
        if self._ocr_note:
            w("end", "\n" + self._ocr_note + "\n", "warn")
            self._ocr_note = ""
        self._end_write()

    def _make_link(self, path: str):
        btn = ttk.Button(self.result, text="打开原图", command=lambda p=path: os.startfile(p))
        return btn

    def _set_result_text(self, text: str, tag: Optional[str] = None):
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        if text:
            self.result.insert("end", text, tag or ())
        self.result.configure(state="disabled")

    def _clear_result(self):
        self.current_hits = []
        self._set_result_text("")

    def query_from_file(self):
        path = filedialog.askopenfilename(
            title="选择题目截图",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"), ("全部文件", "*.*")])
        if path:
            self._ocr_and_search(path)

    def query_from_clipboard(self):
        try:
            from PIL import ImageGrab
            data = ImageGrab.grabclipboard()
        except Exception as exc:
            messagebox.showwarning("读取剪贴板失败", f"{exc}\n先用 Win+Shift+S 截个图再试。")
            return
        if data is None:
            messagebox.showinfo("剪贴板里没有图片", "先用 Win+Shift+S 截图（或复制一张图片），再点这个按钮。")
            return
        if isinstance(data, list):
            if data and Path(data[0]).exists():
                self._ocr_and_search(data[0])
            return
        tmp = APP_DIR / "data" / "_clipboard.png"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        data.save(tmp)
        self._ocr_and_search(str(tmp))

    def _ocr_and_search(self, path: str):
        self._set_result_text("正在识别图片…", "hint")
        self.update_idletasks()

        def work():
            try:
                lines = self.ocr.image_lines(path)
                self.queue.put(("query_ocr", path, lines, None))
            except Exception as exc:
                self.queue.put(("query_ocr", path, None, str(exc)))

        threading.Thread(target=work, daemon=True).start()

    # --------------------------------------------------------------- 答案库
    def _refresh_count(self):
        n = self.store.count()
        self.count_var.set(f"答案库：{n} 题")

    def refresh_library(self):
        kw = self.lib_kw.get().strip()
        self.tree.delete(*self.tree.get_children())
        rows = self.store.list_questions(keyword=kw)
        for qid, q in rows:
            stem = q.stem.replace("\n", " ")
            if suspicious_reason(q):
                stem = "⚠ " + stem
            self.tree.insert("", "end", iid=str(qid),
                             values=(q.qno, stem[:90], q.answer_display, q.qtype,
                                     Path(q.source).name if q.source else ""))
        self._refresh_count()
        total = self.store.count()
        if kw:
            self.lib_hint.set(f"关键词「{kw}」命中 {len(rows)} 题（共 {total} 题）。"
                              f"空格可分隔多个词；题干、选项、答案、题号都会被搜索。")
        else:
            self.lib_hint.set(f"共 {total} 题。搜索时可用空格分隔多个词（例如：染色体 组）；"
                              f"双击一行可直接改这题。")

    def clear_library(self):
        """一键清空答案库（两次确认，防误点）。"""
        n = self.store.count()
        if n == 0:
            messagebox.showinfo("提示", "答案库已经是空的。")
            return
        if not messagebox.askyesno(
                "清空答案库",
                f"将删除答案库里全部 {n} 道题。\n\n这个操作不能撤销，建议先「导出 CSV」留个备份。\n\n继续吗？",
                icon="warning", default="no"):
            return
        if not messagebox.askyesno("再次确认", f"真的要清空这 {n} 道题吗？", icon="warning", default="no"):
            return
        removed = self.store.delete_all()
        self.refresh_library()
        messagebox.showinfo("已清空", f"已删除 {removed} 道题，答案库现在是空的。")

    def _selected_ids(self) -> List[int]:
        return [int(i) for i in self.tree.selection()]

    def delete_selected(self):
        ids = self._selected_ids()
        if not ids:
            messagebox.showinfo("提示", "先在列表里选中要删的题目。")
            return
        if not messagebox.askyesno("确认删除", f"删除选中的 {len(ids)} 条题目？此操作不可撤销。"):
            return
        for qid in ids:
            self.store.delete_question(qid)
        self.refresh_library()

    def edit_selected(self):
        ids = self._selected_ids()
        if len(ids) != 1:
            messagebox.showinfo("提示", "一次编辑一道题，请只选一条。")
            return
        q = self.store.get_question(ids[0])
        if not q:
            return
        EditorDialog(self, ids[0], q, self.store, on_save=self.refresh_library)

    def export_csv(self):
        path = filedialog.asksaveasfilename(
            title="导出答案库", defaultextension=".csv",
            initialfile="答案库导出.csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        rows = self.store.list_questions()
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["题号", "题干", "选项", "答案字母", "答案内容", "题型", "来源图片"])
            for _, q in rows:
                opts = " | ".join(f"{k}. {v}" for k, v in sorted(q.options.items()))
                writer.writerow([q.qno, q.stem, opts, q.answer_letter or "",
                                 q.answer_text or "", q.qtype,
                                 Path(q.source).name if q.source else ""])
        messagebox.showinfo("导出完成", f"已导出 {len(rows)} 条到：\n{path}")

    # ----------------------------------------------------------------- 导入
    def choose_files(self):
        paths = filedialog.askopenfilenames(
            title="选择答案图片（可多选）",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"), ("全部文件", "*.*")])
        self._add_import_files(paths)

    def choose_folder(self):
        folder = filedialog.askdirectory(title="选择答案图片所在文件夹")
        if not folder:
            return
        exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
        paths = sorted(str(p) for p in Path(folder).iterdir()
                       if p.is_file() and p.suffix.lower() in exts)
        self._add_import_files(paths)

    def _add_import_files(self, paths):
        for p in paths:
            if p and p not in self.import_files:
                self.import_files.append(p)
                self.file_list.insert("end", f"{Path(p).name}    （{Path(p).parent}）")
        self.import_hint.set(f"共 {len(self.import_files)} 张待识别。整页答案图也可以，一页多题会自动拆开。")

    def clear_import_list(self):
        self.import_files.clear()
        self.file_list.delete(0, "end")
        self.import_hint.set("列表已清空。")

    def _log(self, text: str, tag: str = ""):
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")

    def start_import(self):
        if not self.import_files:
            messagebox.showinfo("提示", "先选择要导入的答案图片。")
            return
        if getattr(self, "_importing", False):
            return
        self._importing = True
        self.start_btn.configure(state="disabled")
        self.progress.configure(maximum=len(self.import_files), value=0)
        self._log(f"开始识别 {len(self.import_files)} 张图片…", "ok")
        files = list(self.import_files)
        dedupe = self.dedupe_var.get()

        def work():
            pending: List[Question] = []
            failed = 0
            for idx, path in enumerate(files, start=1):
                try:
                    lines = self.ocr.image_lines(path)
                    questions = parse_questions(lines, source=path)
                    if not questions:
                        self.queue.put(("import_line", f"⚠ {Path(path).name}：没认出题目，可能图片太糊或不是答案页", "warn"))
                        failed += 1
                    else:
                        pending.extend(questions)
                        sus = [q for q in questions if suspicious_reason(q)]
                        tail = f"，{len(sus)} 题需核对" if sus else ""
                        self.queue.put(("import_line",
                                        f"✓ {Path(path).name}：识别 {len(questions)} 题{tail}", "warn" if sus else "ok"))
                except Exception as exc:
                    failed += 1
                    self.queue.put(("import_line", f"✗ {Path(path).name}：{exc}", "err"))
                self.queue.put(("import_progress", idx, len(files)))
            self.queue.put(("import_review", pending, failed))

        threading.Thread(target=work, daemon=True).start()

    def _open_review(self, questions: List[Question]):
        """识别完先给一张核对表：哪题认错了当场就能改，改完再入库。"""
        ReviewDialog(self, questions, on_confirm=self._commit_import)

    def _commit_import(self, questions: List[Question]):
        if not questions:
            self._log("没有要入库的题目。", "warn")
            self._finish_import()
            return
        dedupe = self.dedupe_var.get()
        added, skipped = self.store.add_questions(
            questions, dedupe_threshold=0.90 if dedupe else 2.0)
        missing = sum(1 for q in questions if not q.answer_letter and not q.answer_text)
        sus = [q for q in questions if suspicious_reason(q)]
        tails = []
        if missing:
            tails.append(f"{missing} 题没有答案")
        if sus:
            tails.append(f"{len(sus)} 题仍可疑（第 " + "、".join(q.qno for q in sus[:6]) + " 题）")
        tail = f"（{'；'.join(tails)}）" if tails else ""
        self._log(f"入库完成：新增 {added} 题，判重跳过 {skipped} 题{tail}",
                  "warn" if (sus or missing) else "ok")
        self._finish_import()

    def _finish_import(self):
        self._importing = False
        self.start_btn.configure(state="normal")
        self._refresh_count()
        self.refresh_library()

    # --------------------------------------------------------------- 队列轮询
    def _poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "query_ocr":
                    _, path, lines, err = item
                    self._update_engine_label()
                    if err:
                        self._set_result_text(f"识别失败：{err}", "warn")
                    else:
                        self._apply_ocr_text(path, lines or [])
                        self.do_search()
                elif kind == "import_line":
                    self._log(item[1], item[2])
                elif kind == "import_progress":
                    self._update_engine_label()
                    self.progress.configure(value=item[1])
                elif kind == "import_review":
                    _, questions, failed = item
                    if failed:
                        self._log(f"有 {failed} 张图片没认出题目。", "warn")
                    if questions:
                        self._log(f"识别结束，共 {len(questions)} 题，请在核对窗口检查后入库。", "ok")
                        self._open_review(questions)
                    else:
                        self._log("没有识别出任何题目。", "warn")
                        self._finish_import()
                elif kind == "import_done":
                    _, added, skipped, failed = item
                    self._log(f"完成：新增 {added} 题，跳过重复 {skipped} 题，失败 {failed} 张。", "ok")
                    self._finish_import()
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _on_close(self):
        try:
            self.store.close()
        finally:
            self.destroy()


class QuestionForm(tk.Toplevel):
    """改一道题（题干 / 选项 / 答案字母），结果交给 on_submit(qno, stem, options, letter)。"""

    def __init__(self, master: tk.Misc, q: Question, on_submit, title: str = "编辑题目"):
        super().__init__(master)
        self.title(title)
        self.geometry("760x600")
        self.transient(master)
        self.grab_set()
        self.on_submit = on_submit

        pad = ttk.Frame(self, padding=12)
        pad.pack(fill="both", expand=True)

        row = ttk.Frame(pad)
        row.pack(fill="x")
        ttk.Label(row, text="题号").pack(side="left")
        self.qno_var = tk.StringVar(value=q.qno)
        ttk.Entry(row, textvariable=self.qno_var, width=8).pack(side="left", padx=(4, 16))
        ttk.Label(row, text="答案字母（多选连写，如 AC）").pack(side="left")
        self.ans_var = tk.StringVar(value=q.answer_letter or "")
        ttk.Entry(row, textvariable=self.ans_var, width=10).pack(side="left", padx=4)

        ttk.Label(pad, text="题干").pack(anchor="w", pady=(10, 2))
        self.stem_text = tk.Text(pad, height=5, wrap="word", font=(UI_FONT, 11), relief="solid", borderwidth=1)
        self.stem_text.insert("1.0", q.stem)
        self.stem_text.pack(fill="x")

        ttk.Label(pad, text="选项（留空表示没有该选项）").pack(anchor="w", pady=(10, 2))
        opts_box = ttk.Frame(pad)
        opts_box.pack(fill="both", expand=True)
        self.opt_vars = {}
        for i, letter in enumerate(OPTION_LETTERS[:6]):
            ttk.Label(opts_box, text=f"{letter}.").grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=q.options.get(letter, ""))
            ttk.Entry(opts_box, textvariable=var).grid(row=i, column=1, sticky="ew", pady=2)
            self.opt_vars[letter] = var
        opts_box.columnconfigure(1, weight=1)

        btns = ttk.Frame(pad)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="保存", command=self.save).pack(side="right")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=8)

    def save(self):
        stem = self.stem_text.get("1.0", "end").strip()
        if not stem:
            messagebox.showwarning("不能保存", "题干不能为空。", parent=self)
            return
        options = {k: v.get().strip() for k, v in self.opt_vars.items() if v.get().strip()}
        letter = re.sub(r"[^A-Ha-h]", "", self.ans_var.get()).upper() or None
        self.on_submit(self.qno_var.get().strip(), stem, options, letter)
        self.destroy()


class EditorDialog(QuestionForm):
    """改答案库里的一条题（写回数据库）。"""

    def __init__(self, master: tk.Misc, qid: int, q: Question, store: AnswerStore, on_save):
        self._qid, self._store, self._on_save = qid, store, on_save
        super().__init__(master, q, self._submit, title=f"编辑第 {q.qno} 题")

    def _submit(self, qno, stem, options, letter):
        self._store.update_question(self._qid, stem, options, letter, qno=qno)
        self._on_save()


class ReviewDialog(tk.Toplevel):
    """导入前核对识别结果：认错的题当场改，认废的题当场删，再确认入库。"""

    def __init__(self, master: tk.Misc, questions: List[Question], on_confirm):
        super().__init__(master)
        self.title(f"核对识别结果（{len(questions)} 题）")
        self.geometry("1080x640")
        self.transient(master)
        self.grab_set()
        self.items = list(questions)
        self.on_confirm = on_confirm
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        pad = ttk.Frame(self, padding=10)
        pad.pack(fill="both", expand=True)

        ttk.Label(pad, foreground="#555",
                  text="识别错了就当场改：双击一行（或按「改这题」）修正题干/选项/答案；"
                       "认废了的按「不要这题」删掉。确认无误再点「全部入库」。").pack(anchor="w")

        cols = ("no", "qno", "stem", "opts", "answer", "state")
        self.tree = ttk.Treeview(pad, columns=cols, show="headings", selectmode="extended")
        for col, title, width in (("no", "#", 46), ("qno", "题号", 58), ("stem", "题干", 540),
                                  ("opts", "选项数", 66), ("answer", "答案", 200), ("state", "状态", 150)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w", stretch=(col == "stem"))
        vsb = ttk.Scrollbar(pad, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True, pady=(8, 0))
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())

        bar = ttk.Frame(pad)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="改这题", command=self.edit_selected).pack(side="left")
        ttk.Button(bar, text="不要这题", command=self.drop_selected).pack(side="left", padx=8)
        ttk.Button(bar, text="取消入库", command=self._cancel).pack(side="right")
        self.confirm_btn = ttk.Button(bar, text="全部入库", command=self.confirm)
        self.confirm_btn.pack(side="right", padx=8)

        self._refresh()

    def _refresh(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for i, q in enumerate(self.items):
            reason = suspicious_reason(q)
            if reason:
                state = "⚠ " + reason
            elif not q.answer_text and not q.answer_letter:
                state = "没有答案"
            else:
                state = "正常"
            self.tree.insert("", "end", iid=str(i),
                             values=(i + 1, q.qno, q.stem.replace("\n", " ")[:110],
                                     len(q.options), q.answer_display, state))
        self.confirm_btn.configure(text=f"全部入库（{len(self.items)} 题）")

    def _selected(self) -> List[int]:
        return [int(i) for i in self.tree.selection()]

    def edit_selected(self):
        ids = self._selected()
        if len(ids) != 1:
            messagebox.showinfo("提示", "一次改一题，请只选一行。", parent=self)
            return
        idx = ids[0]
        q = self.items[idx]
        QuestionForm(self, q,
                     lambda qno, stem, options, letter: self._apply(idx, qno, stem, options, letter),
                     title=f"核对第 {q.qno} 题")

    def _apply(self, idx, qno, stem, options, letter):
        q = self.items[idx]
        q.qno, q.stem, q.options, q.answer_letter = qno, stem, options, letter
        if letter:
            q.answer_text = "；".join(options[c] for c in letter if c in options) or None
        else:
            q.answer_text = None
        self._refresh()

    def drop_selected(self):
        for i in sorted(self._selected(), reverse=True):
            del self.items[i]
        self._refresh()

    def confirm(self):
        items = list(self.items)
        self.destroy()
        self.on_confirm(items)

    def _cancel(self):
        self.destroy()
        self.on_confirm([])


UI_FONT = "Microsoft YaHei UI"


def run():
    global UI_FONT
    UI_FONT = _pick_font()
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        app = App()
        app.mainloop()
    except Exception:
        import traceback
        err_log = APP_DIR / "data" / "启动错误.log"
        try:
            err_log.parent.mkdir(parents=True, exist_ok=True)
            err_log.write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, f"答案速查启动失败：\n\n{traceback.format_exc(limit=3)}\n\n详情已写入：\n{err_log}",
                "答案速查", 0x10)
        except Exception:
            pass


if __name__ == "__main__":
    run()
