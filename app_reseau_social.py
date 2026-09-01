import os
import sqlite3
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --- CONFIGURATION ---
dossier_du_fichier = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(dossier_du_fichier) == "templates":
    dossier_templates = dossier_du_fichier
    dossier_bdd = os.path.dirname(dossier_du_fichier)
else:
    dossier_templates = os.path.join(dossier_du_fichier, "templates")
    if not os.path.exists(dossier_templates):
        dossier_templates = dossier_du_fichier
    dossier_bdd = dossier_du_fichier

UPLOAD_FOLDER = os.path.join(dossier_bdd, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__, template_folder=dossier_templates, static_folder=os.path.join(dossier_bdd, "static"))
app.secret_key = "cle_ultra_securisee_reseau_social_pro_v4_2025"
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 Mo max
db_path = os.path.join(dossier_bdd, "reseau_social_v4.db")


# --- FILTRE JINJA ULTRA SÉCURISÉ (Ne plante jamais) ---
@app.template_filter("temps_relatif")
def temps_relatif(date_str):
    if not date_str:
        return ""
    try:
        date_pub = datetime.strptime(str(date_str), "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            date_pub = datetime.strptime(str(date_str), "%Y-%m-%d %H:%M:%S.%f")
        except Exception:
            return str(date_str)
    
    try:
        secondes = int((datetime.now() - date_pub).total_seconds())
        if secondes < 60: return "À l'instant"
        elif secondes < 3600: return f"Il y a {secondes // 60} min"
        elif secondes < 86400: return f"Il y a {secondes // 3600}h"
        elif secondes < 604800: return f"Il y a {secondes // 86400}j"
        else: return date_pub.strftime("%d/%m/%Y")
    except Exception:
        return str(date_str)


@app.template_filter("hashtags")
def hashtags_filter(texte):
    if not texte:
        return ""
    mots = str(texte).split()
    resultat = []
    for mot in mots:
        if mot.startswith("#") and len(mot) > 1:
            tag = mot[1:].strip(".,!?;:")
            resultat.append(f'<a href="/recherche?q=%23{tag}" class="text-info text-decoration-none fw-bold">{mot}</a>')
        else:
            resultat.append(mot)
    return " ".join(resultat)


# --- INITIALISATION BDD ---
def initialiser_bdd():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS utilisateurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pseudo TEXT UNIQUE NOT NULL,
            mot_de_passe TEXT NOT NULL,
            bio TEXT DEFAULT '',
            date_inscription TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auteur TEXT NOT NULL,
            contenu TEXT NOT NULL,
            image TEXT DEFAULT '',
            epingle INTEGER DEFAULT 0,
            date_publication TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            pseudo TEXT NOT NULL,
            type TEXT NOT NULL,
            UNIQUE(message_id, pseudo)
        );
        CREATE TABLE IF NOT EXISTS commentaires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            auteur TEXT NOT NULL,
            contenu TEXT NOT NULL,
            date_commentaire TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS followers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            follower TEXT NOT NULL,
            following TEXT NOT NULL,
            UNIQUE(follower, following)
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            destinataire TEXT NOT NULL,
            expediteur TEXT NOT NULL,
            type TEXT NOT NULL,
            message_id INTEGER DEFAULT 0,
            lu INTEGER DEFAULT 0,
            date_notif TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS messages_prives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expediteur TEXT NOT NULL,
            destinataire TEXT NOT NULL,
            contenu TEXT NOT NULL,
            lu INTEGER DEFAULT 0,
            date_envoi TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

initialiser_bdd()


def creer_notification(destinataire, expediteur, type_notif, message_id=0):
    if destinataire == expediteur:
        return
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO notifications (destinataire, expediteur, type, message_id) VALUES (?,?,?,?)",
                     (destinataire, expediteur, type_notif, message_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# --- ROUTE PRINCIPALE ---
@app.route("/", methods=["GET", "POST"])
def fil_actualite():
    initialiser_bdd()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    pseudo_connecte = session.get("utilisateur")

    if request.method == "POST" and pseudo_connecte:
        contenu = request.form.get("message", "").strip()
        fichier = request.files.get("image")
        image_nom = ""

        if fichier and fichier.filename and allowed_file(fichier.filename):
            ext = fichier.filename.rsplit(".", 1)[1].lower()
            image_nom = f"{uuid.uuid4().hex}.{ext}"
            fichier.save(os.path.join(UPLOAD_FOLDER, image_nom))

        if contenu and len(contenu) <= 500:
            c.execute("INSERT INTO messages (auteur, contenu, image) VALUES (?,?,?)",
                      (pseudo_connecte, contenu, image_nom))
            conn.commit()
            flash("Message publié ! 🚀", "success")
        elif not contenu and image_nom:
            c.execute("INSERT INTO messages (auteur, contenu, image) VALUES (?,?,?)",
                      (pseudo_connecte, "📸", image_nom))
            conn.commit()
            flash("Photo publiée ! 📸", "success")
        else:
            flash("Message vide ou trop long (500 max).", "danger")
        conn.close()
        return redirect("/")

    page = request.args.get("page", 1, type=int)
    par_page = 10
    offset = (page - 1) * par_page

    c.execute("SELECT COUNT(*) FROM messages")
    total = c.fetchone()[0]
    total_pages = max(1, (total + par_page - 1) // par_page)

    c.execute("SELECT id, auteur, contenu, image, epingle, date_publication FROM messages ORDER BY epingle DESC, id DESC LIMIT ? OFFSET ?",
              (par_page, offset))
    lignes = c.fetchall()

    messages_complets = []
    for msg in lignes:
        msg_id, auteur, contenu, image, epingle, date_pub = msg

        c.execute("SELECT type, COUNT(*) FROM reactions WHERE message_id=? GROUP BY type", (msg_id,))
        reactions = dict(c.fetchall())
        total_reactions = sum(reactions.values())

        ma_reaction = None
        if pseudo_connecte:
            c.execute("SELECT type FROM reactions WHERE message_id=? AND pseudo=?", (msg_id, pseudo_connecte))
            r = c.fetchone()
            if r: ma_reaction = r[0]

        c.execute("SELECT auteur, contenu, date_commentaire FROM commentaires WHERE message_id=? ORDER BY id ASC", (msg_id,))
        commentaires = c.fetchall()

        messages_complets.append({
            "id": msg_id, "auteur": auteur, "contenu": contenu,
            "image": image, "epingle": epingle, "date": date_pub,
            "reactions": reactions, "total_reactions": total_reactions,
            "ma_reaction": ma_reaction, "commentaires": commentaires
        })

    conn.close()
    return render_template("reseau_social.html", messages=messages_complets,
                           utilisateur_connecte=pseudo_connecte,
                           page=page, total_pages=total_pages)


# --- RÉACTIONS MULTIPLES ---
@app.route("/react/<int:message_id>/<emoji>")
def react(message_id, emoji):
    if "utilisateur" not in session:
        return redirect("/connexion")
    pseudo = session["utilisateur"]
    emojis_valides = ["❤️", "👍", "😂", "😢", "😮", "🔥"]
    if emoji not in emojis_valides:
        return redirect("/")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT type FROM reactions WHERE message_id=? AND pseudo=?", (message_id, pseudo))
    existant = c.fetchone()

    if existant:
        if existant[0] == emoji:
            c.execute("DELETE FROM reactions WHERE message_id=? AND pseudo=?", (message_id, pseudo))
        else:
            c.execute("UPDATE reactions SET type=? WHERE message_id=? AND pseudo=?", (emoji, message_id, pseudo))
    else:
        c.execute("INSERT INTO reactions (message_id, pseudo, type) VALUES (?,?,?)", (message_id, pseudo, emoji))
        c.execute("SELECT auteur FROM messages WHERE id=?", (message_id,))
        auteur_msg = c.fetchone()
        if auteur_msg:
            creer_notification(auteur_msg[0], pseudo, "reaction", message_id)

    conn.commit()
    conn.close()
    return redirect("/")


# --- COMMENTER ---
@app.route("/commenter/<int:message_id>", methods=["POST"])
def commenter(message_id):
    if "utilisateur" not in session:
        return redirect("/connexion")
    contenu = request.form.get("commentaire", "").strip()
    if contenu:
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO commentaires (message_id, auteur, contenu) VALUES (?,?,?)",
                     (message_id, session["utilisateur"], contenu))
        c = conn.cursor()
        c.execute("SELECT auteur FROM messages WHERE id=?", (message_id,))
        auteur_msg = c.fetchone()
        if auteur_msg:
            creer_notification(auteur_msg[0], session["utilisateur"], "commentaire", message_id)
        conn.commit()
        conn.close()
        flash("Commentaire ajouté ! 💬", "success")
    return redirect("/")


# --- FOLLOW / UNFOLLOW ---
@app.route("/follow/<pseudo_cible>")
def follow(pseudo_cible):
    if "utilisateur" not in session:
        return redirect("/connexion")
    pseudo = session["utilisateur"]
    if pseudo == pseudo_cible:
        return redirect(f"/profil/{pseudo_cible}")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT 1 FROM followers WHERE follower=? AND following=?", (pseudo, pseudo_cible))
    if c.fetchone():
        c.execute("DELETE FROM followers WHERE follower=? AND following=?", (pseudo, pseudo_cible))
        flash(f"Tu ne suis plus {pseudo_cible}.", "info")
    else:
        c.execute("INSERT INTO followers (follower, following) VALUES (?,?)", (pseudo, pseudo_cible))
        creer_notification(pseudo_cible, pseudo, "follow")
        flash(f"Tu suis maintenant {pseudo_cible} ! 👥", "success")
    conn.commit()
    conn.close()
    return redirect(f"/profil/{pseudo_cible}")


# --- PROFIL ---
@app.route("/profil/<pseudo>")
def profil(pseudo):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT pseudo, bio, date_inscription FROM utilisateurs WHERE pseudo=?", (pseudo,))
    utilisateur = c.fetchone()
    if not utilisateur:
        conn.close()
        flash("Utilisateur introuvable.", "danger")
        return redirect("/")

    c.execute("SELECT COUNT(*) FROM followers WHERE following=?", (pseudo,))
    nb_followers = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM followers WHERE follower=?", (pseudo,))
    nb_following = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM messages WHERE auteur=?", (pseudo,))
    total_messages = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM reactions WHERE message_id IN (SELECT id FROM messages WHERE auteur=?)", (pseudo,))
    total_reactions = c.fetchone()[0]

    c.execute("SELECT id, auteur, contenu, image, epingle, date_publication FROM messages WHERE auteur=? ORDER BY epingle DESC, id DESC", (pseudo,))
    messages = c.fetchall()

    est_follow = False
    pseudo_connecte = session.get("utilisateur")
    if pseudo_connecte and pseudo_connecte != pseudo:
        c.execute("SELECT 1 FROM followers WHERE follower=? AND following=?", (pseudo_connecte, pseudo))
        est_follow = c.fetchone() is not None

    conn.close()
    return render_template("profil.html", profil_utilisateur=utilisateur,
                           messages=messages, nb_followers=nb_followers,
                           nb_following=nb_following, total_messages=total_messages,
                           total_reactions=total_reactions, est_follow=est_follow,
                           utilisateur_connecte=pseudo_connecte)


# --- ÉPINGLER ---
@app.route("/epingle/<int:message_id>")
def epingle(message_id):
    if "utilisateur" not in session:
        return redirect("/connexion")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT epingle FROM messages WHERE id=? AND auteur=?", (message_id, session["utilisateur"]))
    msg = c.fetchone()
    if msg:
        nouveau = 0 if msg[0] else 1
        c.execute("UPDATE messages SET epingle=? WHERE id=?", (nouveau, message_id))
        conn.commit()
        flash("Message épinglé ! 📌" if nouveau else "Message désépinglé.", "info")
    conn.close()
    return redirect("/")


# --- MODIFIER ---
@app.route("/modifier/<int:message_id>", methods=["GET", "POST"])
def modifier_message(message_id):
    if "utilisateur" not in session:
        return redirect("/connexion")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, auteur, contenu FROM messages WHERE id=? AND auteur=?", (message_id, session["utilisateur"]))
    message = c.fetchone()
    if not message:
        conn.close()
        flash("Non autorisé.", "danger")
        return redirect("/")
    if request.method == "POST":
        nouveau = request.form.get("message", "").strip()
        if nouveau and len(nouveau) <= 500:
            c.execute("UPDATE messages SET contenu=? WHERE id=?", (nouveau, message_id))
            conn.commit()
            flash("Message modifié ! ✏️", "success")
        conn.close()
        return redirect("/")
    conn.close()
    return render_template("modifier.html", message=message, utilisateur_connecte=session.get("utilisateur"))


# --- SUPPRIMER ---
@app.route("/supprimer/<int:message_id>")
def supprimer_message(message_id):
    if "utilisateur" in session:
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM messages WHERE id=? AND auteur=?", (message_id, session["utilisateur"]))
        conn.execute("DELETE FROM reactions WHERE message_id=?", (message_id,))
        conn.execute("DELETE FROM commentaires WHERE message_id=?", (message_id,))
        conn.commit()
        conn.close()
        flash("Message supprimé. 🗑️", "warning")
    return redirect("/")


# --- NOTIFICATIONS ---
@app.route("/notifications")
def notifications():
    if "utilisateur" not in session:
        return redirect("/connexion")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, expediteur, type, message_id, lu, date_notif FROM notifications WHERE destinataire=? ORDER BY id DESC LIMIT 50",
              (session["utilisateur"],))
    notifs = c.fetchall()
    c.execute("UPDATE notifications SET lu=1 WHERE destinataire=? AND lu=0", (session["utilisateur"],))
    conn.commit()
    conn.close()
    return render_template("notifications.html", notifs=notifs, utilisateur_connecte=session.get("utilisateur"))


# --- MESSAGES PRIVÉS ---
@app.route("/messages")
def conversations():
    if "utilisateur" not in session:
        return redirect("/connexion")
    pseudo = session["utilisateur"]
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        SELECT DISTINCT CASE WHEN expediteur=? THEN destinataire ELSE expediteur END as interlocuteur
        FROM messages_prives WHERE expediteur=? OR destinataire=?
        ORDER BY id DESC
    """, (pseudo, pseudo, pseudo))
    convs = c.fetchall()
    conn.close()
    return render_template("conversations.html", convs=convs, utilisateur_connecte=pseudo)


@app.route("/messages/<interlocuteur>", methods=["GET", "POST"])
def chat(interlocuteur):
    if "utilisateur" not in session:
        return redirect("/connexion")
    pseudo = session["utilisateur"]
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    if request.method == "POST":
        contenu = request.form.get("contenu", "").strip()
        if contenu:
            c.execute("INSERT INTO messages_prives (expediteur, destinataire, contenu) VALUES (?,?,?)",
                      (pseudo, interlocuteur, contenu))
            creer_notification(interlocuteur, pseudo, "message_prive")
            conn.commit()

    c.execute("""
        SELECT expediteur, contenu, date_envoi FROM messages_prives
        WHERE (expediteur=? AND destinataire=?) OR (expediteur=? AND destinataire=?)
        ORDER BY id ASC
    """, (pseudo, interlocuteur, interlocuteur, pseudo))
    msgs = c.fetchall()

    c.execute("UPDATE messages_prives SET lu=1 WHERE expediteur=? AND destinataire=? AND lu=0",
              (interlocuteur, pseudo))
    conn.commit()
    conn.close()
    return render_template("chat.html", msgs=msgs, interlocuteur=interlocuteur, utilisateur_connecte=pseudo)


# --- RECHERCHE ---
@app.route("/recherche")
def recherche():
    q = request.args.get("q", "").strip()
    resultats_messages = []
    resultats_users = []
    if q:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT id, auteur, contenu, image, date_publication FROM messages WHERE contenu LIKE ? ORDER BY id DESC LIMIT 20",
                  (f"%{q}%",))
        resultats_messages = c.fetchall()
        c.execute("SELECT pseudo, bio FROM utilisateurs WHERE pseudo LIKE ? LIMIT 10", (f"%{q}%",))
        resultats_users = c.fetchall()
        conn.close()
    return render_template("recherche.html", q=q, resultats_messages=resultats_messages,
                           resultats_users=resultats_users, utilisateur_connecte=session.get("utilisateur"))


# --- DASHBOARD ---
@app.route("/dashboard")
def dashboard():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM utilisateurs")
    nb_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM messages")
    nb_messages = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM reactions")
    nb_reactions = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM commentaires")
    nb_commentaires = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM followers")
    nb_follows = c.fetchone()[0]
    c.execute("SELECT auteur, COUNT(*) as cnt FROM messages GROUP BY auteur ORDER BY cnt DESC LIMIT 5")
    top_auteurs = c.fetchall()
    c.execute("SELECT type, COUNT(*) FROM reactions GROUP BY type ORDER BY COUNT(*) DESC")
    stats_reactions = c.fetchall()
    conn.close()
    return render_template("dashboard.html", nb_users=nb_users, nb_messages=nb_messages,
                           nb_reactions=nb_reactions, nb_commentaires=nb_commentaires,
                           nb_follows=nb_follows, top_auteurs=top_auteurs,
                           stats_reactions=stats_reactions,
                           utilisateur_connecte=session.get("utilisateur"))


# --- THÈME SOMBRE/CLAIR ---
@app.route("/toggle_theme")
def toggle_theme():
    session["theme"] = "dark" if session.get("theme") == "light" else "light"
    return redirect(request.referrer or "/")


# --- INSCRIPTION ---
@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    if request.method == "POST":
        pseudo = request.form.get("pseudo", "").strip()
        mdp = request.form.get("mot_de_passe", "")
        if not pseudo or not mdp:
            flash("Tous les champs sont obligatoires.", "danger")
        elif len(pseudo) < 3:
            flash("Le pseudo doit contenir au moins 3 caractères.", "danger")
        elif len(mdp) < 4:
            flash("Le mot de passe doit contenir au moins 4 caractères.", "danger")
        else:
            try:
                conn = sqlite3.connect(db_path)
                conn.execute("INSERT INTO utilisateurs (pseudo, mot_de_passe) VALUES (?,?)",
                             (pseudo, generate_password_hash(mdp)))
                conn.commit()
                conn.close()
                session["utilisateur"] = pseudo
                session["theme"] = "light"
                flash(f"Bienvenue {pseudo} ! 🎉", "success")
                return redirect("/")
            except sqlite3.IntegrityError:
                flash("Ce pseudo est déjà pris !", "danger")
    return render_template("inscription_social.html")


# --- CONNEXION ---
@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "POST":
        pseudo = request.form.get("pseudo", "").strip()
        mdp = request.form.get("mot_de_passe", "")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT pseudo, mot_de_passe FROM utilisateurs WHERE pseudo=?", (pseudo,))
        u = c.fetchone()
        conn.close()
        if u and check_password_hash(u[1], mdp):
            session["utilisateur"] = u[0]
            if "theme" not in session:
                session["theme"] = "light"
            flash(f"Content de te revoir, {u[0]} ! 👋", "success")
            return redirect("/")
        else:
            flash("Identifiants incorrects.", "danger")
    return render_template("connexion_social.html")


# --- DÉCONNEXION ---
@app.route("/deconnexion")
def deconnexion():
    session.pop("utilisateur", None)
    flash("Déconnecté.", "info")
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True)
