"""
veille_emploi_v2.py — Veille Emploi Automatisée · AGON Conseil · Modeste ADDRA
────────────────────────────────────────────────────────────────────────────────
REMPLACE JSearch par des sources 100% françaises :
  Option 1 : APEC RSS + Indeed FR RSS + Cadremploi RSS  (gratuit, zéro clé)
  Option 2 : + Adzuna FR API (gratuit avec clé : developer.adzuna.com)

Prérequis : pip install requests feedparser python-dotenv
────────────────────────────────────────────────────────────────────────────────
"""

import os, json, smtplib, logging, time
from datetime import date
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import feedparser

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ── Configuration ──────────────────────────────────────────────────────────
GMAIL_FROM    = os.environ["GMAIL_FROM"]
GMAIL_TO      = os.environ["GMAIL_TO"]
GMAIL_APP_PWD = os.environ["GMAIL_APP_PWD"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

# Adzuna (Option 2) — laisser vide si non utilisé
# Inscription gratuite : https://developer.adzuna.com/
ADZUNA_APP_ID  = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")

SCORE_MINIMUM = 6

PROFIL = """
Modeste ADDRA — 30 ans d'expérience, industrie internationale, pilotage P&L.
- RFS/Alcatel-Lucent : VP Business Unit & Dir. Usine (2008-2011), CA 65->85M€ (+31%),
  5 sites internationaux, 400 collaborateurs. CTO (2005-2008), 250 ingénieurs.
- Alcatel-Lucent Paris : Dir. Programme Stratégique "Le Cube" AAA, >50M€, 400 ETP.
- Alcatel Mobile Phones : Dir. HW (2003-2005), 130 ingénieurs France+Chine.
- ECMA Concept : DG (2015-2026), machines spéciales & robotique, CA 896K->1,5M€ (+67%).
Compétences : P&L, Lean, GO TO MARKET, management international, restructuration.
Postes visés : DG, Directeur de BU, Directeur d'Usine, Directeur des Opérations,
               Directeur de Site, Directeur de Programmes.
Saint-Nazaire, mobile France entière, disponible immédiatement.
"""

LOG_FILE = Path(__file__).parent / "veille_emploi.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ══════════════════════════════════════════════════════════════════════════
# OPTION 1A — APEC RSS (source #1 pour cadres en France)
# ══════════════════════════════════════════════════════════════════════════

APEC_REQUETES = [
    "directeur+general",
    "directeur+usine",
    "directeur+site+industriel",
    "directeur+business+unit",
    "directeur+operations",
    "directeur+programmes",
    "directeur+filiale",
    "directeur+industriel",
    "Chief+of+staff",
    "COO",
    "Directeur+operations",
]

def fetch_apec():
    offres = []
    base = "https://www.apec.fr/cms/webservices/flux-rss/offre"
    for req in APEC_REQUETES:
        url = f"{base}?motsCles={req}&typeContrat=CDI&page=1&parPage=20"
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            for e in feed.entries:
                offres.append({
                    "titre":       e.get("title", "").strip(),
                    "entreprise":  e.get("apec_societe", e.get("author", "Confidentiel")).strip(),
                    "lieu":        e.get("apec_lieu", "France").strip(),
                    "url":         e.get("link", ""),
                    "description": e.get("summary", "")[:1500],
                    "source":      "APEC",
                    "date":        e.get("published", "")[:10],
                })
            log.info(f"APEC '{req}': {len(feed.entries)} offres")
        except Exception as ex:
            log.warning(f"APEC erreur '{req}': {ex}")
        time.sleep(0.6)
    return offres

# ══════════════════════════════════════════════════════════════════════════
# OPTION 1B — Indeed FR RSS
# ══════════════════════════════════════════════════════════════════════════

INDEED_REQUETES = [
    "directeur general industrie",
    "directeur usine",
    "directeur site industrie",
    "directeur business unit",
    "directeur operations",
    "directeur programmes",
    "DG industrie PME ETI",
    "plant director france",
    "general manager industrie france",
]

def fetch_indeed_fr():
    offres = []
    base = "https://fr.indeed.com/rss"
    for query in INDEED_REQUETES:
        url = (f"{base}?q={query.replace(' ', '+')}"
               f"&l=France&sort=date&fromage=14&limit=20")
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            for e in feed.entries:
                src = e.get("source", "")
                ent = src.get("title", "Confidentiel") if isinstance(src, dict) else "Confidentiel"
                offres.append({
                    "titre":       e.get("title", "").strip(),
                    "entreprise":  ent,
                    "lieu":        "France",
                    "url":         e.get("link", ""),
                    "description": e.get("summary", "")[:1500],
                    "source":      "Indeed FR",
                    "date":        e.get("published", "")[:10],
                })
            log.info(f"Indeed FR '{query}': {len(feed.entries)} offres")
        except Exception as ex:
            log.warning(f"Indeed FR erreur '{query}': {ex}")
        time.sleep(0.6)
    return offres

# ══════════════════════════════════════════════════════════════════════════
# OPTION 1C — Cadremploi RSS
# ══════════════════════════════════════════════════════════════════════════

CADREMPLOI_REQUETES = [
    "directeur-general-industrie",
    "directeur-usine",
    "directeur-business-unit",
    "directeur-operations",
    "directeur-site",
    "directeur-programmes",
]

def fetch_cadremploi():
    offres = []
    base = "https://www.cadremploi.fr/rss/offres"
    for req in CADREMPLOI_REQUETES:
        url = f"{base}?q={req}&contrat=CDI&limit=20"
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            for e in feed.entries:
                offres.append({
                    "titre":       e.get("title", "").strip(),
                    "entreprise":  e.get("cadremploi_company", "Confidentiel").strip(),
                    "lieu":        e.get("cadremploi_location", "France").strip(),
                    "url":         e.get("link", ""),
                    "description": e.get("summary", "")[:1500],
                    "source":      "Cadremploi",
                    "date":        e.get("published", "")[:10],
                })
            log.info(f"Cadremploi '{req}': {len(feed.entries)} offres")
        except Exception as ex:
            log.warning(f"Cadremploi erreur '{req}': {ex}")
        time.sleep(0.6)
    return offres

# ══════════════════════════════════════════════════════════════════════════
# OPTION 2 — Adzuna FR API
# Inscription gratuite : https://developer.adzuna.com/
# Quota : 250 req/mois gratuit (largement suffisant)
# ══════════════════════════════════════════════════════════════════════════

ADZUNA_REQUETES = [
    "directeur general industrie",
    "directeur usine",
    "directeur business unit",
    "directeur operations",
    "plant director",
    "general manager France",
    "directeur filiale",
    "chief operating officer France",
]

def fetch_adzuna():
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        log.info("Adzuna : clés ADZUNA_APP_ID/ADZUNA_APP_KEY non configurées — module ignoré")
        return []

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
# Dédoublonnage
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
# Scoring via Claude API
# ══════════════════════════════════════════════════════════════════════════

def scorer_offres(offres):
    if not offres:
        log.warning("Aucune offre a scorer")
        return []

    scorees = []
    BATCH = 10

    for i in range(0, len(offres), BATCH):
        batch = offres[i:i+BATCH]
        payload = json.dumps([
            {"id": j, "titre": o["titre"], "entreprise": o["entreprise"],
             "lieu": o["lieu"], "description": o["description"][:800]}
            for j, o in enumerate(batch)
        ], ensure_ascii=False)

        prompt = f"""Tu es un expert en recrutement pour cadres dirigeants industriels français.
Evalue l'adequation entre ces offres et le profil candidat.

PROFIL CANDIDAT :
{PROFIL}

OFFRES (JSON) :
{payload}

Grille de scoring :
- 9-10 : DG/DAF/COO/Dir. BU avec P&L, secteur industrie, PME-ETI-Groupe
- 7-8  : Direction operationnelle ou strategique, industrie/tech
- 5-6  : Poste de direction, secteur ou perimetre partiel
- 0-4  : Hors cible (support, junior, non industriel)

JSON uniquement sans markdown :
[{{"id":0,"score":X,"verdict":"synthese max 15 mots"}}]"""

        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 800,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=30
            )
            text = r.json()["content"][0]["text"]
            s, e = text.find("["), text.rfind("]")
            scores = json.loads(text[s:e+1] if s != -1 else text)
            for item in scores:
                idx = item.get("id", 0)
                if idx < len(batch):
                    o = dict(batch[idx])
                    o["score"]   = min(10, max(0, int(item.get("score", 0))))
                    o["verdict"] = item.get("verdict", "")
                    scorees.append(o)
        except Exception as ex:
            log.warning(f"Scoring erreur batch {i//BATCH+1}: {ex}")
            for o in batch:
                o["score"] = 0
                o["verdict"] = "Scoring indisponible"
                scorees.append(o)

    result = sorted(
        [o for o in scorees if o["score"] >= SCORE_MINIMUM],
        key=lambda x: x["score"], reverse=True
    )
    log.info(f"{len(result)} offres retenues (score >= {SCORE_MINIMUM})")
    return result

# ══════════════════════════════════════════════════════════════════════════
# Email HTML
# ══════════════════════════════════════════════════════════════════════════

def score_col(sc):
    return "#1D9E75" if sc >= 8 else "#BA7517" if sc >= 6 else "#D85A30"

def build_email(offres):
    today = date.today().strftime("%d/%m/%Y")
    nb = len(offres)
    sources = "APEC + Indeed FR + Cadremploi" + (" + Adzuna FR" if ADZUNA_APP_ID else "")

    if not offres:
        rows = f'<tr><td colspan="6" style="text-align:center;padding:20px;color:#888">Aucune offre pertinente (score &lt; {SCORE_MINIMUM}/10)</td></tr>'
    else:
        rows = ""
        for o in offres:
            col  = score_col(o["score"])
            lien = f'<a href="{o["url"]}" style="color:#185FA5;text-decoration:none;">Voir</a>' if o.get("url") else "—"
            badge = f'<span style="font-size:10px;padding:2px 5px;border-radius:3px;background:#f0f0f0;color:#555;margin-left:4px">{o.get("source","")}</span>'
            rows += f"""<tr>
              <td style="padding:9px 11px;border-bottom:1px solid #f0f0f0;font-weight:600">{o['titre']}</td>
              <td style="padding:9px 11px;border-bottom:1px solid #f0f0f0;color:#555">{o['entreprise']}</td>
              <td style="padding:9px 11px;border-bottom:1px solid #f0f0f0;color:#555">{o['lieu']}</td>
              <td style="padding:9px 11px;border-bottom:1px solid #f0f0f0;text-align:center">
                <span style="background:{col}22;color:{col};font-weight:700;padding:3px 9px;border-radius:999px">{o['score']}/10</span>
              </td>
              <td style="padding:9px 11px;border-bottom:1px solid #f0f0f0;font-size:12px;color:#555">{o.get('verdict','')}</td>
              <td style="padding:9px 11px;border-bottom:1px solid #f0f0f0">{lien}{badge}</td>
            </tr>"""

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px">
<div style="max-width:920px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">
  <div style="background:#1A1A2E;padding:22px 30px">
    <h1 style="color:#C8A84B;margin:0;font-size:19px">AGON Conseil — Veille Emploi</h1>
    <p style="color:#aaa;margin:5px 0 0;font-size:13px">{today} · {nb} offre(s) pertinente(s) · Sources : {sources}</p>
  </div>
  <div style="padding:22px 30px">
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:#f8f8f8">
        <th style="text-align:left;padding:9px 11px;color:#888;font-size:11px;border-bottom:2px solid #eee">POSTE</th>
        <th style="text-align:left;padding:9px 11px;color:#888;font-size:11px;border-bottom:2px solid #eee">ENTREPRISE</th>
        <th style="text-align:left;padding:9px 11px;color:#888;font-size:11px;border-bottom:2px solid #eee">LIEU</th>
        <th style="text-align:center;padding:9px 11px;color:#888;font-size:11px;border-bottom:2px solid #eee">SCORE</th>
        <th style="text-align:left;padding:9px 11px;color:#888;font-size:11px;border-bottom:2px solid #eee">SYNTHESE</th>
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
# Main
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("== Veille emploi demarree ==")

    offres_apec       = fetch_apec()
    offres_indeed     = fetch_indeed_fr()
    offres_cadremploi = fetch_cadremploi()
    offres_adzuna     = fetch_adzuna()   # vide si clés non configurées

    toutes = offres_apec + offres_indeed + offres_cadremploi + offres_adzuna
    log.info(
        f"Total brut : {len(toutes)} offres "
        f"(APEC:{len(offres_apec)} Indeed:{len(offres_indeed)} "
        f"Cadremploi:{len(offres_cadremploi)} Adzuna:{len(offres_adzuna)})"
    )

    uniques = dedoublonner(toutes)
    scorees = scorer_offres(uniques)
    html    = build_email(scorees)
    send_email(html, len(scorees))

    log.info("== Termine avec succes ==")
