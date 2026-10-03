"""
Campus Lost & Found: Flask + Supabase
Run:  python app.py
"""
import os
import socket
import uuid
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, flash, redirect, render_template, request,
                   send_from_directory, session, url_for)
from supabase import create_client
load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

ITEM_BUCKET = "item-photos"
PROOF_BUCKET = "proof-photos"

CATEGORIES = ["Electronics", "Accessories", "IDs & Cards", "Clothing",
              "Books & Notes", "Bags", "Keys", "Other"]
STATUSES = ["Lost", "Found"]

ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB per photo

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # whole request
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("RENDER"))

# Server-side client (service role). NEVER expose this key to the browser.
db = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def auth_client():
    """Fresh anon client per auth call so one user's login never leaks into another's."""
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# --------------------------------------------------------------- helpers

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Log in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def safe_next(target):
    """Only allow redirects to local paths."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("dashboard")


def upload_image(file_storage, bucket, user_id):
    """Validate and upload one image; return its public URL."""
    if not file_storage or not file_storage.filename:
        raise ValueError("Please choose both photos.")
    mime = file_storage.mimetype
    if mime not in ALLOWED_TYPES:
        raise ValueError("Photos must be JPG, PNG, or WebP.")
    data = file_storage.read()
    if not data:
        raise ValueError("One of the photos is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Each photo must be 5 MB or smaller.")

    path = f"{user_id}/{uuid.uuid4().hex}.{ALLOWED_TYPES[mime]}"
    db.storage.from_(bucket).upload(path, data, {"content-type": mime})
    return db.storage.from_(bucket).get_public_url(path)


def storage_path_from_url(url, bucket):
    marker = f"/{bucket}/"
    return url.split(marker, 1)[1].split("?", 1)[0] if marker in url else None


def ensure_profile(user_id, email, full_name):
    """Safety net in case the SQL trigger was not installed."""
    found = db.table("profiles").select("id").eq("id", user_id).execute()
    if not found.data:
        db.table("profiles").insert(
            {"id": user_id, "email": email, "full_name": full_name}
        ).execute()


# ---------------------------------------------------------------- auth

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if len(name) < 2:
            flash("Enter your full name.", "error")
        elif "@" not in email:
            flash("Enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        else:
            try:
                res = auth_client().auth.sign_up({
                    "email": email,
                    "password": password,
                    "options": {"data": {"full_name": name}},
                })
                if res.user and res.session:
                    ensure_profile(res.user.id, email, name)
                    session.clear()
                    session["user_id"] = res.user.id
                    session["user_name"] = name
                    flash(f"Welcome, {name.split()[0]}!", "success")
                    return redirect(url_for("dashboard"))
                flash("Account created. Check your email to confirm it, then log in.", "success")
                return redirect(url_for("login"))
            except Exception as exc:  # supabase raises AuthApiError etc.
                flash(f"Could not sign up: {getattr(exc, 'message', str(exc))}", "error")

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        try:
            res = auth_client().auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            user = res.user
            meta_name = (user.user_metadata or {}).get("full_name") or email.split("@")[0]
            ensure_profile(user.id, email, meta_name)
            profile = db.table("profiles").select("full_name").eq("id", user.id).single().execute()

            session.clear()
            session["user_id"] = user.id
            session["user_name"] = profile.data["full_name"]
            return redirect(safe_next(request.args.get("next")))
        except Exception:
            flash("Wrong email or password, or the email isn't confirmed yet.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You're logged out.", "info")
    return redirect(url_for("login"))


# ----------------------------------------------------------- dashboard

@app.route("/")
@login_required
def dashboard():
    status = request.args.get("status", "")
    category = request.args.get("category", "")
    q = request.args.get("q", "").strip()
    mine = request.args.get("mine") == "1"

    query = (db.table("items")
               .select("*, profiles(full_name)")
               .order("created_at", desc=True))
    if status in STATUSES:
        query = query.eq("status", status)
    if category in CATEGORIES:
        query = query.eq("category", category)
    if mine:
        query = query.eq("user_id", session["user_id"])
    if q:
        safe_q = q.replace(",", " ").replace("(", " ").replace(")", " ")[:60]
        query = query.or_(f"title.ilike.%{safe_q}%,description.ilike.%{safe_q}%")

    items = query.execute().data or []
    return render_template(
        "dashboard.html", items=items, categories=CATEGORIES,
        f_status=status, f_category=category, f_q=q, f_mine=mine,
    )


# ----------------------------------------------------------- post item

@app.route("/post", methods=["GET", "POST"])
@login_required
def post_item():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "")
        status = request.form.get("status", "")
        description = request.form.get("description", "").strip()
        image = request.files.get("image")
        proof = request.files.get("proof")

        error = None
        if not 3 <= len(title) <= 100:
            error = "Title must be 3 to 100 characters."
        elif category not in CATEGORIES:
            error = "Pick a category."
        elif status not in STATUSES:
            error = "Choose Lost or Found."
        elif not 5 <= len(description) <= 1000:
            error = "Description must be 5 to 1000 characters."

        if not error:
            uploaded = []  # (bucket, url) so we can roll back on failure
            try:
                image_url = upload_image(image, ITEM_BUCKET, session["user_id"])
                uploaded.append((ITEM_BUCKET, image_url))
                proof_url = upload_image(proof, PROOF_BUCKET, session["user_id"])
                uploaded.append((PROOF_BUCKET, proof_url))

                db.table("items").insert({
                    "user_id": session["user_id"],
                    "title": title,
                    "category": category,
                    "status": status,
                    "description": description,
                    "image_url": image_url,
                    "proof_url": proof_url,
                }).execute()
                flash("Your post is live.", "success")
                return redirect(url_for("dashboard"))
            except ValueError as exc:
                error = str(exc)
            except Exception as exc:
                error = f"Something went wrong while saving: {exc}"
            # clean up orphaned uploads
            for bucket, url in uploaded:
                path = storage_path_from_url(url, bucket)
                if path:
                    try:
                        db.storage.from_(bucket).remove([path])
                    except Exception:
                        pass

        flash(error, "error")
        return render_template("post_item.html", categories=CATEGORIES,
                               statuses=STATUSES, form=request.form), 400

    return render_template("post_item.html", categories=CATEGORIES,
                           statuses=STATUSES, form={})


# --------------------------------------------------- manage own items

def get_owned_item(item_id):
    res = db.table("items").select("*").eq("id", item_id).eq("user_id", session["user_id"]).execute()
    return res.data[0] if res.data else None


@app.post("/item/<item_id>/resolve")
@login_required
def resolve_item(item_id):
    item = get_owned_item(item_id)
    if not item:
        flash("That post isn't yours.", "error")
    else:
        db.table("items").update({"is_resolved": not item["is_resolved"]}).eq("id", item_id).execute()
        flash("Post updated.", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.post("/item/<item_id>/delete")
@login_required
def delete_item(item_id):
    item = get_owned_item(item_id)
    if not item:
        flash("That post isn't yours.", "error")
        return redirect(url_for("dashboard"))

    for bucket, key in ((ITEM_BUCKET, "image_url"), (PROOF_BUCKET, "proof_url")):
        path = storage_path_from_url(item[key], bucket)
        if path:
            try:
                db.storage.from_(bucket).remove([path])
            except Exception:
                pass
    db.table("items").delete().eq("id", item_id).execute()
    flash("Post deleted.", "success")
    return redirect(url_for("dashboard"))


@app.errorhandler(413)
def too_large(_):
    flash("Those photos are too big. Keep each under 5 MB.", "error")
    return redirect(url_for("post_item"))

@app.route("/sw.js")
def service_worker():
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


# ----------------------------------------------------------------- run

def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  On this computer:  http://localhost:{port}")
    print(f"  On your phone:     http://{lan_ip()}:{port}   (same Wi-Fi)\n")
    app.run(host="0.0.0.0", port=port, debug=True)
