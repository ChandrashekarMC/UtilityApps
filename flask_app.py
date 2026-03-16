from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urljoin, urlparse
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile
from zoneinfo import ZoneInfo

from authlib.integrations.flask_client import OAuth
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from database import get_connection, init_db
from task_service import (
    add_category,
    delete_task_permanently,
    delete_category,
    get_categories,
    get_custom_categories,
    get_default_categories,
    get_next_child_task_id,
    get_next_main_task_id,
    get_recurring_rule,
    get_task_by_id,
    get_task_notes,
    get_task_reminders,
    get_tasks,
    save_task,
    set_task_status,
    toggle_star,
    validate_task_hierarchy,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-change-me")
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=5)

    init_db()

    project_root = Path(__file__).resolve().parent
    data_root = Path(os.getenv("APP_DATA_DIR", str(project_root))).resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    db_path = data_root / "tasks.db"
    uploads_path = data_root / "uploads"
    auth_user = os.getenv("PERSONAL_SERVER_USER", "mcc")
    auth_password = os.getenv("PERSONAL_SERVER_PASSWORD", "mcc123")
    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    google_oauth_enabled = bool(google_client_id and google_client_secret)

    google_allowed_emails = {
        email.strip().lower()
        for email in os.getenv("PERSONAL_GOOGLE_ALLOWED_EMAILS", "").split(",")
        if email.strip()
    }

    oauth = OAuth(app)
    google = None
    if google_oauth_enabled:
        google = oauth.register(
            name="google",
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_id=google_client_id,
            client_secret=google_client_secret,
            client_kwargs={"scope": "openid email profile"},
        )

    def get_task_level(task_id):
        parts = (task_id or "").split(".")
        if len(parts) != 3:
            return "main"
        if parts[1] == "0" and parts[2] == "0":
            return "main"
        if parts[1] != "0" and parts[2] == "0":
            return "sub"
        return "unit"

    def parse_task_id_tuple(task_id):
        parts = (task_id or "").split(".")
        if len(parts) != 3:
            return None
        try:
            return int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            return None

    def parse_date(value):
        if not value:
            return date.today()
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except ValueError:
            return date.today()

    def session_dict(key: str) -> dict:
        value = session.get(key)
        return value if isinstance(value, dict) else {}

    def session_list(key: str) -> list:
        value = session.get(key)
        return value if isinstance(value, list) else []

    def session_bool(key: str, default: bool = False) -> bool:
        value = session.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return default

    def list_of_dicts(value: list) -> list[dict]:
        return [item for item in value if isinstance(item, dict)]

    def safe_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def add_backup_content(zip_file: ZipFile) -> None:
        if db_path.exists() and db_path.is_file():
            zip_file.write(db_path, arcname="tasks.db")

        if uploads_path.exists() and uploads_path.is_dir():
            for file_path in uploads_path.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(project_root)
                    zip_file.write(file_path, arcname=str(arcname))

    def is_safe_zip_member(name: str) -> bool:
        normalized = name.replace("\\", "/")
        if not normalized or normalized.startswith("/") or normalized.startswith("../"):
            return False
        if "/../" in normalized:
            return False
        return normalized == "tasks.db" or normalized.startswith("uploads/")

    def restore_from_backup(file_storage) -> tuple[bool, str]:
        if not file_storage or not file_storage.filename:
            return False, "Please choose a backup zip file"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            backup_zip_path = temp_dir_path / "backup.zip"
            file_storage.save(backup_zip_path)

            try:
                with ZipFile(backup_zip_path, "r") as zip_file:
                    members = [m for m in zip_file.namelist() if is_safe_zip_member(m)]
                    if not members:
                        return False, "Backup file does not contain restore data"
                    if "tasks.db" not in members:
                        return False, "Backup must include tasks.db"

                    extract_root = temp_dir_path / "extract"
                    extract_root.mkdir(parents=True, exist_ok=True)
                    for member in members:
                        target_path = extract_root / member
                        if member.endswith("/"):
                            target_path.mkdir(parents=True, exist_ok=True)
                            continue
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        with zip_file.open(member) as source, open(
                            target_path, "wb"
                        ) as target:
                            shutil.copyfileobj(source, target)
            except BadZipFile:
                return False, "Invalid backup zip file"

            extracted_db = temp_dir_path / "extract" / "tasks.db"
            if not extracted_db.exists():
                return False, "Backup must include tasks.db"

            db_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(extracted_db, db_path)

            extracted_uploads = temp_dir_path / "extract" / "uploads"
            if uploads_path.exists() and uploads_path.is_dir():
                shutil.rmtree(uploads_path)
            uploads_path.mkdir(parents=True, exist_ok=True)
            if extracted_uploads.exists() and extracted_uploads.is_dir():
                for item in extracted_uploads.iterdir():
                    destination = uploads_path / item.name
                    if item.is_dir():
                        shutil.copytree(item, destination)
                    else:
                        shutil.copy2(item, destination)

        session.clear()
        init_db()
        return True, "Backup restored successfully"

    def get_last_backup_created() -> str | None:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM app_meta WHERE key = ?", ("last_backup_created",)
        )
        row = cur.fetchone()
        conn.close()
        raw_value = row["value"] if row and row["value"] else None
        return format_backup_timestamp_ist(raw_value)

    def format_backup_timestamp_ist(raw_value: str | None) -> str | None:
        if not raw_value:
            return None

        parsed: datetime | None = None
        try:
            parsed = datetime.fromisoformat(raw_value)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d_%H%M%S"):
                try:
                    parsed = datetime.strptime(raw_value, fmt)
                    break
                except ValueError:
                    continue

        if not parsed:
            return raw_value

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        ist_time = parsed.astimezone(ZoneInfo("Asia/Kolkata"))
        return ist_time.strftime("%d %b %Y, %I:%M:%S %p IST")

    def set_last_backup_created(timestamp: str) -> None:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO app_meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            ("last_backup_created", timestamp),
        )
        conn.commit()
        conn.close()

    def is_safe_next_url(target: str | None) -> bool:
        if not target:
            return False
        host_url = request.host_url
        ref = urlparse(host_url)
        test = urlparse(urljoin(host_url, target))
        return test.scheme in {"http", "https"} and ref.netloc == test.netloc

    def get_portal_apps() -> list[dict]:
        finance_url = os.getenv("PERSONAL_FINANCE_URL", "").strip()
        notes_url = os.getenv("PERSONAL_NOTES_URL", "").strip()
        return [
            {
                "name": "Task Manager",
                "description": "Plan and track tasks, reminders, notes, and categories.",
                "url": url_for("task_manager_entry"),
                "status": "Available",
            },
            {
                "name": "Personal Finance",
                "description": "Track income, expenses, and budgets.",
                "url": finance_url or None,
                "status": "Available" if finance_url else "Coming soon",
            },
            {
                "name": "Personal Notes",
                "description": "Store and organize personal notes.",
                "url": notes_url or None,
                "status": "Available" if notes_url else "Coming soon",
            },
        ]

    def get_mcc_dynamic_password() -> str:
        day_token = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%a")
        return f"rak{day_token}esh"

    @app.before_request
    def require_login():
        endpoint = request.endpoint or ""
        if endpoint == "static" or endpoint in {
            "login_page",
            "google_login",
            "google_auth_callback",
            "google_login_health",
        }:
            return None
        is_authenticated = session.get("is_authenticated")
        if is_authenticated:
            return None
        session.clear()
        return redirect(url_for("login_page", next=request.path))

    @app.route("/auth/google/login")
    def google_login():
        if not google_oauth_enabled or google is None:
            flash("Google login is not configured", "error")
            return redirect(url_for("login_page"))

        next_url = request.args.get("next", "")
        session["post_login_next"] = next_url if is_safe_next_url(next_url) else ""
        redirect_uri = url_for("google_auth_callback", _external=True)
        return google.authorize_redirect(redirect_uri)

    @app.route("/auth/google/callback")
    def google_auth_callback():
        if not google_oauth_enabled or google is None:
            flash("Google login is not configured", "error")
            return redirect(url_for("login_page"))

        try:
            token = google.authorize_access_token()
            user_info = token.get("userinfo") if isinstance(token, dict) else None
            if not user_info:
                user_info = google.get("userinfo").json()
        except Exception:
            flash("Google sign-in failed. Please try again.", "error")
            return redirect(url_for("login_page"))

        email = (user_info.get("email") or "").strip().lower()
        email_verified = bool(user_info.get("email_verified"))
        if not email or not email_verified:
            flash("Google account email is not verified.", "error")
            return redirect(url_for("login_page"))

        if google_allowed_emails and email not in google_allowed_emails:
            flash("This Google account is not allowed.", "error")
            return redirect(url_for("login_page"))

        session.clear()
        session.permanent = True
        session["is_authenticated"] = True
        session["user_name"] = email
        session["auth_provider"] = "google"

        next_url = session.pop("post_login_next", "")
        if is_safe_next_url(next_url):
            return redirect(next_url)
        return redirect(url_for("dashboard_page"))

    @app.route("/health/google-login")
    def google_login_health():
        is_configured = bool(google_oauth_enabled and google is not None)
        # Keep this endpoint secret-safe: expose only booleans and callback URL.
        return {
            "ok": is_configured,
            "google_oauth_configured": is_configured,
            "has_google_client_id": bool(google_client_id),
            "has_google_client_secret": bool(google_client_secret),
            "has_allowed_email_list": bool(google_allowed_emails),
            "expected_callback_path": url_for("google_auth_callback"),
        }, (200 if is_configured else 503)

    @app.route("/login", methods=["GET", "POST"])
    def login_page():
        if session.get("is_authenticated"):
            return redirect(url_for("dashboard_page"))

        next_url = request.args.get("next", "")
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""

            is_valid_login = False
            if username == "mcc":
                is_valid_login = password == get_mcc_dynamic_password()
            elif username == auth_user and password == auth_password:
                is_valid_login = True

            if is_valid_login:
                session.clear()
                session.permanent = True
                session["is_authenticated"] = True
                session["user_name"] = username

                post_login_next = request.form.get("next")
                if is_safe_next_url(post_login_next):
                    return redirect(post_login_next)
                return redirect(url_for("dashboard_page"))

            flash("Invalid username or password", "error")

        return render_template(
            "login.html",
            page_title="Sign In",
            next_url=next_url if is_safe_next_url(next_url) else "",
            google_oauth_enabled=google_oauth_enabled,
        )

    @app.route("/logout", methods=["POST"])
    def logout_page():
        session.clear()
        flash("Signed out successfully", "success")
        return redirect(url_for("login_page"))

    @app.route("/")
    def home():
        return redirect(url_for("dashboard_page"))

    @app.route("/dashboard")
    def dashboard_page():
        return render_template(
            "dashboard.html",
            page_title="My Apps",
            apps=get_portal_apps(),
            show_sidebar=False,
        )

    @app.route("/task-manager")
    def task_manager_entry():
        return redirect(url_for("create_task_page"))

    @app.route("/tasks/new", methods=["GET", "POST"])
    def create_task_page():
        edit_task_id = session.get("edit_task_id")
        subtask_parent_id = session.get("subtask_parent_id")

        edit_task = get_task_by_id(edit_task_id) if edit_task_id else None
        subtask_parent_task = (
            get_task_by_id(subtask_parent_id) if subtask_parent_id else None
        )

        if edit_task:
            auto_task_id = edit_task["task_id"]
        elif subtask_parent_task:
            auto_task_id = get_next_child_task_id(subtask_parent_task["task_id"])
        else:
            auto_task_id = get_next_main_task_id()

        if subtask_parent_task and auto_task_id is None:
            flash("Cannot create child task under a Unit-Task", "error")
            session.pop("subtask_parent_id", None)
            return redirect(url_for("tasks_list_page"))

        current_task_level = get_task_level(auto_task_id)
        is_sub_or_unit = current_task_level in ["sub", "unit"]

        existing_recurring = get_recurring_rule(edit_task_id) if edit_task_id else None
        existing_reminders = get_task_reminders(edit_task_id) if edit_task_id else []
        existing_notes = get_task_notes(edit_task_id) if edit_task_id else []

        current_form_key = (
            f"edit:{edit_task_id}"
            if edit_task_id
            else (f"child:{subtask_parent_id}" if subtask_parent_id else "new-main")
        )
        if session.get("config_form_key") != current_form_key:
            session["config_form_key"] = current_form_key
            session["recurring_enabled"] = bool(existing_recurring)
            session["recurring_rule_draft"] = (
                dict(existing_recurring) if existing_recurring else None
            )
            session["reminder_enabled"] = bool(existing_reminders)
            session["reminders_draft"] = [
                {
                    "reminder_offset_minutes": int(r["reminder_offset_minutes"] or 0),
                    "sound": r["sound"],
                    "volume": int(r["volume"] or 50),
                    "snooze": bool(r["snooze"]),
                }
                for r in existing_reminders
            ]

        categories = get_categories()
        inherited_category = (
            edit_task["category"]
            if edit_task
            else (
                subtask_parent_task["category"]
                if subtask_parent_task
                else categories[0]
            )
        )
        inherited_priority = (
            edit_task["priority"]
            if edit_task
            else (subtask_parent_task["priority"] if subtask_parent_task else "Low")
        )
        inherited_urgency = (
            edit_task["urgency"]
            if edit_task
            else (subtask_parent_task["urgency"] if subtask_parent_task else "Low")
        )
        inherited_starred = (
            bool(edit_task["starred"])
            if edit_task
            else (
                bool(subtask_parent_task["starred"]) if subtask_parent_task else False
            )
        )
        due_date_value = (
            str(edit_task["due_date"])
            if edit_task and edit_task["due_date"]
            else (
                str(subtask_parent_task["due_date"])
                if subtask_parent_task and subtask_parent_task["due_date"]
                else date.today().isoformat()
            )
        )

        if request.method == "POST":
            action = request.form.get("action", "save")
            recurring_enabled = request.form.get("recurring_enabled") == "on"
            reminder_enabled = request.form.get("reminder_enabled") == "on"
            session["recurring_enabled"] = recurring_enabled
            session["reminder_enabled"] = reminder_enabled

            if action == "configure_recurring":
                return redirect(url_for("recurring_config_page"))
            if action == "configure_reminder":
                return redirect(url_for("reminder_config_page"))

            name = (request.form.get("name") or "").strip()
            if not name:
                flash("Task name is required", "error")
                return redirect(url_for("create_task_page"))

            due_date = parse_date(request.form.get("due_date"))
            progress = int(request.form.get("progress", 0))
            notes = request.form.get("notes", "")

            if is_sub_or_unit:
                category = inherited_category
                priority = inherited_priority
                urgency = inherited_urgency
                starred = inherited_starred
                attachment = None
            else:
                category = request.form.get("category", inherited_category)
                priority = request.form.get("priority", inherited_priority)
                urgency = request.form.get("urgency", inherited_urgency)
                starred = request.form.get("starred") == "on"
                attachment = request.files.get("attachment")

            hierarchy_ok, hierarchy_message = validate_task_hierarchy(auto_task_id)
            if not hierarchy_ok:
                flash(hierarchy_message, "error")
                return redirect(url_for("create_task_page"))

            recurring_rule = (
                session_dict("recurring_rule_draft") if recurring_enabled else None
            )
            reminders = (
                list_of_dicts(session_list("reminders_draft"))
                if reminder_enabled
                else []
            )

            if recurring_enabled and not recurring_rule:
                flash(
                    "Recurring Task is enabled. Please configure recurring details.",
                    "error",
                )
                return redirect(url_for("create_task_page"))
            if reminder_enabled and not reminders:
                flash("Set Reminder is enabled. Please configure reminders.", "error")
                return redirect(url_for("create_task_page"))

            save_task(
                name,
                auto_task_id,
                category,
                due_date,
                priority,
                urgency,
                progress,
                notes,
                attachment,
                starred,
                recurring_rule,
                reminders,
            )

            flash("Task saved successfully", "success")
            session.pop("edit_task_id", None)
            session.pop("subtask_parent_id", None)
            return redirect(url_for("tasks_list_page", status="active"))

        mode_label = "Create Main-Task"
        if edit_task:
            mode_label = f"Edit {current_task_level.title()}-Task"
        elif subtask_parent_task:
            child_type = "Sub-Task" if current_task_level == "sub" else "Unit-Task"
            mode_label = f"Create {child_type} under {subtask_parent_task['task_id']}"

        recurring_rule_draft = session_dict("recurring_rule_draft")
        reminders_draft = list_of_dicts(session_list("reminders_draft"))

        return render_template(
            "create_edit.html",
            page_title="Create / Edit Task",
            categories=categories,
            mode_label=mode_label,
            task_id=auto_task_id,
            is_sub_or_unit=is_sub_or_unit,
            existing_notes=existing_notes,
            edit_task=edit_task,
            inherited_category=inherited_category,
            inherited_priority=inherited_priority,
            inherited_urgency=inherited_urgency,
            inherited_starred=inherited_starred,
            due_date_value=due_date_value,
            recurring_enabled=session_bool("recurring_enabled", False),
            reminder_enabled=session_bool("reminder_enabled", False),
            recurring_rule=recurring_rule_draft,
            reminders=reminders_draft,
        )

    @app.route("/tasks/list")
    def tasks_list_page():
        status = request.args.get("status", "active")
        if status not in {"active", "completed", "archived"}:
            status = "active"

        category_filter = request.args.get("category", "")
        priority_filter = request.args.get("priority", "")
        urgency_filter = request.args.get("urgency", "")
        starred_filter = request.args.get("starred", "all")
        sort_filter = request.args.get("sort", "creation")
        hierarchical = request.args.get("hierarchical", "0") == "1"

        filters = {
            "categories": [category_filter] if category_filter else [],
            "priorities": [priority_filter] if priority_filter else [],
            "urgencies": [urgency_filter] if urgency_filter else [],
            "starred": starred_filter,
        }

        tasks = get_tasks(status, filters=filters, sort_by=sort_filter)

        if hierarchical:
            tasks = sorted(
                tasks,
                key=lambda task: parse_task_id_tuple(task["task_id"])
                or (10**9, 10**9, 10**9),
            )

        tasks_view = []
        for task in tasks:
            level = get_task_level(task["task_id"])
            recurring = get_recurring_rule(task["task_id"])
            reminders = get_task_reminders(task["task_id"])
            notes = get_task_notes(task["task_id"])

            child_label = None
            parsed = parse_task_id_tuple(task["task_id"])
            if parsed and parsed[2] == 0:
                child_label = "Add Sub-Task" if parsed[1] == 0 else "Add Unit-Task"

            prefix = ""
            if hierarchical:
                if level == "sub":
                    prefix = "↳ "
                elif level == "unit":
                    prefix = "↳ ↳ "

            tasks_view.append(
                {
                    "task": task,
                    "level": level,
                    "is_sub_or_unit": level in ["sub", "unit"],
                    "recurring": recurring,
                    "reminders": reminders,
                    "latest_note": notes[-1]["note_text"] if notes else "",
                    "notes": notes,
                    "child_label": child_label,
                    "display_prefix": prefix,
                }
            )

        return render_template(
            "tasks_list.html",
            page_title="Tasks List",
            selected_status=status,
            tasks=tasks_view,
            statuses=["active", "completed", "archived"],
            categories=get_categories(),
            selected_category=category_filter,
            selected_priority=priority_filter,
            selected_urgency=urgency_filter,
            selected_starred=starred_filter,
            selected_sort=sort_filter,
            hierarchical=hierarchical,
        )

    @app.route("/tasks/<task_id>/complete", methods=["POST"])
    def task_complete(task_id):
        set_task_status(task_id, "completed")
        return redirect(url_for("tasks_list_page", status="active"))

    @app.route("/tasks/<task_id>/archive", methods=["POST"])
    def task_archive(task_id):
        set_task_status(task_id, "archived")
        return redirect(url_for("tasks_list_page", status="active"))

    @app.route("/tasks/<task_id>/delete", methods=["POST"])
    def task_delete(task_id):
        status = request.args.get("status", "active")
        task = get_task_by_id(task_id)
        if not task:
            flash("Task not found", "error")
            return redirect(url_for("tasks_list_page", status=status))

        if task["status"] != "archived":
            set_task_status(task_id, "archived")
            flash(
                "Archiving the task, only archived tasks can be deleted",
                "warning",
            )
            return redirect(url_for("tasks_list_page", status="archived"))

        delete_task_permanently(task_id)
        flash("Task deleted permanently", "success")
        return redirect(url_for("tasks_list_page", status="archived"))

    @app.route("/tasks/<task_id>/activate", methods=["POST"])
    def task_activate(task_id):
        set_task_status(task_id, "active")
        return redirect(
            url_for("tasks_list_page", status=request.args.get("status", "completed"))
        )

    @app.route("/tasks/<task_id>/star", methods=["POST"])
    def task_star(task_id):
        value = request.form.get("value") == "1"
        toggle_star(task_id, value)
        return redirect(
            url_for("tasks_list_page", status=request.args.get("status", "active"))
        )

    @app.route("/tasks/<task_id>/edit", methods=["POST"])
    def task_edit(task_id):
        session["edit_task_id"] = task_id
        session.pop("subtask_parent_id", None)
        return redirect(url_for("create_task_page"))

    @app.route("/tasks/<task_id>/add-child", methods=["POST"])
    def task_add_child(task_id):
        session["subtask_parent_id"] = task_id
        session.pop("edit_task_id", None)
        return redirect(url_for("create_task_page"))

    @app.route("/categories", methods=["GET", "POST"])
    def categories_page():
        if request.method == "POST":
            action = request.form.get("action", "")
            if action == "add":
                ok, message = add_category(request.form.get("new_category", ""))
                flash(message, "success" if ok else "error")
            elif action == "delete":
                ok, message = delete_category(request.form.get("delete_category", ""))
                flash(message, "success" if ok else "error")
            return redirect(url_for("categories_page"))

        default_categories = get_default_categories()
        custom_categories = get_custom_categories()
        return render_template(
            "categories.html",
            page_title="Categories",
            default_categories=default_categories,
            custom_categories=custom_categories,
        )

    @app.route("/calendar")
    def calendar_page():
        selected_date = request.args.get("date", date.today().isoformat())
        tasks = get_tasks(
            "active",
            filters={"due_from": selected_date, "due_to": selected_date},
            sort_by="due",
        )
        return render_template(
            "calendar.html",
            page_title="Calendar View",
            selected_date=selected_date,
            tasks=tasks,
        )

    @app.route("/backup-restore", methods=["GET", "POST"])
    def backup_restore_page():
        if request.method == "POST":
            action = request.form.get("action", "")
            if action == "restore":
                ok, message = restore_from_backup(request.files.get("backup_file"))
                flash(message, "success" if ok else "error")
                return redirect(url_for("backup_restore_page"))

        return render_template(
            "backup_restore.html",
            page_title="Backup & Restore",
            last_backup_created=get_last_backup_created(),
        )

    @app.route("/backup-download")
    def backup_download():
        memory_file = BytesIO()
        with ZipFile(memory_file, "w", compression=ZIP_DEFLATED) as zip_file:
            add_backup_content(zip_file)

        memory_file.seek(0)
        now_utc = datetime.now(timezone.utc)
        timestamp = now_utc.strftime("%Y%m%d_%H%M%S")
        set_last_backup_created(now_utc.isoformat())
        return send_file(
            memory_file,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"personal_organizer_backup_{timestamp}.zip",
        )

    @app.route("/tasks/config/recurring", methods=["GET", "POST"])
    def recurring_config_page():
        if request.method == "POST":
            if request.form.get("action") == "disable":
                session["recurring_enabled"] = False
                session["recurring_rule_draft"] = None
                return redirect(url_for("create_task_page"))

            frequency_type = request.form.get("frequency_type", "Daily")
            weekdays = request.form.get("weekdays", "")
            if frequency_type == "Weekly" and not weekdays.strip():
                flash("Select at least one weekday for weekly recurrence", "error")
                return redirect(url_for("recurring_config_page"))

            session["recurring_enabled"] = True
            session["recurring_rule_draft"] = {
                "frequency_type": frequency_type,
                "interval_x": max(1, safe_int(request.form.get("interval_x", 1), 1)),
                "interval_y": max(0, safe_int(request.form.get("interval_y", 0), 0)),
                "weekdays": weekdays,
                "end_type": request.form.get("end_type", "forever"),
                "end_date": request.form.get("end_date") or None,
                "occurrence_count": safe_int(request.form.get("occurrence_count", 0), 0)
                or None,
            }
            return redirect(url_for("create_task_page"))

        return render_template(
            "recurring_config.html",
            page_title="Recurring Task Configuration",
            draft=session_dict("recurring_rule_draft"),
        )

    @app.route("/tasks/config/reminder", methods=["GET", "POST"])
    def reminder_config_page():
        if request.method == "POST":
            if request.form.get("action") == "disable":
                session["reminder_enabled"] = False
                session["reminders_draft"] = []
                return redirect(url_for("create_task_page"))

            count = min(3, max(1, safe_int(request.form.get("reminder_count", 1), 1)))
            reminders = []
            for idx in range(count):
                days = max(0, safe_int(request.form.get(f"days_{idx}", 0), 0))
                hours = max(0, safe_int(request.form.get(f"hours_{idx}", 0), 0))
                minutes = max(0, safe_int(request.form.get(f"minutes_{idx}", 0), 0))
                reminders.append(
                    {
                        "reminder_offset_minutes": days * 1440 + hours * 60 + minutes,
                        "sound": request.form.get(f"sound_{idx}", "Default"),
                        "volume": min(
                            100,
                            max(0, safe_int(request.form.get(f"volume_{idx}", 50), 50)),
                        ),
                        "snooze": request.form.get(f"snooze_{idx}") == "on",
                    }
                )

            session["reminder_enabled"] = True
            session["reminders_draft"] = reminders
            return redirect(url_for("create_task_page"))

        return render_template(
            "reminder_config.html",
            page_title="Reminder Configuration",
            reminders=list_of_dicts(session_list("reminders_draft")),
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
