from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
    send_from_directory,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import sqlite3
import os

# ====== إعداد التطبيق ======
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# ====== إعداد قاعدة البيانات ======
DB_PATH = "projects.db"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            file_path TEXT NOT NULL,
            image_url TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS liked_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_id INTEGER NOT NULL,
            UNIQUE(user_id, project_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(project_id) REFERENCES projects(id)
        )
    """
    )
    conn.commit()
    conn.close()


init_db()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("لازم تسجل الدخول أولاً.", "warning")
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)

    return decorated_function


@app.route("/")
@login_required
def home():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT projects.*, users.username,
        (SELECT COUNT(*) FROM liked_projects WHERE project_id=projects.id) as like_count,
        (SELECT 1 FROM liked_projects WHERE project_id=projects.id AND user_id=?) as liked
        FROM projects
        JOIN users ON projects.user_id = users.id
        ORDER BY like_count DESC, projects.timestamp DESC
    """,
        (session["user_id"],),
    )
    projects = c.fetchall()
    conn.close()
    return render_template("projects.html", projects=projects)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        email = request.form["email"].strip()
        if len(username) < 3 or len(password) < 6:
            flash("الاسم قصير جدًا أو كلمة السر قصيرة.", "danger")
            return redirect(url_for("register"))
        password_hash = generate_password_hash(password)
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute(
                "INSERT INTO users (username, password_hash, email) VALUES (?,?,?)",
                (username, password_hash, email),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            flash("اسم المستخدم موجود بالفعل.", "danger")
            return redirect(url_for("register"))
        finally:
            conn.close()
        flash("تم التسجيل! سجّل دخولك الآن.", "success")
        return redirect(url_for("login_page"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("تم تسجيل الدخول!", "success")
            return redirect(url_for("home"))
        else:
            flash("اسم المستخدم أو كلمة المرور غير صحيحة.", "danger")
            return redirect(url_for("login_page"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("تم تسجيل الخروج.", "info")
    return redirect(url_for("login_page"))


@app.route("/projects/new", methods=["GET", "POST"])
@login_required
def new_project():
    if request.method == "POST":
        name = request.form["name"].strip()
        description = request.form["description"].strip()
        image_url = request.form["image_url"].strip()
        file = request.files.get("file")
        if not (name and description and image_url and file):
            flash("يرجى تعبئة كل الحقول ورفع الملف.", "danger")
            return redirect(url_for("new_project"))
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO projects (user_id,name,description,file_path,image_url)
            VALUES (?,?,?,?,?)
        """,
            (session["user_id"], name, description, file_path, image_url),
        )
        conn.commit()
        conn.close()
        flash("تم رفع المشروع!", "success")
        return redirect(url_for("home"))
    return render_template("new_project.html")


@app.route("/comments", methods=["GET", "POST"])
@login_required
def comments():
    conn = get_db_connection()
    c = conn.cursor()
    if request.method == "POST":
        content = request.form["content"].strip()
        if content:
            c.execute(
                "INSERT INTO comments (user_id, content) VALUES (?,?)",
                (session["user_id"], content),
            )
            conn.commit()
            flash("تم نشر التعليق!", "success")
        else:
            flash("لا يمكن إرسال تعليق فارغ.", "danger")

    # استرجاع كل التعليقات
    c.execute(
        """
        SELECT comments.id, comments.content, comments.timestamp, users.username, users.id as user_id
        FROM comments
        JOIN users ON comments.user_id = users.id
        ORDER BY comments.timestamp DESC
    """
    )
    all_comments = c.fetchall()
    conn.close()
    return render_template("comments.html", comments=all_comments)


# ===== تعديل تعليق =====
@app.route("/edit_comment/<int:comment_id>", methods=["POST"])
@login_required
def edit_comment(comment_id):
    new_content = request.form.get("new_content", "").strip()
    if not new_content:
        flash("لا يمكن أن يكون التعليق فارغًا.", "danger")
        return redirect(url_for("comments"))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT user_id FROM comments WHERE id=?", (comment_id,))
    comment = c.fetchone()
    if not comment or comment["user_id"] != session["user_id"]:
        conn.close()
        flash("لا يمكنك تعديل هذا التعليق.", "danger")
        return redirect(url_for("comments"))

    c.execute("UPDATE comments SET content=? WHERE id=?", (new_content, comment_id))
    conn.commit()
    conn.close()
    flash("تم تعديل التعليق بنجاح!", "success")
    return redirect(url_for("comments"))


@app.route("/profile")
@login_required
def profile():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id=?", (session["user_id"],))
    user_info = c.fetchone()

    c.execute(
        """
        SELECT projects.*,
        (SELECT COUNT(*) FROM liked_projects WHERE project_id=projects.id) as like_count,
        (SELECT 1 FROM liked_projects WHERE project_id=projects.id AND user_id=?) as liked
        FROM projects
        WHERE user_id=?
        ORDER BY like_count DESC, timestamp DESC
    """,
        (session["user_id"], session["user_id"]),
    )
    user_projects = c.fetchall()

    c.execute(
        """
        SELECT projects.*, users.username,
        (SELECT COUNT(*) FROM liked_projects WHERE project_id=projects.id) as like_count,
        1 as liked
        FROM liked_projects
        JOIN projects ON liked_projects.project_id = projects.id
        JOIN users ON projects.user_id = users.id
        WHERE liked_projects.user_id=?
        ORDER BY like_count DESC, projects.timestamp DESC
    """,
        (session["user_id"],),
    )
    liked_projects = c.fetchall()
    conn.close()
    return render_template(
        "profile.html",
        user=user_info,
        user_projects=user_projects,
        liked_projects=liked_projects,
    )


# ===== حذف الحساب =====
@app.route("/delete_account", methods=["POST"])
@login_required
def delete_account():
    user_id = session["user_id"]
    conn = get_db_connection()
    c = conn.cursor()
    # حذف كل ما يخص المستخدم
    c.execute("DELETE FROM liked_projects WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM comments WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM projects WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    session.clear()
    flash("تم حذف الحساب وكل البيانات المرتبطة به بنجاح.", "info")
    return redirect(url_for("login_page"))


@app.route("/uploads/<path:filename>")
@login_required
def download_file(filename):
    return send_from_directory(
        app.config["UPLOAD_FOLDER"], filename, as_attachment=True
    )


@app.route("/like/<int:project_id>", methods=["POST"])
@login_required
def like_project(project_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "SELECT * FROM liked_projects WHERE user_id=? AND project_id=?",
        (session["user_id"], project_id),
    )
    exists = c.fetchone()
    if exists:
        c.execute(
            "DELETE FROM liked_projects WHERE user_id=? AND project_id=?",
            (session["user_id"], project_id),
        )
        liked = False
    else:
        c.execute(
            "INSERT INTO liked_projects (user_id, project_id) VALUES (?,?)",
            (session["user_id"], project_id),
        )
        liked = True
    conn.commit()
    c.execute(
        "SELECT COUNT(*) as count FROM liked_projects WHERE project_id=?", (project_id,)
    )
    count = c.fetchone()["count"]
    conn.close()
    return jsonify({"liked": liked, "like_count": count})


if __name__ == "__main__":
    app.run(debug=True)
