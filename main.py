"""
Bedroom R&B / Dark Romance / Chill Music — YouTube автопилот.

Толық конвейер (толығымен self-host, үшінші жақтың тегін Space-теріне
тәуелді емес):
  1) Pexels API арқылы "red neon sign love" секілді тег-сұраныстар бойынша
     эстетикалық фон суретін автоматты іздеп табу, содан кейін Pillow
     арқылы үстіне "I Want U" секілді жарқыраған неон мәтінін салу.
     (Pexels қолжетімсіз болса — `images/` папкасындағы жергілікті
     суреттерге автоматты ауысады.)
  2) transformers (facebook/musicgen-small) арқылы фон музыкасын генерациялау —
     CPU-да. Ұзын видео үшін ЖИ уақытын шектеу мақсатында небәрі бірнеше
     unique трек жасалады да, FFmpeg crossfade + stream_loop арқылы керекті
     ұзындыққа дейін "созылады" (толық 10-15 минутты генерациялау емес).
  3) FFmpeg арқылы сурет + аудионы бір MP4 видеоға айналдыру (fade-in/out)
  4) Claude (Anthropic API) арқылы SEO атау/сипаттама/хэштег генерациялау
  5) YouTube Data API v3 арқылы дайын видеоны автоматты жүктеу

Қолдану:
  python main.py --mode shorts
  python main.py --mode long
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
import soundfile as sf
import torch
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# --------------------------------------------------------------------------
# ЖАЛПЫ КОНФИГ
# --------------------------------------------------------------------------

WORKDIR = Path(tempfile.mkdtemp(prefix="rnb_pipeline_"))
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

torch.set_num_threads(max(1, os.cpu_count() or 1))

# Суреттер — біріншіден Pexels API арқылы автоматты ізделеді. Егер
# PEXELS_API_KEY жоқ болса не сұраныс сәтсіз болса, `images/` папкасында
# пайдаланушы өзі қосқан жергілікті суреттерге автоматты ауысады.
IMAGES_DIR = Path(os.environ.get("IMAGES_DIR", "images"))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
PEXELS_QUERIES = [
    "red neon sign love",
    "neon text dark bedroom",
    "glowing red sign quote",
    "neon words aesthetic",
    "red neon quotes bedroom",
    "sensual woman red light silhouette",
    "seductive silhouette dark room",
    "intimate red aesthetic portrait",
    "woman red neon glow bedroom",
    "romantic couple silhouette red light",
]
# ЕСКЕРТУ: Pexels тек SFW (ашық жыныстық мазмұнсыз) stock суреттерді ғана
# индекстейді — жоғарыдағы сұраныстар нәтижесі көркем/эстетикалық
# сипатта болады, нақты ашық мазмұн емес. YouTube монетизация
# саясатына қайшы келетін сұраныстар қоспаңыз (жас шектеуі/страйк қаупі).
MAX_IMAGE_DIMENSION = 1600  # жүктелген суретті осы өлшемге дейін кішірейтеміз

# Видео мұқабасына қосылатын жарқыраған неон мәтіндер (кездейсоқ таңдалады).
NEON_PHRASES = ["I Want U", "TOUCH ME", "YOU & ME"]
NEON_FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "Neonderthaw-Regular.ttf"
NEON_GLOW_COLOR = (255, 35, 70)   # қызыл-қызғылт жарық
NEON_CORE_COLOR = (255, 235, 240)  # ақшыл-ыстық орталық

# Telegram — әр видео жүктелген сайын хабарлама жіберу үшін.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Модель — HF Hub-тан салмақтарды тікелей жүктеп, локалды іске қосамыз.
# Бұл community Gradio Space-тердің API сигнатурасы өзгеруіне/өшуіне тәуелді
# емес: тек модель салмақтары ғана керек, олар өзгермейді.
MUSIC_MODEL = os.environ.get("MUSIC_MODEL", "facebook/musicgen-small")
MUSIC_GUIDANCE_SCALE = float(os.environ.get("MUSIC_GUIDANCE_SCALE", "3.0"))

MUSIC_PROMPT_TEMPLATE = (
    "slow chill R&B beat, late night vibe, dark romantic atmosphere, "
    "80 bpm, smooth bassline, soft drums, lofi texture"
)

MODES = {
    "shorts": {
        "image_size": (1080, 1920),  # 9:16
        # Shorts — бір ғана трек, толық видео ұзындығы осыған тең.
        "unique_tracks": 1,
        "unique_track_duration": 30,
        "target_video_duration": None,  # None = трек ұзындығымен бірдей
        "crossfade": 0,
        "video_suffix": "_shorts",
    },
    "long": {
        "image_size": (1920, 1080),  # 16:9
        # Ұзын видео — небәрі 3 unique трек генерацияланады (CPU уақытын
        # шектеу үшін), содан кейін crossfade + loop арқылы 11 минутқа
        # дейін созылады.
        "unique_tracks": 3,
        "unique_track_duration": 35,
        "target_video_duration": 660,  # 11 минут
        "crossfade": 3,
        "video_suffix": "_long",
    },
}


def log(msg: str) -> None:
    print(f"[pipeline] {msg}", flush=True)


def run_ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    log("ffmpeg: " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def free_memory() -> None:
    gc.collect()


# --------------------------------------------------------------------------
# 1) ФОН СУРЕТІ: Pexels API (+ неон мәтін overlay), fallback — жергілікті
# --------------------------------------------------------------------------

def fetch_pexels_image(orientation: str, out_path: Path) -> Path:
    if not PEXELS_API_KEY:
        raise RuntimeError("PEXELS_API_KEY орнатылмаған.")

    query = random.choice(PEXELS_QUERIES)
    log(f"Pexels-тен сурет іздеу: '{query}' ({orientation}, color=red)")

    def search(use_color: bool) -> list[dict]:
        params = {"query": query, "per_page": 15, "orientation": orientation}
        if use_color:
            params["color"] = "red"
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("photos", [])

    # CRIMSONROOM брендіне сай ең алдымен тек қызыл түсі басым суреттерді
    # сұраймыз; сирек сұраныста бос нәтиже қайтарса, түс сүзгісінсіз
    # қайталаймыз (сұраныс мәтінінің өзі де "red"/"neon" болғандықтан
    # нәтиже баяғыда да негізінен қызыл болып қалады).
    photos = search(use_color=True)
    if not photos:
        log("color=red бойынша нәтиже жоқ — түс сүзгісінсіз қайталанады.")
        photos = search(use_color=False)
    if not photos:
        raise RuntimeError(f"Pexels '{query}' сұранысы бойынша нәтиже қайтармады.")

    photo = random.choice(photos)
    image_url = photo["src"]["original"]
    img_resp = requests.get(image_url, timeout=60)
    img_resp.raise_for_status()
    out_path.write_bytes(img_resp.content)
    log(f"Pexels суреті жүктелді: id={photo['id']}, авторы: {photo.get('photographer')}")
    return out_path


def overlay_neon_text(image_path: Path, out_path: Path) -> Path:
    text = random.choice(NEON_PHRASES)
    log(f"Неон мәтін қосылуда: \"{text}\"")

    image = Image.open(image_path).convert("RGB")
    w, h = image.size
    scale = min(1.0, MAX_IMAGE_DIMENSION / max(w, h))
    if scale < 1.0:
        image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    base = image.convert("RGBA")
    w, h = base.size

    font_size = int(min(w, h) * 0.18)
    font_size = max(60, min(font_size, 260))
    while font_size > 30:
        font = ImageFont.truetype(str(NEON_FONT_PATH), font_size)
        bbox = ImageDraw.Draw(base).textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        if text_w <= w * 0.85:
            break
        font_size = int(font_size * 0.9)

    text_h = bbox[3] - bbox[1]
    pos = ((w - text_w) / 2 - bbox[0], (h - text_h) / 2 - bbox[1])

    text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(text_layer).text(pos, text, font=font, fill=(*NEON_GLOW_COLOR, 255))

    composed = base
    for blur_radius in (font_size * 0.18, font_size * 0.08):
        glow = text_layer.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        composed = Image.alpha_composite(composed, glow)

    core_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(core_layer).text(pos, text, font=font, fill=(*NEON_CORE_COLOR, 255))
    composed = Image.alpha_composite(composed, core_layer)

    composed.convert("RGB").save(out_path, quality=95)
    return out_path


def pick_local_image() -> Path:
    if not IMAGES_DIR.is_dir():
        raise RuntimeError(f"'{IMAGES_DIR}' папкасы табылмады.")

    candidates = sorted(
        p for p in IMAGES_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not candidates:
        raise RuntimeError(f"'{IMAGES_DIR}' папкасында сурет табылмады.")

    chosen = random.choice(candidates)
    out_path = WORKDIR / f"cover{chosen.suffix.lower()}"
    out_path.write_bytes(chosen.read_bytes())
    log(f"Жергілікті сурет қолданылды: {chosen.name} ({len(candidates)} суреттің ішінен)")
    return out_path


def get_background_image(orientation: str) -> Path:
    """
    Біріншіден Pexels API арқылы фон іздеп, үстіне неон мәтін қосады.
    Сәтсіз болса (кілт жоқ/rate-limit/желі қатесі) — жергілікті images/
    папкасына автоматты ауысады (неон мәтінсіз, дайын суретсіз).
    """
    try:
        raw_path = WORKDIR / "pexels_raw.jpg"
        fetch_pexels_image(orientation, raw_path)
        final_path = WORKDIR / "cover.jpg"
        overlay_neon_text(raw_path, final_path)
        return final_path
    except Exception as exc:  # noqa: BLE001
        log(f"Pexels арқылы сурет алу сәтсіз болды ({exc}) — жергілікті суретке ауысу.")
        return pick_local_image()


# --------------------------------------------------------------------------
# 2) МУЗЫКА ГЕНЕРАЦИЯСЫ (transformers MusicGen, локалды CPU)
# --------------------------------------------------------------------------

def generate_music_pool(prompt: str, n_tracks: int, duration: int) -> list[Path]:
    from transformers import AutoProcessor, MusicgenForConditionalGeneration

    log(f"Музыка моделін жүктеу: {MUSIC_MODEL}")
    processor = AutoProcessor.from_pretrained(MUSIC_MODEL)
    model = MusicgenForConditionalGeneration.from_pretrained(MUSIC_MODEL)
    model.to("cpu")

    frame_rate = getattr(model.config.audio_encoder, "frame_rate", 50)
    sampling_rate = model.config.audio_encoder.sampling_rate
    max_new_tokens = int(duration * frame_rate)

    track_paths = []
    for i in range(n_tracks):
        log(f"Трек {i + 1}/{n_tracks} генерациялау ({duration}с)...")
        inputs = processor(text=[prompt], padding=True, return_tensors="pt")
        audio_values = model.generate(
            **inputs,
            do_sample=True,
            guidance_scale=MUSIC_GUIDANCE_SCALE,
            max_new_tokens=max_new_tokens,
        )
        audio = audio_values[0, 0].cpu().numpy()

        track_path = WORKDIR / f"track_{i}.wav"
        sf.write(track_path, audio, sampling_rate)
        track_paths.append(track_path)
        log(f"Трек дайын: {track_path}")

    del model, processor
    free_memory()

    return track_paths


def build_audio_track(mode_cfg: dict) -> Path:
    """
    Unique тректерді генерациялайды. Егер бірнешеу болса — crossfade арқылы
    бір "loop" сегментіне біріктіреді де, соны target ұзындыққа дейін
    қайталап (stream_loop) созады. Осылайша ЖИ генерация уақыты видео
    ұзындығына тәуелсіз, тұрақты болып қалады.
    """
    tracks = generate_music_pool(
        MUSIC_PROMPT_TEMPLATE, mode_cfg["unique_tracks"], mode_cfg["unique_track_duration"]
    )

    if len(tracks) == 1 and mode_cfg["target_video_duration"] is None:
        return tracks[0]

    # Бірнеше unique тректі бірізді crossfade арқылы бір loop сегментіне
    # біріктіру.
    merged = tracks[0]
    crossfade = mode_cfg["crossfade"]
    for i, next_track in enumerate(tracks[1:], start=1):
        step_out = WORKDIR / f"merged_{i}.wav"
        run_ffmpeg([
            "-i", str(merged), "-i", str(next_track),
            "-filter_complex", f"acrossfade=d={crossfade}:c1=tri:c2=tri",
            str(step_out),
        ])
        merged = step_out

    target_duration = mode_cfg["target_video_duration"]
    if target_duration is None:
        return merged

    looped_path = WORKDIR / "looped_audio.wav"
    run_ffmpeg([
        "-stream_loop", "-1", "-i", str(merged),
        "-t", str(target_duration),
        "-c:a", "pcm_s16le",
        str(looped_path),
    ])
    return looped_path


# --------------------------------------------------------------------------
# 3) ВИДЕО РЕНДЕРІ (FFmpeg)
# --------------------------------------------------------------------------

def render_video(image_path: Path, audio_path: Path, width: int, height: int,
                  out_path: Path, fade_seconds: float = 2.0) -> Path:
    duration = ffprobe_duration(audio_path)
    fade_out_start = max(0.0, duration - fade_seconds)

    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    af = f"afade=t=in:st=0:d={fade_seconds},afade=t=out:st={fade_out_start}:d={fade_seconds}"

    run_ffmpeg([
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-vf", vf,
        "-af", af,
        "-c:v", "libx264", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(out_path),
    ])
    log(f"Видео дайын: {out_path}")
    return out_path


# --------------------------------------------------------------------------
# 4) SEO МЕТАДЕРЕКТЕРІ (Claude / Anthropic API)
# --------------------------------------------------------------------------

def generate_seo_metadata(mode: str) -> dict:
    kind = "YouTube Shorts (қысқа, тік форматты)" if mode == "shorts" else "YouTube ұзын видео (10-15 минут)"
    fallback = {
        "title": (
            "Dark Romance R&B Mix 🖤🌹 | Late Night Chill Vibes #shorts"
            if mode == "shorts" else
            "Bedroom R&B Mix — Dark Romantic Late Night Vibes (10 Min Chill Session)"
        ),
        "description": (
            "Slow chill R&B beats for a dark, romantic late-night mood.\n\n"
            "#bedroomrnb #darkromance #chillmusic #rnb #lofi #moodmusic"
        ),
        "tags": [
            "bedroom rnb", "dark romance music", "chill rnb", "late night vibes",
            "r&b mix", "moody music", "lofi rnb", "sensual music", "chillhop",
        ],
    }

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log("ANTHROPIC_API_KEY жоқ — үлгі (fallback) метадеректер қолданылады.")
        return fallback

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""Сен YouTube SEO мамансысың. "Bedroom R&B / Dark Romance / Chill Music"
бағытындағы {kind} үшін SEO-оңтайландырылған метадеректер жаса.

Тек келесі пішіндегі таза JSON қайтар (басқа мәтін болмасын):
{{
  "title": "қызықтыратын, SEO-фразалары бар атау (70 таңбадан аспасын)",
  "description": "2-3 абзац сипаттама, соңында релевантты хэштегтер",
  "tags": ["10-15 релевантты кілт сөз/тег"]
}}"""

        msg = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in msg.content if hasattr(block, "text"))
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
        data = json.loads(text)
        return {
            "title": data["title"],
            "description": data["description"],
            "tags": data["tags"],
        }
    except Exception as exc:  # noqa: BLE001
        log(f"Claude арқылы SEO генерациялау сәтсіз болды ({exc}) — fallback қолданылады.")
        return fallback


# --------------------------------------------------------------------------
# 5) YOUTUBE АВТО-ЖҮКТЕУ
# --------------------------------------------------------------------------

def get_youtube_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    return build("youtube", "v3", credentials=creds)


def upload_to_youtube(file_path: Path, metadata: dict) -> str:
    from googleapiclient.http import MediaFileUpload

    youtube = get_youtube_service()
    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata["tags"],
            "categoryId": "10",  # Music
        },
        "status": {
            "privacyStatus": os.environ.get("YT_PRIVACY_STATUS", "public"),
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(file_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log(f"Жүктелуде: {int(status.progress() * 100)}%")

    video_id = response["id"]
    log(f"YouTube-қа жүктелді: https://youtu.be/{video_id}")
    return video_id


# --------------------------------------------------------------------------
# 6) TELEGRAM ХАБАРЛАМАСЫ
# --------------------------------------------------------------------------

def notify_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"Telegram хабарламасы жіберілмеді: {exc}")


# --------------------------------------------------------------------------
# ГЛАВНЫЙ КОНВЕЙЕР
# --------------------------------------------------------------------------

def run_pipeline(mode: str, upload: bool = True) -> Path:
    if mode not in MODES:
        raise ValueError(f"Белгісіз режим: {mode}")

    cfg = MODES[mode]
    width, height = cfg["image_size"]

    log(f"=== Режим: {mode} ({width}x{height}) ===")

    orientation = "portrait" if height >= width else "landscape"
    image_path = get_background_image(orientation)

    audio_path = build_audio_track(cfg)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    final_video_path = OUTPUT_DIR / f"video{cfg['video_suffix']}_{timestamp}.mp4"
    render_video(image_path, audio_path, width, height, final_video_path)

    if upload:
        metadata = generate_seo_metadata(mode)
        log(f"Тақырып: {metadata['title']}")
        video_id = upload_to_youtube(final_video_path, metadata)
        notify_telegram(
            f"✅ CRIMSONROOM: жаңа видео жүктелді ({mode})\n"
            f"{metadata['title']}\n"
            f"https://youtu.be/{video_id}"
        )
    else:
        log("Жүктеу өткізіп жіберілді (--no-upload).")

    return final_video_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Bedroom R&B YouTube автопилот")
    parser.add_argument("--mode", choices=list(MODES.keys()), default="shorts")
    parser.add_argument("--no-upload", action="store_true", help="YouTube-қа жүктемей, тек видео жасайды")
    args = parser.parse_args()

    try:
        run_pipeline(args.mode, upload=not args.no_upload)
    except Exception as exc:  # noqa: BLE001
        log(f"ҚАТЕ: {exc}")
        notify_telegram(f"❌ CRIMSONROOM: видео генерациясы сәтсіз аяқталды ({args.mode})\n{exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
