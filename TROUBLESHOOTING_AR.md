# 🔧 دليل استكشاف الأخطاء - TLE Bot

## ⚠️ المشاكل الشائعة والحلول

### المشكلة 1: البوت لا يتصل بـ Discord

#### الأعراض:
```
Error: Improper token has been passed
أو
LoginFailure: Improper token has been passed
```

#### الحل:
1. **تحقق من ملف `environment`**:
```bash
# يجب أن يحتوي على:
BOT_TOKEN=YOUR_ACTUAL_TOKEN_HERE
LOGGING_COG_CHANNEL_ID=123456789012345678
```

2. **احصل على Token صحيح**:
   - اذهب إلى https://discord.com/developers/applications
   - اختر تطبيقك → Bot
   - اضغط "Reset Token" وانسخ الـ Token الجديد
   - ضعه في ملف `environment`

---

### المشكلة 2: Intents Error

#### الأعراض:
```
Privileged intent provided is not enabled or whitelisted
```

#### الحل:
1. اذهب إلى Discord Developer Portal
2. اختر تطبيقك → Bot
3. في قسم "Privileged Gateway Intents":
   - ✅ فعّل **Server Members Intent**
   - ✅ فعّل **Message Content Intent**
   - ✅ فعّل **Presence Intent** (اختياري)

---

### المشكلة 3: Python Version

#### الأعراض:
```
SyntaxError: invalid syntax
أو
ModuleNotFoundError
```

#### الحل:
```bash
# تحقق من نسخة Python
python --version

# يجب أن تكون 3.11 أو أحدث (حسب requirements.txt)
# إذا كانت أقل، قم بالترقية:
# Windows: قم بتنزيل من python.org
# Linux: sudo apt install python3.11
```

---

### المشكلة 4: التبعيات غير مثبتة

#### الأعراض:
```
ModuleNotFoundError: No module named 'discord'
ModuleNotFoundError: No module named 'aiohttp'
```

#### الحل:
```bash
# الطريقة 1: باستخدام Poetry
poetry install

# الطريقة 2: باستخدام pip
pip install -r requirements.txt

# تحقق من التثبيت
python -c "import discord; print(discord.__version__)"
```

---

### المشكلة 5: قاعدة البيانات

#### الأعراض:
```
sqlite3.OperationalError: no such table
```

#### الحل:
```bash
# احذف قاعدة البيانات القديمة
rm data/user_db.db

# شغل البوت مرة أخرى - سيتم إنشاؤها تلقائياً
./run.sh
```

---

### المشكلة 6: Firebase (اختياري)

#### الأعراض:
```
FileNotFoundError: firebase-admin.json
```

#### الحل:
إذا لا تريد استخدام Firebase:
```bash
# في ملف environment
STORAGE_BUCKET=None
```

إذا تريد استخدام Firebase:
1. احصل على `firebase-admin.json` من Firebase Console
2. ضعه في مجلد المشروع الرئيسي
3. في ملف `environment`:
```
STORAGE_BUCKET=your-project.appspot.com
```

---

### المشكلة 7: Cogs لا تُحمّل

#### الأعراض:
```
Extension 'tle.cogs.mentorship' raised an error
```

#### الحل:
```bash
# تحقق من وجود الملفات
ls tle/cogs/

# يجب أن ترى:
# mentorship.py, duel.py, reminders.py, etc.

# إذا كان هناك خطأ في cog معين، يمكنك تعطيله مؤقتاً
# بحذف الملف أو إعادة تسميته
mv tle/cogs/mentorship.py tle/cogs/mentorship.py.bak
```

---

## 🧪 اختبار الاتصال

### اختبار بسيط:
```python
# test_connection.py
import discord
import os

# ضع الـ Token مباشرة للاختبار
TOKEN = "YOUR_TOKEN_HERE"

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'✅ تم الاتصال بنجاح: {client.user}')
    await client.close()

client.run(TOKEN)
```

شغّل الاختبار:
```bash
python test_connection.py
```

إذا نجح، المشكلة في الكود الأساسي للبوت.

---

## 📋 قائمة التحقق الكاملة

### قبل تشغيل البوت:

- [ ] Python 3.11+ مثبت
- [ ] جميع التبعيات مثبتة (`poetry install`)
- [ ] ملف `environment` موجود ويحتوي على `BOT_TOKEN`
- [ ] Discord Bot Intents مفعلة
- [ ] البوت مضاف إلى السيرفر
- [ ] البوت لديه صلاحيات (Administrator أو صلاحيات مخصصة)

### عند التشغيل:

```bash
# شغل البوت
./run.sh

# أو
poetry run python -m tle

# راقب السجلات
tail -f data/logs/tle.log
```

---

## 🔍 فحص السجلات

```bash
# آخر 50 سطر من السجل
tail -n 50 data/logs/tle.log

# تتبع السجل مباشرة
tail -f data/logs/tle.log

# ابحث عن أخطاء
grep -i "error" data/logs/tle.log
```

---

## 📞 طلب المساعدة

إذا استمرت المشكلة، أرسل لي:

1. **رسالة الخطأ الكاملة**:
```bash
# انسخ آخر 100 سطر من السجل
tail -n 100 data/logs/tle.log
```

2. **نسخة Python**:
```bash
python --version
```

3. **التبعيات المثبتة**:
```bash
pip list | grep discord
```

4. **محتوى environment** (بدون الـ Token):
```bash
cat environment | sed 's/BOT_TOKEN=.*/BOT_TOKEN=HIDDEN/'
```

---

## ✅ التحقق من نجاح التشغيل

عند نجاح التشغيل، يجب أن ترى:

```
INFO:discord.client:logging in using static token
INFO:discord.gateway:Shard ID None has connected to Gateway
INFO:__main__:Cogs loaded: Codeforces, Contests, Duel, Graphs, Handles, Mentorship, Reminders, ...
```

وفي Discord:
- البوت يظهر "Online" 🟢
- يمكنك كتابة `;help` والحصول على رد
