"""Appels aux modèles locaux (Ollama), avec un cache publié dans le dépôt.

En mode « direct », les modèles tournent sur le poste et le cache se remplit.
En mode « cache », rien n'est calculé : tout vient du cache. C'est ce que fait la CI, sans modèle ni réseau.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

RACINE = Path(__file__).resolve().parent.parent
CACHE = RACINE / 'resultats' / 'cache'
OLLAMA = 'http://127.0.0.1:11434'
MODELE_LLM = 'gemma4:e4b'
MODELE_EMBEDDING = 'bge-m3'
OPTIONS = {'temperature': 0, 'seed': 7, 'num_ctx': 16384, 'num_predict': 800}


def cle(*parties):
    return hashlib.sha1('\x1f'.join(parties).encode('utf-8')).hexdigest()


class Modele:
    def __init__(self, mode='cache'):
        if mode not in ('cache', 'direct'):
            raise ValueError(mode)
        self.mode = mode
        CACHE.mkdir(parents=True, exist_ok=True)
        f = CACHE / 'reponses.json'
        self._reponses = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
        f = CACHE / 'embeddings.npz'
        self._vecteurs = {}
        if f.exists():
            d = np.load(f)
            self._vecteurs = dict(zip(d['cles'].tolist(), d['vecteurs']))
        self._utilisees = set()
        self.modifie = False
        self.appels = 0
        self.mots_envoyes = 0

    def _manque(self):
        raise RuntimeError('Calcul absent du cache : relancez en mode direct, avec Ollama démarré.')

    def texte(self, invite, systeme=None):
        messages = ([{'role': 'system', 'content': systeme}] if systeme else []) + [{'role': 'user', 'content': invite}]
        k = cle(MODELE_LLM, json.dumps(messages, ensure_ascii=False, sort_keys=True), json.dumps(OPTIONS, sort_keys=True))
        self.appels += 1
        self.mots_envoyes += sum(len(m['content'].split()) for m in messages)
        self._utilisees.add(k)
        if k not in self._reponses:
            if self.mode == 'cache':
                self._manque()
            import requests
            r = requests.post(f'{OLLAMA}/api/chat', json={'model': MODELE_LLM, 'messages': messages, 'stream': False,
                                                         'think': False, 'options': OPTIONS}, timeout=900)
            r.raise_for_status()
            self._reponses[k] = (r.json()['message'].get('content') or '').strip()
            self.modifie = True
        return self._reponses[k]

    def vecteurs(self, textes):
        cles = [cle(MODELE_EMBEDDING, t) for t in textes]
        manquants = [(k, t) for k, t in zip(cles, textes) if k not in self._vecteurs]
        if manquants:
            if self.mode == 'cache':
                self._manque()
            import requests
            for i in range(0, len(manquants), 16):
                lot = manquants[i:i + 16]
                r = requests.post(f'{OLLAMA}/api/embed', json={'model': MODELE_EMBEDDING, 'input': [t for _, t in lot]}, timeout=600)
                r.raise_for_status()
                for (k, _), v in zip(lot, r.json()['embeddings']):
                    self._vecteurs[k] = np.asarray(v, dtype=np.float16)
            self.modifie = True
        m = np.stack([self._vecteurs[k].astype(np.float32) for k in cles])
        return m / np.linalg.norm(m, axis=1, keepdims=True)

    def enregistrer(self, elaguer=False):
        if elaguer:
            self._reponses = {k: v for k, v in self._reponses.items() if k in self._utilisees}
            self.modifie = True
        if not self.modifie:
            return
        (CACHE / 'reponses.json').write_text(json.dumps(dict(sorted(self._reponses.items())), ensure_ascii=False, indent=0) + '\n',
                                            encoding='utf-8')
        cles = sorted(self._vecteurs)
        if cles:
            np.savez_compressed(CACHE / 'embeddings.npz', cles=np.array(cles),
                                vecteurs=np.stack([self._vecteurs[k] for k in cles]))
        self.modifie = False
