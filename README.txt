WA Booking Parser - Travel Wise
================================

SETUP AWAL (sekali aja)
------------------------
1. Install Tesseract OCR engine (ini program terpisah, BUKAN cuma pip install):
   Download installer Windows di:
   https://github.com/UB-Mannheim/tesseract/wiki
   Install seperti biasa (Next-Next-Finish), catat lokasi instalnya
   (defaultnya: C:\Program Files\Tesseract-OCR\tesseract.exe)

2. Buka app.py, di bagian paling atas ada baris (di-comment):
   # pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

   Kalau nanti pas run muncul error "tesseract is not installed or it's not
   in your PATH", hapus tanda # di depan baris itu dan sesuaikan path-nya
   sama lokasi hasil install Tesseract-OCR di komputer lu. Kalau installnya
   pake lokasi default, biasanya ga perlu diubah, tinggal uncomment aja.

3. Aktifin venv, install dependency Python:
   .venv\Scripts\activate
   pip install -r requirements.txt

CARA PAKAI
----------
Jalanin:
   streamlit run app.py

Ada 2 mode di app-nya:

A) Paste teks WA -> klik "Parse"
   Otomatis deteksi salah satu dari 3 format:
   - Rekap bulanan (banyak booking sekaligus) -> jadi tabel, bisa download CSV
   - Detail passenger (Full name/Country/Passport/Email/DOB) -> jadi field per
     passenger + notes siap-copy
   - Baris ringkas ("Tgl 11. 2 pax deck" + nama sales) -> jadi field
     tanggal/pax/cabin/sales

B) Upload foto passport (opsional, di bagian bawah halaman)
   Bisa upload LEBIH DARI SATU foto sekaligus (drag beberapa file, atau
   klik browse lalu select-multiple).

   Tiap foto diproses jadi 4 field: Nama, No. Passport, Nationality, Age
   (Age dihitung otomatis dari tanggal lahir, ga perlu dihitung manual).

   Urutan proses tiap foto:
   1. Coba baca MRZ (baris kode di bawah passport) dulu -- ini paling
      akurat karena field angkanya (no. passport, tanggal lahir) divalidasi
      pake checksum matematis bawaan MRZ.
   2. Kalau MRZ ga kedeteksi (foto ga kefoto sampe bagian bawah, atau
      emang passportnya ga ada MRZ), otomatis fallback baca dari teks
      tercetak biasa (label "Surname", "Given name", "Nationality",
      "Passport No", dll). Ini kurang akurat karena ga ada checksum,
      SELALU cek manual ke foto aslinya.

   Kalau upload lebih dari 1 foto, di bagian bawah ada tabel ringkasan
   semua foto sekaligus + tombol download CSV.

CATATAN PENTING
----------------
- 100% jalan lokal. TIDAK ada panggilan ke AI/API apapun, baik buat parsing
  teks maupun OCR gambar. Gratis, ga makan token, Claude tetep full available
  buat analisis kapan aja.
- Field ANGKA hasil OCR lewat jalur MRZ (no. passport, tanggal lahir)
  divalidasi pake checksum bawaan MRZ (rumus matematika standar passport
  internasional). Kalau statusnya "checksum valid", hampir pasti bener.
  Kalau "checksum GAGAL", itu tandanya OCR salah baca, cek manual ke foto.
- Field NAMA sengaja TIDAK ditebak urutan depan/belakangnya (surname vs
  given name), karena field ini ga ada checksum-nya dan gampang salah kalau
  fotonya kurang tajam. Selalu cocokin ke foto aslinya.
- Kalau MRZ ga kedeteksi, tool otomatis fallback ke baca teks tercetak
  biasa. Jalur ini TIDAK ada validasi checksum sama sekali, jadi WAJIB
  dicek manual ke foto, terutama buat nama dan tanggal lahir.
- Kalau MRZ ga kedeteksi sama sekali DAN fallback teks juga hasilnya
  berantakan, biasanya karena foto miring/blur/pantulan cahaya. Coba foto
  ulang lebih rata dan terang, pastiin seluruh halaman passport (termasuk
  baris kode di bawah kalau ada) kefoto jelas.
- Kalau baris teks WA gagal ke-parse (format baru), tool bakal nunjukkin
  daftar baris yang gagal biar bisa dicek manual, bukan ditebak asal.
