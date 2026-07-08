#!/usr/bin/env python3
"""
Interroge l'API France Travail (Offres d'emploi v2) côté serveur — donc sans
la restriction CORS qui bloque un appel direct depuis le navigateur — et écrit
un fichier JSON unique, dédupliqué, prêt à être importé dans l'Agent Veille
Emploi AGON via le champ "Importer un export France Travail".

Identifiants requis (variables d'environnement, jamais en dur dans le code) :
  FT_CLIENT_ID
  FT_CLIENT_SECRET

Usage :
  export FT_CLIENT_ID="..."
  export FT_CLIENT_SECRET="..."
  pip install requests --break-system-packages
  python3 fetch_france_travail.py --output ft_offers.json

En GitHub Actions : stocker FT_CLIENT_ID / FT_CLIENT_SECRET en secrets de repo,
planifier ce script (cron), committer/pousser ft_offers.json, puis coller
l'URL raw.githubusercontent.com du fichier dans l'agent.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import requests

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
API_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
SCOPE = "api_offresdemploiv2 o2dsoffre"

# Mêmes intitulés cibles que côté agent (à garder synchronisés si modifiés
# dans l'artefact : const FT_QUERIES dans agent_veille_emploi_agon.html)
QUERIES = [
    "directeur général",
    "directeur de business unit",
    "directeur d'usine",
    "directeur industriel",
    "COO",
]


def get_access_token(client_id: str, client_secret: str) -> str:
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": SCOPE,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    if resp.status_code != 200:
        # On affiche le corps de la réponse : France Travail y renvoie un
        # "error" et "error_description" précis (ex: invalid_scope,
        # invalid_client...) bien plus utile que le code HTTP seul.
        raise RuntimeError(
            f"Échec de l'authentification (HTTP {resp.status_code})\n"
            f"Réponse du serveur : {resp.text}"
        )
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Pas d'access_token dans la réponse : {data}")
    return token


def search_offres(token: str, mots_cles: str) -> list:
    resp = requests.get(
        API_URL,
        params={"motsCles": mots_cles, "range": "0-49"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    # L'API renvoie 206 (Partial Content) quand la pagination est tronquée : normal.
    if resp.status_code not in (200, 206):
        raise RuntimeError(f"HTTP {resp.status_code} pour '{mots_cles}': {resp.text[:300]}")
    return resp.json().get("resultats", [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="ft_offers.json", help="Chemin du fichier JSON de sortie")
    args = parser.parse_args()

    client_id = os.environ.get("FT_CLIENT_ID")
    client_secret = os.environ.get("FT_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Erreur : variables d'environnement FT_CLIENT_ID / FT_CLIENT_SECRET manquantes.", file=sys.stderr)
        sys.exit(1)

    # Cause très fréquente d'un 400 "invalid_client" : un espace ou un retour
    # à la ligne collé par erreur dans le secret GitHub. On le détecte et on
    # nettoie automatiquement, sans jamais afficher la valeur du secret.
    if client_id != client_id.strip() or client_secret != client_secret.strip():
        print("⚠️  Espace(s) ou retour à la ligne détecté(s) en début/fin de FT_CLIENT_ID ou FT_CLIENT_SECRET.")
        print("    Nettoyage automatique appliqué pour cette exécution, mais corrige le secret dans GitHub"
              " (Settings > Secrets and variables > Actions) pour éviter toute ambiguïté à l'avenir.")
        client_id = client_id.strip()
        client_secret = client_secret.strip()
    print(f"Client ID chargé : {len(client_id)} caractère(s), commence par {client_id[:4]!r}")

    print("Authentification France Travail (OAuth2)...")
    token = get_access_token(client_id, client_secret)

    seen_ids = set()
    combined = []
    for q in QUERIES:
        print(f"Recherche : {q!r}")
        try:
            results = search_offres(token, q)
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
