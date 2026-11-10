# -*- coding: utf-8 -*-
"""高中学科数据片段（fragment）作者工具。

每个学科一个模块，import 本文件后用 K()/Q() 登记，最后 emit() 写出
data/_hs/<subject>.json。片段是纯数据，不改动 data/*.json；
由 scripts/hs_merge.py 统一合并。
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHAPTER_RE = re.compile(r"^\S+ 第\d+(?:单元|章) \S+$")
TYPES = ("conceptual", "reasoning", "application", "procedural", "modeling")


def Q(prompt, answer, wrongs, explanation, difficulty="standard"):
    """一道四选一：题干、正确项、三个干扰项、解析。"""
    if difficulty not in ("basic", "standard"):
        raise SystemExit("difficulty 只能是 basic / standard")
    wrongs = [str(w).strip() for w in wrongs]
    if len(wrongs) != 3:
        raise SystemExit("干扰项必须 3 个：%s" % str(prompt)[:30])
    return {
        "difficulty": difficulty,
        "prompt": str(prompt).strip(),
        "answer": str(answer).strip(),
        "wrongs": wrongs,
        "explanation": str(explanation).strip(),
    }


def K(key, name, domain, book, unit_no, unit_name, typ, description, criteria, stds, questions):
    """登记一个知识点。

    book      : 册名，必须与 emit() 的 books 里登记的一致，如「中外历史纲要（上）」
    unit_no   : 单元序号（整数）
    unit_name : 单元名，不能含空格
    stds      : 课标条目 id 列表，至少一个
    questions : 恰好 4 道 Q()
    """
    if typ not in TYPES:
        raise SystemExit("%s type 非法：%s" % (key, typ))
    if len(questions) != 4:
        raise SystemExit("%s 需要恰好 4 题" % key)
    if len(stds) < 1:
        raise SystemExit("%s 至少引用 1 条课标" % key)
    return {
        "key": key,
        "name": str(name).strip(),
        "domain": str(domain).strip(),
        "book": book,
        "unitNo": int(unit_no),
        "unitName": str(unit_name).strip(),
        "type": typ,
        "description": str(description).strip(),
        "masteryCriteria": [str(c).strip() for c in criteria],
        "standards": list(stds),
        "questions": questions,
    }


def hard(prereq_key, topic_key, reason):
    """登记一条硬先修：topic 依赖 prereq，prereq 必须排在前面的册/单元/位置。"""
    return {"prerequisiteKey": str(prereq_key), "topicKey": str(topic_key), "reason": str(reason).strip()}


def emit(subject, id_prefix, std_prefix, books, domains, topics, hard_edges, std_items, std_meta, path=None):
    """校验片段并写出 JSON。

    books: [{"grade": 10, "semester": "全"|"上"|"下", "name": "中外历史纲要（上）"}]
    """
    if not re.match(r"^cn[a-z]+_h$", id_prefix):
        raise SystemExit("id_prefix 形态应为 cnh_h / cng_h / cnb_h / cnpo_h")
    keys = [t["key"] for t in topics]
    if len(set(keys)) != len(keys):
        raise SystemExit("知识点 key 重复")
    names = [t["name"] for t in topics]
    if len(set(names)) != len(names):
        raise SystemExit("知识点名称重复")

    book_map = {b["name"]: b for b in books}
    if len(book_map) != len(books):
        raise SystemExit("册名重复")
    for t in topics:
        if t["book"] not in book_map:
            raise SystemExit("%s 的册名未在 books 登记：%s" % (t["key"], t["book"]))
        chapter = "%s 第%d单元 %s" % (t["book"], t["unitNo"], t["unitName"])
        if not CHAPTER_RE.match(chapter):
            raise SystemExit("%s 章节名不合规（单元名不能含空格）：%s" % (t["key"], chapter))
        for q in t["questions"]:
            opts = [q["answer"]] + q["wrongs"]
            if len(set(x.strip().lower() for x in opts)) != 4:
                raise SystemExit("%s 选项重复：%s" % (t["key"], opts))
            blob = q["prompt"] + q["explanation"]
            if re.search(r"本知识点|课标|是否要求", blob):
                raise SystemExit("%s 题干或解析出现元用语" % t["key"])
            if re.match(r"^(同一|上题|该题|同上)", q["prompt"]):
                raise SystemExit("%s 题干以指代词开头" % t["key"])

    order = {b["name"]: i for i, b in enumerate(books)}
    rank = {}
    for i, t in enumerate(topics):
        b = book_map[t["book"]]
        rank[t["key"]] = (order[t["book"]], t["unitNo"], i)
        t["grade"] = b["grade"]
        t["semester"] = b["semester"]
    for e in hard_edges:
        if e["prerequisiteKey"] not in rank or e["topicKey"] not in rank:
            raise SystemExit("硬先修指向未登记知识点：%r" % e)
        if rank[e["prerequisiteKey"]] >= rank[e["topicKey"]]:
            raise SystemExit("硬先修必须排在前面：%s → %s" % (e["prerequisiteKey"], e["topicKey"]))

    ids = {}
    for i, t in enumerate(topics, start=1):
        t["id"] = "%s%03d" % (id_prefix, i)
        ids[t["key"]] = t["id"]
    std_ids = {s["id"] for s in std_items}
    if len(std_ids) != len(std_items):
        raise SystemExit("课标条目 id 重复")

    out_topics = []
    for t in topics:
        chapter = "%s 第%d单元 %s" % (t["book"], t["unitNo"], t["unitName"])
        missing = [s for s in t["standards"] if s not in std_ids]
        if missing:
            raise SystemExit("%s 引用了未登记的课标条目：%s" % (t["key"], missing))
        out_topics.append({
            "id": t["id"],
            "name": t["name"],
            "domain": t["domain"],
            "grade": t["grade"],
            "semester": t["semester"],
            "chapter": chapter,
            "type": t["type"],
            "description": t["description"],
            "mastery_criteria": t["masteryCriteria"],
            "standards": [{"id": s, "confidence": "inferred"} for s in t["standards"]],
            "questions": t["questions"],
            "key": t["key"],
        })

    frag = {
        "subject": subject,
        "idPrefix": id_prefix,
        "stdPrefix": std_prefix,
        "books": books,
        "domains": list(domains),
        "topics": out_topics,
        "hardEdges": [
            {"topicId": ids[e["topicKey"]], "prerequisiteId": ids[e["prerequisiteKey"]], "reason": e["reason"]}
            for e in hard_edges
        ],
        "standardsItems": std_items,
        "standardsMeta": std_meta,
    }

    target = path or os.path.join(ROOT, "data", "_hs", "%s.json" % subject)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(frag, f, ensure_ascii=False, indent=2)
        f.write("\n")

    dom = {}
    for t in out_topics:
        dom[t["domain"]] = dom.get(t["domain"], 0) + 1
    print("写出 %s：知识点 %d，硬先修 %d，课标条目 %d" % (target, len(out_topics), len(hard_edges), len(std_items)))
    for k, v in sorted(dom.items(), key=lambda kv: -kv[1]):
        print("  %s %d" % (k, v))
    return target
