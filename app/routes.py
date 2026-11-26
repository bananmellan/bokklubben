import io
import json

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from PIL import Image

from . import auth, services
from .auth import admin_required, login_required
from .db import audit, execute, one, query

bp = Blueprint("main", __name__)


def avatar_url(member):
    if member["avatar"]:
        return url_for("main.upload", filename=member["avatar"])
    return None


def member_public(m):
    return {"id": m["id"], "name": m["name"], "avatar": avatar_url(m)}


def register(app):
    app.register_blueprint(bp)
    auth.register(app)

    @app.route("/healthz")
    def healthz():
        return "ok", 200


@bp.route("/")
def index():
    member = auth.current_member()
    if member is None:
        if one("SELECT COUNT(*) AS c FROM members")["c"] == 0:
            return redirect(url_for("main.setup"))
        return redirect(url_for("main.login"))

    round_row = services.ensure_round()
    candidates = query("SELECT * FROM book_candidates WHERE round_id = ? ORDER BY id", (round_row["id"],))
    votes = query(
        "SELECT v.*, m.name AS member_name FROM votes v JOIN members m ON m.id = v.member_id WHERE v.round_id = ? ORDER BY v.id",
        (round_row["id"],),
    )
    tally = services.tally(round_row["id"])
    my_vote = one("SELECT * FROM votes WHERE round_id = ? AND member_id = ?", (round_row["id"], member["id"]))
    read_marks = query(
        "SELECT rm.*, m.name AS member_name FROM read_marks rm JOIN members m ON m.id = rm.member_id WHERE rm.round_id = ? ORDER BY rm.id",
        (round_row["id"],),
    )
    my_read = one("SELECT * FROM read_marks WHERE round_id = ? AND member_id = ?", (round_row["id"], member["id"]))
    chooser = one("SELECT * FROM members WHERE id = ?", (round_row["chooser_id"],)) if round_row["chooser_id"] else None
    winner = (
        one("SELECT * FROM book_candidates WHERE id = ?", (round_row["winner_candidate_id"],))
        if round_row["winner_candidate_id"]
        else None
    )
    members = query("SELECT * FROM members ORDER BY lower(name), id")
    pool = services.wheel_candidates()
    wheel_json = json.dumps([member_public(m) for m in pool])

    return render_template(
        "index.html",
        round=round_row,
        candidates=candidates,
        votes=votes,
        tally=tally,
        my_vote=my_vote,
        read_marks=read_marks,
        my_read=my_read,
        chooser=chooser,
        winner=winner,
        members=members,
        wheel_json=wheel_json,
        wheel_pool=pool,
        tie=services.is_tie(round_row["id"]),
        vote_weight=services.vote_weight(member, round_row),
    )


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    if one("SELECT COUNT(*) AS c FROM members")["c"] > 0:
        return redirect(url_for("main.login"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        if not name or not email:
            flash("Fyll i både namn och e-post.", "error")
            return render_template("setup.html")
        execute(
            "INSERT INTO members(name, email, is_admin, voting_active, in_wheel_pool) VALUES (?, ?, 1, 1, 1)",
            (name, email),
        )
        services.ensure_round()
        flash("Adminkontot är skapat. Logga in med din e-post.", "success")
        return redirect(url_for("main.login"))
    return render_template("setup.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if auth.current_member() is not None:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        member, code = auth.create_login_code(email)
        if member is None:
            flash("Om e-postadressen är registrerad skickas en inloggningskod.", "info")
            return render_template("login.html")
        dev_code = None
        if current_app.config["DEV_MODE"]:
            dev_code = code
        else:
            try:
                auth.send_code_email(member, code, services.get_setting("club_name", "Bokklubben"))
            except Exception:
                current_app.logger.exception("Kunde inte skicka inloggningskod via SMTP")
                flash("Kunde inte skicka e-post. Kontakta administratören.", "error")
                return render_template("login.html")
        return render_template("verify.html", email=email, dev_code=dev_code)
    return render_template("login.html")


@bp.route("/verify", methods=["GET", "POST"])
def verify():
    email = request.args.get("email", "") or request.form.get("email", "")
    if request.method == "POST":
        code = request.form.get("code", "")
        member = auth.verify_code(email, code)
        if member is None:
            flash("Fel eller utgången kod. Försök igen.", "error")
            return render_template("verify.html", email=email, dev_code=code if current_app.config["DEV_MODE"] else None)
        flash(f"Välkommen, {member['name']}!", "success")
        return redirect(url_for("main.index"))
    return render_template("verify.html", email=email, dev_code=None)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


@bp.route("/api/wheel")
@login_required
def api_wheel():
    r = services.current_round()
    pool = services.wheel_candidates()
    return jsonify(
        {
            "state": r["state"] if r else "spin",
            "can_spin": bool(r and r["state"] == "spin"),
            "chooser_id": r["chooser_id"] if r else None,
            "candidates": [member_public(m) for m in pool],
        }
    )


@bp.route("/api/spin", methods=["POST"])
@login_required
def api_spin():
    result, error = services.spin(auth.current_member()["id"])
    if error:
        return jsonify({"ok": False, "error": error}), 409
    return jsonify({"ok": True, "index": result["index"], "member": member_public(result["member"])})


@bp.route("/round/candidates/add", methods=["POST"])
@login_required
def add_candidate():
    member = auth.current_member()
    r = services.current_round()
    if r["state"] != "candidates":
        flash("Inget bokval pågår just nu.", "error")
        return redirect(url_for("main.index"))
    if r["chooser_id"] != member["id"] and not member["is_admin"]:
        abort(403)
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    description = request.form.get("description", "").strip()
    if not title:
        flash("Titeln får inte vara tom.", "error")
        return redirect(url_for("main.index"))
    count = one("SELECT COUNT(*) AS c FROM book_candidates WHERE round_id = ?", (r["id"],))["c"]
    if count >= 3:
        flash("Max 3 kandidater per omgång.", "error")
        return redirect(url_for("main.index"))
    execute(
        "INSERT INTO book_candidates(round_id, title, author, description) VALUES (?, ?, ?, ?)",
        (r["id"], title, author, description),
    )
    audit(member["id"], "candidate_add", f"Omgång #{r['id']}: '{title}'")
    flash("Kandidat tillagd.", "success")
    return redirect(url_for("main.index"))


@bp.route("/round/candidates/<int:cid>/delete", methods=["POST"])
@login_required
def delete_candidate(cid):
    member = auth.current_member()
    cand = one("SELECT * FROM book_candidates WHERE id = ?", (cid,))
    if cand is None:
        abort(404)
    r = one("SELECT * FROM rounds WHERE id = ?", (cand["round_id"],))
    if r["state"] != "candidates" or (r["chooser_id"] != member["id"] and not member["is_admin"]):
        abort(403)
    execute("DELETE FROM book_candidates WHERE id = ?", (cid,))
    audit(member["id"], "candidate_delete", f"Omgång #{cand['round_id']}: '{cand['title']}' borttagen")
    flash("Kandidat borttagen.", "success")
    return redirect(url_for("main.index"))


@bp.route("/round/candidates/submit", methods=["POST"])
@login_required
def submit_candidates():
    member = auth.current_member()
    r = services.current_round()
    if r["state"] != "candidates" or (r["chooser_id"] != member["id"] and not member["is_admin"]):
        abort(403)
    count = one("SELECT COUNT(*) AS c FROM book_candidates WHERE round_id = ?", (r["id"],))["c"]
    if count != 3:
        flash("Det måste finnas exakt 3 kandidater innan omröstningen startar.", "error")
        return redirect(url_for("main.index"))
    execute("UPDATE rounds SET state = 'voting', updated_at = datetime('now') WHERE id = ?", (r["id"],))
    audit(member["id"], "voting_open", f"Omgång #{r['id']}")
    flash("Omröstningen är öppen!", "success")
    return redirect(url_for("main.index"))


@bp.route("/round/vote", methods=["POST"])
@login_required
def vote():
    member = auth.current_member()
    candidate_id = request.form.get("candidate_id", type=int)
    r = services.current_round()
    error = services.cast_vote(r["id"], member, candidate_id)
    if error:
        flash(error, "error")
    else:
        cand = one("SELECT title FROM book_candidates WHERE id = ?", (candidate_id,))
        audit(
            member["id"],
            "vote",
            f"Omgång #{r['id']}: röstade på '{cand['title'] if cand else candidate_id}' (vikt {services.vote_weight(member, r)})",
        )
        flash("Din röst är registrerad.", "success")
    return redirect(url_for("main.index"))


@bp.route("/round/meeting", methods=["POST"])
@login_required
def meeting():
    r = services.current_round()
    if r["state"] not in ("decided", "meeting"):
        flash("En bok måste vara vald innan mötesdatum sätts.", "error")
        return redirect(url_for("main.index"))
    date = request.form.get("date", "").strip()
    if not date:
        flash("Välj ett datum.", "error")
        return redirect(url_for("main.index"))
    services.set_meeting_date(r["id"], date)
    audit(member["id"], "meeting_date", f"Omgång #{r['id']}: mötesdatum satt till {date}")
    flash("Mötesdatum sparat.", "success")
    return redirect(url_for("main.index"))


@bp.route("/round/read", methods=["POST"])
@login_required
def read():
    member = auth.current_member()
    r = services.current_round()
    if r["state"] not in ("meeting", "done"):
        flash("Boken måste vara vald och ett mötesdatum satt innan du kan markera läsning.", "error")
        return redirect(url_for("main.index"))
    has_read = request.form.get("has_read") == "1"
    services.mark_read(r["id"], member["id"], has_read, actor_id=member["id"])
    flash("Läsning markerad." if has_read else "Markering sparad – kom ihåg att din rösträtt är pausad tills du läst en bok.", "success" if has_read else "info")
    return redirect(url_for("main.index"))


@bp.route("/members")
@login_required
def members():
    all_members = query("SELECT * FROM members ORDER BY lower(name), id")
    return render_template("members.html", members=all_members)


@bp.route("/members/<int:mid>/avatar", methods=["POST"])
@login_required
def upload_avatar(mid):
    member = auth.current_member()
    target = one("SELECT * FROM members WHERE id = ?", (mid,))
    if target is None:
        abort(404)
    if member["id"] != mid and not member["is_admin"]:
        abort(403)
    file = request.files.get("avatar")
    if file is None or not file.filename:
        flash("Ingen fil vald.", "error")
        return redirect(url_for("main.members"))
    data = file.read(current_app.config["MAX_AVATAR_BYTES"] + 1)
    if len(data) > current_app.config["MAX_AVATAR_BYTES"]:
        flash("Filen är för stor (max 2 MB).", "error")
        return redirect(url_for("main.members"))
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        img.thumbnail((256, 256))
    except Exception:
        flash("Ogiltig bildfil.", "error")
        return redirect(url_for("main.members"))
    filename = f"member_{mid}.png"
    img.save(current_app.config["UPLOAD_DIR"] / filename, "PNG")
    execute("UPDATE members SET avatar = ? WHERE id = ?", (filename, mid))
    audit(member["id"], "avatar_upload", f"Medlem #{mid}")
    flash("Profilbild uppdaterad.", "success")
    return redirect(url_for("main.members"))


@bp.route("/uploads/<path:filename>")
@login_required
def upload(filename):
    return send_from_directory(current_app.config["UPLOAD_DIR"], filename)


@bp.route("/stats")
@login_required
def stats():
    round_books = query(
        """
        SELECT b.title, b.author, r.id AS round_id, r.meeting_date, r.created_at,
               (SELECT COUNT(*) FROM read_marks rm WHERE rm.round_id = r.id AND rm.has_read = 1) AS nread
        FROM rounds r
        JOIN book_candidates b ON b.id = r.winner_candidate_id
        ORDER BY coalesce(r.meeting_date, r.created_at) DESC, r.id DESC
        """
    )
    past_books = query(
        """
        SELECT pb.id, pb.title, pb.author, pb.read_date,
               (SELECT COUNT(*) FROM past_book_readers p WHERE p.past_book_id = pb.id) AS nread
        FROM past_books pb
        ORDER BY pb.read_date DESC, pb.id DESC
        """
    )

    years = {}
    for b in round_books:
        y = (b["meeting_date"] or b["created_at"] or "")[:4] or "okänt"
        years[y] = years.get(y, 0) + 1
    for b in past_books:
        y = (b["read_date"] or "")[:4] or "okänt"
        years[y] = years.get(y, 0) + 1
    per_year = sorted(years.items(), key=lambda kv: (1, "") if kv[0] == "okänt" else (0, kv[0]), reverse=True)

    authors = {}
    for b in list(round_books) + list(past_books):
        a = (b["author"] or "").strip()
        if a:
            key = a.lower()
            if key not in authors:
                authors[key] = [a, 0]
            authors[key][1] += 1
    top_authors = sorted(authors.values(), key=lambda x: (-x[1], x[0].lower()))[:10]

    member_stats = query(
        """
        SELECT m.id, m.name,
               (SELECT COUNT(*) FROM read_marks rm JOIN rounds r ON r.id = rm.round_id
                WHERE rm.member_id = m.id AND rm.has_read = 1 AND r.winner_candidate_id IS NOT NULL) AS round_reads,
               (SELECT COUNT(*) FROM past_book_readers p WHERE p.member_id = m.id) AS past_reads
        FROM members m
        ORDER BY (round_reads + past_reads) DESC, lower(m.name)
        """
    )

    totals = {
        "books": len(round_books) + len(past_books),
        "from_rounds": len(round_books),
        "past": len(past_books),
        "members": one("SELECT COUNT(*) AS c FROM members")["c"],
    }
    max_year = max([c for _, c in per_year], default=1) or 1
    max_author = max([c for _, c in top_authors], default=1) or 1
    max_member = max([m["round_reads"] + m["past_reads"] for m in member_stats], default=1) or 1

    return render_template(
        "stats.html",
        round_books=round_books,
        past_books=past_books,
        per_year=per_year,
        top_authors=top_authors,
        member_stats=member_stats,
        totals=totals,
        max_year=max_year,
        max_author=max_author,
        max_member=max_member,
    )


@bp.route("/history")
@login_required
def history():
    rounds = query(
        """
        SELECT r.*, m.name AS chooser_name, b.title AS winner_title, b.author AS winner_author
        FROM rounds r
        LEFT JOIN members m ON m.id = r.chooser_id
        LEFT JOIN book_candidates b ON b.id = r.winner_candidate_id
        ORDER BY r.id DESC
        """
    )
    return render_template("history.html", rounds=rounds)
