from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for

from . import auth, services
from .auth import admin_required
from .db import audit, backup_database, execute, one, query

bp = Blueprint("admin", __name__, url_prefix="/admin")


def register(app):
    app.register_blueprint(bp)


@bp.route("/")
@admin_required
def panel():
    members = query("SELECT * FROM members ORDER BY lower(name), id")
    rounds = query(
        """
        SELECT r.*, m.name AS chooser_name, b.title AS winner_title
        FROM rounds r
        LEFT JOIN members m ON m.id = r.chooser_id
        LEFT JOIN book_candidates b ON b.id = r.winner_candidate_id
        ORDER BY r.id DESC
        """
    )
    pool = services.wheel_candidates()
    past_books = query(
        """
        SELECT pb.*, (SELECT COUNT(*) FROM past_book_readers p WHERE p.past_book_id = pb.id) AS nreaders
        FROM past_books pb
        ORDER BY pb.read_date DESC, pb.id DESC
        """
    )
    return render_template(
        "admin.html", members=members, rounds=rounds, pool=pool, states=services.STATES, past_books=past_books
    )


@bp.route("/past-books", methods=["POST"])
@admin_required
def past_book_add():
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    read_date = request.form.get("read_date", "").strip() or None
    if not title:
        flash("Titeln får inte vara tom.", "error")
        return redirect(url_for("admin.panel"))
    pid = execute("INSERT INTO past_books(title, author, read_date) VALUES (?, ?, ?)", (title, author, read_date))
    for mid in request.form.getlist("member_ids"):
        execute("INSERT OR IGNORE INTO past_book_readers(past_book_id, member_id) VALUES (?, ?)", (pid, int(mid)))
    audit(auth.current_member()["id"], "past_book_add", f"'{title}' ({read_date or 'okänt datum'})")
    flash("Tidigare bok tillagd.", "success")
    return redirect(url_for("admin.panel"))


@bp.route("/past-books/<int:pid>", methods=["GET", "POST"])
@admin_required
def past_book_edit(pid):
    pb = one("SELECT * FROM past_books WHERE id = ?", (pid,))
    if pb is None:
        abort(404)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Titeln får inte vara tom.", "error")
            return redirect(url_for("admin.past_book_edit", pid=pid))
        execute(
            "UPDATE past_books SET title = ?, author = ?, read_date = ? WHERE id = ?",
            (title, request.form.get("author", "").strip(), request.form.get("read_date", "").strip() or None, pid),
        )
        execute("DELETE FROM past_book_readers WHERE past_book_id = ?", (pid,))
        for mid in request.form.getlist("member_ids"):
            execute("INSERT OR IGNORE INTO past_book_readers(past_book_id, member_id) VALUES (?, ?)", (pid, int(mid)))
        audit(auth.current_member()["id"], "past_book_edit", f"Tidigare bok #{pid} -> '{title}'")
        flash("Tidigare bok uppdaterad.", "success")
        return redirect(url_for("admin.panel"))
    members = query("SELECT * FROM members ORDER BY lower(name), id")
    readers = {r["member_id"] for r in query("SELECT member_id FROM past_book_readers WHERE past_book_id = ?", (pid,))}
    return render_template("admin_past_book.html", pb=pb, members=members, readers=readers)


@bp.route("/past-books/<int:pid>/delete", methods=["POST"])
@admin_required
def past_book_delete(pid):
    pb = one("SELECT * FROM past_books WHERE id = ?", (pid,))
    if pb is None:
        abort(404)
    execute("DELETE FROM past_books WHERE id = ?", (pid,))
    audit(auth.current_member()["id"], "past_book_delete", f"'{pb['title']}' borttagen")
    flash(f"'{pb['title']}' borttagen från historiken.", "success")
    return redirect(url_for("admin.panel"))


ACTION_LABELS = {
    "spin": "Hjul snurrat",
    "wheel_reset": "Hjulpool återställd",
    "wheel_suspension": "Hjulplats ändrad",
    "vote": "Röst lagd",
    "meeting_date": "Mötesdatum ändrat",
    "read_mark": "Läsning markerad",
    "candidate_add": "Kandidat tillagd",
    "candidate_delete": "Kandidat borttagen",
    "voting_open": "Omröstning öppnad",
    "avatar_upload": "Profilbild uppladdad",
    "member_add": "Medlem tillagd",
    "member_edit": "Medlem ändrad",
    "member_delete": "Medlem borttagen",
    "round_state": "Omgångsstatus ändrad",
    "round_chooser": "Bokväljare ändrad",
    "round_meeting": "Mötesdatum ändrat (admin)",
    "round_winner": "Vinnare ändrad",
    "round_delete": "Omgång borttagen",
    "candidate_edit": "Kandidat ändrad",
    "vote_add": "Röst ändrad (admin)",
    "vote_edit": "Röst ändrad (admin)",
    "vote_delete": "Röst borttagen",
    "readmark_set": "Läsmarkering ändrad (admin)",
    "readmark_delete": "Läsmarkering borttagen",
    "past_book_add": "Tidigare bok tillagd",
    "past_book_edit": "Tidigare bok ändrad",
    "past_book_delete": "Tidigare bok borttagen",
    "settings": "Inställning ändrad",
    "backup": "Backup skapad",
}


@bp.route("/audit")
@admin_required
def audit_page():
    entries = query(
        """
        SELECT a.*, m.name AS actor_name
        FROM audit_log a LEFT JOIN members m ON m.id = a.actor_id
        ORDER BY a.id DESC LIMIT 300
        """
    )
    return render_template("admin_audit.html", entries=entries, labels=ACTION_LABELS)


@bp.route("/settings", methods=["POST"])
@admin_required
def settings():
    club_name = request.form.get("club_name", "").strip() or "Bokklubben"
    services.set_setting("club_name", club_name)
    audit(auth.current_member()["id"], "settings", f"club_name='{club_name}'")
    flash("Inställningar sparade.", "success")
    return redirect(url_for("admin.panel"))


@bp.route("/backup", methods=["POST"])
@admin_required
def backup_now():
    path = backup_database(current_app.config["DATABASE_PATH"], current_app.config["DATA_DIR"] / "backups")
    audit(auth.current_member()["id"], "backup", path.name)
    flash(f"Backup skapad: {path.name}", "success")
    return redirect(url_for("admin.panel"))


@bp.route("/backup/download")
@admin_required
def backup_download():
    path = backup_database(current_app.config["DATABASE_PATH"], current_app.config["DATA_DIR"] / "backups")
    return send_file(path, as_attachment=True, download_name="bokklubben-backup.db")


@bp.route("/members", methods=["POST"])
@admin_required
def add_member():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    is_admin = request.form.get("is_admin") == "1"
    in_pool = request.form.get("in_wheel_pool") == "1"
    if not name or not email:
        flash("Namn och e-post krävs.", "error")
        return redirect(url_for("admin.panel"))
    if one("SELECT id FROM members WHERE lower(email) = lower(?)", (email,)):
        flash("E-postadressen används redan.", "error")
        return redirect(url_for("admin.panel"))
    execute(
        "INSERT INTO members(name, email, is_admin, voting_active, in_wheel_pool) VALUES (?, ?, ?, 1, ?)",
        (name, email, 1 if is_admin else 0, 1 if in_pool else 0),
    )
    audit(auth.current_member()["id"], "member_add", f"{name} <{email}> (admin={is_admin}, hjulpool={in_pool})")
    flash(f"Medlemmen {name} är tillagd.", "success")
    return redirect(url_for("admin.panel"))


@bp.route("/members/<int:mid>", methods=["GET", "POST"])
@admin_required
def edit_member(mid):
    member = one("SELECT * FROM members WHERE id = ?", (mid,))
    if member is None:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        if not name or not email:
            flash("Namn och e-post krävs.", "error")
            return render_template("admin_member.html", member=member)
        execute(
            """
            UPDATE members SET name = ?, email = ?, is_admin = ?, voting_active = ?, in_wheel_pool = ?, wheel_suspended = ?
            WHERE id = ?
            """,
            (
                name,
                email,
                1 if request.form.get("is_admin") == "1" else 0,
                1 if request.form.get("voting_active") == "1" else 0,
                1 if request.form.get("in_wheel_pool") == "1" else 0,
                1 if request.form.get("wheel_suspended") == "1" else 0,
                mid,
            ),
        )
        audit(
            auth.current_member()["id"],
            "member_edit",
            f"{name} <{email}>: admin={request.form.get('is_admin') == '1'}, rösträtt={request.form.get('voting_active') == '1'}, hjulpool={request.form.get('in_wheel_pool') == '1'}, hjulavstängd={request.form.get('wheel_suspended') == '1'}",
        )
        flash("Medlem uppdaterad.", "success")
        return redirect(url_for("admin.panel"))
    return render_template("admin_member.html", member=member)


@bp.route("/members/<int:mid>/delete", methods=["POST"])
@admin_required
def delete_member(mid):
    member = one("SELECT * FROM members WHERE id = ?", (mid,))
    if member is None:
        abort(404)
    execute("DELETE FROM members WHERE id = ?", (mid,))
    services.ensure_round()
    audit(auth.current_member()["id"], "member_delete", f"{member['name']} <{member['email']}>")
    flash(f"Medlemmen {member['name']} är borttagen.", "success")
    return redirect(url_for("admin.panel"))


@bp.route("/wheel/reset", methods=["POST"])
@admin_required
def wheel_reset():
    services.reset_wheel_pool()
    audit(auth.current_member()["id"], "wheel_reset", "Manuell återställning av hjulpoolen")
    flash("Hjulpoolen är återställd – alla medlemmar är kandidater igen.", "success")
    return redirect(url_for("admin.panel"))


@bp.route("/rounds/<int:rid>")
@admin_required
def round_detail(rid):
    r = one("SELECT * FROM rounds WHERE id = ?", (rid,))
    if r is None:
        abort(404)
    chooser = one("SELECT * FROM members WHERE id = ?", (r["chooser_id"],)) if r["chooser_id"] else None
    candidates = query("SELECT * FROM book_candidates WHERE round_id = ? ORDER BY id", (rid,))
    votes = query(
        "SELECT v.*, m.name AS member_name FROM votes v JOIN members m ON m.id = v.member_id WHERE v.round_id = ? ORDER BY v.id",
        (rid,),
    )
    read_marks = query(
        "SELECT rm.*, m.name AS member_name FROM read_marks rm JOIN members m ON m.id = rm.member_id WHERE rm.round_id = ? ORDER BY rm.id",
        (rid,),
    )
    members = query("SELECT * FROM members ORDER BY lower(name), id")
    tally = services.tally(rid)
    return render_template(
        "admin_round.html",
        round=r,
        chooser=chooser,
        candidates=candidates,
        votes=votes,
        read_marks=read_marks,
        members=members,
        tally=tally,
        states=services.STATES,
    )


@bp.route("/rounds/<int:rid>/state", methods=["POST"])
@admin_required
def round_state(rid):
    state = request.form.get("state", "")
    if state not in services.STATES:
        abort(400)
    old = one("SELECT state FROM rounds WHERE id = ?", (rid,))
    if state == "done":
        services.close_round(rid)
    else:
        execute("UPDATE rounds SET state = ?, updated_at = datetime('now') WHERE id = ?", (state, rid))
    audit(auth.current_member()["id"], "round_state", f"Omgång #{rid}: {old['state'] if old else '?'} -> {state}")
    flash("Omgångens status ändrad.", "success")
    return redirect(url_for("admin.round_detail", rid=rid))


@bp.route("/rounds/<int:rid>/chooser", methods=["POST"])
@admin_required
def round_chooser(rid):
    chooser_id = request.form.get("chooser_id", type=int)
    if chooser_id and one("SELECT id FROM members WHERE id = ?", (chooser_id,)) is None:
        abort(400)
    execute("UPDATE rounds SET chooser_id = ?, updated_at = datetime('now') WHERE id = ?", (chooser_id, rid))
    if chooser_id:
        execute("UPDATE members SET in_wheel_pool = 0 WHERE id = ?", (chooser_id,))
    name = one("SELECT name FROM members WHERE id = ?", (chooser_id,))["name"] if chooser_id else "ingen"
    audit(auth.current_member()["id"], "round_chooser", f"Omgång #{rid}: bokväljare -> {name}")
    flash("Bokväljare ändrad.", "success")
    return redirect(url_for("admin.round_detail", rid=rid))


@bp.route("/rounds/<int:rid>/meeting", methods=["POST"])
@admin_required
def round_meeting(rid):
    date = request.form.get("date", "").strip() or None
    execute("UPDATE rounds SET meeting_date = ?, updated_at = datetime('now') WHERE id = ?", (date, rid))
    audit(auth.current_member()["id"], "round_meeting", f"Omgång #{rid}: mötesdatum -> {date or 'borttaget'}")
    flash("Mötesdatum ändrat.", "success")
    return redirect(url_for("admin.round_detail", rid=rid))


@bp.route("/rounds/<int:rid>/winner", methods=["POST"])
@admin_required
def round_winner(rid):
    winner_id = request.form.get("winner_candidate_id", type=int)
    if winner_id and one("SELECT id FROM book_candidates WHERE id = ? AND round_id = ?", (winner_id, rid)) is None:
        abort(400)
    execute(
        "UPDATE rounds SET winner_candidate_id = ?, state = CASE WHEN ? IS NOT NULL THEN 'decided' ELSE state END, updated_at = datetime('now') WHERE id = ?",
        (winner_id, winner_id, rid),
    )
    title = one("SELECT title FROM book_candidates WHERE id = ?", (winner_id,))["title"] if winner_id else "ingen"
    audit(auth.current_member()["id"], "round_winner", f"Omgång #{rid}: vinnare -> {title}")
    flash("Vinnare ändrad.", "success")
    return redirect(url_for("admin.round_detail", rid=rid))


@bp.route("/rounds/<int:rid>/delete", methods=["POST"])
@admin_required
def round_delete(rid):
    execute("DELETE FROM rounds WHERE id = ?", (rid,))
    services.ensure_round()
    audit(auth.current_member()["id"], "round_delete", f"Omgång #{rid} borttagen")
    flash("Omgången är borttagen.", "success")
    return redirect(url_for("admin.panel"))


@bp.route("/rounds/<int:rid>/candidates", methods=["POST"])
@admin_required
def round_add_candidate(rid):
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    description = request.form.get("description", "").strip()
    if not title:
        flash("Titeln får inte vara tom.", "error")
        return redirect(url_for("admin.round_detail", rid=rid))
    execute(
        "INSERT INTO book_candidates(round_id, title, author, description) VALUES (?, ?, ?, ?)",
        (rid, title, author, description),
    )
    audit(auth.current_member()["id"], "candidate_add", f"Omgång #{rid}: '{title}'")
    flash("Kandidat tillagd.", "success")
    return redirect(url_for("admin.round_detail", rid=rid))


@bp.route("/candidates/<int:cid>", methods=["POST"])
@admin_required
def candidate_edit(cid):
    cand = one("SELECT * FROM book_candidates WHERE id = ?", (cid,))
    if cand is None:
        abort(404)
    title = request.form.get("title", "").strip()
    if not title:
        flash("Titeln får inte vara tom.", "error")
        return redirect(url_for("admin.round_detail", rid=cand["round_id"]))
    execute(
        "UPDATE book_candidates SET title = ?, author = ?, description = ? WHERE id = ?",
        (title, request.form.get("author", "").strip(), request.form.get("description", "").strip(), cid),
    )
    audit(auth.current_member()["id"], "candidate_edit", f"Omgång #{cand['round_id']}: kandidat #{cid} -> '{title}'")
    flash("Kandidat uppdaterad.", "success")
    return redirect(url_for("admin.round_detail", rid=cand["round_id"]))


@bp.route("/candidates/<int:cid>/delete", methods=["POST"])
@admin_required
def candidate_delete(cid):
    cand = one("SELECT * FROM book_candidates WHERE id = ?", (cid,))
    if cand is None:
        abort(404)
    execute("DELETE FROM book_candidates WHERE id = ?", (cid,))
    audit(auth.current_member()["id"], "candidate_delete", f"Omgång #{cand['round_id']}: kandidat '{cand['title']}' borttagen")
    flash("Kandidat borttagen.", "success")
    return redirect(url_for("admin.round_detail", rid=cand["round_id"]))


@bp.route("/rounds/<int:rid>/votes", methods=["POST"])
@admin_required
def vote_add(rid):
    member_id = request.form.get("member_id", type=int)
    candidate_id = request.form.get("candidate_id", type=int)
    weight = request.form.get("weight", type=float)
    if member_id is None or candidate_id is None or weight is None:
        flash("Medlem, kandidat och vikt krävs.", "error")
        return redirect(url_for("admin.round_detail", rid=rid))
    execute(
        """
        INSERT INTO votes(round_id, candidate_id, member_id, weight) VALUES (?, ?, ?, ?)
        ON CONFLICT(round_id, member_id) DO UPDATE SET candidate_id = excluded.candidate_id, weight = excluded.weight
        """,
        (rid, candidate_id, member_id, weight),
    )
    services.maybe_decide(rid)
    mname = one("SELECT name FROM members WHERE id = ?", (member_id,))["name"]
    audit(auth.current_member()["id"], "vote_add", f"Omgång #{rid}: {mname} vikt {weight}")
    flash("Röst sparad.", "success")
    return redirect(url_for("admin.round_detail", rid=rid))


@bp.route("/votes/<int:vid>", methods=["POST"])
@admin_required
def vote_edit(vid):
    vote = one("SELECT * FROM votes WHERE id = ?", (vid,))
    if vote is None:
        abort(404)
    candidate_id = request.form.get("candidate_id", type=int)
    weight = request.form.get("weight", type=float)
    execute("UPDATE votes SET candidate_id = ?, weight = ? WHERE id = ?", (candidate_id, weight, vid))
    services.maybe_decide(vote["round_id"])
    audit(auth.current_member()["id"], "vote_edit", f"Omgång #{vote['round_id']}: röst #{vid} -> kandidat {candidate_id}, vikt {weight}")
    flash("Röst uppdaterad.", "success")
    return redirect(url_for("admin.round_detail", rid=vote["round_id"]))


@bp.route("/votes/<int:vid>/delete", methods=["POST"])
@admin_required
def vote_delete(vid):
    vote = one("SELECT * FROM votes WHERE id = ?", (vid,))
    if vote is None:
        abort(404)
    execute("DELETE FROM votes WHERE id = ?", (vid,))
    audit(auth.current_member()["id"], "vote_delete", f"Omgång #{vote['round_id']}: röst #{vid} borttagen")
    flash("Röst borttagen.", "success")
    return redirect(url_for("admin.round_detail", rid=vote["round_id"]))


@bp.route("/rounds/<int:rid>/readmarks", methods=["POST"])
@admin_required
def readmark_set(rid):
    member_id = request.form.get("member_id", type=int)
    has_read = 1 if request.form.get("has_read") == "1" else 0
    if member_id is None:
        abort(400)
    execute(
        """
        INSERT INTO read_marks(round_id, member_id, has_read) VALUES (?, ?, ?)
        ON CONFLICT(round_id, member_id) DO UPDATE SET has_read = excluded.has_read, marked_at = datetime('now')
        """,
        (rid, member_id, has_read),
    )
    execute("UPDATE members SET voting_active = ? WHERE id = ?", (has_read, member_id))
    services.update_wheel_suspension(member_id, actor_id=auth.current_member()["id"])
    audit(auth.current_member()["id"], "readmark_set", f"Omgång #{rid}: medlem {member_id} -> {'läst' if has_read else 'inte läst'}")
    flash("Läsmarkering sparad.", "success")
    return redirect(url_for("admin.round_detail", rid=rid))


@bp.route("/readmarks/<int:rmid>/delete", methods=["POST"])
@admin_required
def readmark_delete(rmid):
    rm = one("SELECT * FROM read_marks WHERE id = ?", (rmid,))
    if rm is None:
        abort(404)
    execute("DELETE FROM read_marks WHERE id = ?", (rmid,))
    services.update_wheel_suspension(rm["member_id"], actor_id=auth.current_member()["id"])
    audit(auth.current_member()["id"], "readmark_delete", f"Omgång #{rm['round_id']}: läsmarkering #{rmid} borttagen")
    flash("Läsmarkering borttagen.", "success")
    return redirect(url_for("admin.round_detail", rid=rm["round_id"]))
