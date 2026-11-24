"""把答案图片 OCR 出来的文字，切成结构化的题目记录。

适配学习平台（超星/学习通式）答案页：
    21.[单选题]
    X染色体属于
    A.C组
    B.E组
    ...
    我的答案：A
    得分：4.4分
同时兼容：1. / 1、 / 第3题 / (3)、【答案】B / 正确答案：C（与“我的答案”同页时以正确答案为准）、
多选、判断（答案为“对/错”）、选项后打 √、全角字母、跨行题干与跨行选项、
以及长截图里混进来的“写笔记”悬浮按钮、分数、章节标题等噪声。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

OPTION_LETTERS = "ABCDEFGH"

# 页脚 / 进度之类
_FOOTER_RE = re.compile(
    r"^(第\s*\d+\s*页(?:\s*[,，/]?\s*共\s*\d+\s*页)?|\d+\s*/\s*\d+|共\s*\d+\s*页|[-—–_=]{3,})$"
)

# 平台 UI 噪声（整行丢弃）
_NOISE_LINE_RES = [
    re.compile(r"^写笔记$"),
    re.compile(r"^(?:我的|本次|本题|您的)?得分[：:]?\s*\d+(?:\.\d+)?\s*分?$"),
    re.compile(r"^已完成$"),
    re.compile(r"^(?:上一节|下一节|上一页|下一页|返回|分享|收藏|举报)+$"),
    re.compile(r"^第[一二三四五六七八九十百\d]+章.*$"),
    re.compile(r"^章节(?:讨论|测试|测验|练习|作业|小结)?$"),
    re.compile(r"^\d+(?:\.\d+)?\s*(?:章节|测试|测验|练习|作业|讨论)$"),
    re.compile(r"^[\(（]?\s*\d+\s*[\)）]?\s*[章节日]"),
    # 作业详情页（超星 App）的固定 UI
    re.compile(r"^(?:作业详情|教师批阅|AI\s*讲解|答案解析|解析|视频讲解|查看解析|题目解析)\s*[:：]?$"),
    # 章节测试卷面底部按钮
    re.compile(r"^(?:暂时保存|暂存|保存|提交|提交试卷|交卷|确认提交)\s*[:：]?$"),
    # 题型徽标单独一行（"单选题"）
    re.compile(r"^(?:单选题|多选题|单项选择题|多项选择题|不定项选择题|判断题|填空题|简答题|问答题|案例分析题)"
               r"(?:\s*[\(（]\s*共\s*\d+\s*题\s*[\)）])?$"),
    # 大题标题："1.单选题(共36题)"
    re.compile(r"^\d{1,3}\s*[\.、．]?\s*(?:单选题|多选题|单项选择题|多项选择题|不定项选择题|判断题|填空题|简答题)"
               r"\s*[\(（]?\s*共\s*\d+\s*题?\s*[\)）]?$"),
]

# 行内噪声片段（直接删掉）
_NOISE_SUB_RE = re.compile(
    r"(?:写笔记|我的得分\s*[：:]?\s*\d+(?:\.\d+)?\s*分?|本次得分\s*[：:]?\s*\d+(?:\.\d+)?\s*分?"
    r"|AI\s*讲解|A[/\\|]\s*讲解|A1\s*讲解)"
)

# 题号后面括号里的“（单选题，2.9分）”——题型留下，分数丢掉
_SCORE_PAREN_RE = re.compile(
    r"[（(]\s*(单选题|多选题|单项选择题|多项选择题|不定项选择题|判断题|填空题|简答题|问答题|案例分析题)?"
    r"\s*[,，]?\s*\d+(?:\.\d+)?\s*分\s*[）)]"
)

# 左括号被 OCR 吃掉的情况：“单选题，2.9分）”
_SCORE_PAREN_NO_OPEN_RE = re.compile(
    r"(单选题|多选题|单项选择题|多项选择题|不定项选择题|判断题|填空题|简答题|问答题|案例分析题)"
    r"\s*[,，]\s*\d+(?:\.\d+)?\s*分\s*[）)]"
)

# 题号：第3题 / (3) / 3. / 3、 / 3)
_QNUM_RES = [
    re.compile(r"^第\s*(\d{1,3})\s*题\s*[\.、．:：]?\s*"),
    re.compile(r"^[\(（]\s*(\d{1,3})\s*[\)）]\s*[\.、．,，:：]?\s*"),
    # 试卷格式：3【单选题】题干（数字后面没有标点，紧接题型标签）
    re.compile(r"^(\d{1,3})\s*(?=[【\[]\s*(?:单选|多选|不定项|判断|填空|简答|问答|案例分析))"),
    re.compile(r"^(\d{1,3})\s*[、\.．\)）:：,，]\s*"),
]

# 试卷格式的选项：字母和文字直接相连（"A性染色体"）、或只隔空格（"A 4"）
_OPT_GLUE_RE = re.compile(r"^[\(（]?\s*([A-Ha-h])\s*[\)）]?\s*[\.、．,，:：]?\s*(\S.*)$")

_QTYPE_WORDS = r"(?:单选|多选|不定项|判断|填空|简答|问答|案例分析)"
_EMBED_QNUM_RE = re.compile(r"(\d{1,3})\s*[、\.．]?\s*[【\[]\s*" + _QTYPE_WORDS)
_BARE_NUM_RE = re.compile(r"^\d{1,3}$")
_TAG_START_RE = re.compile(r"^[【\[]\s*" + _QTYPE_WORDS)

# 题号独占一行（"1." / "1、" / "1"）——浙江高校平台等卷面的版式
_BARE_QNO_RE = re.compile(r"^(\d{1,3})\s*[\.、．\)）]?\s*$")
# 每题右上角的分值独占一行（"3.5分"），同时也是题目分界
_SCORE_ONLY_RE = re.compile(r"^\d+(?:\.\d+)?\s*分$")
# 整行只有一个（或几个并列的）答案字母："B" / "A,C"
_BARE_LETTERS_RE = re.compile(r"^[A-Ha-h](?:\s*[、，,；;/\s]*[A-Ha-h]){0,7}$")

# 答案区标记：我的答案 / 正确答案 / 参考答案 / 标准答案 / 得分
_ANS_MARK_RE = re.compile(r"(?:我的|你的|您)?(?:正确答案|参考答案|标准答案|答案|得分|考分)")
_ANS_LEAD_STRIP = " \t：:，,、。；;【】[]()（）"
_ANS_TAIL_STRIP = " \t：:，,、。；;】)）"
# 字母后面紧跟的分数字段（"得 2.9 分" / "得0分"）不算答案内容
_ANS_SCORE_RE = re.compile(r"^(?:得|扣|满分)?\s*\d+(?:\.\d+)?\s*分")
_ANS_SCORE_TAIL_RE = re.compile(r"[,，]?\s*(?:得|扣)\s*\d+(?:\.\d+)?\s*分")
_LETTERS_RE = re.compile(r"^([A-Ha-h](?:\s*[、，,；;/\s]*[A-Ha-h]){0,9})")

_OPT_STRICT_RE = re.compile(r"^[\(（]?\s*([A-Ha-h])\s*[\)）]?\s*[\.、．,，:：]\s*(.*)$")
_OPT_BRACKET_RE = re.compile(r"^[\(（]\s*([A-Ha-h])\s*[\)）]\s*(.*)$")
_OPT_SPACE_RE = re.compile(r"^([A-Ha-h])\s+(.*)$")
# 只有字母、没有正文的选项行（"B." / "D"）
_OPT_MARKER_ONLY_RE = re.compile(r"^[\(（]?\s*([A-Ha-h])\s*[\)）]?\s*[\.、．,，:：]?$")

_RIGHT_MARK_RE = re.compile(r"(?:[√✓✔]|（正确）|\(正确\)|【正确】|→正确)$")

_QTYPE_RE = re.compile(
    r"[【\[\(（]?\s*(单选题|多选题|单项选择题|多项选择题|不定项选择题|判断题|填空题|简答题|问答题|案例分析题)\s*[】\]\)）]?"
)
_QTYPE_MAP = {"单项选择题": "单选题", "多项选择题": "多选题", "不定项选择题": "多选题"}

_CJK = r"[\u4e00-\u9fff]"
_JUDGE_RE = re.compile(r"^(对|错|正确|错误|是|否|√|×|✓|✗)$")


@dataclass
class Question:
    qno: str = ""
    stem: str = ""
    options: Dict[str, str] = field(default_factory=dict)
    answer_letter: Optional[str] = None
    answer_text: Optional[str] = None
    qtype: str = ""
    source: str = ""
    raw: str = ""

    @property
    def answer_display(self) -> str:
        if self.answer_text:
            return self.answer_text
        if self.answer_letter:
            return "选项 " + "、".join(self.answer_letter)
        return "（原图未标答案）"

    def to_dict(self) -> dict:
        return {
            "qno": self.qno,
            "stem": self.stem,
            "options": dict(self.options),
            "answer_letter": self.answer_letter,
            "answer_text": self.answer_text,
            "qtype": self.qtype,
            "source": self.source,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Question":
        return cls(
            qno=str(d.get("qno") or ""),
            stem=d.get("stem") or "",
            options={k: v for k, v in (d.get("options") or {}).items()},
            answer_letter=d.get("answer_letter") or None,
            answer_text=d.get("answer_text") or None,
            qtype=d.get("qtype") or "",
            source=d.get("source") or "",
            raw=d.get("raw") or "",
        )


def _normalize_line(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).replace("\u3000", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


# OCR 常把遗传学里的 X 读成乘号 ×（X染色体 / X小体），只在紧跟这些词时纠正
_X_GLITCH_RE = re.compile(r"×(?=染色体|小体)")

# zjooc 这类卷面的选项前面带圆圈标记：○ A.xxx / ◉ B.xxx（◉ 是当前选中的那个）
_CIRCLE_MARK_RE = re.compile(r"^[\u25cb\u25c9\u25cf\u25ce\u25ef\u2022\u25aa\u3007]\s*")


def _clean_line(s: str) -> str:
    s = _CIRCLE_MARK_RE.sub("", s)
    s = _NOISE_SUB_RE.sub("", s)
    s = _SCORE_PAREN_RE.sub(lambda m: f"【{m.group(1)}】" if m.group(1) else "", s)
    s = _SCORE_PAREN_NO_OPEN_RE.sub(lambda m: f"【{m.group(1)}】", s)
    s = _X_GLITCH_RE.sub("X", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def _is_noise_line(s: str) -> bool:
    return any(rx.match(s) for rx in _NOISE_LINE_RES)


def _as_lines(text_or_lines: Iterable[str] | str) -> List[str]:
    if isinstance(text_or_lines, str):
        return text_or_lines.splitlines()
    return list(text_or_lines)


def _join_text(a: str, b: str) -> str:
    if not a:
        return b
    if not b:
        return a
    if re.match(_CJK, a[-1]) or re.match(_CJK, b[0]):
        return a + b
    return a + " " + b


def _match_qnum(line: str) -> Optional[tuple[str, str]]:
    for rx in _QNUM_RES:
        m = rx.match(line)
        if not m:
            continue
        rest = line[m.end():].strip()
        if not rest:
            # 整行就只有“第N题”：分值被 _clean_line 剥掉了，这仍是一道题的题号
            if m.end() >= len(line):
                return m.group(1), ""
            continue
        # "7.4 章节测试" 这类小数编号是标题，不是题号
        if m.end() > 0 and line[m.end() - 1] in ".．" and re.match(r"\d", line[m.end():]):
            continue
        return m.group(1), rest
    return None


def _split_answer_segments(line: str) -> tuple[str, List[tuple[str, Optional[str], Optional[str]]]]:
    """把一行拆成 (正文, [(类别, 字母, 文字)])。

    类别：correct（正确答案）、mine（我的答案）、noise（得分）。
    """
    marks = list(_ANS_MARK_RE.finditer(line))
    if not marks:
        return line, []
    prefix = line[: marks[0].start()]
    segs: List[tuple[str, Optional[str], Optional[str]]] = []
    for i, m in enumerate(marks):
        key = m.group(0)
        end = marks[i + 1].start() if i + 1 < len(marks) else len(line)
        seg = line[m.end():end].lstrip(_ANS_LEAD_STRIP).strip(_ANS_TAIL_STRIP)
        if "得分" in key or "考分" in key:
            kind = "noise"
        elif "正确" in key or "参考" in key or "标准" in key:
            kind = "correct"
        else:
            kind = "mine"
        if kind == "noise":
            continue
        # "正确答案 C ， 我的答案：A 得 0 分" 里的“得 X 分”不是答案内容
        seg = _ANS_SCORE_TAIL_RE.sub("", seg).strip(_ANS_TAIL_STRIP)
        lm = _LETTERS_RE.match(seg)
        if lm:
            letters = re.sub(r"[^A-Ha-h]", "", lm.group(1)).upper()
            if letters:
                segs.append((kind, letters, None))
        else:
            # 标记后面什么都没有（"正确答案："单独一行、字母在下一行）→ 记为待填
            segs.append((kind, None, seg or None))
    return prefix, segs


def _strip_answer(line: str) -> tuple[str, Optional[str], Optional[str]]:
    """兼容旧接口：返回 (正文, 答案字母, 文字答案)，正确答案优先。"""
    prefix, segs = _split_answer_segments(line)
    correct_letters = mine_letters = correct_text = mine_text = None
    for kind, letters, text in segs:
        if kind == "correct":
            correct_letters = letters or correct_letters
            correct_text = text or correct_text
        else:
            mine_letters = letters or mine_letters
            mine_text = text or mine_text
    return prefix, (correct_letters or mine_letters), (correct_text or mine_text)


def _split_multi_options(line: str) -> List[str]:
    """OCR 有时把两个选项挤到一行：'A. 甲 B. 乙'，拆开处理。"""
    marks = []
    for m in re.finditer(r"[\(（]?([A-Ha-h])[\)）]?\s*[\.、．]\s*", line):
        start = m.start()
        if start == 0 or line[start - 1] in " \t，,；;":
            marks.append((start, m.group(1).upper()))
    if len(marks) < 2:
        return [line]
    idx = [OPTION_LETTERS.find(x[1]) for x in marks]
    if any(idx[i + 1] - idx[i] != 1 for i in range(len(idx) - 1)):
        return [line]
    parts: List[str] = []
    head = line[: marks[0][0]].strip()
    if head:
        parts.append(head)
    for i, (st, _) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(line)
        parts.append(line[st:end].strip())
    return parts


def _detect_option(piece: str, expected_idx: int) -> tuple[Optional[str], Optional[str]]:
    """识别选项行；expected_idx 是当前期望的下一个选项序号，用来挡住正文里的假选项。"""
    text = piece.strip()
    # 试卷里选项字母被单独识别成一行（"A" 单独一行，下一行才是选项文字）
    if len(text) == 1 and text.upper() in OPTION_LETTERS:
        if OPTION_LETTERS.find(text.upper()) == expected_idx:
            return text.upper(), ""
        return None, None
    for rx in (_OPT_STRICT_RE, _OPT_BRACKET_RE, _OPT_SPACE_RE):
        m = rx.match(piece)
        if not m:
            continue
        letter = m.group(1).upper()
        i = OPTION_LETTERS.find(letter)
        if i < 0:
            continue
        if i > expected_idx + 1:      # 跳了不止一个字母，判为正文
            continue
        if rx is _OPT_SPACE_RE:
            body = m.group(2).strip()
            # 选项正文可能全是英文缩写 / 基因型符号（"AD"、"PKU"、"-a/aa"、"--/--"）
            if not body or len(body) > 40:
                continue
            if i != expected_idx:
                continue
        return letter, m.group(2).strip()
    # 最后兜底：试卷式"字母紧贴文字"，只认当前期望的那个字母。
    # 要求字母是大写、且正文不以小写字母开头 —— 否则 "a珠蛋白位于…"、
    # "ArchibaldGarrod(1857-1936)曾深入研究…" 这类题干会被当成选项 A。
    m = _OPT_GLUE_RE.match(text)
    if m:
        letter = m.group(1)
        body = m.group(2).strip()
        if letter.isupper() and OPTION_LETTERS.find(letter) == expected_idx and body \
                and not re.match(r"[a-z]", body) \
                and (re.search(_CJK, body) or re.search(r"\d", body)) and len(body) <= 220:
            return letter, body
    return None, None


def _option_letter_of(line: str) -> Optional[str]:
    """这一行是不是选项起始行？是则返回字母（含只有字母的 "B."）。"""
    text = (line or "").strip()
    if not text:
        return None
    m = _OPT_MARKER_ONLY_RE.match(text)
    if m:
        return m.group(1).upper()
    for rx in (_OPT_STRICT_RE, _OPT_BRACKET_RE):
        m = rx.match(text)
        if m:
            return m.group(1).upper()
    return None


def _should_absorb_abstract(b: "_Builder", line: str, next_line: str) -> bool:
    """作业详情页里 ✓/✗ 图标会把选项字母整个挤掉，只剩正文行。

    典型形态：`外祖父` / `B.` / `姨表兄弟` / `姑姑` / `D` / ...
    四栏答案页里也会整行丢字母：`B.是符合医学道德的医学行为` / `即使是抢救成功…` / `D.…`。
    正文行的下一行是字母比“当前期望序号”更靠后的选项标记，说明中间那道选项
    的字母丢了 —— 这行就是它的正文。
    """
    next_letter = _option_letter_of(next_line)
    if not next_letter:
        return False
    gap = OPTION_LETTERS.find(next_letter) - b.expected_idx
    if gap < 1:
        return False
    text = (line or "").strip()
    if not text or len(text) > 40 or text[0] in "✓√✗×":
        return False
    if _option_letter_of(text):
        return False
    # 题干行常以空的括号收尾（“…的是（）”），选项正文不会这样
    if re.search(r"[（(]\s*[）)]\s*$", text):
        return False
    return bool(re.search(r"[^\s]", text))


def _finalize(q: Question) -> None:
    stem = q.stem.strip()
    for m in _QTYPE_RE.finditer(stem):
        raw = m.group(1)
        q.qtype = q.qtype or _QTYPE_MAP.get(raw, raw)
        stem = stem.replace(m.group(0), " ")
    stem = re.sub(r"[ \t]+", " ", stem).strip()
    q.stem = stem

    # 选项值整体只有一个 O/o：OCR 把数字 0 认成了字母（"E.O"）
    for k, v in list(q.options.items()):
        if re.fullmatch(r"[Oo]", v.strip()):
            q.options[k] = "0"

    if q.answer_letter:
        letters = list(dict.fromkeys(q.answer_letter))
        q.answer_letter = "".join(letters)
        texts = [q.options[l] for l in letters if l in q.options]
        if texts:
            q.answer_text = "；".join(texts)
    if not q.qtype:
        if q.answer_letter and len(q.answer_letter) > 1:
            q.qtype = "多选题"
        elif q.answer_text and _JUDGE_RE.match(q.answer_text.strip()):
            q.qtype = "判断题"
        elif q.answer_letter:
            q.qtype = "单选题"


def _is_blank_builder(b: "_Builder") -> bool:
    """空壳：只开了一道题的头，题干、选项、答案都还没有。"""
    return not b.q.stem.strip() and not b.q.options and not b.answer_seen


class _Builder:
    def __init__(self, qno: str, source: str):
        self.q = Question(qno=qno, source=source)
        self.expected_idx = 0
        self.last_target: Optional[str] = "stem"
        self.raw: List[str] = []
        self.correct_letters: Optional[str] = None
        self.mine_letters: Optional[str] = None
        self.correct_text: Optional[str] = None
        self.mine_text: Optional[str] = None
        self.answer_seen = False
        # 出现“只有字母、没有正文”的选项行（"A." 一行、正文另起一行）时置位
        self.two_line = False
        # "正确答案：" 后面空着、答案在下一行时，记下待填的类别
        self.pending_kind: Optional[str] = None

    def _set_answer(self, kind: str, letters: Optional[str], text: Optional[str]) -> None:
        if kind == "correct":
            self.correct_letters = letters or self.correct_letters
            self.correct_text = text or self.correct_text
        else:
            self.mine_letters = letters or self.mine_letters
            self.mine_text = text or self.mine_text

    def add_content(self, piece: str) -> None:
        piece = piece.strip()
        if not piece:
            return
        text, segs = _split_answer_segments(piece)
        for kind, letters, ans_text in segs:
            if letters is None and ans_text is None:
                self.pending_kind = kind      # 标记后面还空着，等下一行填
                continue
            self._set_answer(kind, letters, ans_text)
        if segs:
            self.answer_seen = True
        if not text.strip():
            return
        text = text.strip()
        if self.pending_kind:
            kind, self.pending_kind = self.pending_kind, None
            if _BARE_LETTERS_RE.match(text):
                self._set_answer(kind, re.sub(r"[^A-Ha-h]", "", text).upper(), None)
            else:
                self._set_answer(kind, None, text)
            return
        # 选项已经排完（A~E 都在），后面再冒出来的单字母是“答案解析”里的答案残留
        if self.expected_idx >= 5 and len(text) == 1 and text.upper() in OPTION_LETTERS:
            return
        letter, body = _detect_option(text, self.expected_idx)
        if letter is not None:
            body, marked = self._strip_mark(body)
            if marked:
                self.correct_letters = letter
            if not body.strip():
                self.two_line = True      # 字母单独一行，正文另起一行
            self.q.options[letter] = body
            self.last_target = letter
            self.expected_idx = OPTION_LETTERS.find(letter) + 1
            return
        if self.answer_seen and self.expected_idx > 0:
            # 答案区之后的解析文字 / 图标残留，不能再并进选项
            return
        # 有“空壳选项”没填正文（字母行先到、正文后到），先补给最早的那个
        empty = self._first_empty_option()
        if empty is not None:
            self.q.options[empty] = text
            self.last_target = empty
            self.expected_idx = max(self.expected_idx, OPTION_LETTERS.find(empty) + 1)
            return
        # 两行式版式里连续出现的正文行，各是一道选项，只是字母整行丢了
        if (self.two_line and self.expected_idx < 5 and self.last_target != "stem"
                and self.last_target in self.q.options):
            self.absorb_abstract_option(text)
            return
        if self.last_target and self.last_target != "stem" and self.last_target in self.q.options:
            self.q.options[self.last_target] = _join_text(self.q.options[self.last_target], text)
        else:
            self.q.stem = _join_text(self.q.stem, text)
            self.last_target = "stem"

    def _first_empty_option(self) -> Optional[str]:
        for letter in OPTION_LETTERS:
            if letter in self.q.options and not self.q.options[letter].strip():
                return letter
        return None

    @staticmethod
    def _strip_mark(body: str) -> tuple[str, bool]:
        m = _RIGHT_MARK_RE.search(body.strip())
        if m:
            return body.strip()[: m.start()].strip(), True
        return body, False

    def absorb_abstract_option(self, text: str) -> None:
        """字母被图标挤掉时，把一行正文补成当前期望的那个选项。"""
        if self.expected_idx >= len(OPTION_LETTERS):
            return
        letter = OPTION_LETTERS[self.expected_idx]
        self.q.options[letter] = text.strip()
        self.last_target = letter
        self.expected_idx = OPTION_LETTERS.find(letter) + 1

    def finish(self) -> Question:
        q = self.q
        q.raw = "\n".join(self.raw).strip()
        q.answer_letter = self.correct_letters or self.mine_letters
        text_answer = self.correct_text or self.mine_text
        if text_answer and not q.answer_text:
            q.answer_text = text_answer
        _finalize(q)
        return q


def _split_embedded_qnums(lines: List[str]) -> List[str]:
    """修题号被 OCR 拆坏的情况，避免整道题被上一题吞掉。

    两种形态：
    1. 题号粘在上一行末尾：`E A组2【单选题】第二题题干` → 断成两行；
    2. 题号自己占一行、题型标签在下一行：`2` + `【单选题】第二题题干` → 合并成一行。
    """
    out: List[str] = []
    for line in lines:
        pieces: List[str] = []
        start = 0
        for m in _EMBED_QNUM_RE.finditer(line):
            if m.start() == 0 or m.start() <= start:
                continue
            pieces.append(line[start:m.start()])
            start = m.start()
        if not pieces:
            out.append(line)
            continue
        pieces.append(line[start:])
        out.extend(p.strip() for p in pieces if p.strip())

    merged: List[str] = []
    i = 0
    while i < len(out):
        if i + 1 < len(out) and _BARE_NUM_RE.match(out[i]) and _TAG_START_RE.match(out[i + 1]):
            merged.append(out[i].strip() + out[i + 1].strip())
            i += 2
            continue
        merged.append(out[i])
        i += 1
    return merged


def parse_questions(text_or_lines: Iterable[str] | str, source: str = "") -> List[Question]:
    lines = [_clean_line(_normalize_line(x)) for x in _as_lines(text_or_lines)]
    lines = _split_embedded_qnums(lines)
    # 先把纯噪声行摘掉，后面做“下一行是不是选项标记”的前瞻才不会被噪声打断
    lines = [ln for ln in lines if ln and not _FOOTER_RE.match(ln) and not _is_noise_line(ln)]
    out: List[Question] = []
    b: Optional[_Builder] = None

    for i, line in enumerate(lines):
        next_line = lines[i + 1] if i + 1 < len(lines) else ""
        next_is_score = bool(_SCORE_ONLY_RE.match(next_line or ""))
        nm = _OPT_STRICT_RE.match(next_line or "")
        next_is_first_option = bool(nm) and nm.group(1).upper() == "A"

        # 题号独占一行（"1."），分值独占另一行（"3.5分"）。
        # 只认“明显是题目开头”的裸数字：下一行是分值、或下一行就是 A 选项。
        # 手机端的页码条（"18" / "20 21 22 23"）正是靠这条规则避开的。
        bare = _BARE_QNO_RE.match(line)
        if bare and (next_is_score or (b is not None and next_is_first_option)):
            if b is not None and not _is_blank_builder(b):
                out.append(b.finish())
            b = _Builder(bare.group(1), source)
            b.raw.append(line)
            continue

        # 分值行是一道题的结束标志：上一题的题号可能整行被 OCR 漏掉
        if _SCORE_ONLY_RE.match(line):
            if b is not None and b.expected_idx >= 1:
                if not _is_blank_builder(b):
                    out.append(b.finish())
                b = _Builder("", source)
                b.raw.append(line)
            continue

        qm = _match_qnum(line)
        if qm:
            qno, rest = qm
            if b is not None and not _is_blank_builder(b):
                out.append(b.finish())
            b = _Builder(qno, source)
            b.raw.append(line)
            for piece in _split_multi_options(rest):
                b.add_content(piece)
            continue

        if b is None:
            continue   # 第一题之前的标题、广告之类

        b.raw.append(line)
        # 选项字母被 ✓/✗ 图标挤掉时，这行正文要按顺序补成缺失的选项
        if _should_absorb_abstract(b, line, next_line):
            b.absorb_abstract_option(line)
            continue
        for piece in _split_multi_options(line):
            b.add_content(piece)

    if b is not None and not _is_blank_builder(b):
        out.append(b.finish())
    return out


def suspicious_reason(q: Question) -> Optional[str]:
    """切题后自检：返回可疑原因，正常返回 None。

    OCR 偶尔会把相邻两行选项粘成一行，或漏掉一个选项字母，
    这类题要提醒用户到答案库里核对。
    """
    if not q.stem.strip():
        return "题干为空"
    if q.options and q.qtype != "判断题" and len(q.options) < 4:
        return f"只认出 {len(q.options)} 个选项"
    if len(q.options) >= 3:
        lengths = sorted(len(v) for v in q.options.values())
        median = lengths[len(lengths) // 2] or 1
        longest = lengths[-1]
        if longest >= 20 and longest >= median * 2.2:
            return (f"选项文字过长（最长 {longest} 字，其他选项约 {median} 字，"
                    f"可能两行被粘在一起）")
    return None
