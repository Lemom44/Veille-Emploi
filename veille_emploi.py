"""
Veille emploi automatisée — Modeste ADDRA
Recherche quotidienne d'offres DG / Dir. Usine / Dir. BU / Dir. Ops / Dir. Programmes
Envoi des résultats scorés par email via Gmail SMTP
"""

import os
import json
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date

# ── Configuration ─────────────────────────────────────────────────────────────

GMAIL_FROM      = os.environ["GMAIL_FROM"]       # ex: modeste.addra@gmail.com
GMAIL_TO        = os.environ["GMAIL_TO"]         # ex: modeste.addra@free.fr
GMAIL_APP_PWD   = os.environ["GMAIL_APP_PWD"]    # mot de passe applicatif Gmail
ANTHROPIC_KEY   = os.environ["ANTHROPIC_API_KEY"]
JSEARCH_KEY     = os.environ["JSEARCH_API_KEY"]  # RapidAPI key

SCORE_MINIMUM   = 6   # n'envoyer que les offres scorées >= à cette valeur

POSTES_CIBLES = [
    "Directeur Général",
    "Directeur de Site",
    "Directeur d'Usine",
    "Directeur de Site Industriel",
    "Directeur Business Unit",
    "Directeur des Opérations",
    "Directeur de Programmes",
    "Chief of Staff",

]

PROFIL = """
Modeste ADDRA — DG / Directeur de BU / Directeur d'Usine / COO / Directeur des Opérations
30 ans d'expérience en industrie internationale, pilotage de P&L, transformation industrielle.
- RFS/Alcatel-Lucent : VP Business Unit & Directeur d'Usine (2008-2011), CA 65→85M€ (+31%),
  EBITDA +2pts, 5 sites internationaux (France, USA, Brésil, Australie, Inde), 400 collaborateurs.
  CTO (2005-2008), ~20 brevets/an, 7 sites R&D, 250 ingénieurs.
- Alcatel-Lucent Paris : Directeur Programme Stratégique "Le Cube" AAA, >50M€, 400 ETP.
- Alcatel Mobile Phones : Directeur HW (2003-2005), 130 ingénieurs France+Chine, 5 brevets.
- ECMA Concept : DG (2015-2026), machines spéciales & robotique, CA 896K€→1,5M€ (+67%), +14pts marge.
Formations : ENST Bretagne (Ingénieur Télécom), DEA Microélectronique INPG, Mastère ESSEC, HEC.
Compétences : P&L, Lean, GO TO MARKET, management international, restructuration, innovation.
Saint-Nazaire, mobile France, disponible immédiatement.
"""

# ── Étape 1 : Récupération des offres via JSearch ─────────────────────────────

def fetch_offres():
    """Interroge JSearch (Indeed + LinkedIn + Glassdoor agrégés) pour chaque poste cible."""
    offres = []
    seen_ids = set()

    headers = {
        "X-RapidAPI-Key": JSEARCH_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }

    for poste in POSTES_CIBLES:
        try:
            resp = requests.get(
                "https://jsearch.p.rapidapi.com/search",
                headers=headers,
                params={
                    "query": f"{poste} France",
                    "page": "1",
                    "num_pages": "1",
                    "date_posted": "week",   # offres des 7 derniers jours
                    "country": "fr",
                    "language": "fr",
                },
                timeout=15
            )
            data = resp.json()
            for job in data.get("data", []):
                job_id = job.get("job_id", "")
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                offres.append({
                    "titre":       job.get("job_title", ""),
                    "entreprise":  job.get("employer_name", ""),
                    "lieu":        job.get("job_city", "") + ", " + job.get("job_country", ""),
                    "url":         job.get("job_apply_link", ""),
                    "description": (job.get("job_description", "") or "")[:1500],
                    "source":      job.get("job_publisher", ""),
                    "date":        job.get("job_posted_at_datetime_utc", "")[:10],
                })
        except Exception as e:
            print(f"[JSearch] Erreur pour '{poste}': {e}")
            continue

    print(f"[JSearch] {len(offres)} offres récupérées (dédoublonnées)")
    return offres


# ── Étape 2 : Scoring des offres via Claude API ───────────────────────────────

def scorer_offres(offres):
    """Envoie les offres à Claude pour scoring et filtrage."""
    if not offres:
        return []

    # On envoie les offres par batch de 10 pour économiser les tokens
    BATCH = 10
    offres_scorees = []

    for i in range(0, len(offres), BATCH):
        batch = offres[i:i+BATCH]
        batch_json = json.dumps(
            [{"id": j, "titre": o["titre"], "entreprise": o["entreprise"],
              "lieu": o["lieu"], "description": o["description"][:800]}
             for j, o in enumerate(batch)],
            ensure_ascii=False
        )

        prompt = f"""Tu es un expert en recrutement industriel. Évalue l'adéquation entre ces offres d'emploi et le profil candidat.

PROFIL CANDIDAT :
{PROFIL}

OFFRES À ÉVALUER (JSON) :
{batch_json}

Pour chaque offre, donne un score d'adéquation 0-10 et une synthèse en 1 phrase.
Critères : intitulé du poste, périmètre P&L, management d'équipe, secteur industriel, dimension internationale.

Réponds UNIQUEMENT en JSON, sans markdown ni backticks :
[{{"id": 0, "score": X, "verdict": "..."}}]"""

        try:
            resp = requests.post(
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
            text = resp.json()["content"][0]["text"]
            s, e = text.find("["), text.rfind("]")
            scores = json.loads(text[s:e+1] if s != -1 else text)

            for item in scores:
                idx = item.get("id", 0)
                if idx < len(batch):
                    offre = dict(batch[idx])
                    offre["score"]   = min(10, max(0, int(item.get("score", 0))))
                    offre["verdict"] = item.get("verdict", "")
                    offres_scorees.append(offre)

        except Exception as ex:
            print(f"[Claude] Erreur scoring batch {i//BATCH + 1}: {ex}")
            # En cas d'erreur, on garde les offres sans score
            for offre in batch:
                offre["score"] = 0
                offre["verdict"] = "Scoring indisponible"
                offres_scorees.append(offre)

    # Filtrage et tri
    offres_filtrees = [o for o in offres_scorees if o["score"] >= SCORE_MINIMUM]
    offres_filtrees.sort(key=lambda x: x["score"], reverse=True)
    print(f"[Scoring] {len(offres_filtrees)} offres retenues (score >= {SCORE_MINIMUM})")
    return offres_filtrees


# ── Étape 3 : Formatage du mail HTML ─────────────────────────────────────────

def score_couleur(score):
    if score >= 8: return "#1D9E75"   # vert
    if score >= 6: return "#BA7517"   # orange
    return "#D85A30"                   # rouge

def formater_email(offres):
    today = date.today().strftime("%d/%m/%Y")
    nb = len(offres)

    if nb == 0:
        body_offres = """
        <tr><td colspan="5" style="text-align:center;padding:24px;color:#888;font-size:14px;">
            Aucune offre pertinente trouvée aujourd'hui (score &lt; {}).
        </td></tr>""".format(SCORE_MINIMUM)
    else:
        rows = ""
        for o in offres:
            col = score_couleur(o["score"])
            url = o.get("url", "#")
            lien = f'<a href="{url}" style="color:#185FA5;text-decoration:none;">Voir →</a>' if url and url != "#" else "—"
            rows += f"""
            <tr>
              <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0;font-weight:600;color:#1a1a1a">{o['titre']}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0;color:#555">{o['entreprise']}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0;color:#555">{o['lieu']}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0;text-align:center">
                <span style="background:{col}22;color:{col};font-weight:700;padding:4px 10px;border-radius:999px;font-size:13px">{o['score']}/10</span>
              </td>
              <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0;color:#555;font-size:13px">{o.get('verdict','')}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #f0f0f0">{lien}</td>
            </tr>"""
        body_offres = rows

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px">
<div style="max-width:860px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">

  <!-- En-tête -->
  <div style="background:#1A1A2E;padding:24px 32px">
    <h1 style="color:#C8A84B;margin:0;font-size:20px;letter-spacing:.5px">AGON Conseil — Veille Emploi</h1>
    <p style="color:#aaa;margin:6px 0 0;font-size:13px">{today} · {nb} offre(s) pertinente(s) (score ≥ {SCORE_MINIMUM}/10)</p>
  </div>

  <!-- Tableau des offres -->
  <div style="padding:24px 32px">
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <thead>
        <tr style="background:#f8f8f8">
          <th style="text-align:left;padding:10px 12px;color:#888;font-size:12px;border-bottom:2px solid #eee">POSTE</th>
          <th style="text-align:left;padding:10px 12px;color:#888;font-size:12px;border-bottom:2px solid #eee">ENTREPRISE</th>
          <th style="text-align:left;padding:10px 12px;color:#888;font-size:12px;border-bottom:2px solid #eee">LIEU</th>
          <th style="text-align:center;padding:10px 12px;color:#888;font-size:12px;border-bottom:2px solid #eee">SCORE</th>
          <th style="text-align:left;padding:10px 12px;color:#888;font-size:12px;border-bottom:2px solid #eee">SYNTHÈSE</th>
          <th style="text-align:left;padding:10px 12px;color:#888;font-size:12px;border-bottom:2px solid #eee">LIEN</th>
        </tr>
      </thead>
      <tbody>{body_offres}</tbody>
    </table>
  </div>

  <!-- Pied de page -->
  <div style="background:#f8f8f8;padding:16px 32px;border-top:1px solid #eee">
    <p style="color:#aaa;font-size:12px;margin:0">
      Veille automatisée · AGON Conseil · Modeste ADDRA ·
      <a href="mailto:{GMAIL_TO}" style="color:#aaa">{GMAIL_TO}</a>
    </p>
  </div>

</div>
</body></html>"""
    return html


# ── Étape 4 : Envoi du mail ───────────────────────────────────────────────────

def envoyer_email(html_body, nb_offres):
    today = date.today().strftime("%d/%m/%Y")
    sujet = f"[Veille Emploi] {today} — {nb_offres} offre(s) pertinente(s)"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = sujet
    msg["From"]    = GMAIL_FROM
    msg["To"]      = GMAIL_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_FROM, GMAIL_APP_PWD)
            server.sendmail(GMAIL_FROM, GMAIL_TO, msg.as_string())
        print(f"[Email] Envoyé à {GMAIL_TO} — {nb_offres} offre(s)")
    except Exception as e:
        print(f"[Email] Erreur d'envoi : {e}")
        raise


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("── Veille emploi démarrée ──")
    offres_brutes   = fetch_offres()
    offres_scorees  = scorer_offres(offres_brutes)
    html            = formater_email(offres_scorees)
    envoyer_email(html, len(offres_scorees))
    print("── Terminé ──")
