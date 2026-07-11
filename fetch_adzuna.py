#!/usr/bin/env python3
"""
Interroge l'API Adzuna côté serveur (authentification par simple clé, pas
d'OAuth) et écrit un fichier JSON unique, dédupliqué, prêt à être importé
dans l'Agent Veille Emploi AGON via le champ "Coller directement le contenu
JSON" ou "Importer depuis l'URL" de l'onglet Veille.

Utile si le JSONP direct depuis le navigateur (contournement CORS habituel
pour Adzuna) est bloqué par la politique de sécurité du panneau d'artefact.

Identifiants requis (variables d'environnement) :
  ADZUNA_APP_ID
  ADZUNA_APP_KEY

Usage :
  export ADZUNA_APP_ID="..."
  export ADZUNA_APP_KEY="..."
  pip install requests --break-system-packages
  python3 fetch_adzuna.py --output adzuna_offers.json
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import requests

API_URL = "https://api.adzuna.com/v1/api/jobs/fr/search/1"

# Mêmes intitulés cibles que côté agent (à garder synchronisés si modifiés
# dans l'artefact : const PERIMETER_ROLES dans agent_veille_emploi_agon.html)
QUERIES = [
    "directeur général",
    "directeur de business unit",
    "directeur d'usine",
    "directeur des opérations",
    "COO",
    "directeur de projets",
    "directeur industriel",
    "directeur de site",
    "chief of staff",
]


def search_offres(app_id: str, app_key: str, what: str) -> list:
    resp = requests.get(
        API_URL,
        params={"app_id": app_id, "app_key": app_key, "what": what, "results_per_page": 20},
        timeout=20,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} pour '{what}': {resp.text[:300]}")
    return resp.json().get("results", [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="adzuna_offers.json", help="Chemin du fichier JSON de sortie")
    args = parser.parse_args()

    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("Erreur : variables d'environnement ADZUNA_APP_ID / ADZUNA_APP_KEY manquantes.", file=sys.stderr)
        sys.exit(1)

    seen_ids = set()
    combined = []
    for q in QUERIES:
        print(f"Recherche : {q!r}")
        try:
            results = search_offres(app_id, app_key, q)
        except Exception as e:
            print(f"  -> échec ({e}), requête ignorée", file=sys.stderr)
            continue
        new_count = 0
        for r in results:
            rid = str(r.get("id"))
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            combined.append(r)
            new_count += 1
        print(f"  -> {len(results)} résultat(s), {new_count} nouvel(aux)")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "queries": QUERIES,
        "results": combined,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{len(combined)} offre(s) unique(s) écrite(s) dans {args.output}")


if __name__ == "__main__":
    main()
