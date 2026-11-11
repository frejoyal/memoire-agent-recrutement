"""Fait tourner Mem0 (bibliothèque mem0ai) en local sur le scénario, et enregistre ce qu'il retient et retrouve.

Usage : python -m memoire.mem0_local   (avec Ollama démarré : gemma4:e4b et bge-m3)

Mem0 appelle lui-même le modèle de langage et le modèle d'embeddings : ses appels ne passent pas par le cache du dépôt.
On enregistre donc son résultat dans resultats/mem0-enregistrement.json : les souvenirs gardés pour chaque utilisateur,
et les 5 souvenirs retrouvés pour chaque question. L'évaluation lit cet enregistrement, ce qui permet à la CI de la refaire.
La télémétrie de Mem0 est coupée : rien ne sort du poste.
"""
import json
import os
import sys
import tempfile
import time

os.environ['MEM0_TELEMETRY'] = 'False'

from .modele import MODELE_EMBEDDING, MODELE_LLM, OLLAMA, RACINE  # noqa: E402

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
SORTIE = RACINE / 'resultats' / 'mem0-enregistrement.json'


def main():
    from importlib.metadata import version

    from mem0 import Memory
    conversations = json.loads((RACINE / 'donnees' / 'conversations.json').read_text(encoding='utf-8'))
    questions = json.loads((RACINE / 'evaluation' / 'questions.json').read_text(encoding='utf-8'))
    # La base Qdrant garde un verrou sur son dossier sous Windows : on ignore les erreurs de nettoyage.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as dossier:
        memoire = Memory.from_config({
            'llm': {'provider': 'ollama', 'config': {'model': MODELE_LLM, 'temperature': 0, 'ollama_base_url': OLLAMA}},
            'embedder': {'provider': 'ollama', 'config': {'model': MODELE_EMBEDDING, 'ollama_base_url': OLLAMA, 'embedding_dims': 1024}},
            'vector_store': {'provider': 'qdrant', 'config': {'path': dossier, 'collection_name': 'recrutement',
                                                              'embedding_model_dims': 1024, 'on_disk': True}},
        })
        debut = time.perf_counter()
        for c in conversations:
            messages = [dict(m) for m in c['messages']]
            # Mem0 date les souvenirs à l'heure réelle : la date simulée de la conversation est donnée dans le texte.
            messages[0]['content'] = f"(Conversation du {c['date']}) {messages[0]['content']}"
            memoire.add(messages, user_id=c['utilisateur'])
            print(f"{c['id']} mémorisée", flush=True)
        duree = time.perf_counter() - debut
        utilisateurs = sorted({c['utilisateur'] for c in conversations})
        souvenirs = {u: sorted(r['memory'] for r in memoire.get_all(filters={'user_id': u}, top_k=500)['results']) for u in utilisateurs}
        rappels = {u: {} for u in utilisateurs}
        for q in questions:
            trouves = memoire.search(q['question'], filters={'user_id': q['utilisateur']}, top_k=5)['results']
            rappels[q['utilisateur']][q['question']] = [r['memory'] for r in trouves]
        SORTIE.write_text(json.dumps({
            'mem0ai': version('mem0ai'),
            'duree_memorisation_s': round(duree),
            'souvenirs': souvenirs,
            'rappels': rappels,
        }, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f"Enregistré dans {SORTIE.relative_to(RACINE)} : " + ', '.join(f'{u} {len(s)} souvenirs' for u, s in souvenirs.items()))


if __name__ == '__main__':
    main()
