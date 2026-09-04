# Bedroom R&B / Dark Romance — YouTube автопилот. Орнату нұсқаулығы

## Архитектура қысқаша

- **Сурет**: Pexels API арқылы автоматты ізделеді (тег-сұраныстар: "red
  neon sign love", "neon text dark bedroom" т.б.), содан кейін Pillow
  арқылы үстіне "I Want U" / "TOUCH ME" / "YOU & ME" секілді жарқыраған
  неон мәтіні салынады (`assets/fonts/Neonderthaw-Regular.ttf` шрифтімен).
  Pexels қолжетімсіз болса (кілт жоқ/rate-limit), жүйе автоматты түрде
  `images/` папкасындағы жергілікті суреттерге ауысады (қосымша, міндетті
  емес fallback).
- **Музыка**: `facebook/musicgen-small` моделі GitHub Actions runner-дің өз
  CPU-ында (`transformers` кітапханасы арқылы) тікелей іске қосылады —
  үшінші жақтың тегін Space-теріне тәуелді емес, сондықтан ешқашан
  "API өзгеріп кетті" деп бұзылмайды. Уақытты үнемдеу үшін ұзын видео үшін
  небәрі 3 қысқа (35с) unique трек генерацияланып, FFmpeg crossfade+loop
  арқылы ~11 минутқа дейін созылады.
- **Видео**: FFmpeg арқылы сурет+аудио бір MP4-ке біріктіріледі
  (fade-in/out әсерімен).
- **SEO**: Claude (Anthropic API) арқылы атау/сипаттама/хэштег
  генерацияланады (кілт қоспасаңыз — үлгі мәтін қолданылады).
- **Жүктеу**: YouTube Data API v3 арқылы автоматты.
- **Хабарлама**: әр видео жүктелген сайын (сәтті не сәтсіз) Telegram
  боты арқылы сізге сілтемемен хабарлама келеді.

---

## 0. Талаптар

- GitHub аккаунт
- Pexels API кілті (тегін, https://www.pexels.com/api/)
- Google/YouTube аккаунт (жүктейтін арна) + Google Cloud жоба
- (Міндетті емес) Anthropic API кілті — SEO атау/сипаттама үшін. Болмаса, скрипт үлгі мәтінді қолданады.
- (Міндетті емес) ~5-10 жеке эстетикалық сурет — Pexels қолжетімсіз болған
  жағдайдағы fallback ретінде
- Жергілікті тестілеу үшін: Python 3.11+, [FFmpeg](https://ffmpeg.org/download.html)

---

## 1. Pexels API кілтін алу

1. https://www.pexels.com/api/ бетінде тіркеліп, тегін API кілт алыңыз.
2. Бұл — `PEXELS_API_KEY` секреті.
3. Скрипт өзі `main.py`-дегі `PEXELS_QUERIES` тізіміндегі тег-сұраныстар
   (мыс. "red neon sign love") бойынша фон суретін іздейді, содан кейін
   `NEON_PHRASES` тізіміндегі мәтіндердің біреуін ("I Want U", "TOUCH ME",
   "YOU & ME") жарқыраған неон стилінде үстіне салады. Екі тізімді де
   өз қалауыңызша толықтыруға/өзгертуге болады.

**(Міндетті емес) Жергілікті суреттер — fallback:**

Pexels уақытша қолжетімсіз болса (rate-limit, желі қатесі) деген
жағдайға сақтық ретінде `images/` папкасына бірнеше өз суретіңізді
қосуға болады (`.jpg`/`.jpeg`/`.png`/`.webp`). Бос қалдырсаңыз да
жүйе жұмыс істей береді — fallback папка бос болса, ол жай пайдаланылмайды.

> `images/` папкасындағы файлдар `.gitignore`-де ЕСКЕРІЛМЕЙДІ — егер
> қоссаңыз, GitHub-қа commit жасалуы керек.

---

## 2. YouTube Data API v3 орнату (OAuth)

1. https://console.cloud.google.com/ бетінде жаңа жоба жасаңыз.
2. **APIs & Services → Library** → "YouTube Data API v3" тауып, **Enable** басыңыз.
3. **APIs & Services → OAuth consent screen**:
   - Түрі: External, Testing режимінде қалдыруға болады.
   - Өз Google email-іңізді **Test users** тізіміне қосыңыз.
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Desktop app**
   - Жасалған client_secret JSON файлын жүктеп алып, жобаның түбіріне
     `client_secret.json` деп сақтаңыз (бұл файл `.gitignore`-де, GitHub-қа
     кетпейді).
5. Жергілікті компьютерде бір рет орындаңыз:
   ```
   pip install google-auth-oauthlib
   python get_youtube_token.py
   ```
6. Браузер ашылады → YouTube арнасы бар Google аккаунтпен кіріп рұқсат
   беріңіз (Testing режимінде "unverified app" ескертуі шығады — Advanced →
   Go to app (unsafe) арқылы жалғастырыңыз, бұл өз жобаңыз болғандықтан
   қауіпсіз).
7. Терминалда шыққан үш мәнді сақтап қойыңыз:
   - `YT_CLIENT_ID`
   - `YT_CLIENT_SECRET`
   - `YT_REFRESH_TOKEN`

---

## 3. (Міндетті емес) Anthropic API кілті

SEO атау/сипаттама/хэштегтерді Claude арқылы генерациялау үшін:

1. https://console.anthropic.com/ → **API Keys** → жаңа кілт жасаңыз.
2. Бұл — `ANTHROPIC_API_KEY` секреті.

Кілт қоспасаңыз да жүйе жұмыс істей береді — дайын үлгі (fallback)
атау/сипаттама қолданылады.

---

## 4. Жобаны GitHub-қа жүктеу

Жоба папкасында (`D:\Relax_music`):

```powershell
git init
git add main.py get_youtube_token.py requirements.txt .gitignore SETUP.md .github assets images
git commit -m "Bedroom R&B auto-pipeline"
git branch -M main
git remote add origin https://github.com/<сіздің-логин>/<репо-аты>.git
git push -u origin main
```

**Ескерту:** `client_secret.json` және `output/` папкасы `.gitignore`-де
тұр — олар GitHub-қа кетпейді (құпия/уақытша файлдар). Ал `images/`
папкасындағы суреттер міндетті түрде commit жасалады.

---

## 5. GitHub Secrets қосу

Репозиторийде: **Settings → Secrets and variables → Actions → New repository secret**

Мына секреттерді қосыңыз:

| Secret аты | Мәні |
|---|---|
| `PEXELS_API_KEY` | 1-қадамдағы Pexels API кілті |
| `YT_CLIENT_ID` | 2-қадамдағы OAuth client ID |
| `YT_CLIENT_SECRET` | 2-қадамдағы OAuth client secret |
| `YT_REFRESH_TOKEN` | 2-қадамдағы refresh token |
| `ANTHROPIC_API_KEY` | (міндетті емес) 3-қадамдағы Claude кілті |
| `TELEGRAM_BOT_TOKEN` | (міндетті емес) Telegram бот токені — әр видео жүктелген сайын хабарлама келу үшін |
| `TELEGRAM_CHAT_ID` | (міндетті емес) Telegram chat ID (сіздің немесе бот жіберетін чат) |
| `HF_TOKEN` | (міндетті емес) Hugging Face токені — модель салмақтарын жүктегенде анонимді rate-limit-ке тап болсаңыз ғана керек |

---

## 6. Cron кестесін тексеру / реттеу

`.github/workflows/main.yml` ішінде — 24 сағат 4-ке бөлініп, әр 6 сағат
сайын **тек 1 видео** жүктеледі (барлығы бір мезгілде жүктелмейді):

```yaml
schedule:
  - cron: "0 3 * * *"   # 08:00 Almaty — Shorts
  - cron: "0 9 * * *"   # 14:00 Almaty — Shorts
  - cron: "0 15 * * *"  # 20:00 Almaty — Shorts
  - cron: "0 21 * * *"  # 02:00 Almaty (келесі күн) — ұзын видео
```

Workflow-дағы "Determine mode for this run" қадамы `github.event.schedule`
мәні арқылы қай уақыт іске қосылғанын анықтап, соған сай `shorts` не
`long` режимін таңдайды. GitHub Actions cron әрдайым **UTC** уақытпен
жұмыс істейді — басқа уақытта жіберу керек болса, осы 4 cron мәнін
(UTC-ке қайта есептеп) және workflow ішіндегі сәйкес `case` шартын бірге
өзгертіңіз.

---

## 7. Қолмен іске қосып тексеру

Push жасағаннан кейін:

1. GitHub репозиторийде **Actions** табына өтіңіз.
2. "Bedroom R&B Auto Pipeline" workflow-ын таңдап **Run workflow** басыңыз
   (mode: `shorts` немесе `long` — қолмен іске қосқанда әр ран бір ғана
   видео жасайды).
3. Логтарды бақылаңыз. Алғашқы ран музыка моделінің салмақтарын жүктейтіндіктен
   (~1.5GB) баяулау болады; келесі ран-дарда GitHub Actions cache арқасында
   жылдамырақ жүреді.

Жергілікті түрде тексеру үшін (жүктеусіз, тек видео жасау):

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
$env:PEXELS_API_KEY="ваш_pexels_кілт"
python main.py --mode shorts --no-upload
```

Нәтиже `output/` папкасында пайда болады.

---

## 8. Күнделікті автопилот

Cron іске қосылғаннан кейін жүйе күніне 4 рет (08:00, 14:00, 20:00,
02:00 Almaty — 6 сағат сайын, 3 Shorts + 1 ұзын видео), әр триггерде
тек 1 видео жасап, өздігінен:

1. Pexels API арқылы фон суретін тауып, үстіне жарқыраған неон мәтін
   салады (Pexels қолжетімсіз болса — `images/`-тен жергілікті сурет),
2. `facebook/musicgen-small` моделін GitHub Actions runner-дің өз CPU-ында
   іске қосып фон музыкасын жасайды (shorts үшін 1×30с трек, ұзын видео
   үшін 3×35с unique трек crossfade+loop арқылы ~11 минутқа созылады),
3. FFmpeg арқылы MP4 видео рендерлейді (fade-in/out әсерімен),
4. Claude арқылы (немесе fallback үлгімен) SEO атау/сипаттама жасайды,
5. YouTube-қа автоматты жүктейді (`YT_PRIVACY_STATUS` арқылы public/
   unlisted/private реттеуге болады, workflow файлында).

## Белгілі шектеулер

- CPU-да MusicGen генерациясы (әсіресе алғашқы ран, модель кэші жоқ кезде)
  біраз уақыт алады. Ұзақтық ұзарса, `.github/workflows/main.yml`-дегі
  `timeout-minutes` мәнін көбейтуге немесе `main.py`-дегі `MODES` ішіндегі
  `unique_tracks`/`unique_track_duration` мәндерін азайтуға болады.
- GitHub Actions free tier — жария репозиторийлерге шектеусіз, жеке
  репозиторийге айына 2000 минут (ubuntu runner) тегін.
- YouTube OAuth consent screen "Testing" режимінде тек **Test users**
  тізіміндегі аккаунттар үшін жұмыс істейді. Егер бірнеше адам/арна
  болса, әрқайсысын тізімге қосу керек, немесе консентті "In production"-ге
  ауыстырып Google верификациясынан өту керек.
- Pexels тегін тарифі шамамен 200 сұраныс/сағат, 20 000 сұраныс/ай —
  күніне небәрі 2 сұраныс (shorts+long) жасалатындықтан бұл шектеу
  іс жүзінде тимейді.
- `images/` fallback папкасы бос болса және Pexels та сәтсіз болса,
  сол күнгі видео жасалмайды (лог GitHub Actions-та көрінеді).
