# Warkop Bahenol - Aplikasi Kasir Online untuk Cafe / Warkop

Aplikasi kasir (POS) berbasis web yang bisa diakses online, cocok untuk cafe, warkop, dan usaha F&B kecil-menengah.

## Fitur

- **Login multi user** (Admin & Kasir)
- **Kasir / POS** cepat: pilih produk, keranjang, diskon, berbagai metode bayar (Tunai, QRIS, Transfer)
- **Manajemen Produk** & stok
- **Riwayat Transaksi** detail
- **Pengeluaran** (bahan baku, operasional, gaji, dll)
- **Laporan Laba Rugi** lengkap + analisis produk terlaris, metode bayar, penjualan harian
- **Dashboard** real-time: penjualan hari ini, laba bersih, chart 7 hari
- **Pengaturan toko** (nama, alamat, pajak)

## Cara Menjalankan (Lokal)

```bash
cd warkop_pos
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Buka browser: http://localhost:5000

### Akun Default
- Admin: `admin` / `admin123`
- Kasir: `kasir` / `kasir123`

## Deploy Online (Gratis)

Bisa di-deploy ke:
- **Render.com** (free tier)
- **Railway.app**
- **PythonAnywhere**
- **VPS** sendiri

Contoh di Render:
1. Push folder ini ke GitHub
2. Buat Web Service baru di Render
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Tambahkan Environment Variable `SECRET_KEY` (random string)

## Teknologi
- Python Flask
- SQLite (bisa diganti PostgreSQL nanti)
- Bootstrap 5
- Chart.js

## Selanjutnya (AI Analysis)
Semakin banyak data transaksi yang masuk, kita bisa terus diskusi untuk menambah analisis cerdas, misalnya:
- Prediksi stok
- Rekomendasi promo
- Analisis jam ramai
- dll

Hubungi developer untuk kustomisasi lebih lanjut.
