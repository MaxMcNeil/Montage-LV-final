"""Accès à l'IA (gratuit) : réutilise le moteur de Vid-o-presse-finder (rotation des 5 clés Gemini, tous les modèles
gratuits, relais Groq → Cerebras → OpenRouter, mémoire des quotas). Si ce moteur est indisponible, un client
minimal intégré prend le relais (Gemini puis Groq). Jamais bloquant : sans IA, le montage se fait quand même."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time

import requests

log = logging.getLogger("montage.ai")


def keys(*names: str) -> list[str]:
    out = []
    for n in names:
        for k in re.split(r"[\s,;]+", os.environ.get(n, "") or ""):
            k = k.strip()
            if k and k not in out:
                out.append(k)
    return out


def groq_keys() -> list[str]:
    ks = keys("GROQ_API_KEYS", "GROQ_API_KEY")
    ks += [k for k in keys("FALLBACK_LLM_KEYS") if k.startswith("gsk_") and k not in ks]
    return ks


def parse_json_loose(t: str):
    t = (t or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        pass
    for a, b in (("{", "}"), ("[", "]")):
        i, j = t.find(a), t.rfind(b)
        if i >= 0 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except ValueError:
                continue
    raise ValueError("réponse IA illisible")


class _MiniGemini:
    MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-flash-latest"]
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"

    def __init__(self, ks):
        self.keys = ks
        self.dead: set = set()
        self.i = 0

    def json(self, prompt, image=None, timeout=150):
        parts = []
        if image:
            parts.append({"inline_data": {"mime_type": image[0], "data": base64.b64encode(image[1]).decode()}})
        parts.append({"text": prompt})
        last = ""
        for _ in range(len(self.keys) * len(self.MODELS)):
            k = self.keys[self.i % len(self.keys)]
            self.i += 1
            for m in self.MODELS:
                if (k, m) in self.dead:
                    continue
                try:
                    r = requests.post(self.URL.format(m=m), params={"key": k}, timeout=timeout, json={
                        "contents": [{"role": "user", "parts": parts}],
                        "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"}})
                except requests.RequestException as e:
                    last = str(e)
                    continue
                if r.status_code == 200:
                    try:
                        return parse_json_loose(r.json()["candidates"][0]["content"]["parts"][0]["text"])
                    except (KeyError, IndexError, ValueError) as e:
                        last = str(e)
                        continue
                last = f"HTTP {r.status_code} {r.text[:120]}"
                if r.status_code in (404, 400, 403, 429):
                    self.dead.add((k, m))
                if r.status_code >= 500:
                    time.sleep(3)
        raise RuntimeError(f"Gemini indisponible : {last}")


class _MiniGroq:
    URL = "https://api.groq.com/openai/v1/chat/completions"
    MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    def __init__(self, ks):
        self.keys = ks

    def json(self, prompt, image=None, timeout=120):
        if image:
            raise RuntimeError("Groq : pas d'image")
        last = ""
        for k in self.keys:
            try:
                r = requests.post(self.URL, headers={"Authorization": f"Bearer {k}"}, timeout=timeout, json={
                    "model": self.MODEL, "temperature": 0.3, "response_format": {"type": "json_object"},
                    "messages": [{"role": "user", "content": prompt + "\n\nRéponds uniquement en JSON."}]})
            except requests.RequestException as e:
                last = str(e)
                continue
            if r.status_code == 200:
                try:
                    return parse_json_loose(r.json()["choices"][0]["message"]["content"])
                except (KeyError, IndexError, ValueError) as e:
                    last = str(e)
                    continue
            last = f"HTTP {r.status_code} {r.text[:120]}"
        raise RuntimeError(f"Groq indisponible : {last}")


class AI:
    def __init__(self):
        self.router = None
        self.mini = []
        self.calls = 0
        self.errors: list[str] = []
        try:
            from quote_finder.llm import LLMRouter  # moteur de Vid-o-presse-finder (cloné par le workflow)
            r = LLMRouter.from_env()
            if r.has_text:
                self.router = r
                log.info("IA : moteur Vid-o-presse-finder (rotation des clés et des modèles)")
        except Exception as e:  # noqa: BLE001
            log.info("IA : moteur Vid-o-presse-finder indisponible (%s) → client intégré", str(e)[:120])
        g = keys("GEMINI_API_KEYS", "GEMINI_API_KEY")
        if g:
            self.mini.append(_MiniGemini(g))
        gq = groq_keys()
        if gq:
            self.mini.append(_MiniGroq(gq))

    @property
    def ok(self) -> bool:
        return bool(self.router or self.mini)

    def json(self, prompt: str, image: tuple | None = None, media_key: str = ""):
        """Réponse JSON de l'IA, ou None si toute l'IA est indisponible (le montage continue sans)."""
        self.calls += 1
        if self.router:
            try:
                return self.router.generate_json(prompt, inline_media=image, media_key=media_key)
            except Exception as e:  # noqa: BLE001
                self.errors.append(str(e)[:160])
                log.warning("IA (moteur principal) : %s", str(e)[:160])
        for c in self.mini:
            try:
                return c.json(prompt, image=image)
            except Exception as e:  # noqa: BLE001
                self.errors.append(str(e)[:160])
                log.warning("IA (%s) : %s", type(c).__name__, str(e)[:160])
        return None

    def save_quota(self):
        try:
            from quote_finder import quota
            quota.state().save()
        except Exception:  # noqa: BLE001
            pass
