# راه‌اندازی نسخهٔ بتا روی سرور داخل ایران

این راهنما سرویس را روی یک سرور مجازی (VPS) داخل ایران بالا می‌آورد: وب‌اپ با
ورود دعوتی، HTTPS خودکار، و به‌روزرسانی ساعتی دادهٔ نوبیتکس. نوبیتکس فقط از
IP ایران جواب می‌دهد، پس این بخش فقط روی سرور داخلی کار می‌کند.

## پیش‌نیازها

* یک VPS لینوکسی (Ubuntu 22.04 یا 24.04)، دست‌کم ۲ هسته و ۲ گیگ رم، از یک
  ارائه‌دهندهٔ داخلی.
* یک دامنه (مثلاً `.ir` از nic.ir) با رکورد A به IP سرور.
* پورت‌های ۸۰ و ۴۴۳ باز.

## روش الف: Docker (پیشنهادی)

Docker Hub و PyPI از داخل ایران معمولاً مسدودند. دو راه هست:

1. **ساخت ایمیج بیرون از ایران و انتقال آن** (مطمئن‌ترین):
   ```bash
   # روی کامپیوتری که به اینترنت آزاد دسترسی دارد
   git clone <repo> && cd NNFXSystem && git checkout ccr-acce0f30-krmwaq
   docker build -f deploy/Dockerfile -t nnfx-beta .
   docker pull caddy:2
   docker save nnfx-beta caddy:2 | gzip > nnfx-beta.tar.gz
   scp nnfx-beta.tar.gz user@SERVER:~
   # روی سرور
   gunzip -c nnfx-beta.tar.gz | docker load
   ```
2. **استفاده از میرور داخلی** Docker Hub و PyPI که ارائه‌دهندهٔ سرورتان معرفی
   می‌کند. آدرس میرورها مرتب عوض می‌شود؛ از پشتیبانی ارائه‌دهنده بپرسید.

سپس روی سرور:
```bash
cd NNFXSystem
cp deploy/.env.example deploy/.env      # NNFX_DOMAIN و NNFX_SYMBOLS را تنظیم کنید
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d
# ساخت حساب مدیر (رمز را می‌پرسد)
docker compose -f deploy/docker-compose.yml exec app /app/.venv/bin/nnfx beta --db /app/runs/beta/beta.db create-admin admin
```

اگر ایمیج را با `docker load` آورده‌اید، در compose بخش `build` نادیده گرفته
می‌شود و از ایمیج موجود استفاده می‌شود. اگر compose خواست بسازد، `--no-build`
بدهید.

## روش ب: بدون Docker

```bash
sudo useradd --system --create-home --home-dir /opt/nnfx nnfx
sudo -u nnfx git clone <repo> /opt/nnfx && cd /opt/nnfx && sudo -u nnfx git checkout ccr-acce0f30-krmwaq
# uv و وابستگی‌ها (اگر pypi.org در دسترس نیست، UV_INDEX_URL را روی میرور بگذارید)
sudo -u nnfx python3 -m pip install --user uv
sudo -u nnfx ~/.local/bin/uv sync --frozen --no-dev
sudo cp deploy/nnfx-beta.service deploy/nnfx-refresh.service deploy/nnfx-refresh.timer /etc/systemd/system/
sudo systemctl enable --now nnfx-beta nnfx-refresh.timer
sudo -u nnfx /opt/nnfx/.venv/bin/nnfx beta --db /opt/nnfx/runs/beta/beta.db create-admin admin
```
برای HTTPS، Caddy را نصب کنید و فایل `deploy/Caddyfile` را با `reverse_proxy 127.0.0.1:8765` به‌کار ببرید.

## ضبط اردربوک

قوانین اردربوک (دیوار، اسپوف) فقط با دادهٔ زنده کار می‌کنند، چون نوبیتکس تاریخچهٔ اردربوک نمی‌دهد. سرویس `orderbook` در Docker هر `NNFX_ORDERBOOK_INTERVAL` ثانیه اردربوک نمادهای `NNFX_ORDERBOOK_SYMBOLS` را می‌گیرد و در volume با نام `orderbook-data` ذخیره می‌کند. هرچه زودتر روشن شود، بک‌تست قوانین اردربوک روی بازهٔ بلندتری ممکن می‌شود. بدون Docker:

```bash
uv run nnfx orderbook record --symbols BTC/IRT USDT/IRT --interval 10 --root data/orderbook
```

اگر یک درخواست خطا بدهد، ضبط‌کننده خطا را چاپ می‌کند و ادامه می‌دهد.

## معاملهٔ کاغذی و هشدارها

هر کاربر از تب «معاملهٔ کاغذی» می‌تواند یکی از استراتژی‌های ذخیره‌شدهٔ خود را روی کندل‌های ۱۵ دقیقهٔ زندهٔ نوبیتکس اجرا و متوقف کند (حداکثر ۳ اجرای هم‌زمان). برنامه هر ۶۰ ثانیه (`--paper-interval`، صفر یعنی خاموش) کندل جدید را می‌گیرد؛ وضعیت اجراها و هشدارها در volumeهای `paper-data` و `alerts-data` می‌ماند و بعد از راه‌اندازی دوباره ادامه می‌یابد.

هشدارها (نامزد ستاپ، ثبت/پر شدن/لغو/انقضای تریگر) در فید همان تب نشان داده می‌شوند. برای بله، در بله یک ربات با BotFather بله بسازید، توکن آن را در `deploy/.env` به‌عنوان `NNFX_BALE_TOKEN` بگذارید و سرویس را دوباره بالا بیاورید؛ هر کاربر شناسهٔ عددی چت خودش را در همان تب وارد و بله را روشن می‌کند. اگر بله در دسترس نباشد، ارسال چند بار با فاصلهٔ بیشتر تکرار و در نهایت در لاگ ثبت می‌شود و معاملهٔ کاغذی هیچ تأثیری نمی‌پذیرد. تلگرام بعداً از طریق یک رله بیرونی اضافه می‌شود.

## دعوت از دوستان

* از تب «مدیریت» در سایت: یادداشت (مثلاً اسم دوست) بنویسید و «ساخت کد دعوت» را بزنید.
* یا از خط فرمان: `nnfx beta --db .../beta.db invite 5 --note "موج اول"`.
* کد را برای دوستتان بفرستید؛ او در صفحهٔ ورود، «ثبت‌نام با کد دعوت» را می‌زند.
  هر کد فقط یک بار کار می‌کند.
* بازخوردها در همان تب مدیریت دیده می‌شوند (یا `nnfx beta feedback`).

## پشتیبان‌گیری

پایگاه دادهٔ کاربران یک فایل SQLite است. روزانه از آن نسخه بگیرید:
```bash
# Docker
docker compose -f deploy/docker-compose.yml exec app python -c "import sqlite3; s=sqlite3.connect('/app/runs/beta/beta.db'); d=sqlite3.connect('/app/runs/beta/backup.db'); s.backup(d)"
```
و فایل `backup.db` را به جای دیگری منتقل کنید.

## به‌روزرسانی

`git pull`، ساخت دوبارهٔ ایمیج (یا انتقال ایمیج جدید)، سپس `docker compose ... up -d`.
داده‌ها و حساب‌ها در volumeها می‌مانند.

## عیب‌یابی

* **گواهی HTTPS گرفته نمی‌شود:** رکورد A دامنه را و باز بودن پورت ۸۰ را بررسی
  کنید. اگر Let's Encrypt از سرورتان در دسترس نیست، از گواهی CDN داخلی
  استفاده کنید و Caddy را روی HTTP پشت CDN بگذارید.
* **دادهٔ نوبیتکس نمی‌آید:** `docker compose logs refresh`. نوبیتکس محدودیت نرخ
  دارد؛ بازهٔ `NNFX_START` را کوتاه‌تر کنید.
* **امنیت:** سرویس بدون `--auth-db` روی IP عمومی بالا نمی‌آید. رمز مدیر را
  قوی بگذارید. هرگز کلید API صرافی روی این سرور نگذارید.
