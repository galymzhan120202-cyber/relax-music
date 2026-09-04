"""
Бір реттік жергілікті скрипт: YouTube OAuth рефреш-токенін алу үшін.

GitHub Actions интерактивті браузер логинін жасай алмайды, сондықтан бұл
скриптті ӨЗ КОМПЬЮТЕРІҢІЗДЕ бір рет іске қосып, шыққан refresh_token-ды
GitHub Secrets-ке (YT_REFRESH_TOKEN) қолмен қосасыз.

Қолдану:
  1. Google Cloud Console-да OAuth 2.0 Client ID (Desktop app) жасаңыз,
     client_secret.json файлын жүктеп алып осы папкаға салыңыз.
  2. python get_youtube_token.py
  3. Браузерде Google аккаунтыңызбен (YouTube арнасы бар) кіріп рұқсат беріңіз.
  4. Терминалда шыққан client_id / client_secret / refresh_token үшеуін де
     GitHub Secrets-ке сақтаңыз.
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET_FILE = "client_secret.json"


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n=== OAuth сәтті аяқталды ===")
    print(f"YT_CLIENT_ID={creds.client_id}")
    print(f"YT_CLIENT_SECRET={creds.client_secret}")
    print(f"YT_REFRESH_TOKEN={creds.refresh_token}")
    print("\nБұл 3 мәнді GitHub → Settings → Secrets and variables → Actions ішіне қосыңыз.")


if __name__ == "__main__":
    main()
