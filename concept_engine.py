# -*- coding: utf-8 -*-
# AIMENTORA Concept Engine (Engine 3): concept-weighted generation.
# Practice-priority weights from the concept library; not a prediction of any paper.
# plan_set() returns a SINGLE enriched-prompt item so the caller makes ONE fast
# generation call that is concept-weighted (avoids per-concept timeouts).
from math import floor

_FR_NODES = [
 ("a21","Article 21 - Right to Life and Personal Liberty (incl. right to privacy, due process)",99,0.61,0.33),
 ("a19","Article 19 - the six freedoms and reasonable restrictions",93,0.73,0.23),
 ("a32","Article 32 and the five writs - Right to Constitutional Remedies",86,0.85,0.12),
 ("a2022","Articles 20-22 - protection in conviction, double jeopardy, self-incrimination, preventive detention",76,0.80,0.16),
 ("a14","Article 14 - equality before law and equal protection of laws",73,0.52,0.42),
 ("a1518","Articles 15-18 - non-discrimination, equality of opportunity, abolition of untouchability and titles",66,0.67,0.28),
 ("a2324","Articles 23-24 - Right against Exploitation (trafficking, forced labour, child labour)",65,0.61,0.33),
 ("a2528","Articles 25-28 - Right to Freedom of Religion",55,0.64,0.31),
 ("a12","Article 12 - the definition of 'State' for Fundamental Rights",48,0.60,0.34),
 ("a2930","Articles 29-30 - Cultural and Educational Rights of minorities",47,0.70,0.25),
 ("meta","Nature and scope of Fundamental Rights (Part III; citizens vs persons; are they absolute)",46,0.59,0.41),
 ("a13","Article 13 - laws inconsistent with Fundamental Rights and judicial review",44,0.60,0.34),
 ("prop","Right to Property (Article 300A) and the saving clauses (Articles 31A/31B/31C)",44,0.80,0.17),
 ("a21a","Article 21A - Right to Education",42,0.70,0.25),
 ("emg","Suspension of Fundamental Rights during a National Emergency (Articles 358 and 359)",42,1.00,0.00),
 ("a3335","Articles 33-35 - application of Fundamental Rights (armed forces, martial law, Parliament's power)",35,0.60,0.34),
 ("cross","Fundamental Rights linkages - women, voting rights, and international human-rights instruments",33,1.00,0.00),
]
_MAP = {
 ("indian polity","fundamental rights"): _FR_NODES,
 ("polity","fundamental rights"): _FR_NODES,
 ("governance","fundamental rights"): _FR_NODES,
}
_MAX_CONCEPTS = 10

def _lookup(subject, topic):
    s=(subject or "").strip().lower(); t=(topic or "").strip().lower()
    if not t: return None
    for (sk,tk),nodes in _MAP.items():
        if sk in s and tk in t: return nodes
    return None

def is_mapped(subject, topic):
    return _lookup(subject, topic) is not None

def _largest_remainder(weights, total):
    ss=float(sum(weights)) or 1.0
    quotas=[w/ss*total for w in weights]
    base=[floor(q) for q in quotas]
    rem=total-sum(base)
    order=sorted(range(len(weights)), key=lambda i:(quotas[i]-base[i]), reverse=True)
    for i in range(rem): base[order[i%len(order)]] += 1
    return base

def detailed_plan(subject, topic, num_questions):
    """Per-concept weighted allocation (used to build the prompt distribution)."""
    nodes=_lookup(subject, topic)
    if not nodes: return []
    n=max(1,int(num_questions or 1))
    k=min(len(nodes), _MAX_CONCEPTS, n)
    chosen=sorted(nodes, key=lambda x:-x[2])[:k]
    counts=_largest_remainder([c[2] for c in chosen], n)
    out=[]
    for (cid,label,score,ds,an),cnt in zip(chosen,counts):
        if cnt<=0: continue
        out.append({"concept_id":cid,"label":label,"count":int(cnt),"score":score})
    out.sort(key=lambda p:-p["score"])
    return out

def enrich_topic(subject, topic, num_questions):
    dp=detailed_plan(subject, topic, num_questions)
    if not dp: return topic
    parts="; ".join("%d on %s"%(p["count"],p["label"]) for p in dp)
    return (str(topic)+" -- build a single set with a weighted mix across these areas, "
            "roughly this many each: "+parts+". Favour the higher-count areas. VARY the KIND "
            "of question across the set: about half factual/provisional (what specific Articles "
            "and clauses actually say), about a third analytical/conceptual (doctrines and "
            "philosophy: basic structure, the golden triangle of Articles 14-19-21, procedure "
            "established by law vs due process, reasonable classification, horizontal vs "
            "vertical application), and a few current-affairs / case-based questions built on "
            "landmark Supreme Court judgments (e.g. Kesavananda Bharati, Maneka Gandhi, "
            "Puttaswamy, Shreya Singhal, Navtej Johar). Do NOT make every question a "
            "which-Article recall question.")

def plan_set(subject, topic, num_questions):
    """Returns a ONE-item plan: a single enriched-topic generation of the full set.
    The caller's existing per-item loop therefore makes exactly one fast call."""
    if not is_mapped(subject, topic): return []
    n=max(1,int(num_questions or 1))
    return [{"concept_id":"weighted","topic":enrich_topic(subject, topic, n),
             "count":n,"question_type":"all","score":100}]
