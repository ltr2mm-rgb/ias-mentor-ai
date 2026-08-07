/* ============================================================================
   real_mission_api.js — RealMissionAPI: the transport-only adapter that fulfils the
   FROZEN Mission API contract (mission_api.md) against the live /me/... endpoints.

   Drop-in replacement for AIMLoop.MockMissionAPI. The module cannot tell them apart
   (proven by test_contract_equivalence). To go live, change ONE injected dependency:
       AIMLoop.init({ mount: "#aimloop-mount", api: RealMissionAPI })

   TRANSPORT ONLY — HTTP → deserialize → return Promise. It performs exactly the two
   transformations the contract sanctions, and NOTHING else (if an endpoint returns the
   wrong shape, fix the endpoint, not this adapter):
     1. submitAnswer(qid, selectedIndex): maps the 0-based index → letter A–D for
        POST /me/attempt (the contract documents this mapping).
     2. submitAnswer response: picks {correct, correct_index, explanation}; `explanation`
        is /me/attempt's `answer_explanation` (renamed only because /me/attempt already
        uses `explanation` for its intel field — a name collision at the endpoint).

   Dev logging (your recommendation): each call logs method · endpoint · status · whether
   the payload satisfied the expected contract. Toggle with RealMissionAPI.configure({debug:false}).
   ========================================================================== */
window.RealMissionAPI = (function () {
  "use strict";

  var cfg = {
    base: "",
    debug: true,
    // auth: reuse the SPA's session token. Override via configure({getToken}) if the
    // app exposes it differently. Cookies (same-origin) are also sent.
    getToken: function () {
      try {
        return (typeof window !== "undefined" && window.token) ||
               localStorage.getItem("ias_token") ||
               localStorage.getItem("token") || null;
      } catch (e) { return null; }
    }
  };

  function log(method, ep, status, okShape) {
    if (!cfg.debug || typeof console === "undefined") return;
    var tag = okShape === undefined ? "" : (okShape ? " ✓contract" : " ✗contract-mismatch");
    (console.debug || console.log).call(console, "[AIMLoop/api] " + method + " " + ep + " → " + status + tag);
  }

  function headers(hasBody) {
    var h = { "Accept": "application/json" };
    if (hasBody) h["Content-Type"] = "application/json";
    var t = cfg.getToken && cfg.getToken();
    if (t) h["Authorization"] = "Bearer " + t;
    return h;
  }

  function req(method, ep, body, expect) {
    var opts = { method: method, headers: headers(!!body), credentials: "same-origin" };
    if (body) opts.body = JSON.stringify(body);
    return fetch(cfg.base + ep, opts).then(function (r) {
      return r.text().then(function (txt) {
        var data = null;
        try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = null; }
        var okShape = expect ? !!expect(data) : undefined;
        log(method, ep, r.status, okShape);
        if (!r.ok) {
          var err = new Error((data && data.detail) || ("HTTP " + r.status));
          err.status = r.status; err.retryable = (r.status >= 500);
          throw err;
        }
        // In development, a 2xx with the WRONG shape (a dropped/renamed field) is a
        // contract regression — fail loudly rather than letting the UI run on partial
        // data. With debug:false this reverts to logging only (production tolerance).
        if (cfg.debug && expect && !okShape) {
          throw new Error("Mission API contract mismatch: " + method + " " + ep);
        }
        return data;
      });
    }, function () {
      log(method, ep, 0);
      var e = new Error("network error"); e.status = 0; e.retryable = true; throw e;
    });
  }

  var LETTERS = ["A", "B", "C", "D"];

  return {
    configure: function (o) { for (var k in (o || {})) cfg[k] = o[k]; },

    getCurrentMission: function () {
      return req("GET", "/me/mission/current", null,
        function (d) { return d && ("mission_id" in d) && ("reason" in d); });
    },
    getMissionDetail: function (id) {
      return req("GET", "/me/mission/" + encodeURIComponent(id), null,
        function (d) { return d && ("concept" in d) && ("n_questions" in d); });
    },
    getQuestions: function (id) {
      return req("GET", "/me/mission/" + encodeURIComponent(id) + "/questions", null,
        function (d) { return Array.isArray(d) && (d.length === 0 || ("options" in d[0])); });
    },
    submitAnswer: function (questionId, selectedIndex) {
      return req("POST", "/me/attempt",
        { question_id: questionId, selected: LETTERS[selectedIndex] },
        function (d) { return d && ("correct" in d); }
      ).then(function (d) {
        return {
          correct: !!d.correct,
          correct_index: (d.correct_index == null ? null : d.correct_index),
          explanation: d.answer_explanation || d.explanation || ""
        };
      });
    },
    getOutcome: function (id) {
      return req("GET", "/me/mission/" + encodeURIComponent(id) + "/outcome", null,
        function (d) { return d && ("mastery_after" in d) && ("next_recommendation" in d); });
    }
  };
})();
