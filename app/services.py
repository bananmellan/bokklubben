import random

from .db import audit, execute, one, query

STATES = ["spin", "candidates", "voting", "decided", "meeting", "done"]

STATE_LABELS = {
    "spin": "Väntar på snurr",
    "candidates": "Bokval",
    "voting": "Omröstning",
    "decided": "Bok vald",
    "meeting": "Möte planerat",
    "done": "Avslutad",
}


def get_setting(key, default=None):
    row = one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key, value):
    execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def current_round():
    return one("SELECT * FROM rounds ORDER BY id DESC LIMIT 1")


def ensure_round():
    r = current_round()
    if r is None:
        execute("INSERT INTO rounds(state) VALUES ('spin')")
        r = current_round()
    return r


def wheel_candidates():
    return query(
        "SELECT * FROM members WHERE in_wheel_pool = 1 AND wheel_suspended = 0 ORDER BY lower(name), id"
    )


def update_wheel_suspension(member_id, actor_id=None):
    rows = query("SELECT id FROM rounds WHERE winner_candidate_id IS NOT NULL ORDER BY id DESC LIMIT 2")
    if len(rows) < 2:
        return
    missed = 0
    for row in rows:
        mark = one("SELECT has_read FROM read_marks WHERE round_id = ? AND member_id = ?", (row["id"], member_id))
        if mark is not None and not mark["has_read"]:
            missed += 1
    suspended = 1 if missed >= 2 else 0
    current = one("SELECT name, wheel_suspended FROM members WHERE id = ?", (member_id,))
    if current is None or current["wheel_suspended"] == suspended:
        return
    execute("UPDATE members SET wheel_suspended = ? WHERE id = ?", (suspended, member_id))
    audit(
        actor_id,
        "wheel_suspension",
        f"{current['name']} {'stängs av från hjulet' if suspended else 'får tillbaka sin plats i hjulet'} (ej läst de 2 senaste böckerna)"
        if suspended
        else f"{current['name']} får tillbaka sin plats i hjulet (har läst en bok igen)",
    )


def reset_wheel_pool():
    execute("UPDATE members SET in_wheel_pool = 1")


def spin(actor_id=None):
    r = ensure_round()
    if r["state"] != "spin":
        return None, "Hjulet kan bara snurras när ingen omgång pågår"
    pool = wheel_candidates()
    if not pool:
        reset_wheel_pool()
        audit(actor_id, "wheel_reset", "Hjulpoolen var tom – återställd till alla medlemmar automatiskt")
        pool = wheel_candidates()
    if not pool:
        return None, "Det finns inga medlemmar i hjulpoolen"
    winner = random.choice(pool)
    execute("UPDATE members SET in_wheel_pool = 0 WHERE id = ?", (winner["id"],))
    if not wheel_candidates():
        reset_wheel_pool()
        audit(actor_id, "wheel_reset", "Hjulpoolen tömdes – återställd till alla medlemmar automatiskt")
    audit(actor_id, "spin", f"Omgång #{r['id']}: {winner['name']} snurrades fram som bokväljare")
    execute(
        "UPDATE rounds SET chooser_id = ?, state = 'candidates', updated_at = datetime('now') WHERE id = ?",
        (winner["id"], r["id"]),
    )
    index = [m["id"] for m in pool].index(winner["id"])
    return {"member": winner, "index": index}, None


def vote_weight(member, round_row):
    if not member["voting_active"]:
        return 0.0
    return 1.5 if round_row["chooser_id"] == member["id"] else 1.0


def cast_vote(round_id, member, candidate_id):
    r = one("SELECT * FROM rounds WHERE id = ?", (round_id,))
    if r is None or r["state"] != "voting":
        return "Omröstningen är inte öppen"
    if not member["voting_active"]:
        return "Du har ingen rösträtt just nu (du har inte läst en bok i klubben)"
    candidate = one("SELECT * FROM book_candidates WHERE id = ? AND round_id = ?", (candidate_id, round_id))
    if candidate is None:
        return "Ogiltig kandidat"
    existing = one("SELECT * FROM votes WHERE round_id = ? AND member_id = ?", (round_id, member["id"]))
    weight = vote_weight(member, r)
    if existing:
        execute("UPDATE votes SET candidate_id = ?, weight = ? WHERE id = ?", (candidate_id, weight, existing["id"]))
    else:
        execute(
            "INSERT INTO votes(round_id, candidate_id, member_id, weight) VALUES (?, ?, ?, ?)",
            (round_id, candidate_id, member["id"], weight),
        )
    maybe_decide(round_id)
    return None


def tally(round_id):
    return query(
        """
        SELECT c.id AS candidate_id, c.title, c.author,
               COALESCE(SUM(v.weight), 0) AS total,
               COUNT(v.id) AS nvotes
        FROM book_candidates c
        LEFT JOIN votes v ON v.candidate_id = c.id AND v.round_id = c.round_id
        WHERE c.round_id = ?
        GROUP BY c.id
        ORDER BY total DESC, c.id
        """,
        (round_id,),
    )


def is_tie(round_id):
    rows = tally(round_id)
    if not rows:
        return False
    top = rows[0]["total"]
    return top > 0 and sum(1 for r in rows if r["total"] == top) > 1


def maybe_decide(round_id):
    r = one("SELECT * FROM rounds WHERE id = ?", (round_id,))
    if r is None or r["state"] != "voting":
        return
    voters = query("SELECT id FROM members WHERE voting_active = 1")
    if not voters:
        return
    voted = {v["member_id"] for v in query("SELECT member_id FROM votes WHERE round_id = ?", (round_id,))}
    if all(v["id"] in voted for v in voters):
        decide(round_id)


def decide(round_id):
    rows = tally(round_id)
    if not rows:
        return
    top = rows[0]["total"]
    winners = [r for r in rows if r["total"] == top]
    if len(winners) == 1 and top > 0:
        execute(
            "UPDATE rounds SET winner_candidate_id = ?, state = 'decided', updated_at = datetime('now') WHERE id = ?",
            (winners[0]["candidate_id"], round_id),
        )


def set_meeting_date(round_id, date_str):
    execute(
        "UPDATE rounds SET meeting_date = ?, state = CASE WHEN state = 'decided' THEN 'meeting' ELSE state END, updated_at = datetime('now') WHERE id = ?",
        (date_str, round_id),
    )


def mark_read(round_id, member_id, has_read, actor_id=None):
    has_read = 1 if has_read else 0
    execute(
        """
        INSERT INTO read_marks(round_id, member_id, has_read) VALUES (?, ?, ?)
        ON CONFLICT(round_id, member_id) DO UPDATE SET has_read = excluded.has_read, marked_at = datetime('now')
        """,
        (round_id, member_id, has_read),
    )
    execute("UPDATE members SET voting_active = ? WHERE id = ?", (has_read, member_id))
    update_wheel_suspension(member_id, actor_id=actor_id)
    audit(actor_id, "read_mark", f"Omgång #{round_id}: {'har läst' if has_read else 'har inte läst'} boken")
    members = query("SELECT id FROM members")
    marked = {m["member_id"] for m in query("SELECT member_id FROM read_marks WHERE round_id = ?", (round_id,))}
    if members and all(m["id"] in marked for m in members):
        close_round(round_id)


def close_round(round_id):
    r = one("SELECT * FROM rounds WHERE id = ?", (round_id,))
    if r is None or r["state"] == "done":
        return
    execute("UPDATE rounds SET state = 'done', updated_at = datetime('now') WHERE id = ?", (round_id,))
    if current_round()["id"] == round_id:
        execute("INSERT INTO rounds(state) VALUES ('spin')")
