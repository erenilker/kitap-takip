import os
import tempfile

import pytest

import db
import application as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "kitap.db"))
    db.init_db()
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        client.post("/login", data={"username": "test", "password": "123"})
        yield client


def test_login_required(client):
    client.get("/logout")
    response = client.get("/kitaplik")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_manual_book_and_page_rules(client):
    response = client.post(
        "/kitap/elle-ekle",
        data={
            "title": "Suç ve Ceza",
            "author": "Fyodor Dostoyevski",
            "pages": "500",
            "status": "okunuyor",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    connection = db.get_db()
    book = connection.execute(
        "SELECT * FROM books WHERE title = 'Suç ve Ceza'"
    ).fetchone()
    assert book["pages"] == 500
    assert book["status"] == "okunuyor"

    first = client.post(
        f"/kitap/{book['id']}/okuma",
        data={"current_page": "100"},
        follow_redirects=False,
    )
    assert first.status_code == 302

    invalid = client.post(
        f"/kitap/{book['id']}/okuma",
        data={"current_page": "80"},
        follow_redirects=False,
    )
    assert invalid.status_code == 302
    connection.close()


def test_duplicate_book(client):
    data = {
        "title": "Tek Kitap",
        "author": "Tek Yazar",
        "pages": "200",
        "status": "okunacak",
    }
    client.post("/kitap/elle-ekle", data=data)
    client.post("/kitap/elle-ekle", data=data)
    connection = db.get_db()
    count = connection.execute(
        "SELECT COUNT(*) AS count FROM books WHERE title = 'Tek Kitap'"
    ).fetchone()["count"]
    connection.close()
    assert count == 1


def test_last_page_moves_to_finished(client):
    client.post(
        "/kitap/elle-ekle",
        data={
            "title": "Son Sayfa",
            "author": "Yazar",
            "pages": "120",
            "status": "okunuyor",
        },
    )
    connection = db.get_db()
    book = connection.execute(
        "SELECT * FROM books WHERE title = 'Son Sayfa'"
    ).fetchone()
    connection.close()
    client.post(
        f"/kitap/{book['id']}/okuma",
        data={"current_page": "120"},
    )
    connection = db.get_db()
    updated = connection.execute(
        "SELECT * FROM books WHERE id = ?", (book["id"],)
    ).fetchone()
    connection.close()
    assert updated["status"] == "okundu"
    assert updated["finished_at"]


def test_yearly_goal_setting(client):
    response = client.post(
        "/ayarlar",
        data={"yearly_goal": "30"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert db.get_setting("yearly_goal") == "30"


def test_finish_estimate(client):
    client.post(
        "/kitap/elle-ekle",
        data={
            "title": "Tahmin Kitabı",
            "author": "Yazar",
            "pages": "100",
            "status": "okunuyor",
        },
    )
    connection = db.get_db()
    book = connection.execute(
        "SELECT * FROM books WHERE title = 'Tahmin Kitabı'"
    ).fetchone()
    connection.execute(
        "INSERT INTO reading_logs(book_id, log_date, current_page, pages_added) "
        "VALUES (?, ?, ?, ?)",
        (book["id"], app_module.today_istanbul().isoformat(), 20, 20),
    )
    connection.commit()
    connection.close()

    with app_module.app.app_context():
        estimate = app_module.estimate_days(book["id"], 100)
    assert estimate is not None
    assert estimate > 0
