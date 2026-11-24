"""题干模糊匹配 + 选项重排映射。

关键点：
1. 题干乱序 / 题号不同 / OCR 小误差 —— 用字符二元组 Dice + 编辑距离双指标比相似度；
2. 选项乱序 —— 答案一律换算成“正确选项的文字”，再拿文字回查用户卷面上的选项；
3. 输出同时给：答案原文、在你选项里对应的字母。
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from .parse import (
    OPTION_LETTERS,
    Question,
    _as_lines,
    _detect_option,
    _join_text,
    _normalize_line,
    _split_multi_options,
    _strip_answer,
)

_QTYPE_WORDS = re.compile(
    r"(单项|多项|不定项|单选|多选|判断|填空|简答|问答|案例分析)?题?|"
    r"单项选择|多项选择|不定项选择"
)
_PUNCT_RE = re.compile(r"[^\w\u4e00-\u9fff]+")
_LEAD_NUM_RE = re.compile(r"^[\(（]?\d{1,3}[\)）]?(?!\d)[\s\.、．,，:：]*(?=\S)")


def normalize_text(s: str) -> str:
    """去掉题号、题型词、标点、空白，只留“可比较的字”。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = s.lower()
    s = _LEAD_NUM_RE.sub("", s)
    s = re.sub(r"(单项选择|多项选择|不定项选择|单选题|多选题|判断题|填空题|简答题|问答题|案例分析题)", "", s)
    s = _PUNCT_RE.sub("", s)
    return s


def _bigrams(s: str) -> set:
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def similarity(a: str, b: str) -> float:
    """0~1 的相似度，兼顾词序与字面片段。"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    if len(a) > 2 and len(b) > 2:
        ga, gb = _bigrams(a), _bigrams(b)
        dice = 2 * len(ga & gb) / (len(ga) + len(gb))
    else:
        dice = seq
    score = max(seq, dice)
    if a in b or b in a:
        score = max(score, 0.98 * min(len(a), len(b)) / max(len(a), len(b)))
    return min(score, 1.0)


def split_question(text: str) -> tuple[str, Dict[str, str]]:
    """把用户粘贴的题目拆成题干 + 选项（选项顺序原样保留）。"""
    stem_parts: List[str] = []
    options: Dict[str, str] = {}
    expected = 0
    started = False
    for raw_line in _as_lines(text):
        line = _normalize_line(raw_line)
        if not line:
            continue
        for piece in _split_multi_options(line):
            content, letters, _ = _strip_answer(piece)
            if not content.strip():
                continue
            letter, body = _detect_option(content, expected)
            if letter is not None:
                started = True
                options[letter] = re.sub(r"(?:[√✓✔]|（正确）|\(正确\))$", "", body).strip()
                expected = OPTION_LETTERS.find(letter) + 1
            elif started and options:
                last = list(options)[-1]
                options[last] = _join_text(options[last], content.strip())
            else:
                stem_parts.append(content.strip())
    return _join_text_lines(stem_parts), options


def _join_text_lines(parts: List[str]) -> str:
    out = ""
    for p in parts:
        out = _join_text(out, p)
    return out


def _option_set_similarity(user_opts: Dict[str, str], key_opts: Dict[str, str]) -> Optional[float]:
    if not user_opts or not key_opts:
        return None
    A = {normalize_text(v) for v in user_opts.values() if v}
    B = {normalize_text(v) for v in key_opts.values() if v}
    if not A or not B:
        return None
    return 2 * len(A & B) / (len(A) + len(B))


@dataclass
class ScanHit:
    question: Question
    score: float
    stem_score: float
    option_score: Optional[float]
    user_options: Dict[str, str] = field(default_factory=dict)


def find_matches(
    query: str,
    questions: Iterable[Question],
    top_n: int = 3,
    threshold: float = 0.45,
) -> List[ScanHit]:
    user_stem, user_opts = split_question(query)
    norm_query = normalize_text(user_stem)
    hits: List[ScanHit] = []
    for q in questions:
        stem_score = similarity(norm_query, normalize_text(q.stem))
        option_score = _option_set_similarity(user_opts, q.options)
        total = stem_score if option_score is None else 0.75 * stem_score + 0.25 * option_score
        if total >= threshold:
            hits.append(ScanHit(q, total, stem_score, option_score, user_opts))
    hits.sort(key=lambda h: (-h.score, -h.stem_score))
    return hits[:top_n]


def _answer_texts(q: Question) -> List[str]:
    if q.answer_text:
        return [t for t in re.split(r"[；;]", q.answer_text) if t.strip()]
    return []


def map_answer_to_user_options(
    question: Question,
    user_options: Optional[Dict[str, str]],
    threshold: float = 0.42,
) -> Optional[List[str]]:
    """把答案原文映射到用户卷面上的选项字母。找不到返回 None。"""
    if not user_options:
        return None
    texts = _answer_texts(question)
    if not texts:
        return None
    matched: List[str] = []
    for text in texts:
        n_text = normalize_text(text)
        raw_text = text.strip()
        # “75%”“0”这类纯数字/符号答案归一化后会被抹成空，先用原文精确比对一次
        if raw_text:
            exact = [letter for letter, opt in user_options.items()
                     if (opt or "").strip() == raw_text]
            if len(exact) == 1:
                matched.append(exact[0])
                continue
        if not n_text:
            continue
        best_letter, best_score, best_raw = None, 0.0, -1.0
        for letter, opt_text in user_options.items():
            opt = (opt_text or "").strip()
            score = similarity(n_text, normalize_text(opt_text))
            # 归一化会把标点/全半角抹平，两个选项可能同分；此时用逐字比对区分"完全一致"的那个
            raw = 1.0 if raw_text == opt else difflib.SequenceMatcher(None, raw_text, opt).ratio()
            if score > best_score + 1e-6 or (abs(score - best_score) <= 1e-6 and raw > best_raw):
                best_letter, best_score, best_raw = letter, score, raw
        if best_letter and best_score >= threshold:
            matched.append(best_letter)
    if not matched:
        return None
    return sorted(set(matched), key=OPTION_LETTERS.find)
