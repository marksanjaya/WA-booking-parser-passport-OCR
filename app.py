"""
WA Booking Parser - Travel Wise
--------------------------------
Parser berbasis rule (regex), TANPA panggil AI/API sama sekali.
Jalan 100% lokal, gratis, ga ada token yang kepake.

Cara jalanin:
    py -m streamlit run app.py
"""

import re
import io
import pandas as pd
import streamlit as st
from PIL import Image
import pytesseract

# Kalau di Windows dan tesseract.exe ga otomatis kedetect, uncomment baris
# di bawah dan sesuaikan path-nya sama lokasi hasil install Tesseract-OCR:
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ---------------------------------------------------------------------------
# KAMUS & REGEX
# ---------------------------------------------------------------------------

DAY_NAMES = [
    "senin", "selasa", "rabu", "kamis", "jumat", "jum'at", "sabtu", "minggu",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
]

MONTH_NAMES = [
    "januari", "january", "februari", "february", "maret", "march", "april",
    "mei", "may", "juni", "june", "juli", "july", "agustus", "august",
    "september", "oktober", "october", "november", "desember", "december",
]

DATE_HEADER_RE = re.compile(
    r"^[\*#\s]*(?P<day>" + "|".join(DAY_NAMES) + r")\s+(?P<num>\d{1,2})"
    r"(st|nd|rd|th)?\s+(?P<month>" + "|".join(MONTH_NAMES) + r")[\*#\s]*$",
    re.IGNORECASE,
)

MONTH_HEADER_RE = re.compile(
    r"^[#\*\s]*(?P<month>" + "|".join(MONTH_NAMES) + r")[#\*\s]*$",
    re.IGNORECASE,
)

BULLET_RE = re.compile(r"^-\s*(?P<rest>.+)$")
PAX_IN_LINE_RE = re.compile(r"(\d+)\s*(?:people|pax)", re.IGNORECASE)
HARGA_RE = re.compile(r"harga\s*[\d.,]+", re.IGNORECASE)
TRAILING_PAX_RE = re.compile(r",?\s*\d+\s*(?:people|pax)\s*$", re.IGNORECASE)

PASSENGER_HEADER_RE = re.compile(r"passenger\s*\d+\s*:?", re.IGNORECASE)

# Prefix metadata WA kalau di-copy dari chat export, misal:
# "[3:00 pm, 08/07/2026] mas Imamm: Tgl 11. 2 pax deck"
WA_PREFIX_RE = re.compile(
    r"^\[\d{1,2}:\d{2}\s*(?:am|pm)?,\s*\d{1,2}/\d{1,2}/\d{2,4}\]\s*[^:]+:\s*",
    re.IGNORECASE,
)

TGL_LINE_RE = re.compile(
    r"^Tgl\s*(?P<tgl>\d{1,2})\.?\s*(?P<pax>\d+)\s*pax\s+(?P<rest>.+)$",
    re.IGNORECASE,
)


def strip_wa_prefix(line: str) -> str:
    return WA_PREFIX_RE.sub("", line).strip()


def extract_schedule_info(lines):
    """Cari baris 'Tgl X. N pax <cabin>' -- nama sales bisa nempel di baris
    yang sama (dipisah titik) ATAU di baris berikutnya (format WA asli)."""
    for idx, raw_line in enumerate(lines):
        line = strip_wa_prefix(raw_line.strip())
        m = TGL_LINE_RE.match(line)
        if not m:
            continue

        rest = m.group("rest").strip()
        sales = None

        if "." in rest:
            cabin_part, name_part = rest.split(".", 1)
            cabin_part = cabin_part.strip()
            name_part = name_part.strip()
            if name_part:
                sales = name_part
        else:
            cabin_part = rest.rstrip(".").strip()

        if not sales:
            # nama sales sering nempel di baris SETELAHNYA, bukan satu baris
            for j in range(idx + 1, min(idx + 3, len(lines))):
                nxt = strip_wa_prefix(lines[j].strip())
                if not nxt:
                    continue
                if ":" in nxt or len(nxt.split()) > 4:
                    break
                sales = nxt
                break

        return {
            "tgl": m.group("tgl"),
            "pax": m.group("pax"),
            "cabin": classify_cabin(cabin_part),
            "sales": sales or "(ga ketemu, cek manual)",
        }

    return None

PASSENGER_LABELS = {
    "full name": "name",
    "country": "country",
    "passeport number": "passport",
    "passport number": "passport",
    "email": "email",
    "date of birth": "dob",
}

# Format baru: "Trip Detail" -- Trip / Departure date / Name / Phone / Email /
# Guest / Classe / Pick up point
TRIP_DETAIL_LABELS = {
    "departure date": "departure_date",
    "pick up point": "pickup",
    "trip": "trip",
    "name": "name",
    "phone": "phone",
    "email": "email",
    "guest": "guest",
    "classe": "cabin_class",
    "class": "cabin_class",
}


def parse_trip_detail_block(text: str) -> dict:
    lines = text.splitlines()
    data = {}
    i = 0
    while i < len(lines):
        line = strip_wa_prefix(lines[i].strip())
        for label, key in TRIP_DETAIL_LABELS.items():
            if line.lower().startswith(label):
                value = line.split(":", 1)[1].strip() if ":" in line else ""
                if not value and i + 1 < len(lines):
                    nxt = strip_wa_prefix(lines[i + 1].strip())
                    if nxt and not any(nxt.lower().startswith(l) for l in TRIP_DETAIL_LABELS):
                        value = nxt
                        i += 1
                data[key] = value
                break
        i += 1
    return data


def classify_cabin(raw: str) -> str:
    r = raw.lower()
    if "shere" in r or "shared" in r or "share" in r:
        return "Shared Cabin"
    if "private" in r:
        return "Private Cabin"
    if "deck" in r:
        return "Deck"
    return raw.strip().title() if raw.strip() else "-"


# ---------------------------------------------------------------------------
# PARSER: FORMAT REKAP BULANAN (list per tanggal)
# ---------------------------------------------------------------------------

def parse_rekap_list(text: str):
    rows = []
    failed_lines = []
    current_month = ""
    current_date_label = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m_month = MONTH_HEADER_RE.match(line)
        if m_month:
            current_month = m_month.group("month").title()
            continue

        m_date = DATE_HEADER_RE.match(line)
        if m_date:
            current_date_label = (
                f"{m_date.group('day').title()} {m_date.group('num')} "
                f"{m_date.group('month').title()}"
            )
            continue

        m_bullet = BULLET_RE.match(line)
        if m_bullet:
            rest = m_bullet.group("rest")

            pax_match = PAX_IN_LINE_RE.search(rest)
            pax = pax_match.group(1) if pax_match else "?"

            if "(" in rest:
                name_part, cabin_part = rest.split("(", 1)
                cabin_raw = cabin_part.rsplit(")", 1)[0] if ")" in cabin_part else cabin_part
            else:
                name_part, cabin_raw = rest, ""

            name = TRAILING_PAX_RE.sub("", name_part).strip().rstrip(",").strip()

            price_match = HARGA_RE.search(cabin_raw)
            price_note = price_match.group(0) if price_match else ""
            cabin_clean = HARGA_RE.sub("", cabin_raw).strip()

            # kalau ada lebih dari 1 sebutan "N people/pax" di dalam kurung,
            # itu breakdown campuran (misal 2 private + 4 shared) -- jangan ditebak,
            # tandain buat dicek manual biar ga salah input.
            inner_pax_mentions = PAX_IN_LINE_RE.findall(cabin_raw)
            if len(inner_pax_mentions) > 1:
                cabin_type = f"CAMPURAN, cek manual: {cabin_clean}"
            else:
                cabin_type = classify_cabin(cabin_clean)

            if not name:
                failed_lines.append(raw_line)
                continue

            rows.append({
                "Month": current_month,
                "Date": current_date_label,
                "Customer Name": name,
                "Pax": pax,
                "Cabin Type": cabin_type,
                "Price Note": price_note,
                "Status": "Pending",
                "Source": "WhatsApp",
            })
            continue

        # baris lain yang ga match apapun (misal judul "Rekap tamu...")
        if line.startswith("-"):
            failed_lines.append(raw_line)

    return rows, failed_lines


# ---------------------------------------------------------------------------
# PARSER: FORMAT PASSENGER DETAIL (+ baris ringkas opsional)
# ---------------------------------------------------------------------------

def parse_passenger_block(text: str):
    lines = text.splitlines()
    passengers = []
    current = None

    i = 0
    while i < len(lines):
        line = strip_wa_prefix(lines[i].strip())

        if PASSENGER_HEADER_RE.match(line):
            if current is not None:
                passengers.append(current)
            current = {}
            i += 1
            continue

        matched = False
        for label, key in PASSENGER_LABELS.items():
            if line.lower().startswith(label):
                value = line.split(":", 1)[1].strip() if ":" in line else ""
                if not value and i + 1 < len(lines):
                    nxt = strip_wa_prefix(lines[i + 1].strip())
                    if nxt and not any(nxt.lower().startswith(l) for l in PASSENGER_LABELS) \
                            and not PASSENGER_HEADER_RE.match(nxt):
                        value = nxt
                        i += 1
                if current is not None:
                    current[key] = value
                matched = True
                break
        i += 1

    if current is not None:
        passengers.append(current)

    schedule_info = extract_schedule_info(lines)
    return passengers, schedule_info


def _age_from_ddmmyyyy(dd: str, mm: str, yyyy: str):
    import datetime
    try:
        dob = datetime.date(int(yyyy), int(mm), int(dd))
    except ValueError:
        return None
    today = datetime.date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return age


def _mrz_date(yymmdd: str, is_expiry: bool) -> str:
    if len(yymmdd) != 6 or not yymmdd.isdigit():
        return yymmdd
    yy, mm, dd = yymmdd[0:2], yymmdd[2:4], yymmdd[4:6]
    import datetime
    current_yy = datetime.date.today().year % 100
    if is_expiry:
        century = "20"
    else:
        century = "19" if int(yy) > current_yy else "20"
    return f"{dd}/{mm}/{century}{yy} (mentah: {yymmdd})"


# --- Fallback: baca dari teks tercetak biasa kalau MRZ ga kedeteksi -------
# Confidence lebih rendah dari MRZ (ga ada checksum), selalu perlu cek manual.

LABEL_STOPWORDS = {
    "PASSPORT", "PASAPORTE", "PASSEPORT", "REISEPASS", "TYPE", "TYP",
    "SURNAME", "SUMAME", "NAME", "NOM", "NOME", "GIVEN", "NAMES", "PRENOMS",
    "PRÉNOMS", "VORNAMEN", "NATIONALITY", "NATIONALITÉ", "NACIONALIDAD",
    "STAATSANGEHORIGKEIT", "SEX", "SEXE", "DATE", "BIRTH", "GEBURTSTAG",
    "NAISSANCE", "NACIMIENTO", "AUTHORITY", "AUTORITE", "AUTORITÉ",
    "BEHORDE", "REPUBLIK", "DEUTSCHLAND", "ESPANA", "REINO", "PLACE",
    "LIEU", "LUGAR", "ISSUE", "EXPIRY", "EXPIRATION", "SIGNATURE",
    "BEARER", "INHABERIN", "INHABERS", "TITULAIRE", "TITULARE",
}

NATIONALITY_LABEL_WORDS = ["nationality", "nationalité", "staatsangehorigkeit", "nacionalidad"]
SURNAME_LABEL_WORDS = ["surname", "sumame", "apellidos", "nom"]
GIVEN_NAME_LABEL_WORDS = ["given name", "vornamen", "prénoms", "prenoms", "nombre"]
PASSPORT_NO_LABEL_WORDS = ["passport no", "passport number", "pas n", "pasaporte n"]


def _find_caps_token_after(text: str, labels, window: int = 150, min_len: int = 2):
    lower = text.lower()
    for label in labels:
        idx = lower.find(label)
        if idx == -1:
            continue
        chunk = text[idx: idx + window]
        for tok in re.findall(r"[A-ZÀ-Ö][A-ZÀ-Ö\-]{%d,}" % (min_len - 1), chunk):
            if tok in LABEL_STOPWORDS:
                continue
            return tok
    return None


def extract_from_printed_text(ocr_text: str) -> dict:
    flat = re.sub(r"\s+", " ", ocr_text)

    surname = _find_caps_token_after(flat, SURNAME_LABEL_WORDS)
    given = _find_caps_token_after(flat, GIVEN_NAME_LABEL_WORDS)
    name_parts = [p for p in (given, surname) if p]
    name = " ".join(name_parts) if name_parts else None

    nationality = _find_caps_token_after(flat, NATIONALITY_LABEL_WORDS)

    # nomor passport: cari token alfanumerik (campuran huruf+angka) di
    # dekat label, kalau ga ketemu ambil kandidat pertama di seluruh teks
    passport_number = None
    lower = flat.lower()
    search_start = 0
    for label in PASSPORT_NO_LABEL_WORDS:
        idx = lower.find(label)
        if idx != -1:
            search_start = idx
            break
    window_text = flat[search_start: search_start + 250]
    for tok in re.findall(r"\b[A-Z0-9]{6,9}\b", window_text):
        if tok in LABEL_STOPWORDS:
            continue
        if tok.isalpha() or tok.isdigit():
            continue  # passport number biasanya campuran huruf+angka
        passport_number = tok
        break

    # tanggal lahir: ambil tanggal PERTAMA yang muncul di teks (biasanya
    # DOB nongol duluan sebelum tanggal terbit/expired paspor)
    age = None
    dob_display = None
    date_match = re.search(r"\b(\d{2})[.\/\-](\d{2})[.\/\-](\d{4})\b", flat)
    if date_match:
        dd, mm, yyyy = date_match.groups()
        age = _age_from_ddmmyyyy(dd, mm, yyyy)
        dob_display = f"{dd}/{mm}/{yyyy}"

    return {
        "name_tokens_raw": name_parts if name_parts else [],
        "passport_number": passport_number or "-",
        "nationality": nationality or "-",
        "dob": dob_display or "-",
        "age": age,
        "source": "printed_text",
    }


# --- Fallback: baca dari teks tercetak biasa kalau MRZ ga kedeteksi -------


def parse_short_only(text: str):
    return extract_schedule_info(text.splitlines())


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    """Grayscale + upscale + kontras biar Tesseract lebih gampang baca MRZ,
    terutama dari foto HP yang resolusinya gede tapi teksnya kecil di frame."""
    from PIL import ImageOps, ImageEnhance

    img = image.convert("L")  # grayscale

    # upscale kalau gambar masih kecil, MRZ butuh detail tinggi
    max_dim = max(img.size)
    if max_dim < 2000:
        scale = 2000 / max_dim
        new_size = (int(img.width * scale), int(img.height * scale))
        img = img.resize(new_size, Image.LANCZOS)

    img = ImageOps.autocontrast(img)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    return img


# ---------------------------------------------------------------------------
# OCR PASSPORT (Tesseract, lokal) + MRZ PARSER (checksum, murni matematika)
# ---------------------------------------------------------------------------

MRZ_CHAR_FIX = {"€": "E", "§": "S", "«": "<", "»": "<", "‹": "<", "›": "<"}
DIGIT_TO_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B", "6": "G", "2": "Z"}


def _mrz_char_value(c: str) -> int:
    if c == "<":
        return 0
    if c.isdigit():
        return int(c)
    if c.isalpha():
        return ord(c) - ord("A") + 10
    return 0


def mrz_check_digit(s: str) -> int:
    weights = [7, 3, 1]
    total = 0
    for i, ch in enumerate(s):
        total += _mrz_char_value(ch) * weights[i % 3]
    return total % 10


def find_mrz_lines(ocr_text: str):
    """Cari 2 baris MRZ (44 karakter, isinya huruf/angka/'<') dari hasil OCR."""
    candidates = []
    for raw in ocr_text.splitlines():
        cleaned = raw.upper().replace(" ", "")
        for bad, good in MRZ_CHAR_FIX.items():
            cleaned = cleaned.replace(bad, good)
        cleaned = re.sub(r"[^A-Z0-9<]", "", cleaned)
        if 30 <= len(cleaned) <= 46 and cleaned.count("<") >= 2:
            candidates.append(cleaned)

    line1 = next((c for c in candidates if c.startswith("P")), None)
    if not line1:
        return None
    idx = candidates.index(line1)
    if idx + 1 >= len(candidates):
        return None
    return line1, candidates[idx + 1]


def parse_mrz(line1: str, line2: str) -> dict:
    line1 = (line1 + "<" * 44)[:44]
    line2 = (line2 + "<" * 44)[:44]

    country = line1[2:5].replace("<", "")

    name_field = line1[5:44]
    name_tokens = [t for t in re.split(r"<+", name_field) if t]

    passport_number = line2[0:9].replace("<", "")
    check1 = line2[9]
    nat_raw = line2[10:13]
    nationality = "".join(DIGIT_TO_LETTER.get(c, c) for c in nat_raw).replace("<", "").strip()
    nationality = nationality or "-"
    dob_raw = line2[13:19]
    check2 = line2[19]
    sex_raw = line2[20]
    expiry_raw = line2[21:27]
    check3 = line2[27]
    personal_number = line2[28:42].replace("<", "")
    check4 = line2[42]

    def valid(field, check):
        try:
            return str(mrz_check_digit(field)) == check
        except Exception:
            return False

    passport_ok = valid(line2[0:9], check1)
    dob_ok = valid(dob_raw, check2)
    expiry_ok = valid(expiry_raw, check3)
    personal_ok = valid(line2[28:42], check4) if personal_number else True

    sex = {"M": "M", "F": "F"}.get(sex_raw, f"{sex_raw} (ga jelas, cek manual)")

    age = None
    if len(dob_raw) == 6 and dob_raw.isdigit():
        dob_formatted = _mrz_date(dob_raw, is_expiry=False)
        # dob_formatted format: "DD/MM/YYYY (mentah: ...)" -> ambil DD/MM/YYYY
        dd, mm, yyyy = dob_formatted.split(" ")[0].split("/")
        age = _age_from_ddmmyyyy(dd, mm, yyyy)

    return {
        "name_tokens_raw": name_tokens,
        "country": country,
        "nationality": nationality,
        "passport_number": passport_number,
        "passport_number_valid": passport_ok,
        "dob": _mrz_date(dob_raw, is_expiry=False),
        "dob_valid": dob_ok,
        "age": age,
        "sex": sex,
        "expiry": _mrz_date(expiry_raw, is_expiry=True),
        "expiry_valid": expiry_ok,
        "personal_number": personal_number,
        "personal_number_valid": personal_ok,
        "raw_line1": line1,
        "raw_line2": line2,
        "source": "mrz",
    }


# ---------------------------------------------------------------------------
# DETEKSI FORMAT
# ---------------------------------------------------------------------------

def detect_format(text: str) -> str:
    lower = text.lower()

    if re.search(r"^trip\s*:", text, re.IGNORECASE | re.MULTILINE) and \
            re.search(r"^departure date\s*:", text, re.IGNORECASE | re.MULTILINE):
        return "trip_detail"

    if "passenger" in lower and "full name" in lower:
        return "passenger"

    bullet_count = len(re.findall(r"^-\s*.+\(.*(?:people|pax).*\)", text, re.MULTILINE | re.IGNORECASE))
    if bullet_count >= 2:
        return "rekap"

    if any(TGL_LINE_RE.match(strip_wa_prefix(l.strip())) for l in text.splitlines()):
        return "short"

    return "unknown"


# ---------------------------------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="WA Booking Parser", layout="centered")
st.title("WA Booking Parser")
st.caption("Rule-based parser -- tanpa AI, jalan lokal, gratis. Buat Travel Wise booking input.")

raw_text = st.text_area("Paste pesan WA di sini", height=280, placeholder="Paste chat WA dari partner...")

if st.button("Parse", type="primary"):
    if not raw_text.strip():
        st.warning("Paste teksnya dulu bro.")
    else:
        fmt = detect_format(raw_text)

        if fmt == "rekap":
            st.success(f"Format terdeteksi: **Rekap bulanan** ({len(re.findall(chr(10)+'-', chr(10)+raw_text))} baris ditemukan)")
            rows, failed = parse_rekap_list(raw_text)

            if rows:
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True)

                csv_buf = io.StringIO()
                df.to_csv(csv_buf, index=False)
                st.download_button(
                    "Download CSV",
                    csv_buf.getvalue(),
                    file_name="rekap_booking.csv",
                    mime="text/csv",
                )
            else:
                st.error("Ga ada baris yang berhasil di-parse.")

            if failed:
                with st.expander(f"{len(failed)} baris gagal di-parse (cek manual)"):
                    for f in failed:
                        st.code(f, language=None)

        elif fmt == "passenger":
            st.success("Format terdeteksi: **Detail passenger**")
            passengers, schedule_info = parse_passenger_block(raw_text)

            if schedule_info:
                st.subheader("Trip Details")
                col1, col2, col3 = st.columns(3)
                col1.metric("Tanggal", schedule_info["tgl"])
                col2.metric("Pax", schedule_info["pax"])
                col3.metric("Cabin", schedule_info["cabin"])
                st.text_input("Sales / PIC inquiry", value=schedule_info["sales"], disabled=True)

            st.subheader(f"Passengers ({len(passengers)})")
            for idx, p in enumerate(passengers, start=1):
                st.markdown(f"**Passenger {idx}**")
                st.text_input(f"Nama {idx}", value=p.get("name", "-"), key=f"name_{idx}", disabled=True)
                c1, c2 = st.columns(2)
                c1.text_input(f"Passport {idx}", value=p.get("passport", "-"), key=f"pp_{idx}", disabled=True)
                c2.text_input(f"Country {idx}", value=p.get("country", "-"), key=f"co_{idx}", disabled=True)
                c3, c4 = st.columns(2)
                c3.text_input(f"Email {idx}", value=p.get("email", "-"), key=f"em_{idx}", disabled=True)
                c4.text_input(f"DOB {idx}", value=p.get("dob", "-"), key=f"dob_{idx}", disabled=True)

            notes_lines = []
            for idx, p in enumerate(passengers, start=1):
                notes_lines.append(
                    f"P{idx}: {p.get('name','-')} | {p.get('country','-')} | "
                    f"Passport {p.get('passport','-')} | {p.get('email','-')} | DOB {p.get('dob','-')}"
                )
            if schedule_info:
                notes_lines.append(f"Inquiry via: {schedule_info['sales']}")

            st.subheader("Notes (siap copy)")
            st.text_area("Notes", value="\n".join(notes_lines), height=140)

        elif fmt == "trip_detail":
            st.success("Format terdeteksi: **Trip Detail**")
            data = parse_trip_detail_block(raw_text)

            st.subheader("Customer")
            st.text_input("Nama", value=data.get("name", "-"), disabled=True)

            st.subheader("Trip Details")
            c1, c2 = st.columns(2)
            c1.text_input("Trip", value=data.get("trip", "-"), disabled=True)
            c2.text_input("Departure Date", value=data.get("departure_date", "-"), disabled=True)
            c3, c4 = st.columns(2)
            c3.text_input("Guest", value=data.get("guest", "-"), disabled=True)
            c4.text_input("Classe / Cabin", value=classify_cabin(data.get("cabin_class", "")) if data.get("cabin_class") else "-", disabled=True)

            st.subheader("Booking Info")
            c5, c6 = st.columns(2)
            c5.text_input("Phone", value=data.get("phone", "-"), disabled=True)
            c6.text_input("Email", value=data.get("email", "-"), disabled=True)
            st.text_input("Pick up point", value=data.get("pickup", "-"), disabled=True)

            notes_val = (
                f"Trip: {data.get('trip','-')} | Departure: {data.get('departure_date','-')} | "
                f"Guest: {data.get('guest','-')} | Class: {data.get('cabin_class','-')} | "
                f"Phone: {data.get('phone','-')} | Email: {data.get('email','-')} | "
                f"Pick up: {data.get('pickup','-')}"
            )
            st.subheader("Notes (siap copy)")
            st.text_area("Notes", value=notes_val, height=100)

        elif fmt == "short":
            st.success("Format terdeteksi: **Baris ringkas**")
            info = parse_short_only(raw_text)
            col1, col2, col3 = st.columns(3)
            col1.metric("Tanggal", info["tgl"])
            col2.metric("Pax", info["pax"])
            col3.metric("Cabin", info["cabin"])
            st.text_input("Sales / PIC inquiry (masuk ke Notes)", value=f"Inquiry via: {info['sales']}", disabled=True)
            st.info("Nama customer ga ada di teks ini (biasanya nempel di foto passport). Cek manual dari gambar.")

        else:
            st.error("Format ga kekenalin. Coba tempel teks lengkapnya, atau kabarin Mark buat nambah pola baru.")

st.divider()
st.subheader("Upload foto passport (opsional, bisa lebih dari satu)")
st.caption(
    "OCR lokal pake Tesseract, ga manggil AI/API. Coba baca MRZ (baris kode di bawah "
    "passport) dulu -- ini paling akurat karena divalidasi checksum matematis. "
    "Kalau MRZ ga kebaca, fallback baca dari teks tercetak biasa (kurang akurat, "
    "selalu cek manual ke foto)."
)

upload_tab, camera_tab = st.tabs(["Upload dari galeri", "Foto langsung (kamera)"])

with upload_tab:
    uploaded_files = st.file_uploader(
        "Foto halaman passport",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )

with camera_tab:
    camera_photo = st.camera_input("Jepret foto passport")

passport_imgs = list(uploaded_files) if uploaded_files else []
if camera_photo is not None:
    camera_photo.name = "kamera.jpg"
    passport_imgs.append(camera_photo)

if passport_imgs:
    all_results = []

    for n, up_file in enumerate(passport_imgs, start=1):
        image = Image.open(up_file)
        st.markdown(f"---\n**Foto {n}: {up_file.name}**")

        col_img, col_data = st.columns([1, 2])
        col_img.image(image, use_container_width=True)

        with st.spinner(f"Membaca foto {n}..."):
            processed = preprocess_for_ocr(image)
            ocr_text = pytesseract.image_to_string(processed)
            mrz_lines = find_mrz_lines(ocr_text)

            if mrz_lines:
                result = parse_mrz(*mrz_lines)
                name_display = " ".join(result["name_tokens_raw"])
                confidence = "MRZ (checksum valid)" if (
                    result["passport_number_valid"] and result["dob_valid"]
                ) else "MRZ (checksum GAGAL sebagian, cek manual)"
            else:
                result = extract_from_printed_text(ocr_text)
                name_display = " ".join(result["name_tokens_raw"]) if result["name_tokens_raw"] else "-"
                confidence = "Teks tercetak (ga ada checksum, WAJIB cek manual)"

        with col_data:
            st.text_input("Nama", value=name_display or "-", key=f"name_{n}", disabled=True)
            cc1, cc2 = st.columns(2)
            cc1.text_input("No. Passport", value=result.get("passport_number", "-"), key=f"pp_{n}", disabled=True)
            cc2.text_input("Nationality", value=result.get("nationality", "-"), key=f"nat_{n}", disabled=True)
            age_display = result.get("age")
            st.text_input("Age", value=str(age_display) if age_display is not None else "-", key=f"age_{n}", disabled=True)
            st.caption(f"Sumber: {confidence}")

        with st.expander(f"Detail teknis foto {n} (raw OCR / MRZ)"):
            if mrz_lines:
                st.code(f"{result['raw_line1']}\n{result['raw_line2']}", language=None)
            else:
                st.text(ocr_text)

        all_results.append({
            "File": up_file.name,
            "Name": name_display or "-",
            "Passport No": result.get("passport_number", "-"),
            "Nationality": result.get("nationality", "-"),
            "Age": age_display if age_display is not None else "-",
            "Source": confidence,
        })

    if len(all_results) > 1:
        st.markdown("---")
        st.subheader("Ringkasan semua foto")
        df_passports = pd.DataFrame(all_results)
        st.dataframe(df_passports, use_container_width=True)
        csv_buf = io.StringIO()
        df_passports.to_csv(csv_buf, index=False)
        st.download_button("Download CSV", csv_buf.getvalue(), file_name="passport_ocr.csv", mime="text/csv")

st.divider()
st.caption("100% lokal, ga ada request ke AI/API. Kalau ada format WA baru yang gagal ke-parse, kirim contohnya buat diupdate.")