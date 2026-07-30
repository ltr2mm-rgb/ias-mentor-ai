"""
gen_ops_data.py — the OFFLINE (snapshot) producer of ExperimentOpsArtifact v1.

Builds representative `ExperimentResult`s by running the REAL evaluator functions
over synthetic outcomes, then routes them through the SAME
`experiment_ops_adapter.to_artifact()` the live runner uses — so the snapshot and
live artifacts are shape-identical by construction (proven by the parity test).
Writes ops_data.json.
"""
import os, sys, json, datetime
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
os.environ.setdefault("DATABASE_URL", "sqlite:///./_ops_gen.db")
import mission_engine as me, mission_outcome as mo
import policy_scorecard as ps, policy_confidence as pc, policy_promotion as pp
import experiment as ex, experiment_ops_adapter as adapter

DET, CAND = me.POLICY_DET, me.POLICY_DET_11


def rep(pattern, n):
    return (pattern * ((n // len(pattern)) + 1))[:n]


def make_outcomes(policy, n, gain_pattern, complete_pattern, att_pattern, elapsed_pattern, base_seq):
    outs = []
    gains, comps = rep(gain_pattern, n), rep(complete_pattern, n)
    atts, elaps = rep(att_pattern, n), rep(elapsed_pattern, n)
    for i in range(n):
        completed = comps[i] == 1
        cseq = base_seq + i * 3
        outs.append({
            "mission_id": "%s-%d" % (policy[-4:], i), "policy_version": policy,
            "state": "COMPLETED" if completed else "CANCELLED", "completed": completed,
            "mastery_gain": round(gains[i], 4) if completed else None,
            "attempts_on_target": atts[i], "elapsed_seq": elaps[i] if completed else None,
            "created_seq": cseq, "terminal_seq": cseq + 2,
        })
    return outs


def make_result(exp_obj, default_outs, cand_outs):
    """Assemble a synthetic ExperimentResult in the SAME shape run_experiment emits,
    with scorecard/promotion computed by the real evaluator functions."""
    outs = default_outs + cand_outs
    agg = mo.aggregate_by_policy(outs)
    samples = pc.samples_by_policy(outs)
    d_s, c_s = samples.get(DET, {}), samples.get(CAND, {})
    sc = ps.build_scorecard(agg, DET, CAND)
    enriched = pc.enrich_scorecard(sc, d_s, c_s, d_s.get("window"), c_s.get("window"))
    cfg = {"primary": {"metric": exp_obj.primary_metric, "direction": "higher"},
           "guardrails": [{"metric": g, "direction": "higher"} for g in exp_obj.guardrails],
           "min_sample_size": exp_obj.minimum_sample}
    decision = pp.decide(d_s, c_s, cfg)
    all_seqs = [o["created_seq"] for o in outs]
    return {
        "experiment_layer_version": ex.EXPERIMENT_LAYER_VERSION,
        "experiment": exp_obj.to_dict(),
        "enrolled": len(outs),
        "arm_counts": {DET: len(default_outs), CAND: len(cand_outs)},
        "in_window_outcomes": len(outs),
        "window": {"basis": "per-learner seq [enrollment_seq, end_seq]",
                   "start_seq": min(all_seqs), "end_seq": exp_obj.end_seq},
        "result": {"scorecard": enriched, "promotion": decision},
    }


def build_snapshot_artifact(generated_at=None):
    """Representative ExperimentOpsArtifact v1 (source.kind == 'snapshot')."""
    gen_at = generated_at or (datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z")

    featured_exp = ex.Experiment(
        id="exp-17", default_policy=DET, candidate_policy=CAND, end_seq=10000, minimum_sample=20,
        title="Spaced-repetition due gate", status="closed",
        hypothesis="Interrupt acquisition only when a review is genuinely due.",
        activated_at="2026-07-29")
    featured = make_result(featured_exp,
        make_outcomes(DET, 46, [0.08, 0.12, 0.10, 0.11], [1,1,1,1,0], [5,6,4], [6,7,5,6], 20),
        make_outcomes(CAND, 44, [0.17, 0.21, 0.19, 0.18], [1,1,1,1,0], [5,5,6], [6,6,5,7], 20))

    h16 = make_result(ex.Experiment(id="exp-16", default_policy=DET, candidate_policy=CAND,
        end_seq=8000, minimum_sample=20, title="Due gate 0.6 (first trial)", status="closed",
        activated_at="2026-07-28"),
        make_outcomes(DET, 42, [0.09, 0.11], [1,1,1,1,0], [5], [6], 10),
        make_outcomes(CAND, 42, [0.18, 0.20], [1,1,1,1,0], [5], [6], 10))
    h15 = make_result(ex.Experiment(id="exp-15", default_policy=DET, candidate_policy=CAND,
        end_seq=6000, minimum_sample=20, title="Aggressive due threshold 0.75", status="closed",
        activated_at="2026-07-26"),
        make_outcomes(DET, 40, [0.10, 0.12], [1,1,1,1,0], [5], [6], 10),
        make_outcomes(CAND, 40, [0.16, 0.18], [1,0], [5], [6], 10))
    h14 = make_result(ex.Experiment(id="exp-14", default_policy=DET, candidate_policy=CAND,
        end_seq=4000, minimum_sample=20, title="Retention-first ordering (pilot)", status="closed",
        activated_at="2026-07-24"),
        make_outcomes(DET, 8, [0.10], [1,1,1,0], [5], [6], 10),
        make_outcomes(CAND, 8, [0.15], [1,1,1,1], [5], [6], 10))

    return adapter.to_artifact(featured, [h16, h15, h14],
                               source_kind="snapshot", generated_at=gen_at,
                               artifact_version="ops-1.0")


if __name__ == "__main__":
    art = build_snapshot_artifact()
    with open(os.path.join(HERE, "ops_data.json"), "w") as f:
        json.dump(art, f, indent=2)
    print("featured decision:", art["featured"]["promotion"]["decision"], art["featured"]["promotion"]["verdict"])
    print("history:", [(h["experiment_id"], h["decision"], h["verdict"]) for h in art["history"]])
    print("promotion_history:", [(p["experiment_id"], p["action"]) for p in art["promotion_history"]])
    print("schema:", art["schema"], art["schema_version"], "· replay_hash:", art["replay"]["replay_hash"])
    print("wrote ops_data.json")
