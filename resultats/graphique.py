"""Trace le graphique du README à partir de resultats.json.

Usage : python resultats/graphique.py
"""
import json
from pathlib import Path

import matplotlib
import matplotlib.ticker
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ICI = Path(__file__).resolve().parent
SURFACE, TEXTE, TEXTE_2, GRILLE = '#fcfcfb', '#0b0b0b', '#52514e', '#e4e3df'
SERIE_1, SERIE_2 = '#2a78d6', '#eb6834'


def main():
    r = json.loads((ICI / 'resultats.json').read_text(encoding='utf-8'))
    fig, (gauche, droite) = plt.subplots(1, 2, figsize=(12, 3.2), sharey=True, facecolor=SURFACE, gridspec_kw={'wspace': 0.08})
    y = list(range(len(r)))[::-1]
    for ax in (gauche, droite):
        ax.set_facecolor(SURFACE)
        for cote in ('top', 'right', 'left'):
            ax.spines[cote].set_visible(False)
        ax.spines['bottom'].set_color(GRILLE)
        ax.tick_params(colors=TEXTE_2, length=0, labelsize=9)
        ax.grid(axis='x', color=GRILLE, linewidth=1)
        ax.set_axisbelow(True)
    for i, yi in enumerate(y):
        a, b = 100 * r[i]['bonnes_reponses'], 100 * r[i]['refus_corrects']
        gauche.plot([min(a, b), max(a, b)], [yi, yi], color=GRILLE, linewidth=2, zorder=1)
    gauche.scatter([100 * m['bonnes_reponses'] for m in r], y, s=64, color=SERIE_1, edgecolor=SURFACE, linewidth=2, zorder=2,
                   label='Bonnes réponses (19 questions)')
    gauche.scatter([100 * m['refus_corrects'] for m in r], y, s=64, color=SERIE_2, edgecolor=SURFACE, linewidth=2, zorder=2,
                   label='Refus corrects (5 questions)')
    gauche.set_xlim(-3, 103)
    gauche.set_xticks(range(0, 101, 20))
    gauche.set_xticklabels([f'{x} %' for x in range(0, 101, 20)])
    gauche.set_title('Qualité des réponses', loc='left', color=TEXTE, fontsize=11, fontweight='bold', pad=26)
    gauche.legend(loc='lower left', bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=9, labelcolor=TEXTE_2, borderaxespad=0.2)
    mots = [m['mots_envoyes_par_question'] for m in r]
    droite.barh(y, mots, height=0.5, color=SERIE_1)
    for yi, v in zip(y, mots):
        droite.text(v, yi, f'  {v}', va='center', fontsize=9, color=TEXTE_2)
    droite.set_xlim(0, max(mots) * 1.18)
    droite.set_title('Coût : mots envoyés au modèle par question', loc='left', color=TEXTE, fontsize=11, fontweight='bold', pad=26)
    gauche.set_yticks(y)
    gauche.set_yticklabels([m['systeme'] for m in r], color=TEXTE, fontsize=9)
    fig.savefig(ICI / 'graphique-resultats.png', dpi=150, bbox_inches='tight', facecolor=SURFACE)
    print('graphique-resultats.png écrit')


if __name__ == '__main__':
    main()
