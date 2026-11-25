# kitap-takip
# Kitap Takip

Flask ve SQLite tabanlı kitap okuma takip uygulaması.

## Kurulum

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest
python -m flask --app application run --debug
```

## Docker

```powershell
docker compose up -d --build
```

Uygulama: http://localhost:5010

Giriş bilgileri:

- Kullanıcı: `test`
- Şifre: `123`