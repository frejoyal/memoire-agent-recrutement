"""Les systèmes de mémoire comparés. Chaque système a une mémoire séparée par utilisateur.

- Sans mémoire : l'assistant ne se souvient de rien.
- Historique complet : toutes les conversations passées de l'utilisateur sont redonnées au modèle.
- Mémoire vectorielle naïve : chaque message de l'utilisateur est gardé tel quel ; on retrouve les 5 plus proches de la question.
- Mémoire de faits : après chaque conversation, le modèle extrait des faits durables, puis décide pour chacun s'il est nouveau,
  s'il remplace un fait existant (l'ancien est gardé dans son historique) ou s'il est déjà connu. On retrouve les 5 faits
  les plus proches de la question. C'est le mécanisme de Mem0, écrit en clair.
- Mem0 : la bibliothèque mem0ai, en local (voir mem0_local.py). Ses souvenirs sont enregistrés dans resultats/.
"""
import json
import re

import numpy as np

PRENOMS = {'julie': 'Julie Ouellet', 'karim': 'Karim Benali', 'sophie': 'Sophie Gendreau'}
RAPPELS = 5


def prenom(u):
    return PRENOMS[u].split()[0]


def les_plus_proches(modele, question, textes, n=RAPPELS):
    if not textes:
        return []
    scores = modele.vecteurs(textes) @ modele.vecteurs([question])[0]
    ordre = sorted(range(len(textes)), key=lambda i: (-round(float(scores[i]), 6), i))
    return [textes[i] for i in ordre[:n]]


def json_de(texte, cle):
    trouve = re.search(r'\{.*\}', texte, flags=re.S)
    try:
        return json.loads(trouve.group(0)).get(cle) if trouve else None
    except (json.JSONDecodeError, AttributeError):
        return None


class SansMemoire:
    nom = 'Sans mémoire'

    def __init__(self, modele, utilisateur):
        pass

    def memoriser(self, conversation):
        pass

    def rappeler(self, question):
        return None


class HistoriqueComplet:
    nom = 'Historique complet en contexte'

    def __init__(self, modele, utilisateur):
        self.utilisateur, self.blocs = utilisateur, []

    def memoriser(self, conversation):
        lignes = [f"## Conversation du {conversation['date']}"]
        lignes += [f"{prenom(self.utilisateur) if m['role'] == 'user' else 'Assistant'} : {m['content']}" for m in conversation['messages']]
        self.blocs.append('\n'.join(lignes))

    def rappeler(self, question):
        return self.blocs


class VectorielleNaive:
    nom = 'Mémoire vectorielle naïve'

    def __init__(self, modele, utilisateur):
        self.modele, self.utilisateur, self.messages = modele, utilisateur, []

    def memoriser(self, conversation):
        self.messages += [f"[{conversation['date']}] {prenom(self.utilisateur)} : {m['content']}"
                          for m in conversation['messages'] if m['role'] == 'user']

    def rappeler(self, question):
        return les_plus_proches(self.modele, question, self.messages)


class MemoireDeFaits:
    nom = 'Mémoire de faits avec mise à jour'

    def __init__(self, modele, utilisateur):
        self.modele, self.utilisateur = modele, utilisateur
        self.faits = []          # {'texte', 'date', 'historique': [(date, texte)]}
        self.operations = {'AJOUTER': 0, 'REMPLACER': 0, 'IGNORER': 0}

    def memoriser(self, conversation):
        p = prenom(self.utilisateur)
        echange = '\n'.join(f"{p if m['role'] == 'user' else 'Assistant'} : {m['content']}" for m in conversation['messages'])
        invite = (
            f"Voici une conversation du {conversation['date']} entre {p} et son assistant.\n<conversation>\n{echange}\n</conversation>\n\n"
            f"Extrais les faits durables sur {p} : ses préférences, ses règles de travail, ses relations avec des clients ou des contacts, "
            "et les événements qui la ou le concernent. Ignore les salutations et le bavardage. "
            f"Chaque fait est une phrase courte en français qui commence par « {p} ». Recopie les chiffres, les noms et les dates exactement. "
            'Réponds seulement avec du JSON, sous cette forme : {"faits": ["...", "..."]}'
        )
        nouveaux = json_de(self.modele.texte(invite), 'faits') or []
        for fait in [f for f in nouveaux if isinstance(f, str) and f.strip()]:
            self._integrer(fait.strip(), conversation['date'])

    def _integrer(self, fait, date):
        if not self.faits:
            self.faits.append({'texte': fait, 'date': date, 'historique': []})
            self.operations['AJOUTER'] += 1
            return
        textes = [f['texte'] for f in self.faits]
        proches = les_plus_proches(self.modele, fait, textes)
        numeros = [textes.index(t) for t in proches]
        invite = (
            "Mémoire actuelle (faits numérotés) :\n" +
            '\n'.join(f"[{i}] {self.faits[n]['texte']} (noté le {self.faits[n]['date']})" for i, n in enumerate(numeros)) +
            f"\n\nNouveau fait, noté le {date} : {fait}\n\n"
            "Décide quoi faire du nouveau fait. AJOUTER s'il apporte une information absente de la mémoire. "
            "REMPLACER s'il met à jour ou contredit un fait de la mémoire : donne le numéro de ce fait. "
            "IGNORER s'il dit la même chose qu'un fait de la mémoire. "
            'Réponds seulement avec du JSON, sous cette forme : {"operation": "AJOUTER", "numero": null}'
        )
        texte = self.modele.texte(invite)
        operation = (json_de(texte, 'operation') or 'AJOUTER').upper()
        numero = json_de(texte, 'numero')
        if operation == 'REMPLACER' and isinstance(numero, int) and 0 <= numero < len(numeros):
            ancien = self.faits[numeros[numero]]
            ancien['historique'].append((ancien['date'], ancien['texte']))
            ancien['texte'], ancien['date'] = fait, date
        elif operation == 'IGNORER':
            pass
        else:
            operation = 'AJOUTER'
            self.faits.append({'texte': fait, 'date': date, 'historique': []})
        self.operations[operation] += 1

    def rappeler(self, question):
        choisis = les_plus_proches(self.modele, question, [f['texte'] for f in self.faits])
        lignes = []
        for t in choisis:
            f = next(x for x in self.faits if x['texte'] == t)
            avant = ''.join(f" (remplace, depuis le {f['date']} : « {h} », noté le {d})" for d, h in f['historique'])
            lignes.append(f"[{f['date']}] {f['texte']}{avant}")
        return lignes


class Mem0Enregistre:
    """Souvenirs retrouvés par Mem0, lus depuis l'enregistrement fait en mode direct par mem0_local.py."""
    nom = 'Mem0 (local)'
    enregistrement = None

    def __init__(self, modele, utilisateur):
        self.utilisateur = utilisateur

    def memoriser(self, conversation):
        pass

    def rappeler(self, question):
        return self.enregistrement['rappels'][self.utilisateur][question]


SYSTEMES = [SansMemoire, HistoriqueComplet, VectorielleNaive, MemoireDeFaits, Mem0Enregistre]
