"""Compteur IA de PLAN.md : qui a répondu (Gemini par modèle, relais, sans réponse)."""
from types import SimpleNamespace as NS

from montage import ai as A


def make(router_behaviour):
    ai = A.AI.__new__(A.AI)
    ai.calls, ai.errors, ai.recovered, ai.waited, ai.by_source, ai.mini = 0, [], 0, 999, {}, []
    gem = NS(used={})

    def gen(prompt, inline_media=None, media_key=""):
        how = router_behaviour.pop(0)
        if how == "gemini":
            gem.used["gemini-2.5-flash"] = gem.used.get("gemini-2.5-flash", 0) + 1
            return {"ok": 1}
        if how == "relais":
            return {"ok": 1}
        raise RuntimeError("quota")
    ai.router = NS(gemini=gem, generate_json=gen)
    return ai


def test_usage_line_counts_each_source():
    ai = make(["gemini", "gemini", "relais", "fail"])
    for _ in range(4):
        ai.json("question")
    line = ai.usage_line()
    assert line.startswith("IA : 4 demande(s)")
    assert "Gemini 2 (gemini-2.5-flash 2)" in line and "relais Groq / Cerebras / OpenRouter 1" in line
    assert "sans réponse 1" in line


def test_no_call():
    ai = make([])
    assert ai.usage_line() == "IA : aucune demande"
