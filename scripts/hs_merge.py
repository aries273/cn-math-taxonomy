# -*- coding: utf-8 -*-
"""把 data/_hs/*.json 片段合并进 topics / dependencies / questions / 课标。

可重复运行：每次先剥离该学科已有的知识点、先修、题目与课标条目，再重新写入。
用法：python scripts/hs_merge.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SUBJECTS = ["history", "politics", "geography", "biology"]
SUBJECT_LABEL = {"history": "历史", "politics": "思想政治", "geography": "地理", "biology": "生物学"}
KEYS = list("ABCD")


def load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return json.load(f)


def dump(path, data):
    with open(os.path.join(ROOT, path), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def build_questions(topic, offset):
    made = []
    for n, q in enumerate(topic["questions"], start=1):
        texts = list(q["wrongs"])
        texts.insert((offset + n) % 4, q["answer"])
        pos = texts.index(q["answer"])
        made.append({
            "id": "%s_q%d" % (topic["id"], n),
            "topicId": topic["id"],
            "difficulty": q["difficulty"],
            "type": "choice",
            "prompt": q["prompt"],
            "choices": [{"key": KEYS[i], "text": texts[i]} for i in range(4)],
            "answer": KEYS[pos],
            "explanation": q["explanation"],
            "verify": json.dumps(q["answer"], ensure_ascii=False),
        })
    return made


def main():
    topics = load("data/topics.json")
    deps = load("data/dependencies.json")
    questions = load("data/questions.json")
    standards = load("data/cn-curriculum-standards.json")

    frags = []
    for subj in SUBJECTS:
        path = os.path.join(ROOT, "data", "_hs", "%s.json" % subj)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                frags.append(json.load(f))
    if not frags:
        print("没有可合并的片段", file=sys.stderr)
        return 1

    prefixes = [f["idPrefix"] for f in frags]
    std_prefixes = [f["stdPrefix"] for f in frags]

    def ours(tid):
        return any(str(tid).startswith(p) for p in prefixes)

    base_topics = [t for t in topics if not ours(t.get("id"))]
    base_deps = [e for e in deps if not ours(e.get("topicId")) and not ours(e.get("prerequisiteId"))]
    base_questions = [q for q in questions if not ours(q.get("topicId"))]
    base_items = [i for i in standards.get("items", [])
                  if not any(str(i.get("id", "")).startswith(p) for p in std_prefixes)]

    new_topics, new_deps, new_questions, new_items = [], [], [], []
    for frag in frags:
        subj = frag["subject"]
        ts = frag["topics"]
        prefix = frag["idPrefix"]

        ordered_books = [b["name"] for b in frag["books"]]
        by_book = {b: [] for b in ordered_books}
        for t in ts:
            book = next((b for b in ordered_books if t["chapter"].startswith(b + " ")), None)
            if book is None:
                print("%s 的章节不属于已登记册次：%s" % (t["id"], t["chapter"]), file=sys.stderr)
                return 1
            by_book[book].append(t)

        chain = []
        for bi, book in enumerate(ordered_books):
            seq = by_book.get(book, [])
            for i in range(1, len(seq)):
                chain.append((seq[i]["id"], seq[i - 1]["id"],
                              "按%s的常见教学顺序，先学「%s」，再学「%s」。" % (
                                  book, seq[i - 1]["name"], seq[i]["name"])))
            if bi > 0:
                prev_book = ordered_books[bi - 1]
                prev_seq = by_book.get(prev_book, [])
                if prev_seq and seq:
                    chain.append((seq[0]["id"], prev_seq[-1]["id"],
                                  "「%s」是%s的起始内容，先完成「%s」再进入本册。" % (
                                      seq[0]["name"], book, prev_seq[-1]["name"])))

        edges = {}
        for tid, pid, reason in chain:
            edges[(tid, pid)] = {"topicId": tid, "prerequisiteId": pid, "strength": "soft", "reason": reason}
        for e in frag["hardEdges"]:
            edges[(e["topicId"], e["prerequisiteId"])] = {
                "topicId": e["topicId"], "prerequisiteId": e["prerequisiteId"],
                "strength": "hard", "reason": e["reason"],
            }

        for n, t in enumerate(ts):
            tid = t["id"]
            if not tid.startswith(prefix):
                print("%s 的 id 前缀不符：%s" % (subj, tid), file=sys.stderr)
                return 1
            built = build_questions(t, offset=n)
            topic = {
                "id": tid,
                "name": t["name"],
                "domain": t["domain"],
                "grade": t["grade"],
                "semester": t["semester"],
                "chapter": t["chapter"],
                "type": t["type"],
                "description": t["description"],
                "mastery_criteria": t["mastery_criteria"],
                "diagnostic_question": {"question": built[0]["prompt"],
                                        "answer": t["questions"][0]["answer"]},
                "external": False,
                "subject": subj,
                "standards": t["standards"],
            }
            if n == 0:
                topic["root_reason"] = "高中%s从%s开头的单元开始，先修不往前连。" % (
                    SUBJECT_LABEL[subj], frag["books"][0]["name"])
            new_topics.append(topic)
            new_questions.extend(built)

        new_deps.extend(edges.values())

        new_items.extend(frag["standardsItems"])
        print("%s：知识点 %d，边 %d（hard %d），题目 %d，课标条目 %d" % (
            SUBJECT_LABEL[subj], len(ts), len(edges),
            sum(1 for e in edges.values() if e["strength"] == "hard"),
            len(ts) * 4, len(frag["standardsItems"])))

    ids = {t["id"] for t in new_topics}
    for e in new_deps:
        if e["topicId"] not in ids or e["prerequisiteId"] not in ids:
            print("先修边指向缺失知识点：%r" % e, file=sys.stderr)
            return 1

    all_topics = base_topics + new_topics
    all_deps = base_deps + new_deps
    all_questions = base_questions + new_questions

    std_out = dict(standards)
    std_out["items"] = base_items + new_items
    for frag in frags:
        std_out[frag["subject"] + "_senior"] = frag["standardsMeta"]

    dump("data/topics.json", all_topics)
    dump("data/dependencies.json", all_deps)
    dump("data/questions.json", all_questions)
    dump("data/cn-curriculum-standards.json", std_out)

    print("合计：知识点 %d（新增 %d），先修 %d，题目 %d，课标条目 %d" % (
        len(all_topics), len(new_topics), len(all_deps), len(all_questions), len(std_out["items"])))
    by_sub = Counter(t.get("subject") for t in all_topics)
    print("学科分布：", dict(sorted(by_sub.items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
