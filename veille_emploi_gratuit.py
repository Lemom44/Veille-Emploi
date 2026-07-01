"""
veille_emploi_gratuit.py — Veille Emploi Automatisée · AGON Conseil · Modeste ADDRA
────────────────────────────────────────────────────────────────────────────────
VERSION 100% GRATUITE — Zéro appel API payant
Filtrage par mots-clés et scoring local (pas d'API Claude)
Source : Adzuna FR uniquement (fonctionne depuis GitHub Actions)

Prérequis : pip install requests python-dotenv
Secrets GitHub requis : GMAIL_FROM, GMAIL_TO, GMAIL_APP_PWD,
                        ADZUNA_APP_ID, ADZUNA_APP_KEY
────────────────────────────────────────────────────────────────────────────────
"""

import os, json, smtplib, logging, time, re
from datetime import date
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ── Configuration ──────────────────────────────────────────────────────────
GMAIL_FROM     = os.environ["GMAIL_FROM"]
GMAIL_TO       = os.environ["GMAIL_TO"]
GMAIL_APP_PWD  = os.environ["GMAIL_APP_PWD"]
ADZUNA_APP_ID  = os.environ["ADZUNA_APP_ID"]
ADZUNA_APP_KEY = os.environ["ADZUNA_APP_KEY"]

# ── Paramètre de filtrage ──────────────────────────────────────────────────
SCORE_MINIMUM = 3   # Sur 10 — baisser à 2 pour recevoir plus d'offres

LOG_FILE = Path(__file__).parent / "veille_emploi.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
})

# ══════════════════════════════════════════════════════════════════════════
# SCORING LOCAL PAR MOTS-CLÉS (remplace l'API Claude)
# ══════════════════════════════════════════════════════════════════════════

# Mots-clés par niveau de pertinence
MOTS_CLES_FORT = [
    # Intitulés cibles exacts
    "directeur général", "directeur general", "dg ",
    "directeur d'usine", "directeur usine",
    "directeur de site", "directeur site",
    "directeur business unit", "directeur de business unit",
    "directeur des opérations", "directeur des operations",
    "directeur opérations", "directeur operations",
    "directeur de programmes", "directeur programmes",
    "directeur industriel", "directeur de filiale",
    "plant director", "plant manager",
    "general manager", "chief operating officer", "coo",
    "vp operations", "vice-président opérations",
    "directeur de production", "directeur production",
]

MOTS_CLES_MOYEN = [
    # Secteurs et contextes valorisants
    "industrie", "industriel", "manufacturing",
    "robotique", "automatisation", "machines spéciales",
    "naval", "défense", "aéronautique", "aérospatial",
    "électronique", "mécanique", "usinage",
    "p&l", "ebitda", "centre de profit",
    "lean", "amélioration continue",
    "international", "export", "multiculturel",
    "pme", "eti", "groupe industriel",
    "transformation", "restructuration",
    "supply chain", "logistique industrielle",
]

MOTS_CLES_NEGATIF = [
    # Postes hors cible
    "stagiaire", "alternance", "apprenti",
    "assistant", "technicien", "chef de projet junior",
    "commercial terrain", "vendeur",
    "ressources humaines", "comptable", "juriste",
    "infirmier", "médecin", "pharmacien",
    "restauration", "hôtellerie", "tourisme",
    "marketing digital", "community manager",
    "développeur", "développeuse", "data scientist",
]

def scorer_local(offre):
    """
    Score l'offre de 0 à 10 par analyse locale des mots-clés.
    Gratuit, instantané, aucun appel API.
    """
    texte = (offre.get("titre", "") + " " + offre.get("description", "")).lower()

    # Mots négatifs → élimination directe
    for mot in MOTS_CLES_NEGATIF:
        if mot in texte:
            return 0, f"Hors cible ({mot})"

    score = 0
    mots_trouves_fort = []
    mots_trouves_moyen = []

    # Mots-clés forts : +3 points chacun (plafonné à 6)
    for mot in MOTS_CLES_FORT:
        if mot in texte:
            score += 3
            mots_trouves_fort.append(mot)
            if score >= 6:
                break

    # Mots-clés moyens : +1 point chacun (plafonné à 4 supplémentaires)
    pts_moyen = 0
    for mot in MOTS_CLES_MOYEN:
        if mot in texte:
            pts_moyen += 1
            mots_trouves_moyen.append(mot)
            if pts_moyen >= 4:
                break
    score += pts_moyen

    score = min(10, score)

    # Verdict lisible
    if mots_trouves_fort:
        verdict = f"Intitulé : {mots_trouves_fort[0]}"
        if mots_trouves_moyen:
            verdict += f" · {mots_trouves_moyen[0]}"
    elif mots_trouves_moyen:
        verdict = " · ".join(mots_trouves_moyen[:3])
    else:
        verdict = "Peu d'éléments pertinents"

    return score, verdict


# ══════════════════════════════════════════════════════════════════════════
# COLLECTE DES OFFRES — Adzuna FR
# ══════════════════════════════════════════════════════════════════════════

ADZUNA_REQUETES = [
    "directeur general",
    "directeur usine",
    "directeur site industriel",
    "directeur business unit",
    "directeur operations",
    "directeur programmes industriel",
    "directeur filiale",
    "directeur industriel",
    "plant director",
    "plant manager",
    "general manager france",
    "chief operating officer",
    "VP operations",
]

def fetch_adzuna():
    offres = []
    base = "https://api.adzuna.com/v1/api/jobs/fr/search/1"

    for query in ADZUNA_REQUETES:
        url = (
            f"{base}?app_id={ADZUNA_APP_ID}&app_key={ADZUNA_APP_KEY}"
            f"&results_per_page=20"
            f"&what={requests.utils.quote(query)}"
            f"&max_days_old=14&sort_by=date"
            f"&content-type=application/json"
        )
        try:
            r = SESSION.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            for job in data.get("results", []):
                offres.append({
                    "titre":       job.get("title", "").strip(),
                    "entreprise":  job.get("company", {}).get("display_name", "Confidentiel"),
                    "lieu":        job.get("location", {}).get("display_name", "France"),
                    "url":         job.get("redirect_url", ""),
                    "description": job.get("description", "")[:1500],
                    "source":      "Adzuna FR",
                    "date":        job.get("created", "")[:10],
                })
            log.info(f"Adzuna '{query}': {len(data.get('results', []))} offres")
        except Exception as ex:
            log.warning(f"Adzuna erreur '{query}': {ex}")
        time.sleep(0.3)

    return offres


# ══════════════════════════════════════════════════════════════════════════
# DÉDOUBLONNAGE
# ══════════════════════════════════════════════════════════════════════════

def dedoublonner(offres):
    seen_urls, seen_cles, result = set(), set(), []
    for o in offres:
        url = o.get("url", "").strip()
        cle = f"{o['titre'].lower()[:40]}|{o['entreprise'].lower()[:20]}"
        if (url and url in seen_urls) or cle in seen_cles:
            continue
        if url:
            seen_urls.add(url)
        seen_cles.add(cle)
        result.append(o)
    log.info(f"Apres dedoublonnage : {len(result)} offres uniques")
    return result


# ══════════════════════════════════════════════════════════════════════════
# SCORING ET FILTRAGE LOCAL
# ══════════════════════════════════════════════════════════════════════════

def scorer_et_filtrer(offres):
    scorees = []
    for o in offres:
        score, verdict = scorer_local(o)
        if score >= SCORE_MINIMUM:
            o["score"]   = score
            o["verdict"] = verdict
            scorees.append(o)

    result = sorted(scorees, key=lambda x: x["score"], reverse=True)
    log.info(f"{len(result)} offres retenues (score >= {SCORE_MINIMUM})")
    return result


# ══════════════════════════════════════════════════════════════════════════
# EMAIL HTML
# ══════════════════════════════════════════════════════════════════════════

def score_col(sc):
    return "#1D9E75" if sc >= 7 else "#BA7517" if sc >= 4 else "#D85A30"

def build_email(offres):
    today = date.today().strftime("%d/%m/%Y")
    nb = len(offres)

    if not offres:
        rows = f'<tr><td colspan="6" style="text-align:center;padding:20px;color:#888">Aucune offre pertinente aujourd\'hui (score &lt; {SCORE_MINIMUM}/10)</td></tr>'
    else:
        rows = ""
        for o in offres:
            col  = score_col(o["score"])
            lien = f'<a href="{o["url"]}" style="color:#185FA5;text-decoration:none;">Voir →</a>' if o.get("url") else "—"
            rows += f"""<tr>
              <td style="padding:9px 11px;border-bottom:1px solid #f0f0f0;font-weight:600;color:#1a1a1a">{o['titre']}</td>
              <td style="padding:9px 11px;border-bottom:1px solid #f0f0f0;color:#555">{o['entreprise']}</td>
              <td style="padding:9px 11px;border-bottom:1px solid #f0f0f0;color:#555">{o['lieu']}</td>
              <td style="padding:9px 11px;border-bottom:1px solid #f0f0f0;text-align:center">
                <span style="background:{col}22;color:{col};font-weight:700;padding:3px 9px;border-radius:999px">{o['score']}/10</span>
              </td>
              <td style="padding:9px 11px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#555">{o.get('verdict','')}</td>
              <td style="padding:9px 11px;border-bottom:1px solid #f0f0f0">{lien}</td>
            </tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px">
<div style="max-width:920px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">
  <div style="background:#1A1A2E;padding:22px 30px">
    <h1 style="color:#C8A84B;margin:0;font-size:19px">AGON Conseil — Veille Emploi</h1>
    <p style="color:#aaa;margin:5px 0 0;font-size:13px">{today} · {nb} offre(s) · Filtrage mots-clés · Source : Adzuna FR</p>
  </div>
  <div style="padding:22px 30px">
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:#f8f8f8">
        <th style="text-align:left;padding:9px 11px;color:#888;font-size:11px;border-bottom:2px solid #eee">POSTE</th>
        <th style="text-align:left;padding:9px 11px;color:#888;font-size:11px;border-bottom:2px solid #eee">ENTREPRISE</th>
        <th style="text-align:left;padding:9px 11px;color:#888;font-size:11px;border-bottom:2px solid #eee">LIEU</th>
        <th style="text-align:center;padding:9px 11px;color:#888;font-size:11px;border-bottom:2px solid #eee">SCORE</th>
        <th style="text-align:left;padding:9px 11px;color:#888;font-size:11px;border-bottom:2px solid #eee">MOTS-CLES</th>
        <th style="text-align:left;padding:9px 11px;color:#888;font-size:11px;border-bottom:2px solid #eee">LIEN</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <div style="background:#f8f8f8;padding:14px 30px;border-top:1px solid #eee">
    <p style="color:#aaa;font-size:11px;margin:0">Veille automatisee · AGON Conseil · Modeste ADDRA · {GMAIL_TO}</p>
  </div>
</div></body></html>"""

def send_email(html, nb):
    today = date.today().strftime("%d/%m/%Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Veille Emploi] {today} — {nb} offre(s) pertinente(s)"
    msg["From"]    = GMAIL_FROM
    msg["To"]      = GMAIL_TO
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
        srv.login(GMAIL_FROM, GMAIL_APP_PWD)
        srv.sendmail(GMAIL_FROM, GMAIL_TO, msg.as_string())
    log.info(f"Email envoye a {GMAIL_TO}")


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("== Veille emploi demarree (mode gratuit - mots-cles) ==")

    offres   = fetch_adzuna()
    uniques  = dedoublonner(offres)
    filtrees = scorer_et_filtrer(uniques)
    html     = build_email(filtrees)
    send_email(html, len(filtrees))

    log.info("== Termine avec succes ==")
