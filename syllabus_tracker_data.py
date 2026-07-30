"""
UPSC Civil Services syllabus tracker data.

The detailed micro-topic hierarchy is loaded from syllabus_tracker.json
(stage -> paper -> section -> topics). Topics are plain strings; stable IDs are
generated from their position so the frontend can render tickable checklists and
the backend can record completion.

If the JSON is missing, a compact built-in fallback is used so the feature still
works.
"""
import os
import json

_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "syllabus_tracker.json")

_FALLBACK = [
    {"stage": "Prelims", "papers": [
        {"paper": "GS Paper I", "sections": [
            {"section": "History", "topics": ["Ancient India", "Medieval India", "Modern India", "Art & Culture", "Indian National Movement"]},
            {"section": "Geography", "topics": ["Physical Geography", "Indian Geography", "World Geography"]},
            {"section": "Polity & Governance", "topics": ["Constitution", "Union & State Government", "Judiciary", "Local Government"]},
            {"section": "Economy", "topics": ["Basics", "Money & Banking", "Fiscal Policy", "External Sector"]},
            {"section": "Environment", "topics": ["Ecology", "Biodiversity", "Climate Change", "Pollution"]},
            {"section": "Science & Technology", "topics": ["Space", "Defence", "Biotech", "IT"]},
            {"section": "Current Affairs", "topics": ["National", "International", "Economy", "Schemes & Reports"]},
        ]},
        {"paper": "CSAT Paper II", "sections": [
            {"section": "CSAT", "topics": ["Comprehension", "Reasoning", "Numeracy", "Data Interpretation"]},
        ]},
    ]},
]


def _load():
    if os.path.exists(_JSON):
        try:
            with open(_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return _FALLBACK


SYLLABUS = _load()


def tree_with_ids():
    """Nested syllabus with stable IDs and counts.
    Topic ID format: '<stageIdx>.<paperIdx>.<sectionIdx>.<topicIdx>'."""
    out = []
    for si, stage in enumerate(SYLLABUS):
        s_node = {"id": f"s{si}", "stage": stage["stage"], "papers": [], "total": 0}
        for pi, paper in enumerate(stage["papers"]):
            p_node = {"id": f"{si}.{pi}", "paper": paper["paper"], "sections": [], "total": 0}
            for ci, sec in enumerate(paper["sections"]):
                topics = [{"id": f"{si}.{pi}.{ci}.{ti}", "label": t}
                          for ti, t in enumerate(sec["topics"])]
                p_node["sections"].append({"id": f"{si}.{pi}.{ci}", "section": sec["section"],
                                           "topics": topics, "total": len(topics)})
                p_node["total"] += len(topics)
            s_node["papers"].append(p_node)
            s_node["total"] += p_node["total"]
        out.append(s_node)
    return out


def all_topic_ids():
    ids = set()
    for si, stage in enumerate(SYLLABUS):
        for pi, paper in enumerate(stage["papers"]):
            for ci, sec in enumerate(paper["sections"]):
                for ti, _ in enumerate(sec["topics"]):
                    ids.add(f"{si}.{pi}.{ci}.{ti}")
    return ids


def total_topics():
    return len(all_topic_ids())
