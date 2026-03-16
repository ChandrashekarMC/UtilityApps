import os
from datetime import datetime

try:
    import streamlit as st
except ImportError:
    st = None
from database import get_connection


data_dir = os.getenv("APP_DATA_DIR", "").strip()
UPLOAD_FOLDER = os.getenv("APP_UPLOAD_DIR", "").strip() or (
    os.path.join(data_dir, "uploads") if data_dir else "uploads"
)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def display_tasks(status):
    if st is None:
        return

    rows = get_tasks(status)
    if not rows:
        st.info("No tasks found")
        return

    for row in rows:
        st.write(
            {
                "name": row["name"],
                "task_id": row["task_id"],
                "category": row["category"],
                "due_date": row["due_date"],
                "priority": row["priority"],
                "urgency": row["urgency"],
                "progress": row["progress"],
                "starred": bool(row["starred"]),
            }
        )


def get_categories():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM categories ORDER BY is_default DESC, name ASC")
    data = [row[0] for row in cur.fetchall()]
    conn.close()
    return data


def get_default_categories():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM categories WHERE is_default=1 ORDER BY name ASC")
    data = [row[0] for row in cur.fetchall()]
    conn.close()
    return data


def get_custom_categories():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM categories WHERE is_default=0 ORDER BY name ASC")
    data = [row[0] for row in cur.fetchall()]
    conn.close()
    return data


def add_category(name):
    clean_name = (name or "").strip()
    if not clean_name:
        return False, "Category name is required"

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO categories (name, is_default) VALUES (?, 0)",
            (clean_name,),
        )
        conn.commit()
    except Exception:
        conn.close()
        return False, "Category already exists"

    conn.close()
    return True, "Category added"


def delete_category(name):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT is_default FROM categories WHERE name=?", (name,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return False, "Category not found"

    if row["is_default"]:
        conn.close()
        return False, "Default categories cannot be deleted"

    cur.execute("DELETE FROM categories WHERE name=?", (name,))
    conn.commit()
    conn.close()
    return True, "Category deleted"


def get_tasks(status, filters=None, sort_by="created_at"):
    filters = filters or {}
    where_clauses = ["status = ?"]
    params = [status]

    if filters.get("categories"):
        placeholders = ",".join(["?"] * len(filters["categories"]))
        where_clauses.append(f"category IN ({placeholders})")
        params.extend(filters["categories"])

    if filters.get("priorities"):
        placeholders = ",".join(["?"] * len(filters["priorities"]))
        where_clauses.append(f"priority IN ({placeholders})")
        params.extend(filters["priorities"])

    if filters.get("urgencies"):
        placeholders = ",".join(["?"] * len(filters["urgencies"]))
        where_clauses.append(f"urgency IN ({placeholders})")
        params.extend(filters["urgencies"])

    if filters.get("starred") == "starred":
        where_clauses.append("starred = 1")
    elif filters.get("starred") == "not_starred":
        where_clauses.append("starred = 0")

    if filters.get("due_from"):
        where_clauses.append("date(due_date) >= date(?)")
        params.append(str(filters["due_from"]))
    if filters.get("due_to"):
        where_clauses.append("date(due_date) <= date(?)")
        params.append(str(filters["due_to"]))

    sort_map = {
        "creation": "created_at DESC",
        "due": "due_date ASC",
        "completed": "completed_at DESC",
        "archived": "archived_at DESC",
    }
    order_clause = sort_map.get(sort_by, "created_at DESC")

    query = f"""
        SELECT *
        FROM tasks
        WHERE {' AND '.join(where_clauses)}
        ORDER BY {order_clause}
    """

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    conn.close()
    return rows


def set_task_status(task_id, new_status):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    completed_at = now if new_status == "completed" else None
    archived_at = now if new_status == "archived" else None

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE tasks
        SET status = ?,
            completed_at = ?,
            archived_at = ?
        WHERE task_id = ?
        """,
        (new_status, completed_at, archived_at, task_id),
    )
    conn.commit()
    conn.close()


def toggle_star(task_id, value):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE tasks SET starred=? WHERE task_id=?",
        (1 if value else 0, task_id),
    )
    conn.commit()
    conn.close()


def get_task_by_id(task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_recurring_rule(task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM recurring_rules WHERE task_id=?", (task_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_task_reminders(task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM reminders WHERE task_id=? ORDER BY id ASC LIMIT 3",
        (task_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_task_notes(task_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT note_text, created_at
        FROM task_notes
        WHERE task_id=?
        ORDER BY created_at ASC, id ASC
        """,
        (task_id,),
    )
    rows = cur.fetchall()

    if not rows:
        cur.execute(
            "SELECT notes, created_at FROM tasks WHERE task_id=?",
            (task_id,),
        )
        fallback = cur.fetchone()
        if fallback and fallback["notes"]:
            rows = [
                {
                    "note_text": fallback["notes"],
                    "created_at": fallback["created_at"],
                }
            ]

    conn.close()
    return rows


def _parse_task_id(task_id):
    parts = (task_id or "").split(".")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def get_next_main_task_id():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT task_id FROM tasks")
    rows = cur.fetchall()
    conn.close()

    max_main = 0
    for row in rows:
        parsed = _parse_task_id(row["task_id"])
        if parsed is None:
            continue
        max_main = max(max_main, parsed[0])

    return f"{max_main + 1}.0.0"


def get_next_sub_task_id(parent_task_id):
    next_child = get_next_child_task_id(parent_task_id)
    return next_child


def get_next_child_task_id(parent_task_id):
    parent_parsed = _parse_task_id(parent_task_id)
    if parent_parsed is None:
        return None

    target_main, target_sub, target_unit = parent_parsed
    if target_unit > 0:
        return None

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT task_id FROM tasks")
    rows = cur.fetchall()
    conn.close()

    if target_sub == 0:
        max_sub = 0
        for row in rows:
            parsed = _parse_task_id(row["task_id"])
            if parsed is None:
                continue
            main_id, sub_id, unit_id = parsed
            if main_id == target_main and unit_id == 0:
                max_sub = max(max_sub, sub_id)
        return f"{target_main}.{max_sub + 1}.0"

    max_unit = 0
    for row in rows:
        parsed = _parse_task_id(row["task_id"])
        if parsed is None:
            continue
        main_id, sub_id, unit_id = parsed
        if main_id == target_main and sub_id == target_sub:
            max_unit = max(max_unit, unit_id)

    return f"{target_main}.{target_sub}.{max_unit + 1}"


def validate_task_hierarchy(task_id):
    parts = (task_id or "").split(".")
    if len(parts) != 3:
        return False, "Task ID must follow X.Y.Z hierarchy format"

    try:
        main_id, sub_id, unit_id = [int(p) for p in parts]
    except ValueError:
        return False, "Task ID must contain only numeric hierarchy levels"

    if sub_id == 0 and unit_id > 0:
        return False, "Invalid hierarchy: unit task requires a non-zero sub task id"

    conn = get_connection()
    cur = conn.cursor()

    if sub_id > 0 and unit_id == 0:
        parent_main = f"{main_id}.0.0"
        cur.execute("SELECT 1 FROM tasks WHERE task_id=?", (parent_main,))
        if not cur.fetchone():
            conn.close()
            return (
                False,
                f"Main task {parent_main} must exist before creating {task_id}",
            )

    if sub_id > 0 and unit_id > 0:
        parent_main = f"{main_id}.0.0"
        parent_sub = f"{main_id}.{sub_id}.0"
        cur.execute("SELECT 1 FROM tasks WHERE task_id=?", (parent_main,))
        has_main = cur.fetchone() is not None
        cur.execute("SELECT 1 FROM tasks WHERE task_id=?", (parent_sub,))
        has_sub = cur.fetchone() is not None
        conn.close()
        if not has_main:
            return (
                False,
                f"Main task {parent_main} must exist before creating {task_id}",
            )
        if not has_sub:
            return (
                False,
                f"Sub task {parent_sub} must exist before creating {task_id}",
            )
        return True, ""

    conn.close()
    return True, ""


def save_task(
    name,
    task_id,
    category,
    due_date,
    priority,
    urgency,
    progress,
    notes,
    attachment,
    starred=False,
    recurring_rule=None,
    reminders=None,
):

    new_note_text = (notes or "").strip()

    task_parts = (task_id or "").split(".")
    parent_task_id = None
    if len(task_parts) == 3:
        main_id, sub_id, unit_id = task_parts
        if sub_id != "0" and unit_id == "0":
            parent_task_id = f"{main_id}.0.0"
        elif sub_id != "0" and unit_id != "0":
            parent_task_id = f"{main_id}.{sub_id}.0"

    attachment_path = None

    if attachment:
        upload_name = getattr(attachment, "name", None) or getattr(
            attachment, "filename", None
        )
        if upload_name:
            attachment_path = os.path.join(UPLOAD_FOLDER, upload_name)
            with open(attachment_path, "wb") as f:
                f.write(attachment.read())

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT status, created_at, completed_at, archived_at, attachment_path, notes
        FROM tasks
        WHERE task_id=?
        """,
        (task_id,),
    )
    existing = cur.fetchone()
    existing_status = existing["status"] if existing else "active"
    existing_created_at = existing["created_at"] if existing else None
    existing_completed_at = existing["completed_at"] if existing else None
    existing_archived_at = existing["archived_at"] if existing else None
    existing_latest_note = existing["notes"] if existing else None
    if not attachment_path and existing and existing["attachment_path"]:
        attachment_path = existing["attachment_path"]

    latest_note_text = new_note_text if new_note_text else existing_latest_note

    cur.execute(
        """
        INSERT INTO tasks
        (name, task_id, category, due_date,
         priority, urgency, progress, parent_task_id,
         status, notes, attachment_path, starred,
         created_at, completed_at, archived_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                COALESCE(?, CURRENT_TIMESTAMP), ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            name=excluded.name,
            category=excluded.category,
            due_date=excluded.due_date,
            priority=excluded.priority,
            urgency=excluded.urgency,
            progress=excluded.progress,
            parent_task_id=excluded.parent_task_id,
            notes=excluded.notes,
            attachment_path=excluded.attachment_path,
            starred=excluded.starred
    """,
        (
            name,
            task_id,
            category,
            str(due_date),
            priority,
            urgency,
            progress,
            parent_task_id,
            existing_status,
            latest_note_text,
            attachment_path,
            1 if starred else 0,
            existing_created_at,
            existing_completed_at,
            existing_archived_at,
        ),
    )

    if new_note_text:
        cur.execute(
            "INSERT INTO task_notes (task_id, note_text) VALUES (?, ?)",
            (task_id, new_note_text),
        )

    cur.execute("DELETE FROM recurring_rules WHERE task_id=?", (task_id,))
    if recurring_rule:
        cur.execute(
            """
            INSERT INTO recurring_rules
            (task_id, frequency_type, interval_x, interval_y, weekdays,
             end_type, end_date, occurrence_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                recurring_rule.get("frequency_type"),
                recurring_rule.get("interval_x"),
                recurring_rule.get("interval_y"),
                recurring_rule.get("weekdays"),
                recurring_rule.get("end_type"),
                recurring_rule.get("end_date"),
                recurring_rule.get("occurrence_count"),
            ),
        )

    cur.execute("DELETE FROM reminders WHERE task_id=?", (task_id,))
    for reminder in reminders or []:
        cur.execute(
            """
            INSERT INTO reminders
            (task_id, reminder_offset_minutes, sound, volume, snooze)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                task_id,
                reminder.get("reminder_offset_minutes"),
                reminder.get("sound"),
                reminder.get("volume"),
                1 if reminder.get("snooze") else 0,
            ),
        )

    conn.commit()
    conn.close()


def delete_task_permanently(task_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT attachment_path FROM tasks WHERE task_id=?", (task_id,))
    row = cur.fetchone()
    attachment_path = row["attachment_path"] if row else None

    cur.execute("DELETE FROM reminders WHERE task_id=?", (task_id,))
    cur.execute("DELETE FROM recurring_rules WHERE task_id=?", (task_id,))
    cur.execute("DELETE FROM task_notes WHERE task_id=?", (task_id,))
    cur.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))

    conn.commit()
    conn.close()

    if attachment_path and os.path.exists(attachment_path):
        try:
            os.remove(attachment_path)
        except OSError:
            pass
