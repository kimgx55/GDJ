from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import random
import os
from pathlib import Path
from typing import List, Dict, Tuple

# === CONFIGURATION GLOBALE ===
BASE_DIR = Path(__file__).resolve().parent
TEAM_SIZE = 7
COMPOSITION = {"gardien": 1, "défenseur": 2, "milieu": 3, "attaquant": 1}
LAST_MATCHES_FILE = str(BASE_DIR / "historique_matchs.json")
JOUERS_FILE = str(BASE_DIR / "joueurs.json")
MAX_HISTORY = 5
GARDIEN_THRESHOLD = 10
SEUIL_ELITE = 10.0
SEUIL_FAIBLE = 7.0
SEUIL_FAIBLE_POSTE = 7.5

POIDS = {
    "leader": 0.3,
    "individualité": 0.15,
    "condition": 0.2,
    "synergie": 2.0,
    "anti_synergie_meme_poste": 5.0,
    "repetition": 0.1,
}

CONTRAINTES = {
    "elite_min": 1,
    "elite_max": 3,
    "faible_min": 1,
    "faible_max": 3,
    "leadership_min": 12,
    "leadership_max": 35,
    "individualite_min": 20,
    "individualite_max": 50,
    "condition_min": 25,
}

COMPLEMENTARITE = {
    "max_faibles_par_ligne": 1,
    "max_faibles_par_poste": 1,
    "min_score_ligne_defense": 14,
    "min_score_ligne_milieu": 20,
    "bonus_ligne_equilibree": 1.5,
}

# === FLASK APP ===
app = Flask(__name__, static_folder='.')
CORS(app)

# === LECTURE DES DONNÉES ===
with open(JOUERS_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)
    joueurs_data = data["joueurs"]
    synergies = data.get("synergies", [])
    anti_synergies = data.get("anti_synergies", [])

# === ROUTES STATIQUES ===
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

# === FONCTIONS UTILITAIRES ===
def score_joueur(joueur: Dict, poste: str) -> float:
    if poste not in joueur["poste"]:
        return -10
    idx = joueur["poste"].index(poste)
    base = joueur["niveau"][idx]
    bonus_leader = joueur["leader"] * POIDS["leader"]
    bonus_individualité = joueur["individualité"] * POIDS["individualité"]
    bonus_condition = joueur["condition"] * POIDS["condition"]
    return base + bonus_leader + bonus_individualité + bonus_condition

def score_global_joueur(joueur: Dict) -> float:
    scores = [score_joueur(joueur, poste) for poste in joueur["poste"]]
    return sum(scores) / len(scores) if scores else 0

def categoriser_joueur(joueur: Dict) -> str:
    score = score_global_joueur(joueur)
    if score >= SEUIL_ELITE:
        return "elite"
    elif score < SEUIL_FAIBLE:
        return "faible"
    return "moyen"

def charge_historique() -> List:
    try:
        if not os.path.exists(LAST_MATCHES_FILE):
            print(f"📝 Création du fichier {LAST_MATCHES_FILE}")
            with open(LAST_MATCHES_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            return []
        
        with open(LAST_MATCHES_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return []
            historique = json.loads(content)
            nb_matchs = len(historique) // 2
            print(f"📖 Historique chargé : {nb_matchs} match(s)")
            return historique
    except Exception as e:
        print(f"⚠️ Erreur historique: {e}")
        return []

def sauve_historique(historique: List):
    try:
        historique = historique[-(MAX_HISTORY * 2):]
        with open(LAST_MATCHES_FILE, "w", encoding="utf-8") as f:
            json.dump(historique, f, indent=2, ensure_ascii=False)
        nb_matchs = len(historique) // 2
        print(f"💾 Historique sauvegardé : {nb_matchs} match(s)")
    except Exception as e:
        print(f"⚠️ Erreur sauvegarde: {e}")

def similarité_avec_anciens_matchs(equipe: List[str], historique: List) -> float:
    if not historique:
        return 0
    penalty = 0
    equipe_set = set(equipe)
    for i, old in enumerate(reversed(historique)):
        recency_factor = 1.5 - (i / len(historique))
        overlap = len(equipe_set & set(old))
        if overlap >= 5:
            penalty += overlap * POIDS["repetition"] * recency_factor * 2
        else:
            penalty += overlap * POIDS["repetition"] * recency_factor
    return penalty

def calc_synergies(equipe: List[str]) -> float:
    bonus = 0
    equipe_set = set(equipe)
    for pair in synergies:
        if all(j in equipe_set for j in pair):
            bonus += POIDS["synergie"]
    return bonus

def verifier_anti_synergies_meme_poste(joueurs_assignes: List[Tuple[Dict, str]]) -> float:
    penalty = 0
    par_poste = {}
    for joueur, poste in joueurs_assignes:
        if poste not in par_poste:
            par_poste[poste] = []
        par_poste[poste].append(joueur["nom"])
    
    for poste, noms in par_poste.items():
        if len(noms) >= 2:
            for pair in anti_synergies:
                if all(j in noms for j in pair):
                    penalty += POIDS["anti_synergie_meme_poste"]
    return penalty

def analyser_complementarite_postes(joueurs_assignes: List[Tuple[Dict, str]]) -> Tuple[float, Dict]:
    lignes = {"défense": [], "milieu": [], "attaque": [], "gardien": []}
    par_poste = {}
    
    for joueur, poste in joueurs_assignes:
        score = score_joueur(joueur, poste)
        if poste == "gardien":
            lignes["gardien"].append((joueur, score))
        elif poste == "défenseur":
            lignes["défense"].append((joueur, score))
        elif poste == "milieu":
            lignes["milieu"].append((joueur, score))
        elif poste == "attaquant":
            lignes["attaque"].append((joueur, score))
        
        if poste not in par_poste:
            par_poste[poste] = []
        par_poste[poste].append((joueur, score))
    
    bonus = 0
    penalty = 0
    details = {}
    
    for poste, joueurs_poste in par_poste.items():
        if poste == "gardien":
            continue
        nb_faibles = sum(1 for _, score in joueurs_poste if score <= SEUIL_FAIBLE_POSTE)
        if nb_faibles > 1:
            penalty += 20 * nb_faibles
    
    for ligne, joueurs_ligne in lignes.items():
        if ligne == "gardien" or not joueurs_ligne:
            continue
        
        scores = [score for _, score in joueurs_ligne]
        total_score = sum(scores)
        nb_joueurs = len(joueurs_ligne)
        moyenne = total_score / nb_joueurs if nb_joueurs > 0 else 0
        nb_faibles = sum(1 for _, score in joueurs_ligne if score < 7)
        
        if nb_faibles > COMPLEMENTARITE["max_faibles_par_ligne"]:
            penalty += 3 * (nb_faibles - COMPLEMENTARITE["max_faibles_par_ligne"])
        
        if ligne == "défense" and total_score < COMPLEMENTARITE["min_score_ligne_defense"]:
            penalty += (COMPLEMENTARITE["min_score_ligne_defense"] - total_score) * 0.5
        elif ligne == "milieu" and total_score < COMPLEMENTARITE["min_score_ligne_milieu"]:
            penalty += (COMPLEMENTARITE["min_score_ligne_milieu"] - total_score) * 0.5
        
        if nb_joueurs >= 2:
            ecart = max(scores) - min(scores)
            if 2 <= ecart <= 5:
                bonus += COMPLEMENTARITE["bonus_ligne_equilibree"]
        
        details[ligne] = {
            "total_score": total_score,
            "moyenne": moyenne,
            "nb_faibles": nb_faibles,
            "joueurs": [(j["nom"], s) for j, s in joueurs_ligne]
        }
    
    return bonus - penalty, details

def affecter_postes_optimaux(equipe: List[Dict]) -> List[Tuple[Dict, str]]:
    postes_restants = COMPOSITION.copy()
    joueurs_assignes = []
    dispo = equipe.copy()
    
    preferences = []
    for joueur in dispo:
        for i, poste in enumerate(joueur["poste"]):
            score = score_joueur(joueur, poste)
            preferences.append((joueur, poste, score, i))
    
    preferences.sort(key=lambda x: (-x[2], x[3]))
    joueurs_utilises = set()
    
    for joueur, poste, score, _ in preferences:
        if joueur["nom"] in joueurs_utilises:
            continue
        if postes_restants.get(poste, 0) > 0:
            joueurs_assignes.append((joueur, poste))
            postes_restants[poste] -= 1
            joueurs_utilises.add(joueur["nom"])
        if len(joueurs_utilises) == len(equipe):
            break
    
    return joueurs_assignes

def verifier_contraintes(equipe: List[Dict]) -> Tuple[bool, str]:
    nb_elite = sum(1 for j in equipe if categoriser_joueur(j) == "elite")
    nb_faible = sum(1 for j in equipe if categoriser_joueur(j) == "faible")
    total_leadership = sum(j["leader"] for j in equipe)
    total_individualite = sum(j["individualité"] for j in equipe)
    total_condition = sum(j["condition"] for j in equipe)
    
    if nb_elite < CONTRAINTES["elite_min"] or nb_elite > CONTRAINTES["elite_max"]:
        return False, "Elite"
    if nb_faible < CONTRAINTES["faible_min"] or nb_faible > CONTRAINTES["faible_max"]:
        return False, "Faible"
    if total_leadership < CONTRAINTES["leadership_min"] or total_leadership > CONTRAINTES["leadership_max"]:
        return False, "Leadership"
    if total_individualite < CONTRAINTES["individualite_min"] or total_individualite > CONTRAINTES["individualite_max"]:
        return False, "Individualité"
    if total_condition < CONTRAINTES["condition_min"]:
        return False, "Condition"
    return True, "OK"

def verifier_contraintes_complementarite(joueurs_assignes: List[Tuple[Dict, str]]) -> Tuple[bool, str]:
    lignes = {"défense": [], "milieu": [], "attaque": []}
    par_poste = {}
    
    for joueur, poste in joueurs_assignes:
        score = score_joueur(joueur, poste)
        if poste == "défenseur":
            lignes["défense"].append((joueur, score))
        elif poste == "milieu":
            lignes["milieu"].append((joueur, score))
        elif poste == "attaquant":
            lignes["attaque"].append((joueur, score))
        
        if poste not in par_poste:
            par_poste[poste] = []
        par_poste[poste].append((joueur, score))
    
    for poste, joueurs_poste in par_poste.items():
        if poste == "gardien":
            continue
        joueurs_faibles = [(j, s) for j, s in joueurs_poste if s <= SEUIL_FAIBLE_POSTE]
        if len(joueurs_faibles) > 1:
            return False, f"Poste {poste} trop faible"
    
    if lignes["défense"]:
        total_defense = sum(score for _, score in lignes["défense"])
        if total_defense < COMPLEMENTARITE["min_score_ligne_defense"]:
            return False, "Défense insuffisante"
    
    if lignes["milieu"]:
        total_milieu = sum(score for _, score in lignes["milieu"])
        if total_milieu < COMPLEMENTARITE["min_score_ligne_milieu"]:
            return False, "Milieu insuffisant"
    
    return True, "OK"

def score_equipe(equipe: List[Dict], historique: List) -> Tuple[float, Dict]:
    joueurs_choisis = affecter_postes_optimaux(equipe)
    total_score = sum(score_joueur(joueur, poste) for joueur, poste in joueurs_choisis)
    
    noms = [j["nom"] for j, _ in joueurs_choisis]
    synergie_bonus = calc_synergies(noms)
    anti_synergie_penalty = verifier_anti_synergies_meme_poste(joueurs_choisis)
    complementarite_bonus, details_complementarite = analyser_complementarite_postes(joueurs_choisis)
    repetition_penalty = similarité_avec_anciens_matchs(noms, historique)
    
    nb_elite = sum(1 for j in equipe if categoriser_joueur(j) == "elite")
    nb_moyen = sum(1 for j in equipe if categoriser_joueur(j) == "moyen")
    nb_faible = sum(1 for j in equipe if categoriser_joueur(j) == "faible")
    total_leadership = sum(j["leader"] for j in equipe)
    total_individualite = sum(j["individualité"] for j in equipe)
    total_condition = sum(j["condition"] for j in equipe)
    
    total = total_score + synergie_bonus + complementarite_bonus - anti_synergie_penalty - repetition_penalty
    
    return total, {
        "score": total,
        "score_base": total_score,
        "score_reel": total_score + synergie_bonus + complementarite_bonus - anti_synergie_penalty,
        "joueurs": [(j["nom"], poste) for j, poste in joueurs_choisis],
        "joueurs_details": joueurs_choisis,
        "synergie": synergie_bonus,
        "complementarite": complementarite_bonus,
        "details_complementarite": details_complementarite,
        "anti_synergie_meme_poste": anti_synergie_penalty,
        "penalite_repetition": repetition_penalty,
        "nb_elite": nb_elite,
        "nb_moyen": nb_moyen,
        "nb_faible": nb_faible,
        "leadership": total_leadership,
        "individualite": total_individualite,
        "condition": total_condition,
    }

# === ROUTES API ===
@app.route('/api/generate-teams', methods=['POST'])
def generate_teams():
    try:
        data = request.get_json()
        print(f"\n{'='*60}")
        print(f"📥 Requête reçue")
        print(f"   Data: {data}")
        
        selected_names = data.get('selected_players', [])
        print(f"   Joueurs sélectionnés: {len(selected_names)}")
        print(f"   Noms: {selected_names}")
        
        if len(selected_names) != 14:
            print(f"❌ ERREUR: {len(selected_names)} joueurs au lieu de 14")
            return jsonify({"error": f"{len(selected_names)} joueurs au lieu de 14 requis"}), 400
        
        joueurs_selected = [j for j in joueurs_data if j["nom"] in selected_names]
        print(f"   Joueurs trouvés: {len(joueurs_selected)}")
        
        if len(joueurs_selected) != 14:
            print(f"❌ ERREUR: Seulement {len(joueurs_selected)} joueurs trouvés dans la base")
            print(f"   Joueurs manquants:")
            for name in selected_names:
                if name not in [j["nom"] for j in joueurs_data]:
                    print(f"      - {name}")
            return jsonify({"error": f"Joueurs invalides - {len(joueurs_selected)}/14 trouvés"}), 400
        
        meilleur_diff = 9999
        meilleure_A = None
        meilleure_B = None
        historique = charge_historique()
        
        max_iterations = 5000
        tentatives_valides = 0
        
        for _ in range(max_iterations * 3):
            if tentatives_valides >= max_iterations:
                break
            
            random.shuffle(joueurs_selected)
            equipe_A = joueurs_selected[:TEAM_SIZE]
            equipe_B = joueurs_selected[TEAM_SIZE:]
            
            valide_A, _ = verifier_contraintes(equipe_A)
            valide_B, _ = verifier_contraintes(equipe_B)
            if not valide_A or not valide_B:
                continue
            
            joueurs_A_assignes = affecter_postes_optimaux(equipe_A)
            joueurs_B_assignes = affecter_postes_optimaux(equipe_B)
            
            comp_valide_A, _ = verifier_contraintes_complementarite(joueurs_A_assignes)
            comp_valide_B, _ = verifier_contraintes_complementarite(joueurs_B_assignes)
            if not comp_valide_A or not comp_valide_B:
                continue
            
            tentatives_valides += 1
            
            scoreA, detailsA = score_equipe(equipe_A, historique)
            scoreB, detailsB = score_equipe(equipe_B, historique)
            
            diff_score = abs(scoreA - scoreB)
            diff_leadership = abs(detailsA["leadership"] - detailsB["leadership"])
            diff_individualite = abs(detailsA["individualite"] - detailsB["individualite"])
            diff_condition = abs(detailsA["condition"] - detailsB["condition"])
            diff_totale = diff_score + (diff_leadership * 0.5) + (diff_individualite * 0.3) + (diff_condition * 0.3)
            
            if diff_totale < meilleur_diff:
                meilleur_diff = diff_totale
                meilleure_A, meilleure_B = detailsA, detailsB
        
        if meilleure_A is None:
            return jsonify({"error": "Aucune combinaison valide"}), 400
        
        equipe_A_noms = [j["nom"] for j, _ in meilleure_A["joueurs_details"]]
        equipe_B_noms = [j["nom"] for j, _ in meilleure_B["joueurs_details"]]
        historique.append(equipe_A_noms)
        historique.append(equipe_B_noms)
        sauve_historique(historique)
        
        def format_equipe(equipe_details):
            joueurs_formatted = []
            for joueur, poste in equipe_details["joueurs_details"]:
                score = score_joueur(joueur, poste)
                priorite = joueur["poste"].index(poste) + 1 if poste in joueur["poste"] else 0
                joueurs_formatted.append({
                    "nom": joueur["nom"],
                    "poste": poste,
                    "score": round(score, 1),
                    "priorite": priorite,
                    "score_global": round(score_global_joueur(joueur), 1),
                    "categorie": categoriser_joueur(joueur)
                })
            
            return {
                "score": round(equipe_details["score"], 2),
                "score_reel": round(equipe_details["score_reel"], 2),
                "score_base": round(equipe_details["score_base"], 2),
                "synergie": round(equipe_details["synergie"], 2),
                "complementarite": round(equipe_details["complementarite"], 2),
                "anti_synergie": round(equipe_details["anti_synergie_meme_poste"], 2),
                "repetition": round(equipe_details["penalite_repetition"], 2),
                "nb_elite": equipe_details["nb_elite"],
                "nb_moyen": equipe_details["nb_moyen"],
                "nb_faible": equipe_details["nb_faible"],
                "leadership": equipe_details["leadership"],
                "individualite": equipe_details["individualite"],
                "condition": equipe_details["condition"],
                "details_complementarite": equipe_details["details_complementarite"],
                "joueurs": joueurs_formatted
            }
        
        return jsonify({
            "success": True,
            "team_a": format_equipe(meilleure_A),
            "team_b": format_equipe(meilleure_B),
            "tentatives_valides": tentatives_valides
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/players', methods=['GET'])
def get_players():
    players_formatted = []
    for joueur in joueurs_data:
        players_formatted.append({
            "nom": joueur["nom"],
            "score_global": round(score_global_joueur(joueur), 1),
            "categorie": categoriser_joueur(joueur),
            "leader": joueur["leader"],
            "individualite": joueur["individualité"],
            "condition": joueur["condition"]
        })
    return jsonify({"players": players_formatted})

@app.route('/api/history', methods=['GET'])
def get_history():
    try:
        historique = charge_historique()
        nb_matchs = len(historique) // 2
        return jsonify({
            "history": historique,
            "total_matches": nb_matchs,
            "max_history": MAX_HISTORY,
            "file_path": LAST_MATCHES_FILE,
            "file_exists": os.path.exists(LAST_MATCHES_FILE)
        })
    except Exception as e:
        return jsonify({"error": str(e), "history": [], "total_matches": 0}), 500

@app.route('/api/history/clear', methods=['POST'])
def clear_history():
    try:
        with open(LAST_MATCHES_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/debug', methods=['GET'])
def debug_info():
    return jsonify({
        "base_dir": str(BASE_DIR),
        "history_file": LAST_MATCHES_FILE,
        "file_exists": os.path.exists(LAST_MATCHES_FILE),
        "file_size": os.path.getsize(LAST_MATCHES_FILE) if os.path.exists(LAST_MATCHES_FILE) else 0
    })

if __name__ == '__main__':
    print(f"\n{'='*60}")
    print(f"🚀 Serveur Flask")
    print(f"📁 Dossier: {BASE_DIR}")
    print(f"📄 Historique: {LAST_MATCHES_FILE}")
    print(f"✅ Existe: {os.path.exists(LAST_MATCHES_FILE)}")
    print(f"{'='*60}\n")
    app.run(debug=False, port=5001,host="0.0.0.0")  # Désactivé temporairement pour voir les logs
