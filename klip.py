import subprocess
import tempfile
import os
import time
from faster_whisper import WhisperModel
from deep_translator import GoogleTranslator

# --- KONFIGURASI KLIP ---
URL_VIDEO = "https://youtu.be/4HgaGCmKaDQ?si=OLh9Rl9_Y8GneKxm"
MULAI = "00:16:40"
SELESAI = "00:16:50"
NAMA_FILE_HASIL = "alikhan.mp4"

desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
OUTPUT_FINAL = os.path.join(desktop_path, NAMA_FILE_HASIL)


def format_waktu(detik):
    jam, sisa = divmod(detik, 3600)
    menit, det = divmod(sisa, 60)
    return f"{int(jam):02}:{int(menit):02}:{int(det):02},{int((det - int(det)) * 1000):03}"


def terjemahkan_segmen(translator, teks, cache, max_retry=3):
    """Terjemahkan teks penuh satu segmen dengan delay & retry."""
    teks = teks.strip()
    if not teks:
        return teks
    if teks in cache:
        return cache[teks]

    for percobaan in range(1, max_retry + 1):
        try:
            # Jeda 0.5 detik SEBELUM request (hindari rate limit)
            time.sleep(0.5)
            hasil = translator.translate(teks)
            if hasil and hasil.strip():
                cache[teks] = hasil
                return hasil
            print(f"   [peringatan] hasil kosong untuk segmen ini")
        except Exception as e:
            print(f"   [peringatan] percobaan {percobaan} gagal: {e}")
            # Backoff: tunggu lebih lama setiap kali gagal
            time.sleep(2.0 * percobaan)

    print(f"   [GAGAL] semua percobaan gagal, pakai teks asli.")
    cache[teks] = teks
    return teks


with tempfile.TemporaryDirectory() as tmpdir:
    raw_vid = os.path.join(tmpdir, "raw.mp4")
    sub_srt_file = os.path.join(tmpdir, "sub.srt")

    print("1. Mengunduh potongan video...")
    subprocess.run([
        "yt-dlp", "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]",
        "--download-sections", f"*{MULAI}-{SELESAI}",
        "--force-keyframes-at-cuts", "-o", raw_vid, URL_VIDEO
    ], check=True)

    print("2. Mendeteksi bahasa & mentranskrip...")
    model = WhisperModel("medium", device="cpu", compute_type="int8")
    segments, info = model.transcribe(raw_vid, word_timestamps=True)

    bahasa = (info.language or "").lower()
    print(f"   → Bahasa terdeteksi: {bahasa}")

    if bahasa in ("id", "ms"):
        perlu_terjemah = False
        print("3. Video sudah berbahasa Indonesia/Melayu — subtitle apa adanya.")
    else:
        perlu_terjemah = True
        print(f"3. Menerjemahkan per segmen penuh ({bahasa} → id) dengan deep-translator...")
        translator = GoogleTranslator(source="auto", target="id")

    cache = {}

    with open(sub_srt_file, "w", encoding="utf-8") as f:
        counter = 1
        for segment in segments:
            # Terjemahkan SELURUH teks segmen dulu (bukan per 3 kata)
            if perlu_terjemah:
                teks_segmen_id = terjemahkan_segmen(translator, segment.text, cache)
            else:
                teks_segmen_id = segment.text.strip()

            # Pecah hasil terjemahan menjadi potongan kata untuk subtitle dinamis
            kata_kata = teks_segmen_id.split()
            words = segment.words if hasattr(segment, "words") and segment.words else []

            if not words or not kata_kata:
                # Fallback: tulis satu blok utuh
                f.write(
                    f"{counter}\n"
                    f"{format_waktu(segment.start)} --> {format_waktu(segment.end)}\n"
                    f"{teks_segmen_id}\n\n"
                )
                counter += 1
                continue

            # Bagi kata terjemahan menjadi chunk 3 kata,
            # tapi gunakan timestamp dari kata ASLI (karena jumlah kata bisa beda)
            chunk_size = 3
            total_chunk = (len(kata_kata) + chunk_size - 1) // chunk_size

            # Ambil timestamp awal & akhir dari words asli sebagai patokan
            t_start = segment.start
            t_end = segment.end

            # Bagi durasi segmen secara proporsional berdasarkan jumlah chunk
            durasi = t_end - t_start
            durasi_per_chunk = durasi / total_chunk if total_chunk > 0 else durasi

            for i in range(total_chunk):
                chunk_kata = kata_kata[i * chunk_size:(i + 1) * chunk_size]
                teks_chunk = " ".join(chunk_kata)

                start_t = t_start + (i * durasi_per_chunk)
                end_t = start_t + durasi_per_chunk

                f.write(
                    f"{counter}\n"
                    f"{format_waktu(start_t)} --> {format_waktu(end_t)}\n"
                    f"{teks_chunk}\n\n"
                )
                counter += 1

    print("4. Merender video...")
    sub_srt_escaped = sub_srt_file.replace("\\", "/").replace(":", "\\:")

    style = (
        "FontName=Impact,FontSize=15,"
        "PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,"
        "Outline=2.5,Alignment=2,MarginV=80"
    )

    filter_complex = (
        "[0:v]split[v1][v2];"
        "[v1]scale=1080:1350:force_original_aspect_ratio=increase,"
        "crop=1080:1350,gblur=sigma=25[bg];"
        "[v2]scale=1080:-2[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
        f"subtitles='{sub_srt_escaped}':force_style='{style}'"
    )

    subprocess.run([
        "ffmpeg", "-y", "-i", raw_vid,
        "-filter_complex", filter_complex,
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "aac", "-b:a", "192k", OUTPUT_FINAL
    ], check=True)

print(f"\nSelesai! Cek file '{NAMA_FILE_HASIL}' di Desktop Anda.")