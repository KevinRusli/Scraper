# Lead Scraper

Cari leads bisnis cukup dengan memasukkan **sektor bisnis** dan **negara** (opsional: kota).
Setiap lead yang sudah pernah keluar dicatat di database lokal (`leads.db`), jadi **tidak
akan muncul lagi** di pencarian berikutnya. Tidak ada duplikasi data.

## Instalasi

```bash
pip install -r requirements.txt
```

Butuh Python 3.9+.

## Cara pakai

### Mode interaktif (paling gampang)

```bash
python -m lead_scraper
```

```
=== Lead Scraper ===
Sektor bisnis (contoh: restaurant, dentist, bengkel): dentist
Negara (contoh: Indonesia): Indonesia
Kota (opsional, pisahkan dengan koma, Enter = seluruh negara): Jakarta
Jumlah leads baru [50]: 50
```

### Lewat command line

```bash
# 50 leads dokter gigi di Indonesia
python -m lead_scraper search -s dentist -c Indonesia

# 100 leads restoran di Jakarta & Bandung
python -m lead_scraper search -s restaurant -c Indonesia --city Jakarta --city Bandung -n 100

# Hanya leads yang punya nomor telepon, sekalian cari email di website-nya
python -m lead_scraper search -s bengkel -c Indonesia --city Surabaya --require phone --find-emails
```

Hasil disimpan ke `results/<waktu>_<sektor>_<negara>.csv` (bisa langsung dibuka di Excel)
dan hanya berisi **leads baru**. Jalankan perintah yang sama lagi → yang keluar adalah
leads berikutnya yang belum pernah keluar.

| Opsi | Keterangan |
|---|---|
| `-s, --sector` | Sektor bisnis (Inggris atau Indonesia: `restaurant`, `klinik`, `bengkel`, `hotel`, ...) |
| `-c, --country` | Negara |
| `--city` | Kota, boleh diulang |
| `-n, --limit` | Jumlah leads baru yang diinginkan (default 50, `0` = semua) |
| `-p, --provider` | `osm`, `google`, atau `auto` (default: Google jika ada API key, selain itu OSM) |
| `--require` | `phone`, `email`, `website`, atau `any-contact` — hanya ambil leads yang punya kontak tsb |
| `--find-emails` | Cari alamat email di website tiap lead baru |
| `-o, --output` / `-f, --format` | File output / format `csv` atau `json` |
| `--dry-run` | Lihat hasil tanpa menandai leads sebagai sudah keluar |
| `--osm-tag key=value` | Tag OpenStreetMap tambahan untuk sektor yang tidak dikenali |

### Perintah lain

```bash
python -m lead_scraper stats                    # ringkasan leads yang sudah pernah keluar
python -m lead_scraper export -o semua.csv      # ekspor seluruh leads yang pernah keluar
python -m lead_scraper import leads_lama.csv    # tandai leads dari file lama agar tidak keluar lagi
python -m lead_scraper sectors                  # daftar sektor yang dikenali
```

`import` menerima CSV/JSON dengan kolom seperti `name`, `phone`, `email`, `website`,
`address` — cocok kalau Anda sudah punya daftar leads dari sebelumnya.

## Sumber data

| Provider | Biaya | Kelebihan / kekurangan |
|---|---|---|
| **OpenStreetMap** (`osm`) | Gratis, tanpa API key | Data dari komunitas; kelengkapan telepon/website bervariasi per daerah |
| **Google Places** (`google`) | Butuh API key ([Google Maps Platform](https://developers.google.com/maps/documentation/places/web-service/text-search)), ada kuota gratis bulanan | Data lebih lengkap (telepon, website, rating). Maks. 60 hasil per query, jadi cari per kota (`--city`) untuk hasil lebih banyak |

Pakai Google:

```bash
export GOOGLE_MAPS_API_KEY="API_KEY_ANDA"
python -m lead_scraper search -s dentist -c Indonesia --city Jakarta
```

Untuk OSM, disarankan set `LEAD_SCRAPER_CONTACT` (email/URL Anda) sesuai kebijakan
penggunaan Nominatim/Overpass. Pencarian seluruh negara untuk sektor yang sangat banyak
(mis. restoran di seluruh Indonesia) bisa lambat — pakai `--city` agar lebih cepat.

## Cara kerja anti-duplikat

Setiap lead yang dikeluarkan disimpan di `leads.db` (SQLite) beserta beberapa "kunci":

- ID dari sumber data (ID OpenStreetMap / Google Place ID)
- Nomor telepon (dinormalisasi: `+62 21 555 1234` = `021-5551234`)
- Email
- Website (tanpa `https://`, `www.`, dll.; link Facebook/Instagram/WhatsApp diabaikan)
- Nama bisnis + lokasi (± 100 m)

Lead baru dianggap duplikat jika **salah satu** kuncinya sudah ada — jadi bisnis yang sama
tetap terdeteksi walaupun datang dari provider lain, kota lain, atau sektor lain. Cabang
dengan website atau nomor telepon yang sama dianggap perusahaan yang sama.

Catatan:

- `leads.db` adalah "ingatan" scraper. Jangan dihapus kalau tidak mau leads lama muncul lagi,
  dan backup secara berkala. Hapus file ini untuk mulai dari nol. Lokasinya bisa diubah
  dengan `--db path/ke/file.db` atau env `LEAD_SCRAPER_DB`.
- Leads yang dilewati karena `--require` tidak disimpan, jadi masih bisa muncul nanti.
- Leads hanya ditandai setelah file hasil berhasil disimpan (dan tidak ditandai saat `--dry-run`).

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```
