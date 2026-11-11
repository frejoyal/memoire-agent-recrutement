"""Mesure les cinq systèmes de mémoire sur les 24 questions de evaluation/questions.json.

Usage :
    python -m memoire.evaluer --mode direct   # calcule avec les modèles locaux et remplit le cache
    python -m memoire.evaluer                 # recalcule à partir du cache, sans modèle
    python -m memoire.evaluer --verifier      # s'arrête en erreur si les résultats diffèrent de ceux publiés (utilisé par la CI)

Déroulement : chaque système lit les 21 conversations dans l'ordre des dates, avec une mémoire séparée par utilisateur.
Le 30 juin 2026, chaque utilisateur pose ses 8 questions. Le même modèle répond à partir de ce que le système lui rappelle.

Correction automatique :
- bonne réponse : la réponse contient, pour chaque groupe de « attendu », une des formes acceptées (minuscules, sans accents,
  mot entier), et ne commence pas par INCONNU ;
- réponse périmée : une réponse fausse qui donne l'ancienne valeur d'une préférence qui a changé ;
- confusion entre utilisateurs : une réponse fausse qui donne la valeur d'un autre utilisateur, ou une réponse à une
  question sur un collègue au lieu d'un refus. Les mémoires étant séparées par utilisateur, aucun système ne peut lire
  les souvenirs d'un collègue : une confusion attribue à quelqu'un ce qui ne le concerne pas ;
- piège refusé : la réponse dit que l'information manque (INCONNU, « je ne me souviens pas »…).
"""
import argparse
import json
import re
import sys
import unicodedata

from .modele import RACINE, Modele
from .systemes import PRENOMS, SYSTEMES, MemoireDeFaits, Mem0Enregistre, prenom

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
RESULTATS = RACINE / 'resultats'
REFUS = re.compile(
    r"\binconnu\b|aucune information|aucun souvenir|je ne me souviens pas|ne m'en souviens pas|je ne sais pas|"
    r"je n'ai pas (cette|d'|de |l')information|je ne trouve (pas|aucune)|n'ai (pas )?trouve|je ne peux pas repondre|"
    r"(n'est|ne sont) pas (disponible|precise|mentionne|indique)|ne (mentionne|precise|indique)(nt)? pas")


def normaliser(texte):
    texte = ''.join(c for c in unicodedata.normalize('NFD', texte.lower()) if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', texte.replace('’', "'").replace(' ', ' ')).strip()


def contient(texte, forme):
    avant = r'(?<![\w-])' if forme[0].isdigit() else r'(?<!\w)'
    return re.search(avant + re.escape(forme) + r'(?!\w)', texte) is not None


def refus(reponse):
    return REFUS.search(normaliser(reponse)) is not None


def reussie(q, reponse):
    texte = normaliser(reponse)
    if not q['attendu']:
        return refus(reponse)
    return not texte.strip(' *.`"').startswith('inconnu') and all(any(contient(texte, f) for f in g) for g in q['attendu'])


def systeme_reponse(utilisateur):
    return (f"Tu es l'assistant personnel de {PRENOMS[utilisateur]}, chez Recrutement Élite inc. Nous sommes le 30 juin 2026. "
            f"Tu réponds à {prenom(utilisateur)} en français, en une ou deux phrases, seulement avec ce dont tu te souviens "
            "de vos conversations passées. Si tu ne t'en souviens pas, réponds exactement INCONNU.")


def invite_reponse(utilisateur, question, rappel):
    if rappel is None:
        return question
    souvenirs = '\n\n'.join(rappel) if rappel else '(aucun souvenir)'
    return f"Ce dont tu te souviens :\n<souvenirs>\n{souvenirs}\n</souvenirs>\n\nQuestion de {prenom(utilisateur)} : {question}"


def evaluer(mode):
    conversations = json.loads((RACINE / 'donnees' / 'conversations.json').read_text(encoding='utf-8'))
    questions = json.loads((RACINE / 'evaluation' / 'questions.json').read_text(encoding='utf-8'))
    enregistrement = RESULTATS / 'mem0-enregistrement.json'
    Mem0Enregistre.enregistrement = json.loads(enregistrement.read_text(encoding='utf-8')) if enregistrement.exists() else None
    systemes = [s for s in SYSTEMES if s is not Mem0Enregistre or Mem0Enregistre.enregistrement]
    modele = Modele(mode)
    utilisateurs = list(PRENOMS)
    resultats, faits = [], {}
    for classe in systemes:
        modele.appels = modele.mots_envoyes = 0
        memoires = {u: classe(modele, u) for u in utilisateurs}
        for c in conversations:
            memoires[c['utilisateur']].memoriser(c)
        appels_memorisation = modele.appels
        modele.appels = modele.mots_envoyes = 0
        details = {}
        for q in questions:
            rappel = memoires[q['utilisateur']].rappeler(q['question'])
            reponse = modele.texte(invite_reponse(q['utilisateur'], q['question'], rappel), systeme=systeme_reponse(q['utilisateur']))
            texte = normaliser(reponse)
            ok = reussie(q, reponse)
            details[q['id']] = {
                'rappel': rappel, 'reponse': reponse, 'reussie': ok,
                'perimee': (not ok) and any(contient(texte, f) for f in q.get('perime', [])),
                'confusion': (q['type'] == 'isolation' and not ok) or ((not ok) and any(contient(texte, f) for f in q.get('confusion', []))),
            }
        modele.enregistrer()
        repondables = [q for q in questions if q['attendu']]
        refus_attendus = [q for q in questions if not q['attendu']]
        avec_perime = [q for q in questions if q.get('perime')]
        exposees = [q for q in questions if q.get('confusion') or q['type'] == 'isolation']
        par_type = {t: round(sum(details[q['id']]['reussie'] for q in repondables if q['type'] == t) /
                             sum(1 for q in repondables if q['type'] == t), 3)
                    for t in dict.fromkeys(q['type'] for q in repondables)}
        if classe is MemoireDeFaits:
            faits = {u: {'faits': m.faits, 'operations': m.operations} for u, m in memoires.items()}
        taille = {
            'Sans mémoire': 0,
            'Historique complet en contexte': sum(len(m.blocs) for m in memoires.values() if hasattr(m, 'blocs')),
            'Mémoire vectorielle naïve': sum(len(getattr(m, 'messages', [])) for m in memoires.values()),
            'Mémoire de faits avec mise à jour': sum(len(getattr(m, 'faits', [])) for m in memoires.values()),
            'Mem0 (local)': sum(len(s) for s in (Mem0Enregistre.enregistrement or {}).get('souvenirs', {}).values()),
        }[classe.nom]
        resultats.append({
            'systeme': classe.nom,
            'bonnes_reponses': round(sum(details[q['id']]['reussie'] for q in repondables) / len(repondables), 3),
            'bonnes_reponses_par_type': par_type,
            'refus_corrects': round(sum(details[q['id']]['reussie'] for q in refus_attendus) / len(refus_attendus), 3),
            'reponses_perimees': sum(details[q['id']]['perimee'] for q in avec_perime),
            'questions_avec_valeur_perimee': len(avec_perime),
            'confusions_entre_utilisateurs': sum(details[q['id']]['confusion'] for q in exposees),
            'questions_exposees_aux_confusions': len(exposees),
            'souvenirs_gardes': taille,
            'appels_llm_memorisation': appels_memorisation if classe is not Mem0Enregistre else None,
            'mots_envoyes_par_question': round(modele.mots_envoyes / len(questions)),
            'details': details,
        })
        r = resultats[-1]
        print(f"{classe.nom} : bonnes réponses {r['bonnes_reponses']:.0%}, refus corrects {r['refus_corrects']:.0%}, "
              f"périmées {r['reponses_perimees']}/{r['questions_avec_valeur_perimee']}, confusions {r['confusions_entre_utilisateurs']}/{r['questions_exposees_aux_confusions']}, "
              f"{r['mots_envoyes_par_question']} mots par question", flush=True)
    return resultats, faits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['cache', 'direct'], default='cache')
    parser.add_argument('--verifier', action='store_true')
    args = parser.parse_args()
    resultats, faits = evaluer(args.mode)
    sortie = json.loads(json.dumps(resultats, ensure_ascii=False))
    if args.verifier:
        identique = sortie == json.loads((RESULTATS / 'resultats.json').read_text(encoding='utf-8'))
        print('Résultats identiques à ceux publiés.' if identique else 'ERREUR : les résultats diffèrent de ceux publiés.')
        sys.exit(0 if identique else 1)
    (RESULTATS / 'resultats.json').write_text(json.dumps(resultats, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (RESULTATS / 'memoire-de-faits.json').write_text(json.dumps(faits, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('Résultats écrits dans resultats/')


if __name__ == '__main__':
    main()
