import calendar
import os
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import db
import scraper


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "degistir-beni")
app.config["SESSION_COOKIE_HTTPONLY"] = True

ISTANBUL = ZoneInfo("Europe/Istanbul")


def today_istanbul():
    return datetime.now(ISTANBUL).date()


def get_connection():
    return db.get_db()


@app.before_request
def require_login():
    if request.endpoint in ("login", "static"):
        return None
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == "test" and request.form.get("password") == "123":
            session.clear()
            session["logged_in"] = True
            session["csrf_token"] = secrets.token_hex(16)
            return redirect(url_for("library"))
        flash("Kullanıcı adı veya şifre hatalı.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def is_duplicate(title, author):
    connection = get_connection()
    row = connection.execute(
        "SELECT id FROM books WHERE lower(trim(title)) = lower(trim(?)) "
        "AND lower(trim(author)) = lower(trim(?))",
        (title, author),
    ).fetchone()
    connection.close()
    return row is not None


def latest_page(book_id):
    connection = get_connection()
    row = connection.execute(
        "SELECT current_page FROM reading_logs "
        "WHERE book_id = ? ORDER BY log_date DESC, id DESC LIMIT 1",
        (book_id,),
    ).fetchone()
    connection.close()
    return row["current_page"] if row else 0


@app.route("/")
@app.route("/kitaplik")
def library():
    active_shelf = request.args.get("raf", "okunuyor")
    if active_shelf not in ("okunacak", "okunuyor", "okundu"):
        active_shelf = "okunuyor"
    connection = get_connection()
    books = connection.execute(
        "SELECT * FROM books WHERE status = ? ORDER BY created_at DESC",
        (active_shelf,),
    ).fetchall()
    book_cards = []
    for book in books:
        current = latest_page(book["id"])
        progress = 0
        if book["pages"] and book["pages"] > 0:
            progress = min(100, round(current * 100 / book["pages"]))
        last_log = connection.execute(
            "SELECT id, log_date, current_page FROM reading_logs "
            "WHERE book_id = ? ORDER BY log_date DESC, id DESC LIMIT 1",
            (book["id"],),
        ).fetchone()
        estimate = estimate_days(book["id"], book["pages"]) if book["pages"] else None
        book_cards.append(
            dict(
                book,
                current_page=current,
                progress=progress,
                last_log=last_log,
                estimate=estimate,
            )
        )
    counts = {}
    for shelf in ("okunacak", "okunuyor", "okundu"):
        counts[shelf] = connection.execute(
            "SELECT COUNT(*) AS count FROM books WHERE status = ?", (shelf,)
        ).fetchone()["count"]
    connection.close()
    return render_template(
        "library.html",
        books=book_cards,
        active_shelf=active_shelf,
        counts=counts,
    )


@app.route("/ara")
def search():
    query = request.args.get("q", "").strip()
    results = []
    search_error = False
    if query:
        try:
            results = scraper.search_books(query)
        except (requests.RequestException, requests.HTTPError):
            search_error = True
    return render_template(
        "search.html",
        query=query,
        results=results,
        search_error=search_error,
    )


@app.route("/kitap/ekle", methods=["POST"])
def add_book():
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    publisher = request.form.get("publisher", "").strip()
    product_url = request.form.get("product_url", "").strip()
    cover_url = request.form.get("cover_url", "").strip()
    status = request.form.get("status", "okunacak")
    pages = int(request.form.get("pages") or 0)
    isbn = request.form.get("isbn", "").strip()
    publication_year = request.form.get("publication_year", "").strip()

    if not title or not author:
        flash("Kitap adı ve yazar zorunludur.", "danger")
        return redirect(url_for("search", q=request.form.get("query", "")))
    if pages <= 0:
        flash("Sayfa sayısı 0'dan büyük olmalıdır.", "danger")
        return redirect(url_for("search", q=request.form.get("query", "")))
    if status not in ("okunacak", "okunuyor", "okundu"):
        status = "okunacak"
    if is_duplicate(title, author):
        flash("Bu kitap zaten kitaplığınızda.", "warning")
        return redirect(url_for("library"))

    if product_url:
        try:
            detail = scraper.get_book_detail(product_url)
            pages = detail["pages"] or pages
            isbn = isbn or detail["isbn"]
            publication_year = publication_year or detail["publication_year"]
        except (requests.RequestException, requests.HTTPError):
            pass

    cover_path = None
    if cover_url:
        try:
            cover_path = scraper.download_cover(cover_url, isbn, title)
        except (requests.RequestException, requests.HTTPError, OSError):
            cover_path = None

    if pages <= 0:
        flash("Sayfa sayısı 0'dan büyük olmalıdır.", "danger")
        return redirect(url_for("search", q=request.form.get("query", "")))

    connection = get_connection()
    cursor = connection.execute(
        """
        INSERT INTO books
        (title, author, publisher, cover_path, product_url, pages, isbn,
         publication_year, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            author,
            publisher,
            cover_path,
            product_url,
            pages,
            isbn,
            publication_year,
            status,
            today_istanbul().isoformat(),
        ),
    )
    connection.commit()
    connection.close()
    flash(f'"{title}" kitaplığınıza ekledi.', "success")
    return redirect(url_for("library", raf=status))


@app.route("/kitap/elle-ekle", methods=["POST"])
def add_manual():
    request.form = request.form
    return add_book()


@app.route("/kitap/<int:book_id>/raf", methods=["POST"])
def change_shelf(book_id):
    status = request.form.get("status")
    if status not in ("okunacak", "okunuyor", "okundu"):
        return redirect(url_for("library"))
    connection = get_connection()
    finished_at = today_istanbul().isoformat() if status == "okundu" else None
    connection.execute(
        "UPDATE books SET status = ?, finished_at = ? WHERE id = ?",
        (status, finished_at, book_id),
    )
    connection.commit()
    connection.close()
    flash("Raf güncellendi.", "success")
    return redirect(url_for("library", raf=status))


@app.route("/kitap/<int:book_id>/okuma", methods=["POST"])
def add_reading_log(book_id):
    try:
        current_page = int(request.form.get("current_page", ""))
    except (TypeError, ValueError):
        flash("Geçerli bir sayfa numarası girin.", "danger")
        return redirect(url_for("library"))

    connection = get_connection()
    book = connection.execute(
        "SELECT * FROM books WHERE id = ?", (book_id,)
    ).fetchone()
    if not book:
        connection.close()
        return redirect(url_for("library"))
    previous = latest_page(book_id)
    if current_page < previous or current_page > book["pages"] or current_page < 1:
        connection.close()
        flash("Sayfa değeri önceki kayıttan küçük veya toplam sayfadan büyük olamaz.", "danger")
        return redirect(url_for("library", raf="okunuyor"))

    pages_added = current_page - previous
    if pages_added < 0:
        pages_added = 0
    today = today_istanbul().isoformat()
    connection.execute(
        """
        INSERT INTO reading_logs(book_id, log_date, current_page, pages_added)
        VALUES (?, ?, ?, ?)
        """,
        (book_id, today, current_page, pages_added),
    )
    if book["pages"] and current_page >= book["pages"]:
        connection.execute(
            "UPDATE books SET status = 'okundu', finished_at = ? WHERE id = ?",
            (today, book_id),
        )
    elif book["status"] == "okunacak":
        connection.execute(
            "UPDATE books SET status = 'okunuyor' WHERE id = ?", (book_id,)
        )
    connection.commit()
    connection.close()
    flash("Okuma kaydı eklendi.", "success")
    return redirect(url_for("library", raf="okundu" if current_page >= book["pages"] else "okunuyor"))


@app.route("/kitap/<int:book_id>/kayit/<int:log_id>/sil", methods=["POST"])
def delete_reading_log(book_id, log_id):
    connection = get_connection()
    connection.execute(
        "DELETE FROM reading_logs WHERE id = ? AND book_id = ?", (log_id, book_id)
    )
    latest = connection.execute(
        "SELECT current_page FROM reading_logs WHERE book_id = ? "
        "ORDER BY log_date DESC, id DESC LIMIT 1",
        (book_id,),
    ).fetchone()
    connection.execute(
        "UPDATE books SET status = 'okunuyor', finished_at = NULL WHERE id = ?",
        (book_id,),
    )
    if not latest:
        connection.execute(
            "UPDATE books SET status = 'okunacak' WHERE id = ?", (book_id,)
        )
    connection.commit()
    connection.close()
    flash("Son kayıt silindi.", "success")
    return redirect(url_for("library", raf="okunuyor"))


@app.route("/kitap/<int:book_id>/puan", methods=["POST"])
def update_rating(book_id):
    try:
        rating = int(request.form.get("rating", "0"))
    except ValueError:
        rating = 0
    rating = max(0, min(5, rating))
    note = request.form.get("note", "").strip()
    connection = get_connection()
    connection.execute(
        "UPDATE books SET rating = ?, note = ? WHERE id = ?", (rating, note, book_id)
    )
    connection.commit()
    connection.close()
    flash("Puan ve not kaydedildi.", "success")
    return redirect(url_for("library", raf="okundu"))


def estimate_days(book_id, pages):
    connection = get_connection()
    today = today_istanbul()
    start = (today - timedelta(days=6)).isoformat()
    row = connection.execute(
        "SELECT COALESCE(SUM(pages_added), 0) AS total "
        "FROM reading_logs WHERE book_id = ? AND log_date >= ?",
        (book_id, start),
    ).fetchone()
    current = latest_page(book_id)
    connection.close()
    remaining = max(0, pages - current)
    speed = row["total"] / 7 if row else 0
    if speed <= 0:
        return None
    return max(1, round(remaining / speed))


@app.route("/istatistik")
def statistics():
    year = today_istanbul().year
    goal = int(db.get_setting("yearly_goal", "24"))
    connection = get_connection()
    finished = connection.execute(
        "SELECT COUNT(*) AS count FROM books "
        "WHERE status = 'okundu' AND substr(finished_at, 1, 4) = ?",
        (str(year),),
    ).fetchone()["count"]

    monthly = [0] * 12
    rows = connection.execute(
        "SELECT substr(log_date, 1, 7) AS month, SUM(pages_added) AS pages "
        "FROM reading_logs WHERE substr(log_date, 1, 4) = ? "
        "GROUP BY substr(log_date, 1, 7)",
        (str(year),),
    ).fetchall()
    for row in rows:
        try:
            monthly[int(row["month"][5:7]) - 1] = row["pages"]
        except (TypeError, ValueError):
            pass

    log_dates = [
        date.fromisoformat(row["log_date"])
        for row in connection.execute(
            "SELECT DISTINCT log_date FROM reading_logs ORDER BY log_date DESC"
        ).fetchall()
    ]
    connection.close()
    streak = 0
    expected = today_istanbul()
    if log_dates and log_dates[0] == expected - timedelta(days=1):
        expected = log_dates[0]
    if log_dates and log_dates[0] in (today_istanbul(), today_istanbul() - timedelta(days=1)):
        for log_date in log_dates:
            if log_date == expected:
                streak += 1
                expected -= timedelta(days=1)
            elif log_date < expected:
                break

    difference = goal - finished
    if difference <= 0:
        goal_status = f"Bu yıl {finished}/{goal}, hedefini tamamladın"
    elif difference == 1:
        goal_status = f"Bu yıl {finished}/{goal}, hedefin 1 kitap gerisindesin"
    else:
        goal_status = f"Bu yıl {finished}/{goal}, hedefin {difference} kitap gerisindesin"

    return render_template(
        "statistics.html",
        goal=goal,
        goal_status=goal_status,
        monthly=monthly,
        month_labels=[calendar.month_abbr[i] for i in range(1, 13)],
        reading_streak=streak,
    )


@app.route("/ayarlar", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        try:
            goal = int(request.form.get("yearly_goal", "24"))
        except ValueError:
            goal = 24
        if goal < 1:
            goal = 24
        db.set_setting("yearly_goal", goal)
        flash("Yıllık hedef güncellendi.", "success")
        return redirect(url_for("settings"))
    goal = int(db.get_setting("yearly_goal", "24"))
    return render_template("settings.html", goal=goal)


with app.app_context():
    db.init_db()
