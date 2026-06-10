import sys
import os
import logging
import asyncio
import sqlite3
import re
import json
import urllib.parse
from datetime import datetime, timezone, timedelta
import random
import traceback
import urllib.parse

# ИСПРАВЛЕНИЕ ИМПОРТОВ - добавляем в самое начало
try:
    import requests
except ImportError as e:
    print(f"Ошибка импорта requests: {e}")
    # Пробуем альтернативный импорт
    try:
        import urllib3
        import http.client
        # Создаем простую замену для requests
        class SimpleRequests:
            def get(self, url, timeout=10):
                import urllib.request
                import ssl
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(url, timeout=timeout, context=context) as response:
                    return type('Response', (), {'json': lambda: json.loads(response.read().decode())})()
        requests = SimpleRequests()
    except Exception as ex:
        print(f"Не удалось инициализировать requests: {ex}")
        sys.exit(1)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

# Конфигурация
TOKEN = "7602289976:AAErHMuDQHkEO2hXPeuI0O4BtSSrr__sA1g"
ADMIN_ID = 1135127144
CARD_NUMBERS = {
    "Альфа-Банк": "2200 1529 1796 **** - (недоступно)",
    "Т-банк (Тинькофф)": "2200 7008 2028 1425",
    "Сбер": "2202 2082 8349 4368 - (желательно-оплачивать-через-СБП)",
    "Почта банк": "2200770631165505 - (желательно-оплачивать-через-СБП)"
}
SBP_PHONE = "89218748626"
YM_ACCOUNT = "4100119001704075"
STAR_PRICE = 1.40
TON_PRICE = 165 # Фиксированная цена за 1 TON в рублях для покупок
SUPPORT_USERNAME = "@KIRG_17, @manager_k17"
PREMIUM_PRICES = {
    "3 месяца": 1039,
    "6 месяцев": 1389,
    "1 год": 2517
}

# Крипто-кошельки
CRYPTO_WALLETS = {
    "TON": "UQDb_MJJJOkmWkDVpsCiO-xozpDf5T_-Y8GogKq-wAswD5tl",
    "USDT": "UQA_qFBvYKRAwn65kvRPxn2oqGBJffSQgQTetGicaxe6Rw2C"
}

# Флаги стран для валют
FLAGS = {
    "USD": "🇺🇸",
    "EUR": "🇪🇺",
    "RUB": "🇷🇺",
    "TON": "💎",
    "USDT": "💵"
}

# Настройка московского времени (без pytz)
def get_moscow_time():
    """Возвращает текущее время в Москве (UTC+3)"""
    moscow_tz = timezone(timedelta(hours=3))
    return datetime.now(moscow_tz)

# Настройка логгирования
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

# НОВЫЙ ИСПРАВЛЕННЫЙ МОДУЛЬ ДЛЯ КУРСОВ ВАЛЮТ БЕЗ BINANCE
class CurrencyRates:
    def __init__(self):
        self.cache = {}
        self.cache_time = None
        self.cache_duration = 300  # 5 минут кэширования

    async def get_rates(self):
        """Получает актуальные курсы валют из надежных официальных источников"""
        try:
            # Проверяем кэш
            if (self.cache_time and
                (datetime.now() - self.cache_time).total_seconds() < self.cache_duration and
                self.cache):
                return self.cache

            rates = {}

            # Получаем курсы фиатных валют (USD, EUR к RUB)
            usd_rate = await self._get_usd_rate_reliable()
            eur_rate = await self._get_eur_rate_reliable()

            # Получаем курсы криптовалют (TON, USDT)
            ton_rate = await self._get_ton_rate_reliable()
            usdt_rate = await self._get_usdt_rate_reliable()

            if usd_rate and eur_rate:
                rates['USD'] = usd_rate
                rates['EUR'] = eur_rate
                rates['TON'] = ton_rate if ton_rate else 200.0
                rates['USDT'] = usdt_rate if usdt_rate else usd_rate

                # Добавляем время обновления
                rates['last_update'] = get_moscow_time().strftime("%H:%M:%S")

                self.cache = rates
                self.cache_time = datetime.now()

                logger.info(f"✅ Курсы обновлены: USD={usd_rate}, EUR={eur_rate}, TON={rates.get('TON')}, USDT={rates.get('USDT')}")

            return rates

        except Exception as e:
            logger.error(f"❌ Ошибка получения курсов: {e}")
            return self.cache or {
                'USD': 95.0, 'EUR': 102.0, 'TON': 200.0, 'USDT': 95.0,
                'last_update': 'ошибка'
            }

    async def _get_usd_rate_reliable(self):
        """Получает курс USD/RUB из официальных источников"""
        try:
            sources = [
                # Центробанк России (самый надежный)
                "https://www.cbr-xml-daily.ru/daily_json.js",
                # CoinGecko (официальный)
                "https://api.coingecko.com/api/v3/simple/price?ids=usd&vs_currencies=rub",
                # OpenExchangeRates (официальный)
                "https://open.er-api.com/v6/latest/USD",
                # Альтернативный надежный источник
                "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"
            ]

            for source in sources:
                try:
                    response = requests.get(source, timeout=10)
                    if response.status_code == 200:
                        data = response.json()

                        # Центробанк России
                        if 'Valute' in data and 'USD' in data['Valute']:
                            rate = float(data['Valute']['USD']['Value'])
                            logger.info(f"✅ USD курс из ЦБ: {rate}")
                            return rate
                        # CoinGecko
                        elif 'usd' in data and 'rub' in data['usd']:
                            rate = float(data['usd']['rub'])
                            logger.info(f"✅ USD курс из CoinGecko: {rate}")
                            return rate
                        # OpenExchangeRates
                        elif 'rates' in data and 'RUB' in data['rates']:
                            rate = float(data['rates']['RUB'])
                            logger.info(f"✅ USD курс из OpenExchange: {rate}")
                            return rate
                        # Альтернативный источник
                        elif 'usd' in data and 'rub' in data['usd']:
                            rate = float(data['usd']['rub'])
                            logger.info(f"✅ USD курс из альтернативного источника: {rate}")
                            return rate

                except Exception as e:
                    logger.warning(f"⚠️ Ошибка источника USD {source}: {e}")
                    continue

            logger.warning("⚠️ Все источники USD недоступны, используем резервный курс")
            return 95.0

        except Exception as e:
            logger.error(f"❌ Ошибка получения курса USD: {e}")
            return 95.0

    async def _get_eur_rate_reliable(self):
        """Получает курс EUR/RUB из официальных источников"""
        try:
            sources = [
                # Центробанк России
                "https://www.cbr-xml-daily.ru/daily_json.js",
                # CoinGecko
                "https://api.coingecko.com/api/v3/simple/price?ids=eur&vs_currencies=rub",
                # OpenExchangeRates
                "https://open.er-api.com/v6/latest/EUR",
                # Альтернативный источник
                "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/eur.json"
            ]

            for source in sources:
                try:
                    response = requests.get(source, timeout=10)
                    if response.status_code == 200:
                        data = response.json()

                        # Центробанк России
                        if 'Valute' in data and 'EUR' in data['Valute']:
                            rate = float(data['Valute']['EUR']['Value'])
                            logger.info(f"✅ EUR курс из ЦБ: {rate}")
                            return rate
                        # CoinGecko
                        elif 'eur' in data and 'rub' in data['eur']:
                            rate = float(data['eur']['rub'])
                            logger.info(f"✅ EUR курс из CoinGecko: {rate}")
                            return rate
                        # OpenExchangeRates
                        elif 'rates' in data and 'RUB' in data['rates']:
                            rate = float(data['rates']['RUB'])
                            logger.info(f"✅ EUR курс из OpenExchange: {rate}")
                            return rate
                        # Альтернативный источник
                        elif 'eur' in data and 'rub' in data['eur']:
                            rate = float(data['eur']['rub'])
                            logger.info(f"✅ EUR курс из альтернативного источника: {rate}")
                            return rate

                except Exception as e:
                    logger.warning(f"⚠️ Ошибка источника EUR {source}: {e}")
                    continue

            logger.warning("⚠️ Все источники EUR недоступны, используем резервный курс")
            return 102.0

        except Exception as e:
            logger.error(f"❌ Ошибка получения курса EUR: {e}")
            return 102.0

    async def _get_ton_rate_reliable(self):
        """Получает курс TON из официальных источников"""
        try:
            sources = [
                # CoinGecko (официальный)
                "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd",
                # Coinbase (официальный)
                "https://api.coinbase.com/v2/prices/TON-USD/spot",
                # OKX API (официальный)
                "https://www.okx.com/api/v5/market/ticker?instId=TON-USDT",
                # Bybit API (официальный)
                "https://api.bybit.com/v2/public/tickers?symbol=TONUSDT"
            ]

            for source in sources:
                try:
                    response = requests.get(source, timeout=10)
                    if response.status_code == 200:
                        data = response.json()

                        # CoinGecko
                        if 'the-open-network' in data and 'usd' in data['the-open-network']:
                            ton_usd = float(data['the-open-network']['usd'])
                            # Конвертируем в RUB через USD курс
                            usd_rate = await self._get_usd_rate_reliable()
                            rate = ton_usd * usd_rate
                            logger.info(f"✅ TON курс: {rate} RUB (${ton_usd} USD)")
                            return rate
                        # Coinbase
                        elif 'data' in data and 'amount' in data['data']:
                            ton_usd = float(data['data']['amount'])
                            usd_rate = await self._get_usd_rate_reliable()
                            rate = ton_usd * usd_rate
                            logger.info(f"✅ TON курс из Coinbase: {rate} RUB")
                            return rate
                        # OKX
                        elif 'data' in data and len(data['data']) > 0 and 'last' in data['data'][0]:
                            ton_usdt = float(data['data'][0]['last'])
                            usd_rate = await self._get_usd_rate_reliable()
                            rate = ton_usdt * usd_rate
                            logger.info(f"✅ TON курс из OKX: {rate} RUB")
                            return rate
                        # Bybit
                        elif 'result' in data and len(data['result']) > 0 and 'last_price' in data['result'][0]:
                            ton_usdt = float(data['result'][0]['last_price'])
                            usd_rate = await self._get_usd_rate_reliable()
                            rate = ton_usdt * usd_rate
                            logger.info(f"✅ TON курс из Bybit: {rate} RUB")
                            return rate

                except Exception as e:
                    logger.warning(f"⚠️ Ошибка источника TON {source}: {e}")
                    continue

            logger.warning("⚠️ Все источники TON недоступны, используем резервный курс")
            return 200.0

        except Exception as e:
            logger.error(f"❌ Ошибка получения курса TON: {e}")
            return 200.0

    async def _get_usdt_rate_reliable(self):
        """Получает курс USDT (обычно равен USD)"""
        try:
            sources = [
                # CoinGecko
                "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=usd",
                # Coinbase
                "https://api.coinbase.com/v2/prices/USDT-USD/spot",
            ]

            for source in sources:
                try:
                    response = requests.get(source, timeout=10)
                    if response.status_code == 200:
                        data = response.json()

                        # CoinGecko
                        if 'tether' in data and 'usd' in data['tether']:
                            usdt_usd = float(data['tether']['usd'])
                            usd_rate = await self._get_usd_rate_reliable()
                            rate = usdt_usd * usd_rate
                            logger.info(f"✅ USDT курс: {rate} RUB")
                            return rate
                        # Coinbase
                        elif 'data' in data and 'amount' in data['data']:
                            usdt_usd = float(data['data']['amount'])
                            usd_rate = await self._get_usd_rate_reliable()
                            rate = usdt_usd * usd_rate
                            logger.info(f"✅ USDT курс из Coinbase: {rate} RUB")
                            return rate

                except Exception as e:
                    logger.warning(f"⚠️ Ошибка источника USDT {source}: {e}")
                    continue

            # USDT обычно равен USD, поэтому используем USD курс
            usd_rate = await self._get_usd_rate_reliable()
            logger.info(f"✅ USDT курс равен USD: {usd_rate} RUB")
            return usd_rate

        except Exception as e:
            logger.error(f"❌ Ошибка получения курса USDT: {e}")
            usd_rate = await self._get_usd_rate_reliable()
            return usd_rate

    async def convert_currency(self, amount: float, from_currency: str, to_currency: str):
        """Конвертирует сумму из одной валюты в другую"""
        try:
            rates = await self.get_rates()

            # Нормализуем названия валют
            from_currency = from_currency.upper()
            to_currency = to_currency.upper()

            # Если конвертируем из RUB в валюту
            if from_currency == 'RUB' and to_currency != 'RUB':
                if to_currency in rates:
                    return amount / rates[to_currency]

            # Если конвертируем из валюты в RUB
            elif from_currency != 'RUB' and to_currency == 'RUB':
                if from_currency in rates:
                    return amount * rates[from_currency]

            # Если конвертируем между двумя валютами (через RUB)
            elif from_currency != 'RUB' and to_currency != 'RUB':
                if from_currency in rates and to_currency in rates:
                    # Конвертируем сначала в RUB, потом в целевую валюту
                    rub_amount = amount * rates[from_currency]
                    return rub_amount / rates[to_currency]

            return None

        except Exception as e:
            logger.error(f"❌ Ошибка конвертации: {e}")
            return None

# Создаем экземпляр класса курсов
currency_rates = CurrencyRates()

def init_checks_db():
    """Инициализация таблицы для чеков"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS checks (
        check_id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator_id INTEGER,
        check_type TEXT,
        amount REAL,
        cost REAL,
        check_code TEXT UNIQUE,
        is_activated INTEGER DEFAULT 0,
        activated_by INTEGER DEFAULT NULL,
        activated_date TEXT,
        created_date TEXT,
        status TEXT DEFAULT 'active',
        photo_file_id TEXT,
        message_id INTEGER
    )
    ''')

    conn.commit()
    conn.close()
    logger.info("✅ Таблица checks инициализирована с фото")

def create_blocked_users_table():
    """Создает таблицу для заблокированных пользователей"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS blocked_users (
            user_id INTEGER PRIMARY KEY,
            blocked_date TEXT NOT NULL,
            reason TEXT NOT NULL,
            blocked_by_admin_id INTEGER,
            unblocked_date TEXT,
            is_blocked INTEGER DEFAULT 1,
            FOREIGN KEY (blocked_by_admin_id) REFERENCES users(user_id)
        )
        ''')

        conn.commit()
        conn.close()
        logger.info("✅ Таблица blocked_users создана/проверена")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка создания таблицы blocked_users: {e}")
        return False

def check_table_structure():
    """Проверяет структуру таблицы checks"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(checks)")
    columns = cursor.fetchall()

    print("Структура таблицы checks:")
    for column in columns:
        print(f"  {column[1]} ({column[2]})")

    conn.close()

# Вызовите эту функцию перед запуском бота
check_table_structure()

def generate_check_code(length=8):
    """Генерирует уникальный код для чека"""
    import random
    import string

    # Используем буквы и цифры
    characters = string.ascii_uppercase + string.digits
    # Исключаем похожие символы (0/O, 1/I/L)
    characters = characters.replace('0', '').replace('O', '').replace('1', '').replace('I', '').replace('L', '')

    while True:
        code = ''.join(random.choice(characters) for _ in range(length))

        # Проверяем уникальность кода в базе данных
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT check_code FROM checks WHERE check_code = ?', (code,))
        existing = cursor.fetchone()
        conn.close()

        if not existing:
            return code

# Альтернативная версия с проверкой на существование в pending_orders
def generate_check_code_v2(length=8):
    """Генерирует уникальный код для чека с дополнительной проверкой"""
    import random
    import string

    # Используем только буквы (исключаем похожие)
    letters = 'ABCDEFGHJKMNPQRSTUVWXYZ'
    digits = '23456789'

    # Формат: 3 буквы + 3 цифры + 2 буквы (пример: ABC123XY)
    while True:
        part1 = ''.join(random.choice(letters) for _ in range(3))
        part2 = ''.join(random.choice(digits) for _ in range(3))
        part3 = ''.join(random.choice(letters) for _ in range(2))
        code = f"{part1}{part2}{part3}"

        # Проверяем уникальность в checks
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT check_code FROM checks WHERE check_code = ?', (code,))
        existing_check = cursor.fetchone()

        # Также проверяем в pending_orders (friend_username)
        cursor.execute('SELECT friend_username FROM pending_orders WHERE friend_username = ?', (code,))
        existing_order = cursor.fetchone()
        conn.close()

        if not existing_check and not existing_order:
            return code

# Используем вторую версию для большей надежности
def generate_check_code(length=8):
    return generate_check_code_v2()

def create_check(creator_id: int, check_type: str, amount: float, cost: float, photo_file_id: str = None, message_id: int = None):
    """Создает новый чек с фото - УЛУЧШЕННАЯ ВЕРСИЯ"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        check_code = generate_check_code()
        created_date = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute('''
        INSERT INTO checks
        (creator_id, check_type, amount, cost, check_code, created_date, photo_file_id, message_id, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
        ''', (creator_id, check_type, amount, cost, check_code, created_date, photo_file_id, message_id))

        conn.commit()
        check_id = cursor.lastrowid
        conn.close()

        logger.info(f"✅ Чек создан: {check_code}, тип: {check_type}, сумма: {cost}₽, ID: {check_id}")
        return True, check_code, check_id

    except Exception as e:
        logger.error(f"❌ Ошибка создания чека: {e}")
        return False, str(e), None

def get_check_by_code(check_code: str):
    """Получает информацию о чеке по коду - УЛУЧШЕННАЯ ВЕРСИЯ"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        SELECT check_id, creator_id, check_type, amount, cost, check_code,
               is_activated, activated_by, activated_date, created_date, status,
               photo_file_id, message_id
        FROM checks WHERE check_code = ? AND status = 'active'
        ''', (check_code.upper(),))

        check = cursor.fetchone()
        conn.close()

        if check:
            return {
                'check_id': check[0],
                'creator_id': check[1],
                'check_type': check[2],
                'amount': check[3],
                'cost': check[4],
                'check_code': check[5],
                'is_activated': bool(check[6]),
                'activated_by': check[7],
                'activated_date': check[8],
                'created_date': check[9],
                'status': check[10],
                'photo_file_id': check[11],
                'message_id': check[12]
            }
        return None

    except Exception as e:
        logger.error(f"❌ Ошибка получения чека: {e}")
        return None

def activate_check(check_code: str, activated_by: int):
    """Активирует чек в базе данных"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        activated_date = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute('''
        UPDATE checks
        SET is_activated = 1, activated_by = ?, activated_date = ?, status = 'activated'
        WHERE check_code = ? AND is_activated = 0
        ''', (activated_by, activated_date, check_code))

        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        if success:
            logger.info(f"✅ Чек {check_code} активирован пользователем {activated_by}")
        else:
            logger.warning(f"⚠️ Не удалось активировать чек {check_code}")

        return success

    except Exception as e:
        logger.error(f"❌ Ошибка активации чека {check_code}: {e}")
        return False

def get_active_checks(limit=50):
    """Получает активные чеки для публичного канала"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        SELECT check_id, check_code, check_type, amount, cost, created_date, photo_file_id
        FROM checks
        WHERE status = 'active' AND is_activated = 0
        ORDER BY created_date DESC
        LIMIT ?
        ''', (limit,))

        checks = cursor.fetchall()
        conn.close()

        result = []
        for check in checks:
            result.append({
                'check_id': check[0],
                'check_code': check[1],
                'check_type': check[2],
                'amount': check[3],
                'cost': check[4],
                'created_date': check[5],
                'photo_file_id': check[6]
            })

        return result

    except Exception as e:
        logger.error(f"❌ Ошибка получения активных чеков: {e}")
        return []

async def publish_check_to_channel(context: ContextTypes.DEFAULT_TYPE, check_data: dict, photo_file_id: str = None):
    """Публикует чек в канал/группу с кнопкой 'Получить'"""
    try:
        # ID канала или группы куда публиковать чеки
        CHANNEL_ID = "@your_channel_username"  # Замените на ваш канал

        type_text = get_check_type_text(check_data['check_type'])

        if check_data['check_type'] == "premium":
            description = f"🌟 Telegram Premium"
        else:
            unit = "звёзд" if check_data['check_type'] == "stars" else "TON"
            description = f"{type_text} {check_data['amount']} {unit}"

        caption = (
            f"🎁 ЧЕК НА {description}\n\n"
            f"💰 Стоимость: {check_data['cost']:.2f}₽\n"
            f"🎫 Код: {check_data['check_code']}\n\n"
            f"👇 Нажмите кнопку ниже чтобы получить"
        )

        keyboard = [
            [InlineKeyboardButton("🎁 ПОЛУЧИТЬ ЧЕК", callback_data=f"claim_check_{check_data['check_code']}")]
        ]

        # Если есть фото - отправляем с фото, иначе просто текст
        if photo_file_id:
            message = await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photo_file_id,
                caption=caption,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            message = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=caption,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        # Обновляем message_id в базе данных
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE checks SET message_id = ? WHERE check_code = ?',
                      (message.message_id, check_data['check_code']))
        conn.commit()
        conn.close()

        logger.info(f"✅ Чек {check_data['check_code']} опубликован в канале")

    except Exception as e:
        logger.error(f"❌ Ошибка публикации чека в канале: {e}")

def get_user_checks(user_id: int):
    """Получает все чеки пользователя"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        SELECT check_code, check_type, amount, cost, created_date, is_activated, activated_by
        FROM checks
        WHERE creator_id = ?
        ORDER BY created_date DESC
        ''', (user_id,))

        checks = cursor.fetchall()
        conn.close()

        result = []
        for check in checks:
            result.append({
                'check_code': check[0],
                'check_type': check[1],
                'amount': check[2],
                'cost': check[3],
                'created_date': check[4],
                'is_activated': check[5],
                'activated_by': check[6]
            })

        return result

    except Exception as e:
        logger.error(f"❌ Ошибка получения чеков пользователя: {e}")
        return []

async def cancel_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет создание чека и очищает все данные"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # Очищаем все данные чека
    if 'current_check' in context.user_data:
        # Если чек уже создан в БД, помечаем его как отмененный
        check_data = context.user_data['current_check']
        if 'check_code' in check_data:
            # Помечаем чек как отмененный в базе данных
            conn = sqlite3.connect('bot.db')
            cursor = conn.cursor()
            cursor.execute('UPDATE checks SET status = ? WHERE check_code = ?',
                         ('cancelled', check_data['check_code']))
            conn.commit()
            conn.close()

        del context.user_data['current_check']

    # Очищаем остальные состояния
    for key in ['current_check_type', 'awaiting_check_amount', 'awaiting_check_photo', 'temp_check_code']:
        if key in context.user_data:
            del context.user_data[key]

    await query.edit_message_text(
        "✅ Создание чека отменено",
        reply_markup=get_main_menu_keyboard()
    )

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    # Создаем таблицу users с всеми необходимыми колонками
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        registration_date TEXT,
        last_activity TEXT,
        stars_purchased INTEGER DEFAULT 0,
        premium_purchased INTEGER DEFAULT 0,
        ton_purchased REAL DEFAULT 0,
        is_blocked INTEGER DEFAULT 0,
        balance REAL DEFAULT 0,
        stars_gifted INTEGER DEFAULT 0,
        ton_gifted REAL DEFAULT 0,
        premium_gifted INTEGER DEFAULT 0
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admin_messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT,
        sent_date TEXT,
        sent_by INTEGER,
        users_reached INTEGER,
        users_blocked INTEGER
    )
    ''')

    # Новая таблица для временного хранения подарков
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS temp_gifts (
        user_id INTEGER PRIMARY KEY,
        gift_type TEXT,
        amount REAL,
        period TEXT,
        cost REAL,
        friend_username TEXT,
        created_date TEXT
    )
    ''')

    # Таблица для статистики продаж по часам
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sales_stats (
        stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        stat_date TEXT,
        stat_hour INTEGER,
        stars_sold INTEGER DEFAULT 0,
        premium_sold INTEGER DEFAULT 0,
        ton_sold REAL DEFAULT 0,
        revenue REAL DEFAULT 0
    )
    ''')

    # НОВАЯ ТАБЛИЦА для ожидающих подтверждения заказов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS pending_orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        full_name TEXT,
        order_type TEXT,
        amount REAL,
        cost REAL,
        receipt_message_id INTEGER,
        admin_message_id INTEGER,
        created_date TEXT,
        status TEXT DEFAULT 'pending',
        friend_username TEXT DEFAULT '',
        is_balance_replenishment INTEGER DEFAULT 0,
        is_balance_payment INTEGER DEFAULT 0,
        is_promo_creation INTEGER DEFAULT 0
    )
    ''')

    # ОСНОВНАЯ ТАБЛИЦА для промокодов (УДАЛЕНА ДУБЛИРУЮЩАЯ ТАБЛИЦА)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS promo_codes (
        promo_id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        discount_percent REAL DEFAULT 0,
        discount_amount REAL DEFAULT 0,
        min_amount REAL DEFAULT 0,
        max_uses INTEGER DEFAULT 1,
        used_count INTEGER DEFAULT 0,
        valid_until TEXT,
        is_active INTEGER DEFAULT 1,
        created_date TEXT,
        created_by INTEGER,
        gift_amount REAL DEFAULT 0,
        gift_type TEXT DEFAULT 'balance'
    )
    ''')

    # НОВАЯ ТАБЛИЦА для использованных промокодов пользователями
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS used_promo_codes (
        use_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        promo_code TEXT,
        used_date TEXT,
        order_type TEXT,
        original_amount REAL,
        discount_amount REAL,
        final_amount REAL
    )
    ''')

    # НОВАЯ ТАБЛИЦА для пользовательских промокодов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_promo_codes (
        promo_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        code TEXT UNIQUE,
        gift_amount REAL DEFAULT 0,
        gift_type TEXT DEFAULT 'balance',
        max_uses INTEGER DEFAULT 1,
        used_count INTEGER DEFAULT 0,
        created_date TEXT,
        is_active INTEGER DEFAULT 1
    )
    ''')

    # 🔴🔴🔴 УДАЛЕНА ДУБЛИРУЮЩАЯ ТАБЛИЦА promocodes - используем ТОЛЬКО promo_codes 🔴🔴🔴

    # ДОБАВЛЯЕМ ОТСУТСТВУЮЩИЕ КОЛОНКИ ЕСЛИ ТАБЛИЦА УЖЕ СУЩЕСТВУЕТ
    columns_to_add = [
        "is_blocked", "stars_purchased", "premium_purchased", "ton_purchased",
        "balance", "stars_gifted", "ton_gifted", "premium_gifted"
    ]

    for column in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column} INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует

    # ДОБАВЛЯЕМ КОЛОНКУ friend_username ЕСЛИ ЕЕ НЕТ
    try:
        cursor.execute("ALTER TABLE pending_orders ADD COLUMN friend_username TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует

    try:
        cursor.execute("ALTER TABLE pending_orders ADD COLUMN is_balance_replenishment INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует

    # 🔴🔴🔴 ДОБАВЛЯЕМ НОВЫЕ КОЛОНКИ ДЛЯ ПРОМОКОДОВ 🔴🔴🔴
    try:
        cursor.execute("ALTER TABLE pending_orders ADD COLUMN is_balance_payment INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует

    try:
        cursor.execute("ALTER TABLE pending_orders ADD COLUMN is_promo_creation INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Колонка уже существует

    # 🔴 ДОБАВЛЯЕМ ОТСУТСТВУЮЩИЕ КОЛОНКИ В ТАБЛИЦУ promo_codes ЕСЛИ НУЖНО
    promo_columns_to_add = [
        "discount_percent", "discount_amount", "min_amount", "max_uses",
        "used_count", "valid_until", "is_active", "created_date",
        "created_by", "gift_amount", "gift_type"
    ]

    for column in promo_columns_to_add:
        try:
            if column in ["discount_percent", "discount_amount", "min_amount", "gift_amount"]:
                cursor.execute(f"ALTER TABLE promo_codes ADD COLUMN {column} REAL DEFAULT 0")
            elif column in ["max_uses", "used_count", "is_active", "created_by"]:
                cursor.execute(f"ALTER TABLE promo_codes ADD COLUMN {column} INTEGER DEFAULT 0")
            else:
                cursor.execute(f"ALTER TABLE promo_codes ADD COLUMN {column} TEXT")
            logger.info(f"✅ Добавлена колонка {column} в promo_codes")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует

    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована с исправленной структурой промокодов")

# НОВАЯ ТАБЛИЦА ДЛЯ РЕФЕРАЛЬНОЙ СИСТЕМЫ
def init_db():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS referrals (
        ref_id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER,
        referred_id INTEGER UNIQUE,
        referral_code TEXT,
        created_date TEXT,
        is_active INTEGER DEFAULT 1,
        completed_orders INTEGER DEFAULT 0,
        total_earnings REAL DEFAULT 0,
        FOREIGN KEY (referrer_id) REFERENCES users(user_id),
        FOREIGN KEY (referred_id) REFERENCES users(user_id)
    )
    ''')

    # НОВАЯ ТАБЛИЦА ДЛЯ РЕФЕРАЛЬНЫХ ВЫПЛАТ
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS referral_payments (
        payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER,
        referred_id INTEGER,
        order_id INTEGER,
        amount REAL,
        payment_date TEXT,
        status TEXT DEFAULT 'pending',
        admin_message_id INTEGER
    )
    ''')

    # НОВАЯ ТАБЛИЦА ДЛЯ ВЫВОДА СРЕДСТВ
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS withdrawals (
        withdrawal_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        method TEXT, -- bank_card, phone, crypto
        details TEXT, -- номер карты/телефона/кошелька
        status TEXT DEFAULT 'pending', -- pending, approved, rejected
        created_date TEXT,
        processed_date TEXT,
        admin_message_id INTEGER,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    ''')

    # Проверяем и добавляем колонки в users
    columns_to_add = [
        ('referral_code', 'TEXT'),
        ('referred_by', 'INTEGER DEFAULT 0'),
        ('referral_earnings', 'REAL DEFAULT 0'),
        ('completed_referrals', 'INTEGER DEFAULT 0'),
        ('balance', 'REAL DEFAULT 0')
    ]

    for column_name, column_type in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")
            logger.info(f"✅ Добавлена колонка {column_name}")
        except sqlite3.OperationalError:
            pass  # Колонка уже существует

    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована с исправленной реферальной системой и системой вывода средств")

def debug_referral_system():
    """Функция для отладки реферальной системы"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        # Проверяем таблицы
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        logger.info("🔹 Существующие таблицы:")
        for table in tables:
            logger.info(f"   - {table[0]}")

        # Проверяем структуру таблицы referrals
        cursor.execute("PRAGMA table_info(referrals)")
        columns = cursor.fetchall()
        logger.info("🔹 Структура таблицы referrals:")
        for col in columns:
            logger.info(f"   {col}")

        # Считаем пользователей и рефералов
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM referrals")
        ref_count = cursor.fetchone()[0]

        logger.info(f"🔹 Всего пользователей: {user_count}")
        logger.info(f"🔹 Всего реферальных записей: {ref_count}")

        # Показываем последние 5 рефералов
        cursor.execute('''
        SELECT r.referrer_id, r.referred_id, r.created_date, u1.username, u2.username
        FROM referrals r
        LEFT JOIN users u1 ON r.referrer_id = u1.user_id
        LEFT JOIN users u2 ON r.referred_id = u2.user_id
        ORDER BY r.ref_id DESC LIMIT 5
        ''')

        recent_refs = cursor.fetchall()
        logger.info("🔹 Последние реферальные записи:")
        for ref in recent_refs:
            logger.info(f"   Реферер: {ref[0]} (@{ref[3]}), Реферал: {ref[1]} (@{ref[4]}), Дата: {ref[2]}")

        conn.close()

    except Exception as e:
        logger.error(f"❌ Ошибка отладки реферальной системы: {e}")

# Функции для работы с балансом пользователя
def update_user_balance(user_id: int, amount: float):
    """Обновляет баланс пользователя"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()
    logger.info(f"✅ Баланс пользователя {user_id} обновлен на {amount}")

def get_user_stats(user_id: int):
    """Получает полную статистику пользователя"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT username, full_name, registration_date, last_activity,
               stars_purchased, premium_purchased, ton_purchased, balance,
               stars_gifted, ton_gifted, premium_gifted
        FROM users WHERE user_id = ?
    ''', (user_id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        return {
            'username': result[0],
            'full_name': result[1],
            'registration_date': result[2],
            'last_activity': result[3],
            'stars_purchased': result[4] or 0,
            'premium_purchased': result[5] or 0,
            'ton_purchased': result[6] or 0.0,
            'balance': result[7] or 0.0,
            'stars_gifted': result[8] or 0,
            'ton_gifted': result[9] or 0.0,
            'premium_gifted': result[10] or 0
        }
    return None

def create_user_promo_code(user_id: int, code: str, gift_amount: float, gift_type: str = 'balance', max_uses: int = 1):
    """Создает пользовательский промокод для подарка"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

    try:
        cursor.execute('''
        INSERT INTO user_promo_codes
        (user_id, code, gift_amount, gift_type, max_uses, created_date)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, code.upper(), gift_amount, gift_type, max_uses, now))

        conn.commit()
        conn.close()
        logger.info(f"✅ Пользовательский промокод {code} создан пользователем {user_id}")
        return True
    except sqlite3.IntegrityError:
        conn.close()
        logger.error(f"❌ Промокод {code} уже существует")
        return False

def get_promo_code(code: str):
    """Получает информацию о промокоде - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        SELECT promo_id, code, discount_percent, discount_amount, min_amount,
               max_uses, used_count, valid_until, is_active, created_date,
               created_by, gift_amount, gift_type
        FROM promo_codes WHERE code = ? AND is_active = 1
        ''', (code.upper(),))

        promo = cursor.fetchone()
        conn.close()

        if promo:
            return {
                'promo_id': promo[0],
                'code': promo[1],
                'discount_percent': promo[2] or 0,
                'discount_amount': promo[3] or 0,
                'min_amount': promo[4] or 0,
                'max_uses': promo[5] or 1,
                'used_count': promo[6] or 0,
                'valid_until': promo[7],
                'is_active': promo[8],
                'created_date': promo[9],
                'created_by': promo[10],
                'gift_amount': promo[11] or 0,
                'gift_type': promo[12] or 'balance'
            }
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка в get_promo_code: {e}")
        return None

def get_user_promo_code(code: str):
    """Получает информацию о пользовательском промокоде"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('''
    SELECT * FROM user_promo_codes WHERE code = ? AND is_active = 1
    ''', (code.upper(),))

    promo = cursor.fetchone()
    conn.close()

    if promo:
        return {
            'promo_id': promo[0],
            'user_id': promo[1],
            'code': promo[2],
            'gift_amount': promo[3],
            'gift_type': promo[4],
            'max_uses': promo[5],
            'used_count': promo[6],
            'created_date': promo[7],
            'is_active': promo[8]
        }
    return None

def has_user_used_promo(user_id: int, promo_code: str):
    """Проверяет, использовал ли пользователь уже этот промокод"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('''
    SELECT COUNT(*) FROM used_promo_codes
    WHERE user_id = ? AND promo_code = ?
    ''', (user_id, promo_code.upper()))

    count = cursor.fetchone()[0]
    conn.close()

    return count > 0

def use_promo_code(code: str, user_id: int, order_type: str, original_amount: float, discount_amount: float, final_amount: float):
    """Использует промокод (увеличивает счетчик использований и записывает использование)"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    # Увеличиваем счетчик использований промокода
    cursor.execute('''
    UPDATE promo_codes
    SET used_count = used_count + 1
    WHERE code = ? AND is_active = 1 AND (max_uses = 0 OR used_count < max_uses)
    ''', (code.upper(),))

    success = cursor.rowcount > 0

    if success:
        # Записываем использование промокода пользователем
        now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
        INSERT INTO used_promo_codes
        (user_id, promo_code, used_date, order_type, original_amount, discount_amount, final_amount)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, code.upper(), now, order_type, original_amount, discount_amount, final_amount))

    conn.commit()
    conn.close()

    if success:
        logger.info(f"✅ Промокод {code} использован пользователем {user_id}")
    else:
        logger.info(f"❌ Не удалось использовать промокод {code}")

    return success

def create_promo_code(code: str, discount_percent: float = 0, discount_amount: float = 0,
                     min_amount: float = 0, max_uses: int = 1, valid_until: str = None,
                     created_by: int = ADMIN_ID, gift_amount: float = 0, gift_type: str = 'balance'):
    """Создает новый промокод - УПРОЩЕННАЯ ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

        logger.info(f"🔴 СОЗДАНИЕ ПРОМОКОДА: {code}, скидка: {discount_percent}%")

        # Проверяем существование промокода
        cursor.execute('SELECT code FROM promo_codes WHERE code = ?', (code.upper(),))
        existing = cursor.fetchone()

        if existing:
            logger.error(f"❌ Промокод {code} уже существует!")
            conn.close()
            return False, "Промокод с таким кодом уже существует"

        # ПРОСТАЯ ВСТАВКА - только обязательные поля
        cursor.execute('''
        INSERT INTO promo_codes
        (code, discount_percent, max_uses, used_count, is_active, created_date)
        VALUES (?, ?, ?, 0, 1, ?)
        ''', (code.upper(), discount_percent, max_uses, now))

        conn.commit()
        conn.close()

        logger.info(f"✅ Промокод {code} успешно создан")
        return True, "Промокод успешно создан"

    except Exception as e:
        logger.error(f"❌ Ошибка при создании промокода {code}: {e}")
        if conn:
            conn.close()
        return False, f"Ошибка базы данных: {str(e)}"

async def create_simple_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Простая функция создания промокода для тестирования"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет доступа")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /simple_promo CODE DISCOUNT_PERCENT [MAX_USES]\n"
            "Пример: /simple_promo TEST10 10 100"
        )
        return

    code = context.args[0].upper()
    discount_percent = float(context.args[1])
    max_uses = int(context.args[2]) if len(context.args) > 2 else 100

    success, message = create_promo_code(
        code=code,
        discount_percent=discount_percent,
        max_uses=max_uses
    )

    if success:
        await update.message.reply_text(
            f"✅ Промокод создан!\n"
            f"🎫 Код: <code>{code}</code>\n"
            f"💯 Скидка: {discount_percent}%\n"
            f"🔢 Лимит: {max_uses} использований",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(f"❌ Ошибка: {message}")

def use_user_promo_code(code: str, user_id: int):
    """Использует пользовательский промокод"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    # Увеличиваем счетчик использований промокода
    cursor.execute('''
    UPDATE user_promo_codes
    SET used_count = used_count + 1
    WHERE code = ? AND is_active = 1 AND (max_uses = 0 OR used_count < max_uses)
    ''', (code.upper(),))

    success = cursor.rowcount > 0

    if success:
        # Получаем информацию о промокоде
        promo = get_user_promo_code(code)
        if promo:
            # Начисляем подарок пользователю
            if promo['gift_type'] == 'balance':
                update_user_balance(user_id, promo['gift_amount'])
            elif promo['gift_type'] == 'stars':
                update_user_purchase_stats(user_id, 'stars', promo['gift_amount'])
            elif promo['gift_type'] == 'ton':
                update_user_purchase_stats(user_id, 'ton', promo['gift_amount'])

    conn.commit()
    conn.close()

    if success:
        logger.info(f"✅ Пользовательский промокод {code} использован пользователем {user_id}")
    else:
        logger.info(f"❌ Не удалось использовать пользовательский промокод {code}")

    return success

def get_user_used_promocodes(user_id: int):
    """Получает список использованных промокодов пользователя"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('''
    SELECT promo_code, used_date, order_type, original_amount, discount_amount, final_amount
    FROM used_promo_codes
    WHERE user_id = ?
    ORDER BY used_date DESC
    ''', (user_id,))

    promos = cursor.fetchall()
    conn.close()

    result = []
    for promo in promos:
        result.append({
            'code': promo[0],
            'used_date': promo[1],
            'order_type': promo[2],
            'original_amount': promo[3],
            'discount_amount': promo[4],
            'final_amount': promo[5]
        })

    return result

def deactivate_promo_code(code: str):
    """Деактивирует промокод"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('''
    UPDATE promo_codes SET is_active = 0 WHERE code = ?
    ''', (code.upper(),))

    success = cursor.rowcount > 0
    conn.commit()
    conn.close()

    if success:
        logger.info(f"✅ Промокод {code} деактивирован")
    return success

def get_all_promo_codes():
    """Получает все промокоды из базы данных"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        SELECT promo_id, code, discount_percent, discount_amount, min_amount,
               max_uses, used_count, valid_until, is_active, created_date,
               created_by, gift_amount, gift_type
        FROM promo_codes
        ORDER BY created_date DESC
        ''')

        promos = cursor.fetchall()
        conn.close()

        result = []
        for promo in promos:
            result.append({
                'promo_id': promo[0],
                'code': promo[1],
                'discount_percent': promo[2] or 0,
                'discount_amount': promo[3] or 0,
                'min_amount': promo[4] or 0,
                'max_uses': promo[5] or 1,
                'used_count': promo[6] or 0,
                'valid_until': promo[7],
                'is_active': promo[8],
                'created_date': promo[9],
                'created_by': promo[10],
                'gift_amount': promo[11] or 0,
                'gift_type': promo[12] or 'balance'
            })

        return result

    except Exception as e:
        logger.error(f"❌ Ошибка получения всех промокодов: {e}")
        return []

# 🔄 ОБНОВЛЯЕМ функцию add_user() для автоматического создания реферального кода
def add_user(user_id, username, full_name, referred_by=None):
    """Синхронная функция добавления пользователя с рефералами"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

        # Генерируем реферальный код
        ref_code = f"REF{user_id % 10000:04d}"

        # Проверяем существование пользователя
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
        existing_user = cursor.fetchone()

        if existing_user:
            # Просто обновляем данные
            cursor.execute('''
            UPDATE users SET username = ?, full_name = ?, last_activity = ?
            WHERE user_id = ?
            ''', (username, full_name, now, user_id))
            logger.info(f"🔄 Обновлен пользователь {user_id}")
        else:
            # Добавляем нового пользователя
            cursor.execute('''
            INSERT INTO users (user_id, username, full_name, registration_date, last_activity, referral_code, referred_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, username, full_name, now, now, ref_code, referred_by))
            logger.info(f"✅ Добавлен новый пользователь {user_id}, referred_by: {referred_by}")

            # 🔴 СОЗДАЕМ РЕФЕРАЛЬНУЮ ЗАПИСЬ ЕСЛИ ЕСТЬ РЕФЕРЕР
            if referred_by and referred_by != user_id:
                try:
                    cursor.execute('''
                    INSERT OR IGNORE INTO referrals (referrer_id, referred_id, referral_code, created_date)
                    VALUES (?, ?, ?, ?)
                    ''', (referred_by, user_id, ref_code, now))
                    logger.info(f"🎯 Создана реферальная запись: {referred_by} -> {user_id}")

                    # 🔴 ЗАПИСЫВАЕМ В ЛОГ О НОВОМ РЕФЕРАЛЕ (без отправки сообщения)
                    logger.info(f"🎉 Новый реферал: {referred_by} -> {user_id} ({username})")

                except Exception as e:
                    logger.error(f"❌ Ошибка создания реферальной записи: {e}")

        conn.commit()
        conn.close()
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка в add_user: {e}")
        return False

async def add_referral_bonus(order_id, user_id, amount, context):
    """Начисляет реферальный бонус за покупку - ТОЛЬКО НА РЕФЕРАЛЬНЫЙ БАЛАНС"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        # Находим реферера
        cursor.execute('SELECT referred_by FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()

        if not result or not result[0]:
            logger.info(f"ℹ️ У пользователя {user_id} нет реферера")
            conn.close()
            return False

        referrer_id = result[0]
        bonus_amount = amount * 0.05  # 5% бонус

        logger.info(f"💰 Начисляем реферальный бонус: {referrer_id} <- {user_id} = {bonus_amount:.2f}₽")

        # 🔴 ИСПРАВЛЕНО: Начисляем бонус ТОЛЬКО на referral_earnings, НЕ на balance
        cursor.execute('''
        UPDATE users
        SET referral_earnings = referral_earnings + ?,
            completed_referrals = completed_referrals + 1
        WHERE user_id = ?
        ''', (bonus_amount, referrer_id))

        # Обновляем реферальную статистику
        cursor.execute('''
        UPDATE referrals
        SET completed_orders = completed_orders + 1,
            total_earnings = total_earnings + ?,
            is_active = 1
        WHERE referred_id = ? AND referrer_id = ?
        ''', (bonus_amount, user_id, referrer_id))

        # Записываем выплату
        now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
        INSERT INTO referral_payments (referrer_id, referred_id, order_id, amount, payment_date, status)
        VALUES (?, ?, ?, ?, ?, 'confirmed')
        ''', (referrer_id, user_id, order_id, bonus_amount, now))

        conn.commit()
        conn.close()

        # 🔴 УВЕДОМЛЯЕМ РЕФЕРЕРА
        try:
            user_info = get_user_info(user_id)
            await context.bot.send_message(
                referrer_id,
                f"🎉 Реферальная покупка!\n\n"
                f"👤 Пользователь: {user_info['full_name']}\n"
                f"💰 Сумма покупки: {amount:.2f}₽\n"
                f"💸 Ваш бонус: {bonus_amount:.2f}₽\n\n"
                f"💎 Бонус зачислен на РЕФЕРАЛЬНЫЙ баланс!"
            )
            logger.info(f"✅ Уведомление о бонусе отправлено рефереру {referrer_id}")
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить реферера: {e}")

        logger.info(f"✅ Реферальный бонус начислен: {referrer_id} + {bonus_amount:.2f}₽ (ТОЛЬКО на реферальный баланс)")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка начисления реферального бонуса: {e}")
        return False

# 🔴 УЛУЧШЕННАЯ ФУНКЦИЯ ДЛЯ ОБРАБОТКИ ПОДТВЕРЖДЕНИЯ ЗАКАЗА
async def process_order_confirmation(order_id, context):
    """Обрабатывает подтверждение заказа и начисляет реферальные бонусы"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        # Получаем информацию о заказе
        cursor.execute('''
        SELECT user_id, order_type, amount, cost, status
        FROM pending_orders
        WHERE order_id = ? AND status = 'confirmed'
        ''', (order_id,))

        order = cursor.fetchone()

        if not order:
            logger.error(f"❌ Заказ {order_id} не найден или не подтвержден")
            return False

        user_id, order_type, amount, cost, status = order

        # 🔴 ВАЖНО: Начисляем реферальный бонус
        bonus_success = await process_referral_bonus(order_id, user_id, cost, context)

        if bonus_success:
            logger.info(f"✅ Реферальный бонус успешно начислен для заказа {order_id}")
        else:
            logger.info(f"ℹ️ Реферальный бонус не начислен для заказа {order_id}")

        conn.close()
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка обработки подтверждения заказа {order_id}: {e}")
        return False

# 🔴 ОБНОВЛЕННАЯ ФУНКЦИЯ ДЛЯ ОБРАБОТКИ КОМАНДЫ START С РЕФЕРАЛАМИ
async def handle_start_with_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает команду /start с реферальным кодом"""
    user = update.effective_user
    args = context.args

    referred_by = None

    # Проверяем наличие реферального кода
    if args and len(args) > 0:
        ref_code = args[0]
        logger.info(f"🔹 Обработка реферального кода: {ref_code} для пользователя {user.id}")

        # Ищем пользователя по реферальному коду
        referrer_id = get_user_id_by_referral_code(ref_code)

        if referrer_id and referrer_id != user.id:
            referred_by = referrer_id
            logger.info(f"🎯 Найден реферер: {referrer_id} для пользователя {user.id}")
        else:
            logger.warning(f"❌ Реферальный код {ref_code} не найден или ссылка на себя")

    # Добавляем/обновляем пользователя
    username = f"@{user.username}" if user.username else user.first_name
    full_name = user.full_name or user.first_name or "Неизвестно"

    is_new_user = add_user_simple(user.id, username, full_name, referred_by)

    # Обновляем статистику активности
    update_user_activity_stats(user.id)

    # Отправляем приветственное сообщение
    if referred_by:
        welcome_text = (
            f"👋 Добро пожаловать, {full_name}!\n\n"
            f"🎉 Вы были приглашены другим пользователем!\n\n"
            f"💎 Теперь вы можете покупать звёзды, TON и Premium подписки.\n\n"
            f"👇 Используйте кнопки ниже для навигации:"
        )
    else:
        welcome_text = (
            f"👋 Добро пожаловать, {full_name}!\n\n"
            f"💎 Здесь вы можете покупать звёзды, TON и Premium подписки для Telegram.\n\n"
            f"👇 Используйте кнопки ниже для навигации:"
        )

    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="HTML"
    )

    # Логируем результат
    if referred_by:
        logger.info(f"✅ Пользователь {user.id} зарегистрирован по реферальной ссылки от {referred_by}")
    else:
        logger.info(f"✅ Пользователь {user.id} зарегистрирован без реферала")

# 🔴 ДОБАВИМ ВЫЗОВ ОБНОВЛЕНИЯ СТАТИСТИКИ В КРИТИЧЕСКИХ МЕСТАХ
def update_user_purchase_stats(user_id, purchase_type, amount):
    """Обновляет статистику покупок пользователя"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        if purchase_type == 'stars':
            cursor.execute('UPDATE users SET stars_purchased = stars_purchased + ? WHERE user_id = ?', (amount, user_id))
        elif purchase_type == 'premium':
            cursor.execute('UPDATE users SET premium_purchased = premium_purchased + ? WHERE user_id = ?', (amount, user_id))
        elif purchase_type == 'ton':
            cursor.execute('UPDATE users SET ton_purchased = ton_purchased + ? WHERE user_id = ?', (amount, user_id))

        # Всегда обновляем последнюю активность
        now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('UPDATE users SET last_activity = ? WHERE user_id = ?', (now, user_id))

        conn.commit()
        conn.close()
        logger.info(f"📊 Обновлена статистика покупок для {user_id}: {purchase_type} +{amount}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка обновления статистики покупок: {e}")
        return False

def generate_referral_code(user_id):
    """Генерирует уникальный реферальный код"""
    import hashlib
    import random
    # Добавляем случайность чтобы коды были уникальными
    random_suffix = random.randint(1000, 9999)
    return f"REF{user_id % 10000:04d}{hashlib.md5(str(user_id + random_suffix).encode()).hexdigest()[:4].upper()}"

def get_user_referral_info(user_id):
    """Получает информацию о реферальной программе пользователя"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    # Получаем рефералов пользователя
    cursor.execute('''
    SELECT COUNT(*) as total_refs,
           SUM(CASE WHEN completed_orders > 0 THEN 1 ELSE 0 END) as active_refs,
           SUM(total_earnings) as total_earnings
    FROM referrals
    WHERE referrer_id = ? AND is_active = 1
    ''', (user_id,))

    ref_stats = cursor.fetchone()

    # Получаем реферальный код и баланс пользователя
    cursor.execute('SELECT referral_code, referral_earnings FROM users WHERE user_id = ?', (user_id,))
    user_info = cursor.fetchone()

    conn.close()

    return {
        'referral_code': user_info[0] if user_info else generate_referral_code(user_id),
        'total_referrals': ref_stats[0] or 0,
        'active_referrals': ref_stats[1] or 0,
        'total_earnings': ref_stats[2] or 0.0,
        'current_balance': user_info[1] if user_info else 0.0  # referral_earnings как баланс для вывода
    }

def get_user_id_by_referral_code(ref_code):
    """Находит ID пользователя по реферальному коду"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (ref_code,))
        result = cursor.fetchone()

        conn.close()
        return result[0] if result else None

    except Exception as e:
        logger.error(f"❌ Ошибка поиска по реферальному коду: {e}")
        return None

async def process_referral_bonus(order_id, user_id, amount, context):
    """Начисляет реферальный бонус за покупку - 5% бонус ТОЛЬКО НА РЕФЕРАЛЬНЫЙ БАЛАНС"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        # Находим реферера
        cursor.execute('SELECT referred_by FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()

        if not result or not result[0]:
            logger.info(f"ℹ️ У пользователя {user_id} нет реферера")
            conn.close()
            return False

        referrer_id = result[0]
        bonus_amount = amount * 0.05  # 5% бонус

        logger.info(f"💰 Начисляем реферальный бонус: {referrer_id} <- {user_id} = {bonus_amount:.2f}₽")

        # 🔴 ИСПРАВЛЕНО: Начисляем бонус ТОЛЬКО на referral_earnings, НЕ на balance
        cursor.execute('''
        UPDATE users
        SET referral_earnings = referral_earnings + ?,
            completed_referrals = completed_referrals + 1
        WHERE user_id = ?
        ''', (bonus_amount, referrer_id))

        # Обновляем реферальную статистику
        cursor.execute('''
        UPDATE referrals
        SET completed_orders = completed_orders + 1,
            total_earnings = total_earnings + ?,
            is_active = 1
        WHERE referred_id = ? AND referrer_id = ?
        ''', (bonus_amount, user_id, referrer_id))

        # Записываем выплату
        now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
        INSERT INTO referral_payments (referrer_id, referred_id, order_id, amount, payment_date, status)
        VALUES (?, ?, ?, ?, ?, 'confirmed')
        ''', (referrer_id, user_id, order_id, bonus_amount, now))

        conn.commit()
        conn.close()

        # 🔴 УВЕДОМЛЯЕМ РЕФЕРЕРА
        try:
            user_info = get_user_info(user_id)
            await context.bot.send_message(
                referrer_id,
                f"🎉 Реферальная покупка!\n\n"
                f"👤 Пользователь: {user_info['full_name']}\n"
                f"💰 Сумма покупки: {amount:.2f}₽\n"
                f"💸 Ваш бонус: {bonus_amount:.2f}₽ (5%)\n\n"
                f"💎 Бонус зачислен на РЕФЕРАЛЬНЫЙ баланс!"
            )
            logger.info(f"✅ Уведомление о бонусе отправлено рефереру {referrer_id}")
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить реферера: {e}")

        logger.info(f"✅ Реферальный бонус начислен: {referrer_id} + {bonus_amount:.2f}₽ (5% ТОЛЬКО на реферальный баланс)")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка начисления реферального бонуса: {e}")
        return False

def get_referral_payments(user_id, limit=10):
    """Получает историю реферальных выплат"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('''
    SELECT rp.amount, rp.payment_date, u.username, u.full_name
    FROM referral_payments rp
    LEFT JOIN users u ON rp.referred_id = u.user_id
    WHERE rp.referrer_id = ? AND rp.status = 'confirmed'
    ORDER BY rp.payment_date DESC
    LIMIT ?
    ''', (user_id, limit))

    payments = cursor.fetchall()
    conn.close()

    result = []
    for payment in payments:
        result.append({
            'amount': payment[0],
            'date': payment[1],
            'referred_username': payment[2] or 'Пользователь',
            'referred_name': payment[3] or 'Неизвестно'
        })

    return result

async def show_referral_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню реферальной программы - 5% бонус"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    ref_info = get_user_referral_info(user_id)

    text = (
        "👥 РЕФЕРАЛЬНАЯ ПРОГРАММА\n\n"
        f"💎 Ваш реферальный код:\n"
        f"<code>{ref_info['referral_code']}</code>\n\n"

        f"📊 Статистика:\n"
        f"• Всего приглашено: {ref_info['total_referrals']} чел.\n"
        f"• Активных рефералов: {ref_info['active_referrals']} чел.\n"
        f"• Всего заработано: {ref_info['total_earnings']:.2f}₽\n"
        f"• Текущий баланс: {ref_info['current_balance']:.2f}₽\n\n"

        "💰 Условия программы:\n"
        "• 5% с каждой подтвержденной покупки приглашенного (заработок будет увиличен при переходе на новый уровень)\n"  # 🔴 ИЗМЕНЕНО: 1%
        "• Средства зачисляются сразу на баланс\n"
        "• Без ограничений по количеству рефералов\n\n"

        "📣 Ваша реферальная ссылка:\n"
        f"https://t.me/starsshop17_bot?start={ref_info['referral_code']}"
    )

    keyboard = [
        [InlineKeyboardButton("📋 История выплат", callback_data="ref_history")],
        [InlineKeyboardButton("💸 Вывод средств", callback_data="withdraw_menu")],
        [InlineKeyboardButton("📢 Поделиться ссылкой",
                             url=f"https://t.me/share/url?url=https://t.me/starsshop17_bot?start={ref_info['referral_code']}&text=💎 Покупай звёзды, TON и Premium с выгодой!")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile_back")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def show_referral_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает историю реферальных выплат"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    payments = get_referral_payments(user_id, 15)

    if not payments:
        text = "📊 История выплат пуста\n\nПока нет завершенных покупок у ваших рефералов."
    else:
        text = "📊 ИСТОРИЯ РЕФЕРАЛЬНЫХ ВЫПЛАТ:\n\n"
        total_earned = 0

        for i, payment in enumerate(payments, 1):
            text += (
                f"{i}. +{payment['amount']:.2f}₽\n"
                f"   👤 {payment['referred_name']}\n"
                f"   📅 {payment['date'][:16]}\n"
                f"   ──────────────────\n"
            )
            total_earned += payment['amount']

        text += f"\n💰 Всего заработано: {total_earned:.2f}₽"

    keyboard = [
        [InlineKeyboardButton("👥 Назад к реферальной программе", callback_data="referral_program")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

def get_user_balance(user_id):
    """Получает баланс пользователя"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0.0
    except Exception as e:
        logger.error(f"❌ Ошибка получения баланса: {e}")
        return 0.0

def update_user_balance(user_id, amount):
    """Обновляет баланс пользователя"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        # Получаем текущий баланс - ИСПРАВЛЕННАЯ ВЕРСИЯ
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        current_balance = result[0] if result is not None else 0.0  # ← ИСПРАВЛЕНО

        # Обновляем баланс
        new_balance = current_balance + amount
        cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))

        conn.commit()
        conn.close()

        logger.info(f"💰 Баланс пользователя {user_id} обновлен: {current_balance} -> {new_balance}")
        return new_balance

    except Exception as e:
        logger.error(f"❌ Ошибка обновления баланса: {e}")
        return 0.0

async def show_withdrawal_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню вывода средств - ТОЛЬКО РЕФЕРАЛЬНЫЙ БАЛАНС"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    ref_info = get_user_referral_info(user_id)
    main_balance = get_user_balance(user_id)

    text = (
        f"💳 ВЫВОД СРЕДСТВ\n\n"
        f"💰 Основной баланс: {main_balance:.2f}₽\n"
        f"💎 Реферальный баланс: {ref_info['current_balance']:.2f}₽\n\n"
        f"💡 Доступно для вывода: {ref_info['current_balance']:.2f}₽\n"
        f"📝 Вы можете выводить только средства, заработанные в реферальной программе\n\n"
        f"👇 Выберите способ вывода:"
    )

    keyboard = [
        [InlineKeyboardButton("💳 Банковская карта", callback_data="withdraw_bank")],
        [InlineKeyboardButton("📱 Номер телефона", callback_data="withdraw_phone")],
        [InlineKeyboardButton("₿ Криптокошелек", callback_data="withdraw_crypto")],
        [InlineKeyboardButton("📋 История выводов", callback_data="withdraw_history")],
        [InlineKeyboardButton("👥 Назад к реферальной программе", callback_data="referral_program")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор способа вывода - ТОЛЬКО РЕФЕРАЛЬНЫЙ БАЛАНС"""
    query = update.callback_query
    await query.answer()

    method = query.data.replace("withdraw_", "")
    context.user_data['withdraw_method'] = method

    method_names = {
        'bank': 'банковскую карту',
        'phone': 'номер телефона',
        'crypto': 'криптокошелек'
    }

    # 🔴 ПОЛУЧАЕМ ТОЛЬКО РЕФЕРАЛЬНЫЙ БАЛАНС
    user_id = query.from_user.id
    ref_info = get_user_referral_info(user_id)

    text = (
        f"💳 Вывод на {method_names[method]}\n\n"
        f"💰 Доступно для вывода: {ref_info['current_balance']:.2f}₽\n\n"
        f"Введите сумму для вывода (от 10₽):"
    )

    keyboard = [
        [InlineKeyboardButton("🔙 Отмена", callback_data="withdraw_menu")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    # Установим состояние для ожидания суммы
    context.user_data['awaiting_withdrawal'] = True

# ОТДЕЛЬНАЯ функция для обработки суммы вывода
async def process_withdrawal_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод суммы для вывода - ТОЛЬКО РЕФЕРАЛЬНЫЙ БАЛАНС"""
    user_id = update.message.from_user.id
    amount_text = update.message.text.replace(',', '.').strip()

    try:
        amount = float(amount_text)

        # 🔴 ПРОВЕРЯЕМ ТОЛЬКО РЕФЕРАЛЬНЫЙ БАЛАНС
        ref_info = get_user_referral_info(user_id)
        referral_balance = ref_info.get('current_balance', 0)

        logger.info(f"💰 Проверка реферального баланса: user_id={user_id}, referral_balance={referral_balance}, amount={amount}")

        if amount < 10:
            await update.message.reply_text(
                "❌ Минимальная сумма вывода - 10₽",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="withdraw_menu")]
                ])
            )
            return

        if amount > referral_balance:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="withdraw_menu")]
            ])

            await update.message.reply_text(
                f"❌ Недостаточно средств на реферальном балансе!\n\n"
                f"💰 Заработано на рефералах: {ref_info['total_earnings']:.2f}₽\n"
                f"💸 Доступно для вывода: {referral_balance:.2f}₽\n"
                f"💸 Запрошено: {amount:.2f}₽\n\n"
                f"💡 Вы можете выводить только средства, заработанные в реферальной программе.",
                reply_markup=keyboard
            )
            return

        method = context.user_data.get('withdraw_method', 'bank')
        context.user_data['withdrawal_amount'] = amount
        context.user_data['awaiting_withdrawal'] = False
        context.user_data['awaiting_withdrawal_details'] = True

        detail_prompts = {
            'bank': "💳 Введите номер банковской карты (обычно 16-18 цифр):",
            'phone': "📱 Введите номер телефона (в формате 79XXXXXXXXX):",
            'crypto': "₿ Введите адрес криптокошелька:"
        }

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Отмена", callback_data="withdraw_menu")]
        ])

        await update.message.reply_text(
            f"✅ Сумма подтверждена: {amount:.2f}₽\n"
            f"💳 Способ: {get_method_name(method)}\n\n"
            f"{detail_prompts[method]}",
            reply_markup=keyboard
        )

    except ValueError:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data="withdraw_menu")]
        ])
        await update.message.reply_text(
            "❌ Введите корректную сумму (например: 100 или 150.50)\n\n"
            "💡 Можно использовать как точку так и запятую: 150.50 или 150,50",
            reply_markup=keyboard
        )

async def process_withdrawal_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод реквизитов для вывода - ТОЛЬКО РЕФЕРАЛЬНЫЙ БАЛАНС"""
    user_id = update.message.from_user.id
    details = update.message.text.strip()
    amount = context.user_data.get('withdrawal_amount', 0)
    method = context.user_data.get('withdraw_method', 'bank')

    logger.info(f"🔴 НАЧАЛО process_withdrawal_details: user_id={user_id}, amount={amount}, method={method}")

    # 🔴 ПРОВЕРЯЕМ ТОЛЬКО РЕФЕРАЛЬНЫЙ БАЛАНС
    ref_info = get_user_referral_info(user_id)
    referral_balance = ref_info.get('current_balance', 0)

    logger.info(f"💰 Баланс проверка: referral_balance={referral_balance}, amount={amount}")

    if amount > referral_balance:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data="withdraw_menu")]
        ])
        await update.message.reply_text(
            f"❌ Недостаточно средств на реферальном балансе!\n\n"
            f"💸 Доступно: {referral_balance:.2f}₽\n"
            f"💸 Запрошено: {amount:.2f}₽",
            reply_markup=keyboard
        )
        context.user_data['awaiting_withdrawal_details'] = False
        context.user_data['withdrawal_amount'] = None
        context.user_data['withdraw_method'] = None
        return

    # Создаем заявку на вывод
    logger.info(f"🔴 СОЗДАЕМ ЗАЯВКУ В БАЗЕ")
    success = create_withdrawal_request(user_id, amount, method, details)

    if success:
        logger.info(f"✅ Заявка на вывод создана успешно в базе")

        # 🔴 УВЕДОМЛЯЕМ АДМИНА
        try:
            user_info = get_user_info(user_id)
            method_name = get_method_name(method)

            admin_text = (
                f"🔄 НОВАЯ ЗАЯВКА НА ВЫВОД\n\n"
                f"👤 Пользователь: @{user_info['username']} (ID: {user_id})\n"
                f"👤 Имя: {user_info['full_name']}\n"
                f"💰 Сумма: {amount:.2f}₽\n"
                f"💳 Способ: {method_name}\n"
                f"📋 Реквизиты: {details}\n\n"
                f"💰 Реферальный баланс: {referral_balance:.2f}₽\n"
                f"⏰ Время: {get_moscow_time().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            admin_keyboard = [
                [InlineKeyboardButton("✅ Одобрить вывод", callback_data=f"approve_withdraw_{user_id}_{amount}")],
                [InlineKeyboardButton("❌ Отклонить вывод", callback_data=f"reject_withdraw_{user_id}_{amount}")]
            ]

            logger.info(f"🔴 ОТПРАВЛЯЕМ СООБЩЕНИЕ АДМИНУ {ADMIN_ID}...")
            await context.bot.send_message(
                ADMIN_ID,
                admin_text,
                reply_markup=InlineKeyboardMarkup(admin_keyboard)
            )
            logger.info(f"✅ Уведомление админу отправлено!")

        except Exception as e:
            logger.error(f"❌ ОШИБКА ОТПРАВКИ АДМИНУ: {e}")

        # Уведомляем пользователя
        await update.message.reply_text(
            f"✅ Заявка на вывод создана!\n\n"
            f"💰 Сумма: {amount:.2f}₽\n"
            f"💳 Способ: {get_method_name(method)}\n"
            f"📋 Реквизиты: {details}\n\n"
            f"⏳ Заявка будет обработана в течение 1-15 минут\n"
            f"💡 Средства будут списаны с реферального баланса после подтверждения",
            reply_markup=get_main_menu_keyboard()
        )

        # Очищаем состояние
        context.user_data['awaiting_withdrawal_details'] = False
        context.user_data['withdrawal_amount'] = None
        context.user_data['withdraw_method'] = None

    else:
        logger.error(f"❌ Ошибка при создании заявки на вывод в базе")
        await update.message.reply_text("❌ Ошибка при создании заявки")

async def handle_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор способа вывода"""
    query = update.callback_query
    await query.answer()

    method = query.data.replace("withdraw_", "")
    context.user_data['withdraw_method'] = method

    method_names = {
        'bank': 'банковскую карту',
        'phone': 'номер телефона',
        'crypto': 'криптокошелек'
    }

    text = (
        f"💳 Вывод на {method_names[method]}\n\n"
        f"Введите сумму для вывода (от 10₽):"
    )

    keyboard = [
        [InlineKeyboardButton("🔙 Отмена", callback_data="cancel_withdrawal")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    # Установим состояние для ожидания суммы
    context.user_data['awaiting_withdrawal'] = True

async def process_withdrawal_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод реквизитов для вывода"""
    user_id = update.message.from_user.id
    details = update.message.text
    amount = context.user_data.get('withdrawal_amount', 0)
    method = context.user_data.get('withdraw_method', 'bank')

    logger.info(f"🔴 НАЧАЛО process_withdrawal_details: user_id={user_id}, amount={amount}, method={method}")

    # 🔴 ПРОВЕРЯЕМ ТОЛЬКО РЕФЕРАЛЬНЫЙ БАЛАНС
    ref_info = get_user_referral_info(user_id)
    referral_balance = ref_info.get('current_balance', 0)

    logger.info(f"💰 Баланс проверка: referral_balance={referral_balance}, amount={amount}")

    if amount > referral_balance:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Отмена", callback_data="withdraw_menu")]
        ])
        await update.message.reply_text("❌ Недостаточно средств", reply_markup=keyboard)
        context.user_data['awaiting_withdrawal_details'] = False
        context.user_data['withdrawal_amount'] = None
        context.user_data['withdraw_method'] = None
        return

    # Создаем заявку на вывод
    logger.info(f"🔴 СОЗДАЕМ ЗАЯВКУ В БАЗЕ")
    success = create_withdrawal_request(user_id, amount, method, details)

    if success:
        logger.info(f"✅ Заявка на вывод создана успешно в базе")

        # 🔴🔴🔴 ПРИНУДИТЕЛЬНАЯ ОТПРАВКА АДМИНУ 🔴🔴🔴
        try:
            user_info = get_user_info(user_id)
            method_name = get_method_name(method)

            admin_text = (
                f"🔄 НОВАЯ ЗАЯВКА НА ВЫВОД\n\n"
                f"👤 Пользователь: @{user_info['username']} (ID: {user_id})\n"
                f"👤 Имя: {user_info['full_name']}\n"
                f"💰 Сумма: {amount:.2f}₽\n"
                f"💳 Способ: {method_name}\n"
                f"📋 Реквизиты: {details}\n\n"
                f"⏰ Время: {get_moscow_time().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            admin_keyboard = [
                [InlineKeyboardButton("✅ Одобрить вывод", callback_data=f"approve_withdraw_{user_id}_{amount}")],
                [InlineKeyboardButton("❌ Отклонить вывод", callback_data=f"reject_withdraw_{user_id}_{amount}")]
            ]

            logger.info(f"🔴 ОТПРАВЛЯЕМ СООБЩЕНИЕ АДМИНУ {ADMIN_ID}...")
            await context.bot.send_message(
                ADMIN_ID,
                admin_text,
                reply_markup=InlineKeyboardMarkup(admin_keyboard)
            )
            logger.info(f"✅ Уведомление админу отправлено!")

        except Exception as e:
            logger.error(f"❌ ОШИБКА ОТПРАВКИ АДМИНУ: {e}")

        # Уведомляем пользователя
        await update.message.reply_text(
            f"✅ Заявка на вывод создана!\n\n"
            f"💰 Сумма: {amount:.2f}₽\n"
            f"💳 Способ: {get_method_name(method)}\n"
            f"📋 Реквизиты: {details}\n\n"
            f"⏳ Заявка будет обработана в течение 1-15 минут",
            reply_markup=get_main_menu_keyboard()
        )

        # Очищаем состояние
        context.user_data['awaiting_withdrawal_details'] = False
        context.user_data['withdrawal_amount'] = None
        context.user_data['withdraw_method'] = None

    else:
        logger.error(f"❌ Ошибка при создании заявки на вывод в базе")
        await update.message.reply_text("❌ Ошибка при создании заявки")

async def handle_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод суммы для вывода"""
    user_id = update.message.from_user.id
    amount_text = update.message.text

    try:
        amount = float(amount_text)
        balance = get_user_balance(user_id)

        if amount < 10:
            await update.message.reply_text("❌ Минимальная сумма вывода - 10₽")
            return

        if amount > balance:
            await update.message.reply_text("❌ Недостаточно средств на балансе")
            return

        context.user_data['withdraw_amount'] = amount
        context.user_data['awaiting_withdraw_amount'] = False
        context.user_data['awaiting_withdraw_details'] = True

        method = context.user_data.get('withdraw_method', 'bank')
        detail_prompts = {
            'bank': "Введите номер банковской карты:",
            'phone': "Введите номер телефона:",
            'crypto': "Введите адрес криптокошелька:"
        }

        await update.message.reply_text(
            f"💰 Сумма: {amount:.2f}₽\n"
            f"{detail_prompts[method]}"
        )

    except ValueError:
        await update.message.reply_text("❌ Введите корректную сумму")

async def handle_withdraw_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод реквизитов для вывода"""
    user_id = update.message.from_user.id
    details = update.message.text
    amount = context.user_data.get('withdraw_amount', 0)
    method = context.user_data.get('withdraw_method', 'bank')

    # Создаем заявку на вывод
    success = create_withdrawal_request(user_id, amount, method, details)

    if success:
        # Списываем средства с баланса
        new_balance = update_user_balance(user_id, -amount)

        await update.message.reply_text(
            f"✅ Заявка на вывод создана!\n\n"
            f"💰 Сумма: {amount:.2f}₽\n"
            f"💳 Способ: {get_method_name(method)}\n"
            f"📋 Реквизиты: {details}\n"
            f"💸 Новый баланс: {new_balance:.2f}₽\n\n"
            f"⏳ Заявка будет обработана в течение получаса",
            reply_markup=get_main_menu_keyboard()
        )

        # Уведомляем админа
        await notify_admin_about_withdrawal(context, user_id, amount, method, details)
    else:
        await update.message.reply_text("❌ Ошибка при создании заявки")

def create_withdrawal_request(user_id, amount, method, details):
    """Создает заявку на вывод средств"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute('''
        INSERT INTO withdrawals (user_id, amount, method, details, created_date, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
        ''', (user_id, amount, method, details, now))

        withdrawal_id = cursor.lastrowid  # 🔴 ПОЛУЧАЕМ ID созданной заявки

        conn.commit()
        conn.close()

        logger.info(f"✅ Создана заявка на вывод: {user_id} - {amount}₽ (ID: {withdrawal_id})")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка создания заявки на вывод: {e}")
        return False

def get_method_name(method):
    """Возвращает читаемое название метода"""
    names = {
        'bank': '💳 Банковская карта',
        'phone': '📱 Номер телефона',
        'crypto': '₿ Криптокошелек'
    }
    return names.get(method, '❓ Неизвестно')

async def show_withdrawal_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает историю выводов пользователя"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    withdrawals = get_user_withdrawals(user_id)

    if not withdrawals:
        text = "📋 История выводов пуста\n\nУ вас еще не было операций по выводу средств."
    else:
        text = "📋 ИСТОРИЯ ВЫВОДОВ:\n\n"
        total_withdrawn = 0

        for i, withdrawal in enumerate(withdrawals, 1):
            status_emoji = "✅" if withdrawal['status'] == 'approved' else "⏳" if withdrawal['status'] == 'pending' else "❌"
            text += (
                f"{i}. {withdrawal['amount']:.2f}₽ - {withdrawal['method_name']}\n"
                f"   📋 {withdrawal['details']}\n"
                f"   {status_emoji} {withdrawal['status_text']}\n"
                f"   📅 {withdrawal['created_date'][:16]}\n"
                f"   ──────────────────\n"
            )
            if withdrawal['status'] == 'approved':
                total_withdrawn += withdrawal['amount']

        text += f"\n💰 Всего выведено: {total_withdrawn:.2f}₽"

    keyboard = [
        [InlineKeyboardButton("💸 Сделать вывод", callback_data="withdraw_menu")],
        [InlineKeyboardButton("👥 Назад к реферальной программе", callback_data="referral_program")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

def get_user_withdrawals(user_id, limit=10):
    """Получает историю выводов пользователя"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        SELECT amount, method, details, status, created_date, processed_date
        FROM withdrawals
        WHERE user_id = ?
        ORDER BY withdrawal_id DESC
        LIMIT ?
        ''', (user_id, limit))

        withdrawals = cursor.fetchall()
        conn.close()

        result = []
        for withdrawal in withdrawals:
            method_names = {
                'bank': 'Банковская карта',
                'phone': 'Номер телефона',
                'crypto': 'Криптокошелек'
            }
            status_texts = {
                'pending': 'Ожидание',
                'approved': 'Выполнено',
                'rejected': 'Отклонено'
            }

            result.append({
                'amount': withdrawal[0],
                'method': withdrawal[1],
                'method_name': method_names.get(withdrawal[1], 'Неизвестно'),
                'details': withdrawal[2],
                'status': withdrawal[3],
                'status_text': status_texts.get(withdrawal[3], 'Неизвестно'),
                'created_date': withdrawal[4],
                'processed_date': withdrawal[5]
            })

        return result

    except Exception as e:
        logger.error(f"❌ Ошибка получения истории выводов: {e}")
        return []

async def handle_admin_withdrawal_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает действия админа по заявкам на вывод"""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа")
        return

    action, _, user_id_str = query.data.partition('_withdraw_')
    user_id = int(user_id_str)

    # Здесь должна быть логика обработки заявки админом
    # Пока просто уведомляем
    if action == 'approve':
        await query.edit_message_text(f"✅ Заявка на вывод от пользователя {user_id} одобрена")
    else:
        await query.edit_message_text(f"❌ Заявка на вывод от пользователя {user_id} отклонена")

async def notify_admin_about_withdrawal(context, user_id, amount, method, details, ref_info):
    """Уведомляет админа о новой заявке на вывод - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    try:
        if user_id == ADMIN_ID:
            logger.info(f"ℹ️ Админ {ADMIN_ID} создал заявку на вывод, уведомление не отправлено")
            return

        user_info = get_user_info(user_id)
        method_name = get_method_name(method)

        text = (
            f"🔄 НОВАЯ ЗАЯВКА НА ВЫВОД\n\n"
            f"👤 Пользователь: @{user_info['username']} (ID: {user_id})\n"
            f"👤 Имя: {user_info['full_name']}\n"
            f"💰 Сумма: {amount:.2f}₽\n"
            f"💳 Способ: {method_name}\n"
            f"📋 Реквизиты: {details}\n\n"
            f"📊 Статистика реферальных доходов:\n"
            f"• Всего заработано: {ref_info['total_earnings']:.2f}₽\n"
            f"• Доступно для вывода: {ref_info['current_balance']:.2f}₽\n"
            f"• Приглашено пользователей: {ref_info['total_referrals']}\n"
            f"• Активных рефералов: {ref_info['active_referrals']}\n\n"
            f"⏰ Время: {get_moscow_time().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        # 🔴 ИСПРАВЛЕННЫЙ ФОРМАТ CALLBACK DATA
        keyboard = [
            [InlineKeyboardButton("✅ Одобрить вывод", callback_data=f"approve_withdraw_{user_id}_{amount}")],
            [InlineKeyboardButton("❌ Отклонить вывод", callback_data=f"reject_withdraw_{user_id}_{amount}")]
        ]

        message = await context.bot.send_message(ADMIN_ID, text, reply_markup=InlineKeyboardMarkup(keyboard))
        logger.info(f"✅ Уведомление админу отправлено о выводе {user_id} - {amount}₽")

        # Сохраняем ID сообщения
        update_withdrawal_admin_message(user_id, amount, message.message_id)

    except Exception as e:
        logger.error(f"❌ Ошибка уведомления админа о выводе: {e}")

def update_withdrawal_admin_message(user_id, amount, message_id):
    """Сохраняет ID сообщения админа для заявки на вывод"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        UPDATE withdrawals
        SET admin_message_id = ?
        WHERE user_id = ? AND amount = ? AND status = 'pending'
        ''', (message_id, user_id, amount))

        conn.commit()
        conn.close()
        logger.info(f"✅ Сохранен ID сообщения админа: {user_id} - {amount}₽ - message_id: {message_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения ID сообщения админа: {e}")
        return False

async def approve_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Одобряет заявку на вывод - ИСПРАВЛЕННАЯ ВЕРСИЯ СО СПИСАНИЕМ ИЗ РЕФЕРАЛЬНОГО БАЛАНСА"""
    query = update.callback_query
    await query.answer("🔄 Одобряем вывод...")

    logger.info(f"🔴 APPROVE_WITHDRAWAL ВЫЗВАНА")
    logger.info(f"🔴 Callback data: {query.data}")

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа")
        return

    try:
        # Парсим callback data в формате "approve_withdraw_USERID_AMOUNT"
        parts = query.data.split('_')
        logger.info(f"🔴 Parts: {parts}")

        if len(parts) < 4:
            await query.edit_message_text("❌ Ошибка: неверный формат данных")
            return

        # Получаем user_id и amount из callback data
        user_id = int(parts[2])
        amount = float(parts[3])

        logger.info(f"🔴 User ID: {user_id}, Amount: {amount}")

        # Находим заявку в базе
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        SELECT withdrawal_id, method, details, status
        FROM withdrawals
        WHERE user_id = ? AND amount = ? AND status = 'pending'
        ''', (user_id, amount))

        withdrawal = cursor.fetchone()

        if not withdrawal:
            await query.edit_message_text("❌ Заявка не найдена или уже обработана")
            conn.close()
            return

        withdrawal_id, method, details, status = withdrawal
        logger.info(f"🔴 Найдена заявка ID: {withdrawal_id}")

        # 🔴🔴🔴 ВАЖНОЕ ИСПРАВЛЕНИЕ: СПИСЫВАЕМ СРЕДСТВА ИЗ РЕФЕРАЛЬНОГО БАЛАНСА 🔴🔴🔴
        # Получаем реферальный баланс пользователя
        cursor.execute('SELECT referral_earnings, balance FROM users WHERE user_id = ?', (user_id,))
        user_balance_result = cursor.fetchone()

        if not user_balance_result:
            await query.edit_message_text("❌ Пользователь не найден")
            conn.close()
            return

        referral_earnings = user_balance_result[0] or 0.0
        main_balance = user_balance_result[1] or 0.0

        logger.info(f"💰 Реферальный баланс пользователя {user_id}: {referral_earnings}₽")
        logger.info(f"💰 Основной баланс пользователя {user_id}: {main_balance}₽")

        # Проверяем, достаточно ли средств на реферальном балансе
        if referral_earnings < amount:
            await query.edit_message_text(
                f"❌ Недостаточно средств на реферальном балансе!\n\n"
                f"💰 Реферальный баланс: {referral_earnings:.2f}₽\n"
                f"💸 Сумма вывода: {amount:.2f}₽\n\n"
                f"❌ Вывод не может быть одобрен"
            )
            conn.close()
            return

        # 🔴 СПИСЫВАЕМ СРЕДСТВА ИЗ РЕФЕРАЛЬНОГО БАЛАНСА
        new_referral_balance = referral_earnings - amount
        cursor.execute('UPDATE users SET referral_earnings = ? WHERE user_id = ?', (new_referral_balance, user_id))
        logger.info(f"💰 Реферальный баланс пользователя {user_id} обновлен: {referral_earnings} -> {new_referral_balance}₽")

        # Обновляем статус заявки
        cursor.execute('''
        UPDATE withdrawals
        SET status = 'approved',
            processed_date = ?
        WHERE withdrawal_id = ?
        ''', (get_moscow_time().strftime("%Y-%m-%d %H:%M:%S"), withdrawal_id))

        conn.commit()
        conn.close()

        # Уведомляем пользователя
        try:
            method_name = get_method_name(method)
            await context.bot.send_message(
                user_id,
                f"🎉 Ваш вывод одобрен!\n\n"
                f"💰 Сумма: {amount:.2f}₽\n"
                f"💳 Способ: {method_name}\n"
                f"📋 Реквизиты: {details}\n\n"
                f"💸 Сумма списана с реферального баланса\n"
                f"💰 Реферальный баланс: {new_referral_balance:.2f}₽\n"
                f"💳 Основной баланс: {main_balance:.2f}₽\n\n"
                f"⏱️ Средства переведены!"
            )
            logger.info(f"✅ Уведомление отправлено пользователю {user_id}")
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить пользователя: {e}")

        # Обновляем сообщение админа
        method_name = get_method_name(method)
        await query.edit_message_text(
            f"✅ Вывод одобрен!\n\n"
            f"👤 Пользователь: {user_id}\n"
            f"💰 Сумма: {amount:.2f}₽\n"
            f"💳 Метод: {method_name}\n"
            f"📋 Реквизиты: {details}\n\n"
            f"💸 Средства списаны с РЕФЕРАЛЬНОГО баланса\n"
            f"💰 Реферальный баланс был: {referral_earnings:.2f}₽\n"
            f"💰 Реферальный баланс стал: {new_referral_balance:.2f}₽\n"
            f"💳 Основной баланс: {main_balance:.2f}₽\n\n"
            f"✅ Пользователь уведомлен"
        )

        logger.info(f"✅ Вывод успешно одобрен: {user_id} - {amount}₽ (реферальный баланс: {referral_earnings} -> {new_referral_balance}₽)")

    except Exception as e:
        logger.error(f"❌ Ошибка в approve_withdrawal: {e}")
        logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")

async def reject_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отклоняет заявку на вывод - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    query = update.callback_query
    await query.answer("🔄 Отклоняем вывод...")

    logger.info(f"🔴 REJECT_WITHDRAWAL ВЫЗВАНА")
    logger.info(f"🔴 Callback data: {query.data}")

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа")
        return

    try:
        # Парсим callback data в формате "reject_withdraw_USERID_AMOUNT"
        parts = query.data.split('_')
        logger.info(f"🔴 Parts: {parts}")

        if len(parts) < 4:
            await query.edit_message_text("❌ Ошибка: неверный формат данных")
            return

        # Получаем user_id и amount из callback data
        user_id = int(parts[2])
        amount = float(parts[3])

        logger.info(f"🔴 User ID: {user_id}, Amount: {amount}")

        # Находим заявку в базе
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        SELECT withdrawal_id, method, details, status
        FROM withdrawals
        WHERE user_id = ? AND amount = ? AND status = 'pending'
        ''', (user_id, amount))

        withdrawal = cursor.fetchone()

        if not withdrawal:
            await query.edit_message_text("❌ Заявка не найдена или уже обработана")
            conn.close()
            return

        withdrawal_id, method, details, status = withdrawal
        logger.info(f"🔴 Найдена заявка ID: {withdrawal_id}")

        # 🔴 ДОБАВЛЕНО: ВОЗВРАЩАЕМ СРЕДСТВА НА БАЛАНС (если они были списаны)
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        user_balance_result = cursor.fetchone()

        if user_balance_result:
            current_balance = user_balance_result[0] or 0.0
            # Если средства были списаны, возвращаем их
            # (в реальной системе нужно отслеживать, были ли средства списаны)
            # new_balance = current_balance + amount
            # cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
            # logger.info(f"💰 Средства возвращены на баланс: {user_id} + {amount}₽")

        # Обновляем статус заявки
        cursor.execute('''
        UPDATE withdrawals
        SET status = 'rejected',
            processed_date = ?
        WHERE withdrawal_id = ?
        ''', (get_moscow_time().strftime("%Y-%m-%d %H:%M:%S"), withdrawal_id))

        conn.commit()
        conn.close()

        # Уведомляем пользователя
        try:
            method_name = get_method_name(method)
            await context.bot.send_message(
                user_id,
                f"❌ Ваша заявка на вывод отклонена\n\n"
                f"💰 Сумма: {amount:.2f}₽\n"
                f"💳 Способ: {method_name}\n\n"
                f"💡 Если у вас есть вопросы, обратитесь в поддержку"
            )
            logger.info(f"✅ Уведомление об отклонении отправлено пользователю {user_id}")
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить пользователя: {e}")

        # Обновляем сообщение админа
        await query.edit_message_text(
            f"❌ Вывод отклонен!\n\n"
            f"👤 Пользователь: {user_id}\n"
            f"💰 Сумма: {amount:.2f}₽\n\n"
            f"✅ Пользователь уведомлен"
        )

        logger.info(f"❌ Вывод отклонен: {user_id} - {amount}₽")

    except Exception as e:
        logger.error(f"❌ Ошибка в reject_withdrawal: {e}")
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")

def update_withdrawal_status(user_id, amount, status):
    """Обновляет статус заявки на вывод"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        UPDATE withdrawals
        SET status = ?, processed_date = ?
        WHERE user_id = ? AND amount = ? AND status = 'pending'
        ''', (status, get_moscow_time().strftime("%Y-%m-%d %H:%M:%S"), user_id, amount))

        conn.commit()
        conn.close()
        logger.info(f"✅ Статус вывода обновлен: {user_id} - {amount}₽ - {status}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка обновления статуса вывода: {e}")
        return False

async def show_admin_referral_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику реферальной программы для админа"""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа")
        return

    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    # Общая статистика
    cursor.execute('''
    SELECT COUNT(*) as total_referrals,
           SUM(completed_orders) as total_orders,
           SUM(total_earnings) as total_paid
    FROM referrals
    WHERE is_active = 1
    ''')
    stats = cursor.fetchone()

    # Топ рефереров (используем юзернеймы вместо ID)
    cursor.execute('''
    SELECT u.username, u.full_name,
           COUNT(r.referred_id) as ref_count,
           SUM(r.total_earnings) as total_earnings
    FROM referrals r
    JOIN users u ON r.referrer_id = u.user_id
    WHERE r.is_active = 1
    GROUP BY r.referrer_id
    ORDER BY total_earnings DESC
    LIMIT 10
    ''')
    top_referrers = cursor.fetchall()

    conn.close()

    text = (
        "👥 СТАТИСТИКА РЕФЕРАЛЬНОЙ ПРОГРАММЫ\n\n"
        f"📊 Общая статистика:\n"
        f"• Всего рефералов: {stats[0] or 0}\n"
        f"• Всего покупок: {stats[1] or 0}\n"
        f"• Всего выплачено: {stats[2] or 0:.2f}₽\n\n"

        "🏆 Топ рефереров:\n"
    )

    for i, referrer in enumerate(top_referrers, 1):
        username, full_name, ref_count, earnings = referrer
        username_display = f"@{username}" if username else full_name or "Без имени"
        text += f"{i}. {username_display}: {ref_count} реф. / {earnings:.2f}₽\n"

    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_ref_stats")],
        [InlineKeyboardButton("📊 Общая статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_panel")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# 🔴 ДОБАВИМ ФУНКЦИЮ ДЛЯ ОБНОВЛЕНИЯ СТАТИСТИКИ ПОЛЬЗОВАТЕЛЕЙ
def update_user_activity_stats(user_id):
    """Обновляет статистику активности пользователя"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute('''
        UPDATE users SET last_activity = ? WHERE user_id = ?
        ''', (now, user_id))

        conn.commit()
        conn.close()
        logger.info(f"📊 Обновлена статистика активности для пользователя {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка обновления статистики активности: {e}")
        return False

def add_user_simple(user_id, username, full_name, referred_by=None):
    """Упрощенная функция добавления пользователя с рефералами - РЕФЕРАЛЬНЫЙ КОД ФИКСИРОВАН"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

        # Проверяем существование пользователя и получаем ЕГО СУЩЕСТВУЮЩИЙ реферальный код
        cursor.execute('SELECT user_id, referred_by, referral_code FROM users WHERE user_id = ?', (user_id,))
        existing_user = cursor.fetchone()

        is_new_user = False
        ref_code = None

        if existing_user:
            # Пользователь уже существует - используем ЕГО СУЩЕСТВУЮЩИЙ реферальный код
            ref_code = existing_user[2]  # Существующий код
            logger.info(f"🔹 Пользователь {user_id} уже существует, реферальный код: {ref_code}")

            # Обновляем данные (username, full_name, активность), НО НЕ ТРОГАЕМ referral_code
            cursor.execute('''
            UPDATE users SET username = ?, full_name = ?, last_activity = ?
            WHERE user_id = ?
            ''', (username, full_name, now, user_id))
            logger.info(f"🔄 Обновлен существующий пользователь {user_id}")
        else:
            # НОВЫЙ пользователь - генерируем РАЗОВЫЙ реферальный код
            is_new_user = True
            ref_code = generate_referral_code(user_id)  # Генерируем ТОЛЬКО один раз!
            logger.info(f"🔹 Новый пользователь {user_id}, сгенерирован реферальный код: {ref_code}, referred_by: {referred_by}")

            cursor.execute('''
            INSERT INTO users (user_id, username, full_name, registration_date, last_activity, referral_code, referred_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, username, full_name, now, now, ref_code, referred_by))
            logger.info(f"✅ Добавлен новый пользователь {user_id}")

            # СОЗДАЕМ РЕФЕРАЛЬНУЮ ЗАПИСЬ ТОЛЬКО ДЛЯ НОВЫХ ПОЛЬЗОВАТЕЛЕЙ С РЕФЕРЕРОМ
            if referred_by and referred_by != user_id:
                logger.info(f"🔹 Пытаемся создать реферальную запись: {referred_by} -> {user_id}")
                try:
                    cursor.execute('SELECT ref_id FROM referrals WHERE referred_id = ?', (user_id,))
                    existing_ref = cursor.fetchone()

                    if not existing_ref:
                        cursor.execute('''
                        INSERT INTO referrals (referrer_id, referred_id, referral_code, created_date)
                        VALUES (?, ?, ?, ?)
                        ''', (referred_by, user_id, ref_code, now))
                        logger.info(f"🎯 СОЗДАНА реферальная запись: {referred_by} -> {user_id}")

                        # Обновляем статистику реферера
                        cursor.execute('''
                        UPDATE users
                        SET total_referrals = total_referrals + 1
                        WHERE user_id = ?
                        ''', (referred_by,))
                        logger.info(f"📊 Обновлена статистика прихода для реферера {referred_by}")
                    else:
                        logger.info(f"🔹 Реферальная запись для {user_id} уже существует")
                except Exception as e:
                    logger.error(f"❌ Ошибка создания реферальной записи: {e}")
            else:
                logger.info(f"🔹 Нет реферера для нового пользователя {user_id}")

        conn.commit()
        conn.close()

        logger.info(f"🔹 add_user_simple завершена, is_new_user={is_new_user}, ref_code={ref_code}")
        return is_new_user

    except Exception as e:
        logger.error(f"❌ Ошибка в add_user_simple: {e}")
        return False

def get_user_info(user_id):
    """Получает информацию о пользователе"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT username, full_name FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return {'username': result[0] or 'Нет username', 'full_name': result[1] or 'Неизвестно'}
        else:
            return {'username': 'Не найден', 'full_name': 'Неизвестно'}
    except Exception as e:
        logger.error(f"❌ Ошибка получения информации о пользователе: {e}")
        return {'username': 'Ошибка', 'full_name': 'Ошибка'}

async def enter_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE, order_type: str):
    """Обработка ввода промокода - УЛУЧШЕННАЯ ВЕРСИЯ"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # ОЧИЩАЕМ предыдущие состояния промокодов
    if user_id in awaiting_promo_code:
        del awaiting_promo_code[user_id]

    # Очищаем user_data от старых промо-данных
    for key in ['applying_promo_for', 'awaiting_promo_input', 'promo_product_type']:
        if key in context.user_data:
            del context.user_data[key]

    # УСТАНАВЛИВАЕМ новые состояния с ПРАВИЛЬНЫМ типом
    context.user_data['applying_promo_for'] = order_type
    context.user_data['awaiting_promo_input'] = True
    context.user_data['promo_product_type'] = order_type
    awaiting_promo_code[user_id] = True

    logger.info(f"🎫 Активирован ввод промокода для {order_type}, user_id: {user_id}")
    logger.info(f"🎫 Сохранен promo_product_type: {order_type}")
    logger.info(f"🎫 User data после установки: {context.user_data}")

    await query.edit_message_text(
        f"🎫 Введите промокод для {get_promo_type_name(order_type)}:\n\n"
        "❌ Для отмены отправьте 'отмена'"
    )

def calculate_discount(original_amount: float, promo_code: str, user_id: int):
    """Рассчитывает скидку по промокоду с проверкой использования"""
    promo = get_promo_code(promo_code)
    if not promo:
        return original_amount, 0, "Промокод не найден"

    # Проверяем, использовал ли пользователь уже этот промокод
    if has_user_used_promo(user_id, promo_code):
        return original_amount, 0, "Вы уже использовали этот промокод"

    # Проверка минимальной суммы
    if promo['min_amount'] > 0 and original_amount < promo['min_amount']:
        return original_amount, 0, f"Минимальная сумма для промокода: {promo['min_amount']}₽"

    # Проверка срока действия
    if promo['valid_until']:
        valid_until = datetime.strptime(promo['valid_until'], "%Y-%m-%d %H:%M:%S")
        if get_moscow_time() > valid_until:
            return original_amount, 0, "Промокод истек"

    # Проверка лимита использований
    if promo['max_uses'] > 0 and promo['used_count'] >= promo['max_uses']:
        return original_amount, 0, "Промокод уже использован максимальное количество раз"

    # Расчет скидки
    discount = 0
    if promo['discount_percent'] > 0:
        discount = original_amount * (promo['discount_percent'] / 100)
    if promo['discount_amount'] > 0:
        discount = max(discount, promo['discount_amount'])

    final_amount = max(0, original_amount - discount)

    return final_amount, discount, "Скидка применена"

# Глобальные переменные для хранения примененных промокодов
applied_promocodes = {}

# Функции для работы со статистикой продаж
def record_sale(sale_type: str, amount: float, revenue: float):
    """Записывает продажу в статистику"""
    logger.info(f"🔹 ЗАПИСЬ ПРОДАЖИ: type={sale_type}, amount={amount}, revenue={revenue}")

    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    now = get_moscow_time()
    date_str = now.strftime("%Y-%m-%d")
    hour = now.hour

    # Проверяем, есть ли уже запись для этого часа
    cursor.execute('''
    SELECT stat_id, stars_sold, premium_sold, ton_sold, revenue
    FROM sales_stats
    WHERE stat_date = ? AND stat_hour = ?
    ''', (date_str, hour))

    result = cursor.fetchone()

    if result:
        # Обновляем существующую запись
        stat_id, stars_sold, premium_sold, ton_sold, current_revenue = result

        if sale_type == "stars":
            stars_sold += int(amount)
        elif sale_type == "premium":
            premium_sold += int(amount)
        elif sale_type == "ton":
            ton_sold += amount

        revenue += current_revenue

        cursor.execute('''
        UPDATE sales_stats
        SET stars_sold = ?, premium_sold = ?, ton_sold = ?, revenue = ?
        WHERE stat_id = ?
        ''', (stars_sold, premium_sold, ton_sold, revenue, stat_id))
    else:
        # Создаем новую запись
        stars_sold = premium_sold = 0
        ton_sold = 0.0

        if sale_type == "stars":
            stars_sold = int(amount)
        elif sale_type == "premium":
            premium_sold = int(amount)
        elif sale_type == "ton":
            ton_sold = amount

        cursor.execute('''
        INSERT INTO sales_stats (stat_date, stat_hour, stars_sold, premium_sold, ton_sold, revenue)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (date_str, hour, stars_sold, premium_sold, ton_sold, revenue))

    conn.commit()
    conn.close()

def get_sales_stats(hours: int = 24):
    """Получает статистику продаж за указанное количество часов"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    end_time = get_moscow_time()
    start_time = end_time - timedelta(hours=hours)

    cursor.execute('''
    SELECT
        SUM(stars_sold) as total_stars,
        SUM(premium_sold) as total_premium,
        SUM(ton_sold) as total_ton,
        SUM(revenue) as total_revenue
    FROM sales_stats
    WHERE datetime(stat_date || ' ' || printf('%02d', stat_hour) || ':00:00') >= datetime(?)
    ''', (start_time.strftime("%Y-%m-%d %H:%M:%S"),))

    result = cursor.fetchone()
    conn.close()

    return {
        'stars': result[0] or 0,
        'premium': result[1] or 0,
        'ton': result[2] or 0.0,
        'revenue': result[3] or 0.0
    }

def get_hourly_sales_stats():
    """Получает статистику продаж за последний час"""
    return get_sales_stats(1)

def get_daily_sales_stats():
    """Получает статистику продаж за последние 24 часа"""
    return get_sales_stats(24)

def get_total_sales_stats():
    """Получает общую статистику продаж из таблицы users"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('SELECT SUM(stars_purchased), SUM(premium_purchased), SUM(ton_purchased) FROM users')
    result = cursor.fetchone()

    total_stars = result[0] or 0
    total_premium = result[1] or 0
    total_ton = result[2] or 0.0

    # Рассчитываем общую выручку (для TON используем фиксированную цену 200 руб)
    total_revenue = (total_stars * STAR_PRICE) + (total_premium * sum(PREMIUM_PRICES.values()) / len(PREMIUM_PRICES)) + (total_ton * TON_PRICE)

    conn.close()

    return {
        'stars': total_stars,
        'premium': total_premium,
        'ton': total_ton,
        'revenue': total_revenue
    }

def get_user_stats():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]

    # АКТИВНЫЕ ПОЛЬЗОВАТЕЛИ ЗА СЕГОДНЯ
    cursor.execute('SELECT COUNT(*) FROM users WHERE date(last_activity) = date("now")')
    active_today = cursor.fetchone()[0]

    # Заблокированные пользователи
    cursor.execute('SELECT COUNT(*) FROM users WHERE is_blocked = 1')
    blocked_users = cursor.fetchone()[0]

    # Статистика покупок
    cursor.execute('SELECT SUM(stars_purchased) FROM users')
    total_stars = cursor.fetchone()[0] or 0

    cursor.execute('SELECT SUM(premium_purchased) FROM users')
    total_premium = cursor.fetchone()[0] or 0

    cursor.execute('SELECT SUM(ton_purchased) FROM users')
    total_ton = cursor.fetchone()[0] or 0

    conn.close()

    logger.info(f"📊 Статистика пользователей: total={total_users}, active_today={active_today}, blocked={blocked_users}, stars={total_stars}, premium={total_premium}, ton={total_ton}")

    return total_users, active_today, blocked_users, total_stars, total_premium, total_ton

# НОВЫЕ ФУНКЦИИ ДЛЯ СИСТЕМЫ ПОДТВЕРЖДЕНИЯ ЗАКАЗОВ
def save_pending_order(user_id, username, full_name, order_type, amount, cost, receipt_message_id, friend_username="", is_balance_replenishment=False):
    """Сохраняет заказ в ожидании подтверждения"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute('''
    INSERT INTO pending_orders
    (user_id, username, full_name, order_type, amount, cost, receipt_message_id, created_date, status, friend_username, is_balance_replenishment)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
    ''', (user_id, username, full_name, order_type, amount, cost, receipt_message_id, now, friend_username, 1 if is_balance_replenishment else 0))

    order_id = cursor.lastrowid
    conn.commit()
    conn.close()

    logger.info(f"✅ Заказ {order_id} сохранен в ожидании подтверждения")
    return order_id

def get_pending_order(order_id):
    """Получает информацию о заказе"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM pending_orders WHERE order_id = ?', (order_id,))
    order = cursor.fetchone()
    conn.close()

    if order:
        return {
            'order_id': order[0],
            'user_id': order[1],
            'username': order[2],
            'full_name': order[3],
            'order_type': order[4],
            'amount': order[5],
            'cost': order[6],
            'receipt_message_id': order[7],
            'admin_message_id': order[8],
            'created_date': order[9],
            'status': order[10],
            'friend_username': order[11],
            'is_balance_replenishment': order[12]
        }
    return None

def update_order_status(order_id, status, admin_message_id=None):
    """Обновляет статус заказа"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    if admin_message_id:
        cursor.execute('''
        UPDATE pending_orders
        SET status = ?, admin_message_id = ?
        WHERE order_id = ?
        ''', (status, admin_message_id, order_id))
    else:
        cursor.execute('''
        UPDATE pending_orders
        SET status = ?
        WHERE order_id = ?
        ''', (status, order_id))

    conn.commit()
    conn.close()
    logger.info(f"✅ Статус заказа {order_id} обновлен на '{status}'")

def get_pending_orders_count():
    """Возвращает количество заказов в ожидании"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM pending_orders WHERE status = "pending"')
    count = cursor.fetchone()[0]
    conn.close()

    return count

def update_user_purchase_stats(user_id, order_type, amount):
    """Обновляет статистику покупок пользователя"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    logger.info(f"🔹 ОБНОВЛЕНИЕ СТАТИСТИКИ: user_id={user_id}, type={order_type}, amount={amount}")

    if order_type == "stars":
        cursor.execute('UPDATE users SET stars_purchased = stars_purchased + ? WHERE user_id = ?', (amount, user_id))
        logger.info(f"✅ Добавлено {amount} звёзд пользователю {user_id}")
    elif order_type == "premium":
        cursor.execute('UPDATE users SET premium_purchased = premium_purchased + ? WHERE user_id = ?', (amount, user_id))
        logger.info(f"✅ Добавлено {amount} premium пользователю {user_id}")
    elif order_type == "ton":
        cursor.execute('UPDATE users SET ton_purchased = ton_purchased + ? WHERE user_id = ?', (amount, user_id))
        logger.info(f"✅ Добавлено {amount} TON пользователю {user_id}")
    elif order_type == "gift_stars":
        cursor.execute('UPDATE users SET stars_gifted = stars_gifted + ? WHERE user_id = ?', (amount, user_id))
        logger.info(f"✅ Добавлено {amount} подаренных звёзд пользователю {user_id}")
    elif order_type == "gift_ton":
        cursor.execute('UPDATE users SET ton_gifted = ton_gifted + ? WHERE user_id = ?', (amount, user_id))
        logger.info(f"✅ Добавлено {amount} подаренных TON пользователю {user_id}")
    elif order_type == "gift_premium":
        cursor.execute('UPDATE users SET premium_gifted = premium_gifted + ? WHERE user_id = ?', (amount, user_id))
        logger.info(f"✅ Добавлено {amount} подаренного premium пользователю {user_id}")

    conn.commit()
    conn.close()
    logger.info(f"✅ Статистика пользователя {user_id} обновлена: {order_type} +{amount}")

# НОВАЯ ФУНКЦИЯ - получение всех пользователей с пагинацией
def get_all_users_paginated(page=0, limit=10):
    """Получает пользователей с пагинацией"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    # Получаем общее количество пользователей
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]

    # Получаем пользователей для текущей страницы
    offset = page * limit
    cursor.execute('''
        SELECT user_id, username, full_name, registration_date, last_activity, is_blocked, balance
        FROM users
        ORDER BY registration_date DESC
        LIMIT ? OFFSET ?
    ''', (limit, offset))

    users = cursor.fetchall()
    conn.close()

    return users, total_users

def find_user_by_username_or_id(search_term: str):
    """Находит пользователя по username или ID"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    # Пробуем найти по ID
    if search_term.isdigit():
        cursor.execute('SELECT user_id, username, full_name, balance FROM users WHERE user_id = ?', (int(search_term),))
        user = cursor.fetchone()
        if user:
            conn.close()
            return {
                'user_id': user[0],
                'username': user[1],
                'full_name': user[2],
                'balance': user[3]
            }

    # Пробуем найти по username (с @ и без)
    username = search_term.lstrip('@')
    cursor.execute('SELECT user_id, username, full_name, balance FROM users WHERE username LIKE ?', (f'%{username}%',))
    user = cursor.fetchone()
    conn.close()

    if user:
        return {
            'user_id': user[0],
            'username': user[1],
            'full_name': user[2],
            'balance': user[3]
        }
    return None

# УЛУЧШЕННЫЕ КЛАВИАТУРЫ С ЛУЧШИМ ДИЗАЙНОМ
def get_main_menu_keyboard():
    """Главное меню - НЕ СКРЫВАЕТСЯ после нажатия"""
    keyboard = [
        ["⭐ Купить звёзды", "💎 Купить TON"],
        ["🌟 Telegram Premium", "🎁 Сделать подарок"],
        ["💱 Актуальные курсы", "🛍️ Продажа аккаунтов"],
        ["👤 Мой профиль", "ℹ️ Помощь"]
    ]

    logger.info(f"🔹 Создана клавиатура главного меню: {keyboard}")
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_simple_menu_keyboard():
    """Простая клавиатура с одной кнопкой Главное меню"""
    return ReplyKeyboardMarkup(
        [
            ["🏠 Главное меню"]
        ],
        resize_keyboard=True
    )

def get_cancel_keyboard():
    """Клавиатура только с кнопкой отмены"""
    return ReplyKeyboardMarkup(
        [
            ["Отмена"]
        ],
        resize_keyboard=True
    )

def get_admin_keyboard():
    pending_count = get_pending_orders_count()
    pending_badge = f" ({pending_count})" if pending_count > 0 else ""

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(f"✅ Подтвердить заказы{pending_badge}", callback_data="admin_confirm_orders")],
        [InlineKeyboardButton("👥 Все пользователи", callback_data="admin_all_users")],
        [InlineKeyboardButton("👥 Реферальная статистика", callback_data="admin_ref_stats")],
        [InlineKeyboardButton("💰 Пополнить баланс", callback_data="admin_add_balance")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton("🎫 Промокоды", callback_data="admin_promocodes")],
        [InlineKeyboardButton("🔄 Перезапуск", callback_data="admin_restart")],
        [InlineKeyboardButton("🔙 В меню", callback_data="back_to_main")]
    ])

def get_profile_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Пополнить баланс", callback_data="replenish_balance")],
        [InlineKeyboardButton("👥 Реферальная программа", callback_data="referral_program")],
        [InlineKeyboardButton("🎫 Мои промокоды", callback_data="my_promocodes")],
        [InlineKeyboardButton("🧾 Мои чеки", callback_data="my_checks")],
        [InlineKeyboardButton("🎁 Активировать чек", callback_data="activate_check")]
    ])

def get_order_confirmation_keyboard(order_id):
    """Клавиатура для подтверждения заказа"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить заказ", callback_data=f"confirm_order_{order_id}")],
        [InlineKeyboardButton("❌ Отклонить заказ", callback_data=f"reject_order_{order_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_stats")]
    ])

# НОВАЯ КЛАВИАТУРА ДЛЯ КУРСОВ ВАЛЮТ С ФЛАГАМИ
def get_currency_keyboard():
    """Клавиатура для меню курсов валют"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💱 Конвертер валют", callback_data="currency_converter")],
        [InlineKeyboardButton("🔄 Обновить курсы", callback_data="refresh_rates")]
    ])

def get_checks_keyboard():
    """Клавиатура для меню чеков"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Создать чек на звёзды", callback_data="create_check_stars")],
        [InlineKeyboardButton("💎 Создать чек на TON", callback_data="create_check_ton")],
        [InlineKeyboardButton("🌟 Создать чек на Premium", callback_data="create_check_premium")],
        [InlineKeyboardButton("🔙 Назад", callback_data="profile_back")]
    ])

def get_check_payment_keyboard(check_code: str):
    """Клавиатура для оплаты чека"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Оплатить через ЮMoney", callback_data=f"pay_check_{check_code}")],
        [InlineKeyboardButton("📱 Оплатить через СБП", callback_data=f"sbp_check_{check_code}")],
        [InlineKeyboardButton("📲 Оплатить на карту", callback_data=f"card_check_{check_code}")],
        [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data=f"crypto_check_{check_code}")],
        [InlineKeyboardButton("🔙 Отменить", callback_data="cancel_check")]
    ])

# === НОВЫЙ КОНВЕРТЕР ВАЛЮТ С ФЛАГАМИ ===

def get_converter_keyboard():
    """Клавиатура для конвертера валют с флагами"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{FLAGS['USD']} USD → {FLAGS['RUB']} RUB", callback_data="convert_usd_rub")],
        [InlineKeyboardButton(f"{FLAGS['EUR']} EUR → {FLAGS['RUB']} RUB", callback_data="convert_eur_rub")],
        [InlineKeyboardButton(f"{FLAGS['TON']} TON → {FLAGS['RUB']} RUB", callback_data="convert_ton_rub")],
        [InlineKeyboardButton(f"{FLAGS['USDT']} USDT → {FLAGS['RUB']} RUB", callback_data="convert_usdt_rub")],
        [InlineKeyboardButton(f"{FLAGS['RUB']} RUB → {FLAGS['USD']} USD", callback_data="convert_rub_usd")],
        [InlineKeyboardButton(f"{FLAGS['RUB']} RUB → {FLAGS['EUR']} EUR", callback_data="convert_rub_eur")],
        [InlineKeyboardButton(f"{FLAGS['RUB']} RUB → {FLAGS['TON']} TON", callback_data="convert_rub_ton")],
        [InlineKeyboardButton(f"{FLAGS['RUB']} RUB → {FLAGS['USDT']} USDT", callback_data="convert_rub_usdt")],
        [InlineKeyboardButton("📊 Актуальные курсы", callback_data="show_rates")],
        [InlineKeyboardButton("🔙 Назад", callback_data="currency_rates")]
    ])

# Глобальные переменные
pending_payments = {}
awaiting_receipts = {}
awaiting_friend_username = {}
awaiting_broadcast = {}
awaiting_custom_amount = {}
awaiting_ton_amount = {}
awaiting_promo_code = {}

# НОВЫЕ ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ ВВОДА КОЛИЧЕСТВА
awaiting_custom_stars = {}
awaiting_custom_ton = {}

# НОВЫЕ ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ КОНВЕРТЕРА
awaiting_conversion = {}
conversion_data = {}

# НОВЫЕ ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ БАЛАНСА И ПОЛЬЗОВАТЕЛЬСКИХ ПРОМОКОДОВ
awaiting_balance_amount = {}
awaiting_promo_creation = {}
awaiting_user_search = {}

# Функции для работы с БД
def add_user(user_id, username, full_name):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

    # Проверяем существование пользователя
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    existing_user = cursor.fetchone()

    if existing_user:
        # Обновляем существующего пользователя
        cursor.execute('''
        UPDATE users SET username = ?, full_name = ?, last_activity = ?
        WHERE user_id = ?
        ''', (username, full_name, now, user_id))
    else:
        # Добавляем нового пользователя
        cursor.execute('''
        INSERT INTO users (user_id, username, full_name, registration_date, last_activity)
        VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, full_name, now, now))

    conn.commit()
    conn.close()

def update_user_activity(user_id):
    """Обновляет активность пользователя при ЛЮБОМ взаимодействии"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
    UPDATE users SET last_activity = ? WHERE user_id = ?
    ''', (now, user_id))
    conn.commit()
    conn.close()

def mark_user_blocked(user_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    UPDATE users SET is_blocked = 1 WHERE user_id = ?
    ''', (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE is_blocked = 0')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    logger.info(f"Retrieved {len(users)} active users from database")
    return users

# Функции для работы с временными подарками
def save_temp_gift(user_id, gift_type, amount, period, cost, friend_username=""):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute('''
    INSERT OR REPLACE INTO temp_gifts (user_id, gift_type, amount, period, cost, friend_username, created_date)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, gift_type, amount, period, cost, friend_username, now))

    conn.commit()
    conn.close()
    logger.info(f"✅ Подарок сохранен в БД для user_id {user_id}: {gift_type}, {amount}, {friend_username}")
    return True

def get_temp_gift(user_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM temp_gifts WHERE user_id = ?', (user_id,))
    gift = cursor.fetchone()
    conn.close()

    if gift:
        gift_info = {
            "user_id": gift[0],
            "type": gift[1],
            "amount": gift[2],
            "period": gift[3],
            "cost": gift[4],
            "friend_username": gift[5]
        }
        logger.info(f"✅ Подарок найден в БД для user_id {user_id}: {gift_info}")
        return gift_info
    logger.info(f"❌ Подарок не найден в БД для user_id {user_id}")
    return None

def delete_temp_gift(user_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM temp_gifts WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    logger.info(f"✅ Подарок удален из БД для user_id {user_id}")

async def show_my_checks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает чеки пользователя"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    checks = get_user_checks(user_id)

    if not checks:
        text = "🧾 У вас пока нет созданных чеков.\n\nСоздайте свой первый чек и отправьте его другу!"
        keyboard = [
            [InlineKeyboardButton("➕ Создать чек", callback_data="create_check_menu")],
            [InlineKeyboardButton("🔙 Назад", callback_data="profile_back")]
        ]
    else:
        text = "🧾 Ваши чеки:\n\n"

        active_checks = [c for c in checks if not c['is_activated']]
        activated_checks = [c for c in checks if c['is_activated']]

        if active_checks:
            text += "✅ Активные чеки:\n"
            for check in active_checks[:5]:  # Показываем только последние 5
                type_text = get_check_type_text(check['check_type'])
                text += f"🎫 {check['check_code']} - {type_text} {check['amount']} шт\n"
                text += f"   💰 {check['cost']}₽ • {check['created_date'][:16]}\n"
                text += f"   🔗 Отправьте код другу: {check['check_code']}\n\n"

        if activated_checks:
            text += "💰 Активированные чеки:\n"
            for check in activated_checks[:3]:
                type_text = get_check_type_text(check['check_type'])
                text += f"🎫 {check['check_code']} - {type_text} {check['amount']} шт\n"
                text += f"   ✅ Активирован • {check['created_date'][:16]}\n\n"

        keyboard = [
            [InlineKeyboardButton("➕ Создать новый чек", callback_data="create_check_menu")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="my_checks")],
            [InlineKeyboardButton("🔙 Назад", callback_data="profile_back")]
        ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_create_check_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню создания чека"""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🧾 Создание чека\n\n"
        "Выберите тип чека:\n\n"
        "💡 Чек - это цифровой подарочный сертификат, который можно отправить любому пользователю. "
        "Получатель сможет активировать его и получить товар мгновенно!",
        reply_markup=get_checks_keyboard()
    )

async def start_create_check(update: Update, context: ContextTypes.DEFAULT_TYPE, check_type: str):
    """Начинает процесс создания чека с фото"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # Сохраняем тип чека
    context.user_data['current_check_type'] = check_type
    context.user_data['awaiting_check_amount'] = True

    type_text = get_check_type_text(check_type)

    if check_type == "stars":
        message = f"⭐ Создание чека на звёзды\n\nВведите количество звёзд (минимум 50):"
    elif check_type == "ton":
        message = f"💎 Создание чека на TON\n\nВведите количество TON:"
    elif check_type == "premium":
        message = f"🌟 Создание чека на Premium\n\nВведите срок подписки (3 месяца, 6 месяцев, 1 год):"

    await query.edit_message_text(
        f"{message}\n\n❌ Для отмены отправьте 'отмена'"
    )

async def process_check_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает фото чека и создает чек"""
    user_id = update.message.from_user.id

    if not context.user_data.get('awaiting_check_photo'):
        return

    if not update.message.photo:
        await update.message.reply_text("❌ Пожалуйста, отправьте фото")
        return

    # Получаем самое качественное фото
    photo_file = update.message.photo[-1]
    photo_file_id = photo_file.file_id

    check_data = context.user_data.get('current_check')
    if not check_data:
        await update.message.reply_text("❌ Ошибка: данные чека не найдены")
        return

    # Создаем чек в базе данных
    success, check_code, check_id = create_check(
        user_id,
        check_data['type'],
        check_data['amount'],
        check_data['cost'],
        photo_file_id
    )

    if not success:
        await update.message.reply_text(f"❌ Ошибка создания чека: {check_code}")
        return

    # Публикуем чек в канале
    check_info = {
        'check_code': check_code,
        'check_type': check_data['type'],
        'amount': check_data['amount'],
        'cost': check_data['cost']
    }

    await publish_check_to_channel(context, check_info, photo_file_id)

    # Очищаем состояния
    context.user_data['awaiting_check_photo'] = False
    if 'current_check' in context.user_data:
        del context.user_data['current_check']
    if 'current_check_type' in context.user_data:
        del context.user_data['current_check_type']

    # Показываем успешное создание
    type_text = get_check_type_text(check_data['type'])

    if check_data['type'] == "premium":
        description = f"🌟 Telegram Premium на {check_data['period']}"
    else:
        unit = "звёзд" if check_data['type'] == "stars" else "TON"
        description = f"{type_text} {check_data['amount']} {unit}"

    await update.message.reply_text(
        f"🎉 Чек успешно создан и опубликован!\n\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Стоимость: {check_data['cost']:.2f}₽\n"
        f"🎫 Код чека: {check_code}\n\n"
        f"💡 Чек опубликован в канале и готов к получению!",
        reply_markup=get_main_menu_keyboard()
    )

async def claim_check(update: Update, context: ContextTypes.DEFAULT_TYPE, check_code: str):
    """Обрабатывает нажатие кнопки 'Получить чек'"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # Получаем информацию о чеке
    check = get_check_by_code(check_code)
    if not check:
        await query.edit_message_text("❌ Чек не найден или уже активирован")
        return

    if check['is_activated']:
        await query.edit_message_text("❌ Этот чек уже был активирован")
        return

    # Создаем заказ на активацию чека
    user = await context.bot.get_chat(user_id)

    order_id = save_pending_order(
        user_id=user_id,
        username=user.username,
        full_name=user.full_name,
        order_type=f"check_activation_{check['check_type']}",
        amount=check['amount'],
        cost=0,  # Чек уже оплачен
        receipt_message_id=query.message.message_id,
        is_balance_replenishment=False,
        friend_username=check_code
    )

    # Обновляем сообщение в канале
    try:
        type_text = get_check_type_text(check['check_type'])
        if check['check_type'] == "premium":
            description = f"🌟 Telegram Premium"
        else:
            unit = "звёзд" if check['check_type'] == "stars" else "TON"
            description = f"{type_text} {check['amount']} {unit}"

        new_caption = (
            f"🎁 ЧЕК НА {description}\n\n"
            f"💰 Стоимость: {check['cost']:.2f}₽\n"
            f"🎫 Код: {check_code}\n\n"
            f"✅ Запрошен пользователем: @{user.username}\n"
            f"⏳ Ожидает подтверждения..."
        )

        # ID канала
        CHANNEL_ID = "@your_channel_username"

        if check.get('photo_file_id'):
            await context.bot.edit_message_caption(
                chat_id=CHANNEL_ID,
                message_id=check.get('message_id'),
                caption=new_caption,
                reply_markup=None  # Убираем кнопку
            )
        else:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=check.get('message_id'),
                text=new_caption,
                reply_markup=None
            )
    except Exception as e:
        logger.error(f"❌ Ошибка обновления сообщения в канале: {e}")

    # Уведомляем пользователя
    await query.edit_message_text(
        f"🎉 Запрос на получение чека отправлен!\n\n"
        f"📦 Чек: {description}\n"
        f"🎫 Код: {check_code}\n\n"
        f"⏳ Ожидайте подтверждения администратора\n"
        f"Обычно это занимает 1-15 минут",
        reply_markup=get_main_menu_keyboard()
    )

    # Уведомляем админа
    moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
    admin_message = (
        f"🎫 ЗАПРОС АКТИВАЦИИ ЧЕКА!\n\n"
        f"👤 Пользователь: @{user.username} (ID: {user_id})\n"
        f"🎫 Код чека: {check_code}\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Стоимость: {check['cost']:.2f}₽\n"
        f"⏰ Время (МСК): {moscow_time}\n\n"
        f"✅ Подтвердите активацию:"
    )

    admin_msg = await context.bot.send_message(
        ADMIN_ID,
        admin_message,
        reply_markup=get_order_confirmation_keyboard(order_id)
    )

    update_order_status(order_id, "pending", admin_msg.message_id)

async def process_check_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод количества/периода для чека - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    user_id = update.message.from_user.id

    if not context.user_data.get('awaiting_check_amount'):
        return

    check_type = context.user_data.get('current_check_type')
    user_input = update.message.text.strip()

    # Проверяем отмену
    if user_input.lower() in ['отмена', 'cancel', 'отменить']:
        context.user_data['awaiting_check_amount'] = False
        if 'current_check_type' in context.user_data:
            del context.user_data['current_check_type']

        await update.message.reply_text(
            "✅ Создание чека отменено",
            reply_markup=get_main_menu_keyboard()
        )
        return

    try:
        amount = 0
        cost = 0
        period = ""

        if check_type == "premium":
            # Обработка периода для Premium
            period_map = {
                '3 месяца': '3 месяца',
                '6 месяцев': '6 месяцев',
                '1 год': '1 год',
                '3': '3 месяца',
                '6': '6 месяцев',
                '12': '1 год',
                'год': '1 год'
            }

            if user_input.lower() not in period_map:
                await update.message.reply_text(
                    "❌ Неверный срок подписки. Используйте: 3 месяца, 6 месяцев, 1 год\n\n"
                    "Попробуйте еще раз:"
                )
                return

            period = period_map[user_input.lower()]
            amount = 1
            cost = PREMIUM_PRICES[period]

        else:
            # Обработка количества для stars и ton
            user_input = user_input.replace(',', '.').replace(' ', '')
            cleaned_input = ''.join(char for char in user_input if char.isdigit() or char == '.')

            if not cleaned_input:
                await update.message.reply_text("❌ Пожалуйста, введите корректное число")
                return

            amount = float(cleaned_input)

            if check_type == "stars":
                if amount < 50:
                    await update.message.reply_text("❌ Минимальное количество звёзд: 50")
                    return
                cost = amount * STAR_PRICE
            elif check_type == "ton":
                if amount <= 0:
                    await update.message.reply_text("❌ Количество TON должно быть больше 0")
                    return
                cost = amount * TON_PRICE

        # 🔴 НЕМЕДЛЕННО создаем чек в базе данных с РЕАЛЬНЫМ кодом
        success, check_code, check_id = create_check(
            creator_id=user_id,
            check_type=check_type,
            amount=amount,
            cost=cost,
            photo_file_id=None,
            message_id=None
        )

        if not success:
            await update.message.reply_text(f"❌ Ошибка создания чека: {check_code}")
            return

        # 🔴 Сохраняем данные чека с РЕАЛЬНЫМ кодом
        context.user_data['current_check'] = {
            'type': check_type,
            'amount': amount,
            'cost': cost,
            'period': period if check_type == "premium" else "",
            'check_code': check_code,  # РЕАЛЬНЫЙ код
            'check_id': check_id
        }

        # Очищаем состояние
        context.user_data['awaiting_check_amount'] = False
        if 'current_check_type' in context.user_data:
            del context.user_data['current_check_type']

        # Показываем подтверждение с РЕАЛЬНЫМ кодом
        type_text = get_check_type_text(check_type)

        if check_type == "premium":
            description = f"🌟 Telegram Premium на {period}"
        else:
            unit = "звёзд" if check_type == "stars" else "TON"
            description = f"{type_text} {amount} {unit}"

        text = (
            f"🧾 Подтверждение создания чека\n\n"
            f"📦 Содержимое чека: {description}\n"
            f"💰 Стоимость: {cost:.2f}₽\n"
            f"🎫 Код чека: {check_code}\n\n"
            f"💡 После оплаты вы получите этот код, который можно отправить любому пользователю.\n\n"
            f"Выберите способ оплаты:"
        )

        # 🔴 Используем РЕАЛЬНЫЙ код для кнопок
        keyboard = [
            [InlineKeyboardButton("💳 Оплатить через ЮMoney", callback_data=f"pay_check_{check_code}")],
            [InlineKeyboardButton("📱 Оплатить через СБП", callback_data=f"sbp_check_{check_code}")],
            [InlineKeyboardButton("📲 Оплатить на карту", callback_data=f"card_check_{check_code}")],
            [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data=f"crypto_check_{check_code}")],
            [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_check_{check_code}")],
            [InlineKeyboardButton("🔙 Отменить", callback_data="cancel_check")]
        ]

        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        logger.info(f"✅ Чек создан: {check_code}, тип: {check_type}, сумма: {cost}₽")

    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите корректное число")
    except Exception as e:
        logger.error(f"❌ Ошибка создания чека: {e}")
        await update.message.reply_text("❌ Произошла ошибка при создании чека. Попробуйте еще раз.")

async def process_check_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод количества/периода для чека и создает чек"""
    user_id = update.message.from_user.id

    # Проверяем, что мы ожидаем ввод количества для чека
    if not context.user_data.get('awaiting_check_amount'):
        return

    check_type = context.user_data.get('current_check_type')
    user_input = update.message.text.strip()

    # Проверяем отмену
    if user_input.lower() in ['отмена', 'cancel', 'отменить']:
        # Очищаем состояния
        context.user_data['awaiting_check_amount'] = False
        if 'current_check_type' in context.user_data:
            del context.user_data['current_check_type']

        await update.message.reply_text(
            "✅ Создание чека отменено",
            reply_markup=get_main_menu_keyboard()
        )
        return

    try:
        amount = 0
        cost = 0
        period = ""
        description = ""

        if check_type == "premium":
            # Обработка периода для Premium
            period_map = {
                '3 месяца': '3 месяца',
                '6 месяцев': '6 месяцев',
                '1 год': '1 год',
                '3': '3 месяца',
                '6': '6 месяцев',
                '12': '1 год',
                'год': '1 год'
            }

            if user_input.lower() not in period_map:
                await update.message.reply_text(
                    "❌ Неверный срок подписки. Используйте: 3 месяца, 6 месяцев, 1 год\n\n"
                    "Попробуйте еще раз:"
                )
                return

            period = period_map[user_input.lower()]
            amount = 1
            cost = PREMIUM_PRICES[period]
            description = f"🌟 Telegram Premium на {period}"

        else:
            # Обработка количества для stars и ton
            user_input = user_input.replace(',', '.').replace(' ', '')
            cleaned_input = ''.join(char for char in user_input if char.isdigit() or char == '.')

            if not cleaned_input:
                await update.message.reply_text("❌ Пожалуйста, введите корректное число")
                return

            amount = float(cleaned_input)

            if check_type == "stars":
                if amount < 50:
                    await update.message.reply_text("❌ Минимальное количество звёзд: 50")
                    return
                cost = amount * STAR_PRICE
                description = f"⭐ {amount} звёзд"
            elif check_type == "ton":
                if amount <= 0:
                    await update.message.reply_text("❌ Количество TON должно быть больше 0")
                    return
                cost = amount * TON_PRICE
                description = f"💎 {amount} TON"

        # СОЗДАЕМ ЧЕК В БАЗЕ ДАННЫХ
        success, check_code, check_id = create_check(
            creator_id=user_id,
            check_type=check_type,
            amount=amount,
            cost=cost,
            photo_file_id=None,
            message_id=None
        )

        if not success:
            await update.message.reply_text(f"❌ Ошибка создания чека: {check_code}")
            return

        # Сохраняем данные чека в context для использования
        context.user_data['current_check'] = {
            'check_type': check_type,
            'amount': amount,
            'cost': cost,
            'period': period,
            'check_code': check_code,
            'check_id': check_id
        }

        # Очищаем состояние ожидания ввода
        context.user_data['awaiting_check_amount'] = False

        # Показываем подтверждение и способы оплаты
        text = (
            f"🧾 Подтверждение создания чека\n\n"
            f"📦 Содержимое чека: {description}\n"
            f"💰 Стоимость: {cost:.2f}₽\n"
            f"🎫 Код чека: {check_code}\n\n"
            f"💡 После оплаты вы получите этот код, который можно отправить любому пользователю.\n\n"
            f"Выберите способ оплаты:"
        )

        keyboard = [
            [InlineKeyboardButton("💳 Оплатить через ЮMoney", callback_data=f"pay_check_{check_code}")],
            [InlineKeyboardButton("📱 Оплатить через СБП", callback_data=f"sbp_check_{check_code}")],
            [InlineKeyboardButton("📲 Оплатить на карту", callback_data=f"card_check_{check_code}")],
            [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data=f"crypto_check_{check_code}")],
            [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_check_{check_code}")],
            [InlineKeyboardButton("🔙 Отменить", callback_data="cancel_check")]
        ]

        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        logger.info(f"✅ Чек создан: {check_code}, тип: {check_type}, сумма: {cost}₽")

    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите корректное число")
    except Exception as e:
        logger.error(f"❌ Ошибка создания чека: {e}")
        await update.message.reply_text("❌ Произошла ошибка при создании чека. Попробуйте еще раз.")

def get_check_type_text(check_type: str) -> str:
    """Возвращает текстовое описание типа чека"""
    type_map = {
        'stars': '⭐ Звёзды',
        'ton': '💎 TON',
        'premium': '🌟 Premium'
    }
    return type_map.get(check_type, check_type)

async def process_check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, payment_method: str, check_code: str):
    """Обрабатывает оплату чека с реальным кодом"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    logger.info(f"🔴 ОБРАБОТКА ОПЛАТЫ ЧЕКА: метод={payment_method}, код={check_code}")

    # Получаем данные чека из базы данных
    check = get_check_by_code(check_code)
    if not check:
        await query.edit_message_text("❌ Ошибка: чек не найден. Начните создание чека заново.")
        return

    # Для оплаты с баланса
    if payment_method == "balance":
        user_balance = get_user_balance(user_id)
        if user_balance >= check['cost']:
            # Сразу списываем баланс и активируем чек
            update_user_balance(user_id, -check['cost'])

            # Отправляем уведомление админу
            await send_check_notification(context, user_id, check_code, check)

            # Показываем успешное создание
            await show_check_created(query, context, check_code, check)
        else:
            await query.edit_message_text(
                f"❌ Недостаточно средств на балансе!\n\n"
                f"💳 Ваш баланс: {user_balance:.2f}₽\n"
                f"💰 Требуется: {check['cost']:.2f}₽"
            )
        return

    # Для других способов оплаты - создаем pending order
    user = await context.bot.get_chat(user_id)

    # Создаем заказ в ожидании
    order_id = save_pending_order(
        user_id=user_id,
        username=user.username,
        full_name=user.full_name,
        order_type=f"check_{check['check_type']}",
        amount=check['amount'],
        cost=check['cost'],
        receipt_message_id=query.message.message_id,
        is_balance_replenishment=False,
        friend_username=check_code
    )

    # Показываем инструкции по оплате
    if payment_method == "yoomoney":
        await show_yoomoney_check_payment(query, context, check, check_code)
    elif payment_method == "sbp":
        await show_sbp_check_payment(query, context, check, check_code)
    elif payment_method == "card":
        await show_card_check_payment(query, context, check, check_code)
    elif payment_method == "crypto":
        await show_crypto_check_payment(query, context, check, check_code)

async def show_check_created(query, context, check_code: str, check_data: dict):
    """Показывает успешное создание чека"""
    type_text = get_check_type_text(check_data['check_type'])

    if check_data['check_type'] == "premium":
        description = f"🌟 Telegram Premium на {check_data['period']}"
    else:
        unit = "звёзд" if check_data['check_type'] == "stars" else "TON"
        description = f"{type_text} {check_data['amount']} {unit}"

    text = (
        f"🎉 Чек успешно создан!\n\n"
        f"🧾 Код чека: <code>{check_code}</code>\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Стоимость: {check_data['cost']:.2f}₽\n\n"
        f"💡 Отправьте этот код любому пользователю:\n"
        f"<code>{check_code}</code>\n\n"
        f"Получатель сможет активировать чек через меню профиля."
    )

    keyboard = [
        [InlineKeyboardButton("📋 Мои чеки", callback_data="my_checks")],
        [InlineKeyboardButton("➕ Создать еще", callback_data="create_check_menu")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_main")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# 🔴 ФУНКЦИИ АКТИВАЦИИ ЧЕКОВ
async def activate_user_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активирует чек по коду"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    await query.edit_message_text(
        "🎫 Активация чека\n\n"
        "Введите код чека:\n\n"
        "❌ Для отмены отправьте 'отмена'"
    )

    # Устанавливаем состояние ожидания кода чека
    context.user_data['awaiting_check_activation'] = True

async def activate_check_from_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активирует чек из меню профиля"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    await query.edit_message_text(
        "🎫 Активация чека\n\n"
        "Введите код чека для активации:\n\n"
        "💡 Код чека выглядит примерно так: ABC123XY\n\n"
        "❌ Для отмены отправьте 'отмена'"
    )

    # Устанавливаем состояние ожидания кода чека
    context.user_data['awaiting_check_activation'] = True

async def process_check_activation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает активацию чека с уведомлением админу"""
    user_id = update.message.from_user.id

    if not context.user_data.get('awaiting_check_activation'):
        return

    check_code = update.message.text.strip().upper()

    if check_code.lower() in ['отмена', 'cancel', 'отменить']:
        context.user_data['awaiting_check_activation'] = False
        await update.message.reply_text(
            "✅ Активация чека отменена",
            reply_markup=get_main_menu_keyboard()
        )
        return

    # Проверяем чек
    check = get_check_by_code(check_code)

    if not check:
        await update.message.reply_text(
            "❌ Чек не найден или уже активирован\n\n"
            "Проверьте код и попробуйте еще раз.\n"
            "Для отмены отправьте 'отмена':"
        )
        return

    if check['is_activated']:
        await update.message.reply_text(
            "❌ Этот чек уже был активирован\n\n"
            "Введите другой код.\n"
            "Для отмены отправьте 'отмена':"
        )
        return

    # Создаем заказ в ожидании для админского подтверждения
    user = await context.bot.get_chat(user_id)
    creator = await context.bot.get_chat(check['creator_id'])

    order_id = save_pending_order(
        user_id=user_id,
        username=user.username,
        full_name=user.full_name,
        order_type=f"check_activation_{check['check_type']}",
        amount=check['amount'],
        cost=0,  # Чек уже оплачен создателем
        receipt_message_id=update.message.message_id,
        is_balance_replenishment=False,
        friend_username=check_code
    )

    # Уведомляем пользователя
    type_text = get_check_type_text(check['check_type'])

    if check['check_type'] == "premium":
        description = f"🌟 Telegram Premium"
    else:
        unit = "звёзд" if check['check_type'] == "stars" else "TON"
        description = f"{type_text} {check['amount']} {unit}"

    await update.message.reply_text(
        f"🎉 Чек принят в обработку!\n\n"
        f"📦 Вы активировали: {description}\n"
        f"🎫 Код чека: {check_code}\n\n"
        f"⏳ Заказ отправлен на подтверждение администратору.\n"
        f"Обычно это занимает 1-15 минут.\n\n"
        f"📞 Вы получите уведомление, когда чек будет активирован.\n\n"
        f"Спасибо за использование нашего сервиса! ❤️",
        reply_markup=get_main_menu_keyboard()
    )

    # Отправляем уведомление админу с кнопками подтверждения
    moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

    admin_message = (
        f"🎫 АКТИВАЦИЯ ЧЕКА!\n\n"
        f"👤 Активатор: @{user.username} (ID: {user_id})\n"
        f"👤 Создатель: @{creator.username} (ID: {check['creator_id']})\n"
        f"🎫 Код чека: {check_code}\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Стоимость: {check['cost']:.2f}₽ (уже оплачено)\n"
        f"⏰ Время (МСК): {moscow_time}\n\n"
        f"✅ Подтвердите активацию чека:"
    )

    admin_msg = await context.bot.send_message(
        ADMIN_ID,
        admin_message,
        reply_markup=get_order_confirmation_keyboard(order_id)
    )

    update_order_status(order_id, "pending", admin_msg.message_id)

    # Очищаем состояние
    context.user_data['awaiting_check_activation'] = False

    logger.info(f"✅ Запрос на активацию чека {check_code} создан (заказ #{order_id})")

async def notify_check_creator(context: ContextTypes.DEFAULT_TYPE, check: dict, activator_id: int):
    """Уведомляет создателя чека об активации"""
    try:
        creator_id = check['creator_id']
        activator = await context.bot.get_chat(activator_id)

        type_text = get_check_type_text(check['check_type'])

        if check['check_type'] == "premium":
            description = f"🌟 Telegram Premium"
        else:
            unit = "звёзд" if check['check_type'] == "stars" else "TON"
            description = f"{type_text} {check['amount']} {unit}"

        message = (
            f"🎉 Ваш чек активирован!\n\n"
            f"🎫 Код: {check['check_code']}\n"
            f"📦 Содержимое: {description}\n"
            f"👤 Активировал: @{activator.username}\n\n"
            f"💰 Чек успешно использован!"
        )

        await context.bot.send_message(creator_id, message)

    except Exception as e:
        logger.error(f"❌ Ошибка уведомления создателя чека: {e}")

async def process_check_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, payment_method: str, check_code: str):
    """Обрабатывает callback оплаты чеков - ТОЛЬКО ОДИН СПОСОБ ОПЛАТЫ"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    logger.info(f"🔴 ОБРАБОТКА ОПЛАТЫ ЧЕКА: метод={payment_method}, код={check_code}")

    # 🔴 ВАЖНО: Если это временный код, создаем реальный чек
    if check_code.startswith('temp_'):
        if 'current_check' in context.user_data:
            check_data = context.user_data['current_check']

            # Создаем реальный чек в базе данных
            success, real_check_code, check_id = create_check(
                creator_id=user_id,
                check_type=check_data['type'],
                amount=check_data['amount'],
                cost=check_data['cost'],
                photo_file_id=None,
                message_id=None
            )

            if success:
                # Обновляем данные в context
                context.user_data['current_check']['check_code'] = real_check_code
                context.user_data['current_check']['check_id'] = check_id
                check_code = real_check_code
                logger.info(f"✅ Создан реальный чек: {real_check_code}")

                # Сохраняем временную связь для обратной совместимости
                context.user_data['temp_to_real_code'] = {check_data.get('temp_code'): real_check_code}
            else:
                await query.edit_message_text(f"❌ Ошибка создания чека: {real_check_code}")
                return
        else:
            await query.edit_message_text("❌ Ошибка: данные чека не найдены. Начните создание заново.")
            return

    # 🔴 Теперь проверяем реальный чек в базе данных
    check = get_check_by_code(check_code)
    if not check:
        logger.error(f"❌ Чек {check_code} не найден в базе данных")
        await query.edit_message_text(
            "❌ Чек не найден. Возможно, он был удален или уже активирован.",
            reply_markup=get_main_menu_keyboard()
        )
        return

    # 🔴 Проверяем, не активирован ли уже чек
    if check['is_activated']:
        await query.edit_message_text("❌ Этот чек уже был активирован")
        return

    # 🔴 Показываем ТОЛЬКО выбранный способ оплаты (без других способов)
    if payment_method == "yoomoney":
        await show_yoomoney_check_payment_single(query, context, check, check_code)
    elif payment_method == "sbp":
        await show_sbp_check_payment_single(query, context, check, check_code)
    elif payment_method == "card":
        await show_card_check_payment_single(query, context, check, check_code)
    elif payment_method == "crypto":
        await show_crypto_check_payment_single(query, context, check, check_code)
    elif payment_method == "balance":
        await process_balance_check_payment(query, context, check, check_code)

async def show_yoomoney_check_payment(query, context, check: dict, check_code: str):
    """Показывает оплату через ЮMoney для чека"""
    amount = check['cost']

    # Создаем URL для ЮMoney с указанной суммой
    yoomoney_url = f"https://yoomoney.ru/quickpay/confirm.xml"
    params = {
        'receiver': YM_ACCOUNT,
        'quickpay-form': 'shop',
        'targets': f"Чек {check_code}",
        'sum': amount,
        'formcomment': f"Чек {check_code}",
        'short-dest': f"Чек {check_code}",
        'label': f"check_{check_code}_{query.from_user.id}",
        'paymentType': 'AC',  # Все способы оплаты
    }
    encoded_params = urllib.parse.urlencode(params)
    yoomoney_url = f"{yoomoney_url}?{encoded_params}"

    type_text = get_check_type_text(check['check_type'])
    if check['check_type'] == "premium":
        description = f"🌟 Telegram Premium"
    else:
        unit = "звёзд" if check['check_type'] == "stars" else "TON"
        description = f"{type_text} {check['amount']} {unit}"

    text = (
        f"💳 Оплата через ЮMoney\n\n"
        f"🎫 Чек: {check_code}\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Сумма: {amount:.2f}₽\n\n"
        f"▪️ Номер кошелька: <code>{YM_ACCOUNT}</code>\n\n"
        f"📌 Нажмите на кнопку ниже для перехода к оплате.\n"
        f"✅ После оплаты отправьте скриншот чека в этот чат.\n"
        f"⏳ Чек будет активирован в течение 1-15 минут после проверки платежа."
    )

    keyboard = [
        [InlineKeyboardButton("💳 Перейти к оплате ЮMoney", url=yoomoney_url)],
        [InlineKeyboardButton("📱 Оплатить через СБП", callback_data=f"sbp_check_{check_code}")],
        [InlineKeyboardButton("📲 Оплатить на карту", callback_data=f"card_check_{check_code}")],
        [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data=f"crypto_check_{check_code}")],
        [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_check_{check_code}")],
        [InlineKeyboardButton("🔙 Отменить", callback_data="cancel_check")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def show_sbp_check_payment(query, context, check: dict, check_code: str):
    """Показывает оплату через СБП для чека"""
    amount = check['cost']

    type_text = get_check_type_text(check['check_type'])
    if check['check_type'] == "premium":
        description = f"🌟 Telegram Premium"
    else:
        unit = "звёзд" if check['check_type'] == "stars" else "TON"
        description = f"{type_text} {check['amount']} {unit}"

    text = (
        f"📱 Оплата через СБП\n\n"
        f"🎫 Чек: {check_code}\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Сумма: {amount:.2f}₽\n\n"
        f"▪️ Номер телефона: <code>{SBP_PHONE}</code>\n\n"
        f"📌 После оплаты отправьте скриншот чека в этот чат.\n"
        f"✅ Чек будет активирован в течение 1-15 минут после проверки платежа."
    )

    keyboard = [
        [InlineKeyboardButton("💳 Оплатить через ЮMoney", callback_data=f"pay_check_{check_code}")],
        [InlineKeyboardButton("📲 Оплатить на карту", callback_data=f"card_check_{check_code}")],
        [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data=f"crypto_check_{check_code}")],
        [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_check_{check_code}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="cancel_check")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def show_card_check_payment(query, context, check: dict, check_code: str):
    """Показывает оплату на карту для чека"""
    amount = check['cost']

    type_text = get_check_type_text(check['check_type'])
    if check['check_type'] == "premium":
        description = f"🌟 Telegram Premium"
    else:
        unit = "звёзд" if check['check_type'] == "stars" else "TON"
        description = f"{type_text} {check['amount']} {unit}"

    text = (
        f"💳 Оплата на карту\n\n"
        f"🎫 Чек: {check_code}\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Сумма: {amount:.2f}₽\n\n"
        f"▪️ Карты для оплаты:\n"
    )

    for bank, number in CARD_NUMBERS.items():
        text += f"   - {bank}: <code>{number}</code>\n"

    text += (
        f"\n📌 После оплаты отправьте скриншот чека в этот чат.\n"
        f"✅ Чек будет активирован в течение 1-15 минут после проверки платежа."
    )

    keyboard = [
        [InlineKeyboardButton("💳 Оплатить через ЮMoney", callback_data=f"pay_check_{check_code}")],
        [InlineKeyboardButton("📱 Оплатить через СБП", callback_data=f"sbp_check_{check_code}")],
        [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data=f"crypto_check_{check_code}")],
        [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_check_{check_code}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="cancel_check")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def show_crypto_check_payment(query, context, check: dict, check_code: str):
    """Показывает оплату криптовалютой для чека"""
    amount = check['cost']

    type_text = get_check_type_text(check['check_type'])
    if check['check_type'] == "premium":
        description = f"🌟 Telegram Premium"
    else:
        unit = "звёзд" if check['check_type'] == "stars" else "TON"
        description = f"{type_text} {check['amount']} {unit}"

    text = (
        f"₿ Оплата криптовалютой\n\n"
        f"🎫 Чек: {check_code}\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Сумма: {amount:.2f}₽\n\n"
        f"💎 Кошельки для оплаты:\n\n"
        f"<b>TON</b>:\n"
        f"<code>{CRYPTO_WALLETS['TON']}</code>\n\n"
        f"<b>USDT</b> (TRC-20):\n"
        f"<code>{CRYPTO_WALLETS['USDT']}</code>\n\n"
        f"📌 После оплаты отправьте скриншот перевода в этот чат.\n"
        f"✅ Чек будет активирован в течение 1-15 минут после проверки платежа."
    )

    keyboard = [
        [InlineKeyboardButton("💳 Оплатить через ЮMoney", callback_data=f"pay_check_{check_code}")],
        [InlineKeyboardButton("📱 Оплатить через СБП", callback_data=f"sbp_check_{check_code}")],
        [InlineKeyboardButton("📲 Оплатить на карту", callback_data=f"card_check_{check_code}")],
        [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_check_{check_code}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="cancel_check")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def show_yoomoney_check_payment_single(query, context, check: dict, check_code: str):
    """Показывает оплату через ЮMoney для чека (ТОЛЬКО ЮMoney) - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    amount = check['cost']

    # Создаем URL для ЮMoney
    yoomoney_url = f"https://yoomoney.ru/quickpay/confirm.xml"
    params = {
        'receiver': YM_ACCOUNT,
        'quickpay-form': 'shop',
        'targets': f"Чек {check_code}",
        'sum': amount,
        'formcomment': f"Чек {check_code}",
        'short-dest': f"Чек {check_code}",
        'label': f"check_{check_code}_{query.from_user.id}",
        'paymentType': 'AC',
    }
    encoded_params = urllib.parse.urlencode(params)
    yoomoney_url = f"{yoomoney_url}?{encoded_params}"

    type_text = get_check_type_text(check['check_type'])
    if check['check_type'] == "premium":
        description = f"🌟 Telegram Premium"
    else:
        unit = "звёзд" if check['check_type'] == "stars" else "TON"
        description = f"{type_text} {check['amount']} {unit}"

    text = (
        f"💳 Оплата через ЮMoney\n\n"
        f"🎫 Чек: {check_code}\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Сумма: {amount:.2f}₽\n\n"
        f"▪️ Номер кошелька: <code>{YM_ACCOUNT}</code>\n\n"
        f"📌 Нажмите на кнопку ниже для перехода к оплате.\n"
        f"✅ После оплаты отправьте скриншот чека в этот чат.\n"
        f"⏳ Чек будет активирован в течение 1-15 минут после проверки платежа."
    )

    keyboard = [
        [InlineKeyboardButton("💳 Перейти к оплате ЮMoney", url=yoomoney_url)],
        [InlineKeyboardButton("🔙 Назад к способам оплаты", callback_data=f"back_to_payment_{check_code}")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    # 🔴 ВАЖНО: Устанавливаем состояние ожидания чека
    awaiting_receipts[query.from_user.id] = True
    logger.info(f"✅ Установлено состояние awaiting_receipts для пользователя {query.from_user.id}")

async def show_sbp_check_payment_single(query, context, check: dict, check_code: str):
    """Показывает оплату через СБП для чека (ТОЛЬКО СБП) - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    amount = check['cost']

    type_text = get_check_type_text(check['check_type'])
    if check['check_type'] == "premium":
        description = f"🌟 Telegram Premium"
    else:
        unit = "звёзд" if check['check_type'] == "stars" else "TON"
        description = f"{type_text} {check['amount']} {unit}"

    text = (
        f"📱 Оплата через СБП\n\n"
        f"🎫 Чек: {check_code}\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Сумма: {amount:.2f}₽\n\n"
        f"▪️ Номер телефона: <code>{SBP_PHONE}</code>\n\n"
        f"📌 После оплаты отправьте скриншот чека в этот чат.\n"
        f"✅ Чек будет активирован в течение 1-15 минут после проверки платежа."
    )

    keyboard = [
        [InlineKeyboardButton("🔙 Назад к способам оплаты", callback_data=f"back_to_payment_{check_code}")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    # 🔴 ВАЖНО: Устанавливаем состояние ожидания чека
    awaiting_receipts[query.from_user.id] = True

async def show_card_check_payment_single(query, context, check: dict, check_code: str):
    """Показывает оплату на карту для чека (ТОЛЬКО карты) - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    amount = check['cost']

    type_text = get_check_type_text(check['check_type'])
    if check['check_type'] == "premium":
        description = f"🌟 Telegram Premium"
    else:
        unit = "звёзд" if check['check_type'] == "stars" else "TON"
        description = f"{type_text} {check['amount']} {unit}"

    text = (
        f"💳 Оплата на карту\n\n"
        f"🎫 Чек: {check_code}\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Сумма: {amount:.2f}₽\n\n"
        f"▪️ Карты для оплаты:\n"
    )

    for bank, number in CARD_NUMBERS.items():
        text += f"   - {bank}: <code>{number}</code>\n"

    text += (
        f"\n📌 После оплаты отправьте скриншот чека в этот чат.\n"
        f"✅ Чек будет активирован в течение 1-15 минут после проверки платежа."
    )

    keyboard = [
        [InlineKeyboardButton("🔙 Назад к способам оплаты", callback_data=f"back_to_payment_{check_code}")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    # 🔴 ВАЖНО: Устанавливаем состояние ожидания чека
    awaiting_receipts[query.from_user.id] = True

async def show_crypto_check_payment_single(query, context, check: dict, check_code: str):
    """Показывает оплату криптовалютой для чека (ТОЛЬКО крипта) - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    amount = check['cost']

    type_text = get_check_type_text(check['check_type'])
    if check['check_type'] == "premium":
        description = f"🌟 Telegram Premium"
    else:
        unit = "звёзд" if check['check_type'] == "stars" else "TON"
        description = f"{type_text} {check['amount']} {unit}"

    text = (
        f"₿ Оплата криптовалютой\n\n"
        f"🎫 Чек: {check_code}\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Сумма: {amount:.2f}₽\n\n"
        f"💎 Кошельки для оплаты:\n\n"
        f"<b>TON</b>:\n"
        f"<code>{CRYPTO_WALLETS['TON']}</code>\n\n"
        f"<b>USDT</b> (TRC-20):\n"
        f"<code>{CRYPTO_WALLETS['USDT']}</code>\n\n"
        f"📌 После оплаты отправьте скриншот перевода в этот чат.\n"
        f"✅ Чек будет активирован в течение 1-15 минут после проверки платежа."
    )

    keyboard = [
        [InlineKeyboardButton("🔙 Назад к способам оплаты", callback_data=f"back_to_payment_{check_code}")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    # 🔴 ВАЖНО: Устанавливаем состояние ожидания чека
    awaiting_receipts[query.from_user.id] = True

async def process_balance_check_payment(query, context, check: dict, check_code: str):
    """Обрабатывает оплату чека с баланса - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    user_id = query.from_user.id
    user_balance = get_user_balance(user_id)

    if user_balance >= check['cost']:
        # Сразу списываем баланс и активируем чек
        update_user_balance(user_id, -check['cost'])

        # Активируем чек
        activate_check(check_code, user_id)

        # Обновляем статистику
        if check['check_type'] == "stars":
            update_user_purchase_stats(user_id, "stars", check['amount'])
            record_sale("stars", check['amount'], check['cost'])
        elif check['check_type'] == "ton":
            update_user_purchase_stats(user_id, "ton", check['amount'])
            record_sale("ton", check['amount'], check['cost'])
        elif check['check_type'] == "premium":
            update_user_purchase_stats(user_id, "premium", 1)
            record_sale("premium", 1, check['cost'])

        type_text = get_check_type_text(check['check_type'])
        if check['check_type'] == "premium":
            description = f"🌟 Telegram Premium"
        else:
            unit = "звёзд" if check['check_type'] == "stars" else "TON"
            description = f"{type_text} {check['amount']} {unit}"

        await query.edit_message_text(
            f"✅ Чек успешно создан и активирован!\n\n"
            f"🧾 Код чека: <code>{check_code}</code>\n"
            f"📦 Содержимое: {description}\n"
            f"💰 Стоимость: {check['cost']:.2f}₽\n"
            f"💳 Списано с баланса: {check['cost']:.2f}₽\n"
            f"💳 Новый баланс: {get_user_balance(user_id):.2f}₽\n\n"
            f"💡 Отправьте этот код другу:\n"
            f"<code>{check_code}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Мои чеки", callback_data="my_checks")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_main")]
            ])
        )

        # Уведомляем админа
        await send_check_notification(context, user_id, check_code, check)
    else:
        await query.edit_message_text(
            f"❌ Недостаточно средств на балансе!\n\n"
            f"💳 Ваш баланс: {user_balance:.2f}₽\n"
            f"💰 Требуется: {check['cost']:.2f}₽\n\n"
            f"Пополните баланс и попробуйте снова.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Пополнить баланс", callback_data="replenish_balance")],
                [InlineKeyboardButton("🔙 Назад", callback_data=f"back_to_payment_{check_code}")]
            ])
        )

async def send_check_notification(context: ContextTypes.DEFAULT_TYPE, user_id: int, check_code: str, check_data: dict):
    """Отправляет уведомление админу о создании чека"""
    try:
        user = await context.bot.get_chat(user_id)
        moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

        type_text = get_check_type_text(check_data['check_type'])

        if check_data['check_type'] == "premium":
            description = f"🌟 Telegram Premium"
        else:
            unit = "звёзд" if check_data['check_type'] == "stars" else "TON"
            description = f"{type_text} {check_data['amount']} {unit}"

        message = (
            f"🧾 СОЗДАН НОВЫЙ ЧЕК!\n\n"
            f"👤 Создатель: @{user.username} (ID: {user_id})\n"
            f"🎫 Код чека: {check_code}\n"
            f"📦 Содержимое: {description}\n"
            f"💰 Стоимость: {check_data['cost']:.2f}₽\n"
            f"⏰ Время (МСК): {moscow_time}\n\n"
            f"✅ Чек ожидает подтверждения"
        )

        await context.bot.send_message(ADMIN_ID, message)

    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления о чеке: {e}")

async def process_check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, payment_method: str, check_code: str):
    """Обрабатывает оплату чека"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    logger.info(f"🔴 ОБРАБОТКА оплаты чека: метод={payment_method}, код={check_code}")

    # 🔴 ВАЖНО: Если это временный код, используем данные из context.user_data
    if check_code.startswith('temp_'):
        if 'current_check' in context.user_data:
            # Создаем реальный чек в базе данных
            check_data = context.user_data['current_check']

            # Генерируем реальный код чека
            success, real_check_code, check_id = create_check(
                creator_id=user_id,
                check_type=check_data['type'],
                amount=check_data['amount'],
                cost=check_data['cost'],
                photo_file_id=None,
                message_id=None
            )

            if success:
                # Обновляем код в context.user_data
                context.user_data['current_check']['check_code'] = real_check_code
                check_code = real_check_code
                logger.info(f"✅ Создан реальный чек: {real_check_code}")
            else:
                await query.edit_message_text(f"❌ Ошибка создания чека: {real_check_code}")
                return
        else:
            await query.edit_message_text("❌ Ошибка: данные чека не найдены")
            return

    # Теперь проверяем чек в базе данных
    check = get_check_by_code(check_code)
    if not check:
        logger.error(f"❌ Чек {check_code} не найден в базе данных")
        await query.edit_message_text(
            "❌ Чек не найден. Возможно, он был удален или уже активирован.",
            reply_markup=get_main_menu_keyboard()
        )
        return

    # Проверяем, не активирован ли уже чек
    if check['is_activated']:
        await query.edit_message_text("❌ Этот чек уже был активирован")
        return

    # Показываем инструкции по оплате в зависимости от метода
    if payment_method == "yoomoney":
        await show_yoomoney_check_payment(query, context, check, check_code)
    elif payment_method == "sbp":
        await show_sbp_check_payment(query, context, check, check_code)
    elif payment_method == "card":
        await show_card_check_payment(query, context, check, check_code)
    elif payment_method == "crypto":
        await show_crypto_check_payment(query, context, check, check_code)
    elif payment_method == "balance":
        await process_balance_check_payment(query, context, check, check_code)

async def handle_check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, payment_method: str):
    """Универсальный обработчик оплаты чеков - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    logger.info(f"🔴 ОБРАБОТКА оплаты чека: {callback_data}, метод={payment_method}")

    # Извлекаем код из callback_data
    parts = callback_data.split('_')
    if len(parts) < 3:
        await query.edit_message_text("❌ Ошибка: неверный формат кода чека")
        return

    check_code = '_'.join(parts[2:])
    logger.info(f"🔴 Извлечен код чека: {check_code}")

    # 🔴 ВАЖНО: Если это временный код, создаем реальный чек
    if check_code.startswith('temp_'):
        logger.info(f"🔴 Обнаружен временный код: {check_code}")
        if 'current_check' in context.user_data:
            check_data = context.user_data['current_check']
            logger.info(f"🔴 Данные чека из context: {check_data}")

            # Создаем реальный чек в базе данных
            success, real_check_code, check_id = create_check(
                creator_id=query.from_user.id,
                check_type=check_data['type'],
                amount=check_data['amount'],
                cost=check_data['cost'],
                photo_file_id=None,
                message_id=None
            )

            if success:
                # Обновляем код и сохраняем реальный чек
                context.user_data['current_check']['check_code'] = real_check_code
                context.user_data['current_check']['check_id'] = check_id
                old_code = check_code
                check_code = real_check_code
                logger.info(f"✅ Создан реальный чек: {real_check_code} вместо {old_code}")

                # Обновляем callback_data для последующих обработчиков
                query.data = query.data.replace(old_code, real_check_code)
            else:
                await query.edit_message_text(f"❌ Ошибка создания чека: {real_check_code}")
                return
        else:
            logger.error("❌ Данные чека не найдены в context.user_data")
            await query.edit_message_text("❌ Ошибка: данные чека не найдены. Начните создание заново.")
            return

    # Теперь проверяем реальный чек в базе данных
    logger.info(f"🔴 Поиск чека в БД: {check_code}")
    check = get_check_by_code(check_code)

    if not check:
        logger.error(f"❌ Чек {check_code} не найден в базе данных")
        # Попробуем найти в context.user_data как запасной вариант
        if 'current_check' in context.user_data and context.user_data['current_check'].get('check_code') == check_code:
            check = context.user_data['current_check']
            logger.info(f"✅ Чек найден в context.user_data: {check}")
        else:
            await query.edit_message_text(
                "❌ Чек не найден. Возможно, он был удален или уже активирован.",
                reply_markup=get_main_menu_keyboard()
            )
            return

    # Проверяем, не активирован ли уже чек
    if check.get('is_activated'):
        await query.edit_message_text("❌ Этот чек уже был активирован")
        return

    logger.info(f"✅ Чек найден, показываем оплату методом: {payment_method}")

    # Показываем инструкции по оплате
    if payment_method == "yoomoney":
        await show_yoomoney_check_payment(query, context, check, check_code)
    elif payment_method == "sbp":
        await show_sbp_check_payment(query, context, check, check_code)
    elif payment_method == "card":
        await show_card_check_payment(query, context, check, check_code)
    elif payment_method == "crypto":
        await show_crypto_check_payment(query, context, check, check_code)
    elif payment_method == "balance":
        await process_balance_check_payment(query, context, check, check_code)

async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, message: str = None):
    try:
        user = update.message.from_user
        moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        caption = (
            f"Сообщение от @{user.username} (ID: {user.id})\n"
            f"Имя: {user.full_name}\n"
            f"Время (МСК): {moscow_time}\n"
            f"{message if message else ''}"
        )

        if update.message.text:
            await context.bot.send_message(ADMIN_ID, f"{caption}\n\n{update.message.text}")
        elif update.message.photo:
            await context.bot.send_photo(ADMIN_ID, update.message.photo[-1].file_id, caption=caption)
        elif update.message.document:
            await context.bot.send_document(ADMIN_ID, update.message.document.file_id, caption=caption)
    except Exception as e:
        logger.error(f"Ошибка пересылки сообщения админу: {e}")

async def send_admin_notification(context: ContextTypes.DEFAULT_TYPE, user_id: int, message: str):
    try:
        moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        await context.bot.send_message(
            ADMIN_ID,
            f"👤 Пользователь: @{(await context.bot.get_chat(user_id)).username}\n"
            f"🆔 ID: {user_id}\n"
            f"⏰ Время (МСК): {moscow_time}\n"
            f"📢 {message}"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу: {e}")

async def send_gift_notification(context: ContextTypes.DEFAULT_TYPE, user_id: int, gift_info: dict):
    """Отправляет уведомление админу о создании подарка"""
    try:
        gift_type_text = ""
        if gift_info["type"] == "stars":
            gift_type_text = f"🌟 {gift_info['amount']} звёзд"
        elif gift_info["type"] == "ton":
            gift_type_text = f"⚡ {gift_info['amount']} TON"
        elif gift_info["type"] == "premium":
            gift_type_text = f"💎 Telegram Premium на {gift_info['period']}"

        moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        message = (
            f"🎁 СОЗДАН ПОДАРОК!\n"
            f"👤 От: @{(await context.bot.get_chat(user_id)).username} (ID: {user_id})\n"
            f"🎯 Для: {gift_info['friend_username']}\n"
            f"📦 Подарок: {gift_type_text}\n"
            f"💰 Сумма: {gift_info['cost']:.1f}₽\n"
            f"⏰ Время (МСК): {moscow_time}"
        )

        await context.bot.send_message(ADMIN_ID, message)
    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления о подарке админу: {e}")

async def check_yoomoney_payment(amount: float) -> bool:
    # Заглушка для проверки платежей
    return False

async def show_user_profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает профиль пользователя через callback (для кнопок)"""
    try:
        query = update.callback_query
        user = query.from_user
        update_user_activity(user.id)

        # Получаем статистику пользователя
        user_stats = get_user_stats(user.id)
        if not user_stats:
            await query.edit_message_text("❌ Ошибка загрузки профиля: данные не найдены")
            return

        balance = get_user_balance(user.id)
        used_promocodes = get_user_used_promocodes(user.id)

        # Форматируем даты
        reg_date = "Неизвестно"
        if user_stats['registration_date']:
            try:
                reg_date = user_stats['registration_date'][:16]
            except:
                reg_date = str(user_stats['registration_date'])[:16]

        last_activity = "Неактивен"
        if user_stats['last_activity']:
            try:
                last_activity = user_stats['last_activity'][:16]
            except:
                last_activity = str(user_stats['last_activity'])[:16]

        # Формируем текст профиля
        text = (
            f"👤 Ваш профиль\n\n"
            f"📛 Имя: {user_stats.get('full_name', 'Не указано') or 'Не указано'}\n"
            f"🔗 Юзернейм: @{user_stats.get('username', 'Не указан') or 'Не указан'}\n"
            f"🆔 ID: {user.id}\n"
            f"📅 Регистрация: {reg_date}\n"
            f"⏰ Последняя активность: {last_activity}\n\n"

            f"💰 Баланс: {balance:.2f}₽\n\n"

            f"📊 Статистика покупок:\n"
            f"⭐ Куплено звёзд: {user_stats.get('stars_purchased', 0)} шт\n"
            f"🌟 Куплено Premium: {user_stats.get('premium_purchased', 0)} шт\n"
            f"💎 Куплено TON: {user_stats.get('ton_purchased', 0.0):.2f} TON\n\n"

            f"🎁 Статистика подарков:\n"
            f"⭐ Подарено звёзд: {user_stats.get('stars_gifted', 0)} шт\n"
            f"💎 Подарено TON: {user_stats.get('ton_gifted', 0.0):.2f} TON\n"
            f"🌟 Подарено Premium: {user_stats.get('premium_gifted', 0)} шт\n\n"

            f"🎫 Использовано промокодов: {len(used_promocodes)}\n"
            f"🧾 Создано чеков: {len(get_user_checks(user.id))}"
        )

        await query.edit_message_text(
            text,
            reply_markup=get_profile_keyboard()  # Теперь здесь будет новая кнопка
        )

    except Exception as e:
        logger.error(f"❌ Ошибка показа профиля через callback: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка при загрузке профиля. Попробуйте позже.",
            reply_markup=get_main_menu_keyboard()
        )

# ИСПРАВЛЕННАЯ ФУНКЦИЯ - отправка уведомления о чеке админу с правильной информацией
async def send_receipt_to_admin(context: ContextTypes.DEFAULT_TYPE, user_id: int, order_info: dict, receipt_message: Update):
    """Отправляет чек админу с кнопками подтверждения - УЛУЧШЕННАЯ ВЕРСИЯ"""
    try:
        user = await context.bot.get_chat(user_id)
        moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

        # Формируем текст сообщения с правильным определением типа
        order_type_text = ""
        description = ""

        if order_info.get("is_balance_replenishment"):
            order_type_text = "💰 ПОПОЛНЕНИЕ БАЛАНСА"
            description = f"Пополнение баланса на {order_info['amount']}₽"
        elif order_info.get("is_check"):
            check_type = order_info['type'].replace('check_', '')
            type_text = get_check_type_text(check_type)
            if check_type == "premium":
                description = f"🌟 Telegram Premium"
            else:
                unit = "звёзд" if check_type == "stars" else "TON"
                description = f"{type_text} {order_info['amount']} {unit}"
            order_type_text = "🧾 АКТИВАЦИЯ ЧЕКА"
        elif order_info['type'].startswith('gift_'):
            gift_type = order_info['type'].replace('gift_', '')
            if gift_type == "stars":
                description = f"⭐ {order_info['amount']} звёзд (подарок)"
            elif gift_type == "ton":
                description = f"💎 {order_info['amount']} TON (подарок)"
            elif gift_type == "premium":
                description = f"🌟 Telegram Premium на {order_info.get('period', '')} (подарок)"
            order_type_text = "🎁 ПОКУПКА ПОДАРКА"
        elif order_info['type'] == "stars":
            description = f"⭐ {order_info['amount']} звёзд"
            order_type_text = "🛒 ОБЫЧНЫЙ ЗАКАЗ"
        elif order_info['type'] == "ton":
            description = f"💎 {order_info['amount']} TON"
            order_type_text = "🛒 ОБЫЧНЫЙ ЗАКАЗ"
        elif order_info['type'] == "premium":
            description = f"🌟 Telegram Premium на {order_info.get('period', '')}"
            order_type_text = "🛒 ОБЫЧНЫЙ ЗАКАЗ"
        else:
            description = "Неизвестный тип заказа"
            order_type_text = "❓ НЕОПОЗНАННЫЙ ЗАКАЗ"

        # Добавляем информацию о подарке если есть
        gift_info = ""
        if order_info.get("friend_username"):
            gift_info = f"🎁 ПОДАРОК ДЛЯ: {order_info['friend_username']}\n"
        elif order_info.get("check_code"):
            gift_info = f"🎫 КОД ЧЕКА: {order_info['check_code']}\n"

        message_text = (
            f"🧾 НОВЫЙ ЧЕК ОПЛАТЫ!\n\n"
            f"📦 Тип заказа: {order_type_text}\n"
            f"{gift_info}"
            f"👤 Пользователь: @{user.username}\n"
            f"📛 Имя: {user.full_name}\n"
            f"🆔 ID: {user_id}\n\n"
            f"📦 Заказ: {description}\n"
            f"💰 Сумма: {order_info['cost']:.1f}₽\n"
            f"⏰ Время (МСК): {moscow_time}\n\n"
            f"☝️ Чек прикреплен выше"
        )

        # Сохраняем заказ в базу
        order_id = save_pending_order(
            user_id=user_id,
            username=user.username,
            full_name=user.full_name,
            order_type=order_info["type"],
            amount=order_info["amount"],
            cost=order_info["cost"],
            receipt_message_id=receipt_message.message_id,
            friend_username=order_info.get("friend_username", order_info.get("check_code", "")),
            is_balance_replenishment=order_info.get("is_balance_replenishment", False)
        )

        # Обновляем текст с номером заказа
        message_text = message_text.replace("🧾 НОВЫЙ ЧЕК ОПЛАТЫ!", f"🧾 НОВЫЙ ЧЕК ОПЛАТЫ! (Заказ #{order_id})")

        # ПЕРЕСЫЛАЕМ САМО СООБЩЕНИЕ С ФАЙЛОМ админу
        if receipt_message.photo:
            # Пересылаем фото
            admin_msg = await context.bot.send_photo(
                ADMIN_ID,
                photo=receipt_message.photo[-1].file_id,
                caption=message_text,
                reply_markup=get_order_confirmation_keyboard(order_id)
            )
        elif receipt_message.document:
            # Пересылаем документ
            admin_msg = await context.bot.send_document(
                ADMIN_ID,
                document=receipt_message.document.file_id,
                caption=message_text,
                reply_markup=get_order_confirmation_keyboard(order_id)
            )
        else:
            # Если нет файла, отправляем только текст
            admin_msg = await context.bot.send_message(
                ADMIN_ID,
                message_text + "\n\n❌ ФАЙЛ ЧЕКА НЕ ПРИКРЕПЛЕН!",
                reply_markup=get_order_confirmation_keyboard(order_id)
            )

        # Обновляем заказ с ID сообщения админа
        update_order_status(order_id, "pending", admin_msg.message_id)

        logger.info(f"✅ Чек отправлен админу для подтверждения (заказ #{order_id}, тип: {order_info['type']})")

    except Exception as e:
        logger.error(f"❌ Ошибка отправки чека админу: {e}")
        # Пытаемся отправить хотя бы текстовое уведомление
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"❌ ОШИБКА ПРИ ОТПРАВКЕ ЧЕКА!\n"
                f"👤 Пользователь: @{user.username}\n"
                f"Тип заказа: {order_info.get('type', 'неизвестен')}\n"
                f"Ошибка: {e}"
            )
        except Exception as inner_e:
            logger.error(f"❌ Ошибка отправки текстового уведомления админу: {inner_e}")

# НОВЫЕ ФУНКЦИИ ДЛЯ КУРСОВ ВАЛЮТ И КОНВЕРТАЦИИ
async def show_currency_rates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единая функция показа актуальных курсов валют"""
    try:
        # Для текстовых сообщений
        if update.message:
            user = update.message.from_user
            update_user_activity(user.id)
            message_func = update.message.reply_text
        # Для callback запросов
        elif update.callback_query:
            query = update.callback_query
            await query.answer()
            user = query.from_user
            update_user_activity(user.id)
            message_func = query.edit_message_text
        else:
            return

        # Получаем актуальные курсы
        rates = await currency_rates.get_rates()
        moscow_time = get_moscow_time().strftime("%H:%M")

        # Форматируем текст с курсами
        text = (
            "💱 Актуальные курсы валют\n\n"
            f"{FLAGS['USD']} 1 USD = {rates.get('USD', 0):.2f} RUB\n"
            f"{FLAGS['EUR']} 1 EUR = {rates.get('EUR', 0):.2f} RUB\n"
            f"{FLAGS['TON']} 1 TON = {rates.get('TON', 0):.2f} RUB\n"
            f"{FLAGS['USDT']} 1 USDT = {rates.get('USDT', 0):.2f} RUB\n\n"
            f"🕐 {moscow_time} МСК\n"  # ← ДОБАВЛЕНО "МСК"
            "🔄 Курсы обновляются автоматически каждые 5 минут\n\n"
            "💡 Используйте конвертер для расчетов"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💱 Конвертер валют", callback_data="currency_converter")],
            [InlineKeyboardButton("🔄 Обновить курсы", callback_data="refresh_rates")]
        ])

        await message_func(text, reply_markup=keyboard, parse_mode='HTML')

    except Exception as e:
        logger.error(f"❌ Ошибка показа курсов валют: {e}")
        error_text = "❌ Не удалось загрузить актуальные курсы. Попробуйте позже."

        # Создаем клавиатуру для ошибки
        error_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Повторить", callback_data="show_currency_rates")],
            [InlineKeyboardButton("🔙 В меню", callback_data="back_to_main")]
        ])

        if update.message:
            await update.message.reply_text(error_text, reply_markup=error_keyboard)
        elif update.callback_query:
            await update.callback_query.edit_message_text(error_text, reply_markup=error_keyboard)

async def refresh_currency_rates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновляет курсы валют - ТОЛЬКО для callback запросов"""
    query = update.callback_query
    await query.answer()

    try:
        # Сбрасываем кэш для принудительного обновления
        currency_rates.cache_time = None
        rates = await currency_rates.get_rates()

        text = (
            "💱 ОБНОВЛЕННЫЕ КУРСЫ ВАЛЮТ\n\n"
            f"{FLAGS['USD']} USD/RUB: {rates.get('USD', 0):.2f}₽\n"
            f"{FLAGS['EUR']} EUR/RUB: {rates.get('EUR', 0):.2f}₽\n"
            f"{FLAGS['TON']} TON/RUB: {rates.get('TON', 0):.2f}₽\n"
            f"{FLAGS['USDT']} USDT/RUB: {rates.get('USDT', 0):.2f}₽\n\n"
            f"🕐 Обновлено: {rates.get('last_update', 'неизвестно')} (МСК)\n\n"
            "✅ Курсы успешно обновлены"
        )

        await query.edit_message_text(
            text,
            reply_markup=get_currency_keyboard()
        )

    except Exception as e:
        logger.error(f"❌ Ошибка обновления курсов: {e}")
        await query.edit_message_text(
            "❌ Не удалось обновить курсы. Попробуйте позже.",
            reply_markup=get_currency_keyboard()
        )

async def show_currency_converter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню конвертера валют с флагами"""
    query = update.callback_query
    await query.answer()

    # Получаем текущее время в Москве
    moscow_time = get_moscow_time().strftime("%H:%M")

    text = (
        "💱 Конвертер валют\n\n"
        "Выберите направление конвертации:\n"
        f"🕐 {moscow_time}\n\n"
        f"• {FLAGS['USD']} USD → {FLAGS['RUB']} RUB\n"
        f"• {FLAGS['EUR']} EUR → {FLAGS['RUB']} RUB\n"
        f"• {FLAGS['TON']} TON → {FLAGS['RUB']} RUB\n"
        f"• {FLAGS['USDT']} USDT → {FLAGS['RUB']} RUB\n"
        f"• {FLAGS['RUB']} RUB → {FLAGS['USD']} USD\n"
        f"• {FLAGS['RUB']} RUB → {FLAGS['EUR']} EUR\n"
        f"• {FLAGS['RUB']} RUB → {FLAGS['TON']} TON\n"
        f"• {FLAGS['RUB']} RUB → {FLAGS['USDT']} USDT"
    )

    await query.edit_message_text(
        text,
        reply_markup=get_converter_keyboard()
    )

async def start_currency_conversion(update: Update, context: ContextTypes.DEFAULT_TYPE, conversion_type: str):
    """Начинает процесс конвертации для выбранного типа"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    conversion_data[user_id] = conversion_type

    # Определяем текст запроса в зависимости от типа конвертации
    conversion_texts = {
        "convert_usd_rub": f"{FLAGS['USD']} Конвертация: USD → RUB\n\nВведите сумму в USD:",
        "convert_eur_rub": f"{FLAGS['EUR']} Конвертация: EUR → RUB\n\nВведите сумму в EUR:",
        "convert_ton_rub": f"{FLAGS['TON']} Конвертация: TON → RUB\n\nВведите количество TON:",
        "convert_usdt_rub": f"{FLAGS['USDT']} Конвертация: USDT → RUB\n\nВведите количество USDT:",
        "convert_rub_usd": f"{FLAGS['RUB']} Конвертация: RUB → USD\n\nВведите сумму в RUB:",
        "convert_rub_eur": f"{FLAGS['RUB']} Конвертация: RUB → EUR\n\nВведите сумму в RUB:",
        "convert_rub_ton": f"{FLAGS['RUB']} Конвертация: RUB → TON\n\nВведите сумму в RUB:",
        "convert_rub_usdt": f"{FLAGS['RUB']} Конвертация: RUB → USDT\n\nВведите сумму в RUB:"
    }

    await query.edit_message_text(
        f"{conversion_texts.get(conversion_type, 'Конвертация')}\n\n"
        "❌ Для отмены отправьте 'отмена'"
    )

async def process_conversion_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод суммы для конвертации"""
    user_id = update.message.from_user.id

    if user_id not in conversion_data:
        return

    conversion_type = conversion_data[user_id]
    user_input = update.message.text.strip()

    if user_input.lower() in ['отмена', 'cancel', 'отменить']:
        del conversion_data[user_id]
        await update.message.reply_text(
            "✅ Конвертация отменена",
            reply_markup=get_main_menu_keyboard()
        )
        return

    try:
        # УЛУЧШЕННЫЙ ПАРСИНГ ЧИСЕЛ - обрабатывает разные форматы
        user_input = user_input.replace(',', '.').replace(' ', '')

        # Убираем все нечисловые символы кроме точки
        cleaned_input = ''.join(char for char in user_input if char.isdigit() or char == '.')

        if not cleaned_input:
            await update.message.reply_text("❌ Пожалуйста, введите корректное число")
            return

        amount = float(cleaned_input)

        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть больше 0")
            return

        # Выполняем конвертацию
        await perform_conversion(update, context, conversion_type, amount)
        del conversion_data[user_id]

    except ValueError as e:
        logger.error(f"❌ Ошибка парсинга числа: {e}")
        await update.message.reply_text("❌ Пожалуйста, введите корректное число (например: 100, 50.5, 1,000)")

async def perform_conversion(update: Update, context: ContextTypes.DEFAULT_TYPE, conversion_type: str, amount: float):
    """Выполняет конвертацию и показывает результат с флагами"""
    try:
        rates = await currency_rates.get_rates()
        moscow_time = get_moscow_time().strftime("%H:%M")

        result_text = ""
        original_text = ""
        rate_info = ""

        # Определяем направление конвертации и выполняем расчет
        if conversion_type == "convert_usd_rub":
            result = amount * rates['USD']
            original_text = f"{FLAGS['USD']} {amount:.2f} USD ="
            result_text = f"{FLAGS['RUB']} {result:.2f} RUB"
            rate_info = f"📊 Курс: 1 USD = {rates['USD']:.2f} RUB"

        elif conversion_type == "convert_eur_rub":
            result = amount * rates['EUR']
            original_text = f"{FLAGS['EUR']} {amount:.2f} EUR ="
            result_text = f"{FLAGS['RUB']} {result:.2f} RUB"
            rate_info = f"📊 Курс: 1 EUR = {rates['EUR']:.2f} RUB"

        elif conversion_type == "convert_ton_rub":
            result = amount * rates['TON']
            original_text = f"{FLAGS['TON']} {amount:.4f} TON ="
            result_text = f"{FLAGS['RUB']} {result:.2f} RUB"
            rate_info = f"📊 Курс: 1 TON = {rates['TON']:.2f} RUB"

        elif conversion_type == "convert_usdt_rub":
            result = amount * rates['USDT']
            original_text = f"{FLAGS['USDT']} {amount:.2f} USDT ="
            result_text = f"{FLAGS['RUB']} {result:.2f} RUB"
            rate_info = f"📊 Курс: 1 USDT = {rates['USDT']:.2f} RUB"

        elif conversion_type == "convert_rub_usd":
            result = amount / rates['USD']
            original_text = f"{FLAGS['RUB']} {amount:.2f} RUB ="
            result_text = f"{FLAGS['USD']} {result:.2f} USD"
            rate_info = f"📊 Курс: 1 USD = {rates['USD']:.2f} RUB"

        elif conversion_type == "convert_rub_eur":
            result = amount / rates['EUR']
            original_text = f"{FLAGS['RUB']} {amount:.2f} RUB ="
            result_text = f"{FLAGS['EUR']} {result:.2f} EUR"
            rate_info = f"📊 Курс: 1 EUR = {rates['EUR']:.2f} RUB"

        elif conversion_type == "convert_rub_ton":
            result = amount / rates['TON']
            original_text = f"{FLAGS['RUB']} {amount:.2f} RUB ="
            result_text = f"{FLAGS['TON']} {result:.4f} TON"
            rate_info = f"📊 Курс: 1 TON = {rates['TON']:.2f} RUB"

        elif conversion_type == "convert_rub_usdt":
            result = amount / rates['USDT']
            original_text = f"{FLAGS['RUB']} {amount:.2f} RUB ="
            result_text = f"{FLAGS['USDT']} {result:.2f} USDT"
            rate_info = f"📊 Курс: 1 USDT = {rates['USDT']:.2f} RUB"

        else:
            await update.message.reply_text("❌ Неизвестный тип конвертации")
            return

        # Формируем итоговое сообщение
        final_text = (
            f"💱 Результат конвертации:\n\n"
            f"{original_text}\n"
            f"{result_text}\n\n"
            f"{rate_info}\n"
            f"🕐 {moscow_time}"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Новый расчет", callback_data="currency_converter")],
            [InlineKeyboardButton("📊 Все курсы", callback_data="show_rates")]
        ])

        await update.message.reply_text(final_text, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"❌ Ошибка конвертации: {e}")
        await update.message.reply_text(
            "❌ Ошибка конвертации. Попробуйте позже.",
            reply_markup=get_main_menu_keyboard()
        )

# НОВЫЕ ФУНКЦИИ ДЛЯ ПРОФИЛЯ ПОЛЬЗОВАТЕЛЯ
async def show_user_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает профиль пользователя с полной статистикой"""
    try:
        user = update.effective_user
        update_user_activity(user.id)

        logger.info(f"🔹🔹🔹 ОТЛАДКА: Вызвана функция show_user_profile для пользователя {user.id}")

        # Получаем статистику пользователя
        user_stats = get_user_stats(user.id)
        logger.info(f"🔹🔹🔹 ОТЛАДКА: user_stats = {user_stats}")

        if not user_stats:
            logger.error(f"❌ user_stats is None для пользователя {user.id}")
            await update.message.reply_text("❌ Ошибка загрузки профиля: данные не найдены")
            return

        # Получаем баланс
        balance = get_user_balance(user.id)
        logger.info(f"🔹🔹🔹 ОТЛАДКА: balance = {balance}")

        # Получаем использованные промокоды
        used_promocodes = get_user_used_promocodes(user.id)
        logger.info(f"🔹🔹🔹 ОТЛАДКА: used_promocodes count = {len(used_promocodes)}")

        # 🔴🔴🔴 ДОБАВЛЯЕМ РЕФЕРАЛЬНУЮ СТАТИСТИКУ 🔴🔴🔴
        ref_info = get_user_referral_info(user.id)
        logger.info(f"🔹🔹🔹 ОТЛАДКА: ref_info = {ref_info}")

        # Форматируем даты безопасно
        reg_date = "Неизвестно"
        if user_stats['registration_date']:
            try:
                reg_date = user_stats['registration_date'][:16]
            except:
                reg_date = str(user_stats['registration_date'])[:16]

        last_activity = "Неактивен"
        if user_stats['last_activity']:
            try:
                last_activity = user_stats['last_activity'][:16]
            except:
                last_activity = str(user_stats['last_activity'])[:16]

        # Формируем текст профиля
        text = (
            f"👤 Ваш профиль\n\n"
            f"📛 Имя: {user_stats.get('full_name', 'Не указано') or 'Не указано'}\n"
            f"🔗 Юзернейм: @{user_stats.get('username', 'Не указан') or 'Не указан'}\n"
            f"🆔 ID: {user.id}\n"
            f"📅 Регистрация: {reg_date}\n"
            f"⏰ Последняя активность: {last_activity}\n\n"

            f"💰 Баланс: {balance:.2f}₽\n\n"

            f"📊 Статистика покупок:\n"
            f"⭐ Куплено звёзд: {user_stats.get('stars_purchased', 0)} шт\n"
            f"🌟 Куплено Premium: {user_stats.get('premium_purchased', 0)} шт\n"
            f"💎 Куплено TON: {user_stats.get('ton_purchased', 0.0):.2f} TON\n\n"

            f"🎁 Статистика подарков:\n"
            f"⭐ Подарено звёзд: {user_stats.get('stars_gifted', 0)} шт\n"
            f"💎 Подарено TON: {user_stats.get('ton_gifted', 0.0):.2f} TON\n"
            f"🌟 Подарено Premium: {user_stats.get('premium_gifted', 0)} шт\n\n"

            f"🎫 Использовано промокодов: {len(used_promocodes)}\n\n"

            f"👥 Реферальная программа:\n"
            f"• Приглашено друзей: {ref_info['total_referrals']}\n"
            f"• Заработано: {ref_info['total_earnings']:.2f}₽\n"
            f"• Реферальный код: {ref_info['referral_code']}"
        )

        logger.info(f"🔹🔹🔹 ОТЛАДКА: Текст профиля сформирован")

        # Получаем клавиатуру профиля
        keyboard = get_profile_keyboard()
        logger.info(f"🔹🔹🔹 ОТЛААДКА: Клавиатура получена")

        await update.message.reply_text(
            text,
            reply_markup=keyboard
        )

        logger.info(f"✅ Профиль успешно показан пользователю {user.id}")

    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА в show_user_profile: {e}")
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        await update.message.reply_text(
            "❌ Произошла ошибка при загрузке профиля. Попробуйте позже.",
            reply_markup=get_main_menu_keyboard()
        )

async def show_user_profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает профиль пользователя через callback (для кнопок) - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    try:
        query = update.callback_query
        user = query.from_user
        update_user_activity(user.id)

        logger.info(f"🔹🔹🔹 ОТЛАДКА: Вызвана функция show_user_profile_callback для пользователя {user.id}")

        # Получаем статистику пользователя
        user_stats = get_user_stats(user.id)
        if not user_stats:
            await query.edit_message_text("❌ Ошибка загрузки профиля: данные не найдены")
            return

        # Получаем баланс
        balance = get_user_balance(user.id)

        # Получаем использованные промокоды
        used_promocodes = get_user_used_promocodes(user.id)

        # 🔴🔴🔴 ДОБАВЛЯЕМ РЕФЕРАЛЬНУЮ СТАТИСТИКУ (как в show_user_profile)
        ref_info = get_user_referral_info(user.id)
        logger.info(f"🔹🔹🔹 ОТЛАДКА: ref_info в callback = {ref_info}")

        # Форматируем даты
        reg_date = "Неизвестно"
        if user_stats['registration_date']:
            try:
                reg_date = user_stats['registration_date'][:16]
            except:
                reg_date = str(user_stats['registration_date'])[:16]

        last_activity = "Неактивен"
        if user_stats['last_activity']:
            try:
                last_activity = user_stats['last_activity'][:16]
            except:
                last_activity = str(user_stats['last_activity'])[:16]

        # Формируем текст профиля (ТОЧНО ТАКОЙ ЖЕ КАК В show_user_profile)
        text = (
            f"👤 Ваш профиль\n\n"
            f"📛 Имя: {user_stats.get('full_name', 'Не указано') or 'Не указано'}\n"
            f"🔗 Юзернейм: @{user_stats.get('username', 'Не указан') or 'Не указан'}\n"
            f"🆔 ID: {user.id}\n"
            f"📅 Регистрация: {reg_date}\n"
            f"⏰ Последняя активность: {last_activity}\n\n"

            f"💰 Баланс: {balance:.2f}₽\n\n"

            f"📊 Статистика покупок:\n"
            f"⭐ Куплено звёзд: {user_stats.get('stars_purchased', 0)} шт\n"
            f"🌟 Куплено Premium: {user_stats.get('premium_purchased', 0)} шт\n"
            f"💎 Куплено TON: {user_stats.get('ton_purchased', 0.0):.2f} TON\n\n"

            f"🎁 Статистика подарков:\n"
            f"⭐ Подарено звёзд: {user_stats.get('stars_gifted', 0)} шт\n"
            f"💎 Подарено TON: {user_stats.get('ton_gifted', 0.0):.2f} TON\n"
            f"🌟 Подарено Premium: {user_stats.get('premium_gifted', 0)} шт\n\n"

            f"🎫 Использовано промокодов: {len(used_promocodes)}\n\n"

            f"👥 Реферальная программа:\n"
            f"• Приглашено друзей: {ref_info['total_referrals']}\n"
            f"• Заработано: {ref_info['total_earnings']:.2f}₽\n"
            f"• Реферальный код: {ref_info['referral_code']}"
        )

        await query.edit_message_text(
            text,
            reply_markup=get_profile_keyboard()
        )

        logger.info(f"✅ Профиль через callback успешно показан пользователю {user.id}")

    except Exception as e:
        logger.error(f"❌ Ошибка показа профиля через callback: {e}")
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        await query.edit_message_text(
            "❌ Произошла ошибка при загрузке профиля. Попробуйте позже.",
            reply_markup=get_main_menu_keyboard()
        )

def get_user_stats(user_id: int):
    """Получает полную статистику пользователя"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT username, full_name, registration_date, last_activity,
                   stars_purchased, premium_purchased, ton_purchased, balance,
                   stars_gifted, ton_gifted, premium_gifted
            FROM users WHERE user_id = ?
        ''', (user_id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return {
                'username': result[0],
                'full_name': result[1],
                'registration_date': result[2],
                'last_activity': result[3],
                'stars_purchased': result[4] or 0,
                'premium_purchased': result[5] or 0,
                'ton_purchased': result[6] or 0.0,
                'balance': result[7] or 0.0,
                'stars_gifted': result[8] or 0,
                'ton_gifted': result[9] or 0.0,
                'premium_gifted': result[10] or 0
            }
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка в get_user_stats: {e}")
        return None

def get_system_stats():
    """Получает системную статистику (общую)"""
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]

    # АКТИВНЫЕ ПОЛЬЗОВАТЕЛИ ЗА СЕГОДНЯ
    cursor.execute('SELECT COUNT(*) FROM users WHERE date(last_activity) = date("now")')
    active_today = cursor.fetchone()[0]

    # Заблокированные пользователи
    cursor.execute('SELECT COUNT(*) FROM users WHERE is_blocked = 1')
    blocked_users = cursor.fetchone()[0]

    # Статистика покупок
    cursor.execute('SELECT SUM(stars_purchased) FROM users')
    total_stars = cursor.fetchone()[0] or 0

    cursor.execute('SELECT SUM(premium_purchased) FROM users')
    total_premium = cursor.fetchone()[0] or 0

    cursor.execute('SELECT SUM(ton_purchased) FROM users')
    total_ton = cursor.fetchone()[0] or 0

    conn.close()

    logger.info(f"📊 Статистика пользователей: total={total_users}, active_today={active_today}, blocked={blocked_users}, stars={total_stars}, premium={total_premium}, ton={total_ton}")

    return total_users, active_today, blocked_users, total_stars, total_premium, total_ton

def get_user_balance(user_id: int):
    """Получает баланс пользователя"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0.0
    except Exception as e:
        logger.error(f"❌ Ошибка в get_user_balance: {e}")
        return 0.0

async def replenish_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс пополнения баланса"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("❌ Отменить пополнение", callback_data="profile_back")]
    ]

    await query.edit_message_text(
        "💰 Пополнение баланса\n\n"
        "💵 Введите сумму для пополнения (в рублях):\n\n"
        "❌ Для отмены нажмите кнопку ниже",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    awaiting_balance_amount[query.from_user.id] = True

async def pay_with_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Списать с баланса'"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user_balance = get_user_balance(user_id)

    # Здесь должна быть логика определения текущего заказа
    # Это упрощенная версия - вам нужно адаптировать под вашу структуру

    await query.edit_message_text(
        f"💰 Оплата с баланса\n\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        f"Функция оплаты с баланса будет реализована в ближайшее время.",
        reply_markup=get_main_menu_keyboard()
    )

def get_user_used_promocodes(user_id: int):
    """Получает список использованных промокодов пользователя"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT promo_code, used_date, order_type, original_amount, discount_amount, final_amount
            FROM used_promo_codes
            WHERE user_id = ?
            ORDER BY used_date DESC
        ''', (user_id,))
        promos = cursor.fetchall()
        conn.close()

        result = []
        for promo in promos:
            result.append({
                'code': promo[0],
                'used_date': promo[1],
                'order_type': promo[2],
                'original_amount': promo[3],
                'discount_amount': promo[4],
                'final_amount': promo[5]
            })
        return result
    except Exception as e:
        logger.error(f"❌ Ошибка в get_user_used_promocodes: {e}")
        return []

async def create_promo_step_by_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пошаговое создание промокода - УПРОЩЕННАЯ ВЕРСИЯ"""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    # Начинаем процесс создания
    context.user_data['promo_creation'] = {
        'step': 1,
        'code': None,
        'discount_percent': None,
        'max_uses': 100
    }

    await query.edit_message_text(
        "🎫 <b>Создание промокода - Шаг 1/3</b>\n\n"
        "✏️ Введите код промокода (только латинские буквы и цифры):\n\n"
        "❌ Для отмены отправьте 'отмена'",
        parse_mode='HTML'
    )

async def process_promo_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора типа промокода"""
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    promo_type = callback_data.split('_')[2]  # discount или gift

    # Сохраняем тип промокода
    if 'promo_creation' not in context.user_data:
        context.user_data['promo_creation'] = {}

    context.user_data['promo_creation']['type'] = promo_type
    context.user_data['promo_creation']['step'] = 'code'

    logger.info(f"🎫 Выбран тип промокода: {promo_type}")

    # Запрашиваем код промокода
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data="create_promo_back_type")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🎫 <b>Создание промокода</b>\n\n"
        "✏️ Введите код промокода (только латинские буквы и цифры):\n\n"
        "⚠️ Код должен быть уникальным и содержать только A-Z, 0-9",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def process_promo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод промокода - ПОЛНОСТЬЮ ПЕРЕПИСАННАЯ ВЕРСИЯ"""
    user_id = update.message.from_user.id
    message_text = update.message.text.strip()

    logger.info(f"🎫 Обработка ввода промокода от {user_id}: '{message_text}'")

    # Проверяем отмену
    if message_text.lower() in ['отмена', 'cancel', 'отменить']:
        await cancel_promo_input(update, context)
        return

    promo_code = message_text.upper()

    # ПОЛУЧАЕМ тип товара из user_data - ПРОВЕРЯЕМ РАЗНЫЕ ВАРИАНТЫ
    product_type = None

    # Вариант 1: из promo_product_type
    if context.user_data.get('promo_product_type'):
        product_type = context.user_data.get('promo_product_type')
        logger.info(f"🎫 Найден promo_product_type: {product_type}")

    # Вариант 2: из applying_promo_for
    elif context.user_data.get('applying_promo_for'):
        product_type = context.user_data.get('applying_promo_for')
        logger.info(f"🎫 Найден applying_promo_for: {product_type}")

    # Вариант 3: из текущего состояния (для обратной совместимости)
    elif user_id in awaiting_promo_code:
        # Пытаемся определить тип по последним действиям пользователя
        product_type = "stars"  # значение по умолчанию
        logger.info(f"🎫 Используем тип по умолчанию: {product_type}")

    if not product_type:
        logger.error(f"❌ Не найден тип товара для пользователя {user_id}")
        logger.error(f"❌ User data: {context.user_data}")
        await update.message.reply_text(
            "❌ Ошибка: не определен тип товара. Возврат в главное меню...",
            reply_markup=get_main_menu_keyboard()
        )
        await cancel_promo_input(update, context)
        return

    logger.info(f"🎫 Проверка промокода: {promo_code} для типа: {product_type}")

    # Убираем пользователя из состояния ожидания промокода
    if user_id in awaiting_promo_code:
        del awaiting_promo_code[user_id]

    # СНАЧАЛА проверяем пользовательские промокоды (подарки)
    user_promo = get_user_promo_code(promo_code)
    if user_promo:
        # Используем пользовательский промокод
        if use_user_promo_code(promo_code, user_id):
            gift_type_text = ""
            if user_promo['gift_type'] == 'balance':
                gift_type_text = f"{user_promo['gift_amount']}₽ на баланс"
                new_balance = get_user_balance(user_id)
                message_text = f"🎉 Вы активировали промокод!\n\n🎁 Получено: {gift_type_text}\n💰 Новый баланс: {new_balance:.2f}₽"
            elif user_promo['gift_type'] == 'stars':
                gift_type_text = f"{user_promo['gift_amount']} звёзд"
                user_stats = get_user_stats(user_id)
                message_text = f"🎉 Вы активировали промокод!\n\n🎁 Получено: {gift_type_text}\n⭐ Всего звёзд: {user_stats['stars_purchased']}"
            elif user_promo['gift_type'] == 'ton':
                gift_type_text = f"{user_promo['gift_amount']} TON"
                user_stats = get_user_stats(user_id)
                message_text = f"🎉 Вы активировали промокод!\n\n🎁 Получено: {gift_type_text}\n💎 Всего TON: {user_stats['ton_purchased']:.2f}"

            await update.message.reply_text(message_text, reply_markup=get_main_menu_keyboard())
            await cancel_promo_input(update, context)
            return
        else:
            await update.message.reply_text("❌ Промокод уже использован максимальное количество раз", reply_markup=get_main_menu_keyboard())
            await cancel_promo_input(update, context)
            return

    # ЗАТЕМ проверяем обычные промокоды (скидки)
    promo = get_promo_code(promo_code)
    if not promo:
        await update.message.reply_text(
            "❌ Промокод не найден или недействителен",
            reply_markup=get_main_menu_keyboard()
        )
        await cancel_promo_input(update, context)
        return

    # Проверяем, использовал ли пользователь уже этот промокод
    if has_user_used_promo(user_id, promo_code):
        await update.message.reply_text(
            "❌ Вы уже использовали этот промокод",
            reply_markup=get_main_menu_keyboard()
        )
        await cancel_promo_input(update, context)
        return

    # Проверяем срок действия
    if promo['valid_until']:
        try:
            valid_until = datetime.strptime(promo['valid_until'], "%Y-%m-%d %H:%M:%S")
            if get_moscow_time() > valid_until:
                await update.message.reply_text(
                    "❌ Промокод истек",
                    reply_markup=get_main_menu_keyboard()
                )
                await cancel_promo_input(update, context)
                return
        except ValueError:
            pass  # Если дата в неправильном формате, игнорируем

    # Проверяем лимит использований
    if promo['max_uses'] > 0 and promo['used_count'] >= promo['max_uses']:
        await update.message.reply_text(
            "❌ Промокод уже использован максимальное количество раз",
            reply_markup=get_main_menu_keyboard()
        )
        await cancel_promo_input(update, context)
        return

    # Сохраняем примененный промокод с указанием типа товара
    applied_promocodes[user_id] = {
        'code': promo_code,
        'product_type': product_type,
        'discount_percent': promo['discount_percent']
    }

    logger.info(f"✅ Промокод {promo_code} применен для типа: {product_type}")

    # Показываем правильное меню в зависимости от типа товара
    await show_correct_menu_after_promo(update, context, product_type, promo_code)

async def process_promo_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод кода промокода"""
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.user_data.get('promo_creation'):
        await update.message.reply_text("❌ Процесс создания промокода не активен")
        return

    code = update.message.text.strip().upper()

    # Проверяем формат кода
    if not re.match(r'^[A-Z0-9]+$', code):
        await update.message.reply_text(
            "❌ Код должен содержать только латинские буквы и цифры!\n"
            "Попробуйте еще раз:"
        )
        return

    # Проверяем существование промокода
    existing_promo = get_promo_code(code)
    if existing_promo:
        await update.message.reply_text(
            f"❌ Промокод {code} уже существует!\n"
            "Введите другой код:"
        )
        return

    # Сохраняем код
    context.user_data['promo_creation']['code'] = code
    context.user_data['promo_creation']['step'] = 2

    await update.message.reply_text(
        f"🎫 <b>Создание промокода - Шаг 2/3</b>\n\n"
        f"✅ Код: {code}\n\n"
        "💯 Введите процент скидки (0-100):\n\n"
        "❌ Для отмены отправьте 'отмена'",
        parse_mode='HTML'
    )

async def process_promo_discount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод процента скидки"""
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.user_data.get('promo_creation') or context.user_data['promo_creation']['step'] != 2:
        await update.message.reply_text("❌ Неверный шаг процесса")
        return

    try:
        discount_percent = float(update.message.text.replace(',', '.'))

        if discount_percent < 0 or discount_percent > 100:
            await update.message.reply_text(
                "❌ Процент скидки должен быть от 0 до 100!\n\n"
                "Попробуйте еще раз:"
            )
            return

        # Сохраняем процент скидки
        context.user_data['promo_creation']['discount_percent'] = discount_percent
        context.user_data['promo_creation']['step'] = 3

        await update.message.reply_text(
            f"🎫 <b>Создание промокода - Шаг 3/3</b>\n\n"
            f"✅ Код: {context.user_data['promo_creation']['code']}\n"
            f"✅ Скидка: {discount_percent}%\n\n"
            "🔢 Введите максимальное количество использований:\n\n"
            "❌ Для отмены отправьте 'отмена'",
            parse_mode='HTML'
        )

    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введите корректное число!\n\n"
            "Попробуйте еще раз:"
        )

async def process_promo_uses_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод количества использований и создает промокод"""
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.user_data.get('promo_creation') or context.user_data['promo_creation']['step'] != 3:
        await update.message.reply_text("❌ Неверный шаг процесса")
        return

    try:
        max_uses = int(update.message.text)

        if max_uses <= 0:
            await update.message.reply_text(
                "❌ Количество использований должно быть больше 0!\n\n"
                "Попробуйте еще раз:"
            )
            return

        # Получаем данные промокода
        promo_data = context.user_data['promo_creation']

        # СОЗДАЕМ ПРОМОКОД
        success, message = create_promo_code(
            code=promo_data['code'],
            discount_percent=promo_data['discount_percent'],
            max_uses=max_uses
        )

        if success:
            # Очищаем данные создания
            del context.user_data['promo_creation']

            await update.message.reply_text(
                f"✅ Промокод успешно создан!\n\n"
                f"🎫 Код: <code>{promo_data['code']}</code>\n"
                f"💯 Скидка: {promo_data['discount_percent']}%\n"
                f"🔢 Лимит: {max_uses} использований\n\n"
                f"💡 Промокод готов к использованию!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 К списку промокодов", callback_data="list_promos")],
                    [InlineKeyboardButton("➕ Создать еще", callback_data="create_promo")],
                    [InlineKeyboardButton("🔙 В админ-панель", callback_data="back_to_main")]
                ])
            )
        else:
            await update.message.reply_text(
                f"❌ Ошибка при создании промокода:\n{message}\n\n"
                "Попробуйте создать промокод заново.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Попробовать снова", callback_data="create_promo")
                ]])
            )

    except ValueError:
        await update.message.reply_text(
            "❌ Пожалуйста, введите целое число!\n\n"
            "Попробуйте еще раз:"
        )

async def enter_promo_code_for_gift(update: Update, context: ContextTypes.DEFAULT_TYPE, gift_type: str):
    """Обработка ввода промокода для подарков"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # Сохраняем тип подарка для применения промокода
    context.user_data['applying_promo_for'] = f"gift_{gift_type}"
    context.user_data['awaiting_promo_input'] = True
    context.user_data['promo_product_type'] = f"gift_{gift_type}"

    await query.edit_message_text(
        "🎫 Введите промокод для подарка:\n\n"
        "❌ Для отмены отправьте 'отмена'"
    )

    # Добавляем пользователя в состояние ожидания промокода
    awaiting_promo_code[user_id] = True

async def process_promo_uses_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор количества использований"""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    if not context.user_data.get('promo_creation') or context.user_data['promo_creation']['step'] != 4:
        await query.edit_message_text("❌ Неверный шаг процесса")
        return

    callback_data = query.data
    uses_map = {
        'promo_unlimited': 0,
        'promo_uses_1': 1,
        'promo_uses_5': 5,
        'promo_uses_10': 10,
        'promo_uses_50': 50,
        'promo_uses_100': 100
    }

    max_uses = uses_map.get(callback_data)
    if max_uses is None:
        await query.edit_message_text("❌ Неверный выбор")
        return

    # Сохраняем лимит использований
    context.user_data['promo_creation']['max_uses'] = max_uses
    context.user_data['promo_creation']['step'] = 5

    keyboard = [
        [InlineKeyboardButton("⏰ 1 день", callback_data="promo_expire_1")],
        [InlineKeyboardButton("⏰ 7 дней", callback_data="promo_expire_7")],
        [InlineKeyboardButton("⏰ 30 дней", callback_data="promo_expire_30")],
        [InlineKeyboardButton("⏰ 90 дней", callback_data="promo_expire_90")],
        [InlineKeyboardButton("🔄 Без срока", callback_data="promo_expire_none")],
        [InlineKeyboardButton("🔙 Назад к лимиту", callback_data="create_promo_back_4")]
    ]

    uses_text = "♾️ Без ограничений" if max_uses == 0 else f"{max_uses} использований"

    await query.edit_message_text(
        f"🎫 СОЗДАНИЕ ПРОМОКОДА - Шаг 5/5\n\n"
        f"Тип: {context.user_data['promo_creation']['type']}\n"
        f"Код: {context.user_data['promo_creation']['code']}\n"
        f"Скидка: {context.user_data['promo_creation']['discount_percent']}%\n"
        f"Лимит: {uses_text}\n\n"
        "📅 Выберите срок действия промокода:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def request_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос кода промокода (обработка текстового ввода)"""
    query = update.callback_query
    await query.answer()

    # Устанавливаем состояние ожидания ввода кода
    context.user_data['promo_creation']['step'] = 'awaiting_code'

    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data="create_promo_back_type")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🎫 <b>Создание промокода</b>\n\n"
        "✏️ Отправьте код промокода в следующем сообщении:\n\n"
        "📝 Формат: только латинские буквы и цифры (A-Z, 0-9)\n"
        "⏰ У вас есть 2 минуты на ввод\n\n"
        "❌ Для отмены отправьте 'отмена'",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def process_promo_expire_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает создание промокода"""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    if not context.user_data.get('promo_creation'):
        await query.edit_message_text("❌ Процесс создания промокода не найден")
        return

    # Получаем данные промокода
    promo_data = context.user_data['promo_creation']

    logger.info(f"🎯 ЗАВЕРШЕНИЕ СОЗДАНИЯ ПРОМОКОДА: {promo_data}")

    # Создаем промокод в базе данных
    success, message = create_promo_code(
        code=promo_data['code'],
        discount_percent=promo_data['discount_percent'],
        discount_amount=promo_data.get('discount_amount', 0),
        min_amount=0,
        max_uses=promo_data['max_uses'],
        valid_until=promo_data.get('valid_until'),
        created_by=ADMIN_ID,
        gift_amount=0,
        gift_type='balance'
    )

    if success:
        # Очищаем данные создания
        del context.user_data['promo_creation']

        # Формируем информацию о промокоде
        type_names = {
            'stars': '⭐ Звёзды',
            'ton': '💎 TON',
            'premium': '🌟 Premium',
            'gift': '🎁 Подарки',
            'balance': '💰 Пополнение баланса',
            'all': '🎫 Все товары'
        }

        uses_text = "♾️ Без ограничений" if promo_data['max_uses'] == 0 else f"{promo_data['max_uses']} использований"
        expire_text = "Не ограничен" if not promo_data.get('valid_until') else promo_data['valid_until'][:16]

        promo_info = (
            f"✅ ПРОМОКОД УСПЕШНО СОЗДАН!\n\n"
            f"🎫 Код: <code>{promo_data['code']}</code>\n"
            f"📦 Тип: {type_names.get(promo_data['type'], promo_data['type'])}\n"
            f"💯 Скидка: {promo_data['discount_percent']}%\n"
            f"🔢 Лимит: {uses_text}\n"
            f"📅 Срок действия: {expire_text}\n"
            f"🔄 Статус: ✅ Активен\n\n"
            f"💡 Промокод готов к использованию!"
        )

        await query.edit_message_text(
            promo_info,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 К списку промокодов", callback_data="list_promos")],
                [InlineKeyboardButton("➕ Создать еще", callback_data="create_promo")],
                [InlineKeyboardButton("🔙 В админ-панель", callback_data="back_to_main")]
            ])
        )

        # ПРОВЕРЯЕМ, ЧТО ПРОМОКОД ДЕЙСТВИТЕЛЬНО СОЗДАН
        check_promo = get_promo_code(promo_data['code'])
        if check_promo:
            logger.info(f"✅ Промокод {promo_data['code']} успешно проверен в БД")
        else:
            logger.error(f"❌ Промокод {promo_data['code']} не найден после создания!")

    else:
        await query.edit_message_text(
            f"❌ Ошибка при создании промокода!\n\n{message}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="create_promo")],
                [InlineKeyboardButton("🔙 Назад", callback_data="admin_promocodes")]
            ])
        )

async def handle_promo_creation_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает возврат на предыдущий шаг создания промокода - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    if not context.user_data.get('promo_creation'):
        await query.edit_message_text("❌ Процесс создания промокода не активен")
        return

    callback_data = query.data
    logger.info(f"🎫 Обработка возврата: {callback_data}")

    # Определяем, на какой шаг возвращаемся
    if callback_data == "create_promo_back_type":
        await create_promo_step_by_step(update, context)

    elif callback_data == "create_promo_back_code":
        await process_promo_type_selection(update, context)

    elif callback_data == "create_promo_back_discount":
        await request_promo_code(update, context)

    elif callback_data == "create_promo_back_uses":
        await request_promo_discount(update, context)

    elif callback_data == "create_promo_back_expire":
        await request_promo_uses(update, context)

    elif callback_data == "create_promo_back_gift_type":
        await request_promo_code(update, context)

    elif callback_data == "create_promo_back_gift_amount":
        await request_gift_type(update, context)

    else:
        await query.edit_message_text("❌ Неизвестная команда возврата")

async def request_promo_expire(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос срока действия промокода"""
    promo_data = context.user_data['promo_creation']

    keyboard = [
        [InlineKeyboardButton("⏰ 1 день", callback_data="promo_expire_1")],
        [InlineKeyboardButton("⏰ 7 дней", callback_data="promo_expire_7")],
        [InlineKeyboardButton("⏰ 30 дней", callback_data="promo_expire_30")],
        [InlineKeyboardButton("♾️ Без срока", callback_data="promo_expire_unlimited")],
        [InlineKeyboardButton("🔙 Назад", callback_data="create_promo_back_uses")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"🎫 <b>Создание промокода</b>\n\n"
        f"📝 Код: <code>{promo_data['code']}</code>\n"
        f"📉 Скидка: {promo_data['discount_percent']}%\n"
        f"🔢 Использований: {promo_data['max_uses'] if promo_data['max_uses'] > 0 else 'без ограничений'}\n\n"
        "⏰ Выберите срок действия:"
    )

    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def request_promo_uses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос количества использований промокода"""
    promo_data = context.user_data['promo_creation']

    keyboard = [
        [InlineKeyboardButton("♾️ Без ограничений", callback_data="promo_uses_unlimited")],
        [InlineKeyboardButton("1 использование", callback_data="promo_uses_1")],
        [InlineKeyboardButton("5 использований", callback_data="promo_uses_5")],
        [InlineKeyboardButton("10 использований", callback_data="promo_uses_10")],
        [InlineKeyboardButton("50 использований", callback_data="promo_uses_50")],
        [InlineKeyboardButton("100 использований", callback_data="promo_uses_100")],
        [InlineKeyboardButton("🔙 Назад", callback_data="create_promo_back_discount")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"🎫 <b>Создание промокода</b>\n\n"
        f"📝 Код: <code>{promo_data['code']}</code>\n"
        f"📉 Скидка: {promo_data['discount_percent']}%\n\n"
        "🔢 Выберите максимальное количество использований:"
    )

    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def create_promo_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Финальное создание промокода"""
    query = update.callback_query
    await query.answer()

    promo_data = context.user_data['promo_creation']

    try:
        # Создаем промокод в базе данных
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        now = get_moscow_time()
        valid_until = None

        if promo_data['valid_days'] > 0:
            valid_until = (now + timedelta(days=promo_data['valid_days'])).strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute('''
        INSERT INTO promo_codes
        (code, discount_percent, max_uses, used_count, is_active, created_date, valid_until)
        VALUES (?, ?, ?, 0, 1, ?, ?)
        ''', (
            promo_data['code'],
            promo_data['discount_percent'],
            promo_data['max_uses'],
            now.strftime("%Y-%m-%d %H:%M:%S"),
            valid_until
        ))

        conn.commit()
        conn.close()

        # Формируем текст результата
        valid_text = "без срока" if promo_data['valid_days'] == 0 else f"{promo_data['valid_days']} дней"
        uses_text = "без ограничений" if promo_data['max_uses'] == 0 else f"{promo_data['max_uses']} использований"

        success_text = (
            f"✅ <b>Промокод создан успешно!</b>\n\n"
            f"🎫 Код: <code>{promo_data['code']}</code>\n"
            f"📉 Скидка: {promo_data['discount_percent']}%\n"
            f"🔢 Использований: {uses_text}\n"
            f"⏰ Срок действия: {valid_text}\n\n"
            f"🕐 Создан: {now.strftime('%d.%m.%Y %H:%M')}"
        )

        # Очищаем данные создания
        del context.user_data['promo_creation']

        keyboard = [
            [InlineKeyboardButton("📋 Список промокодов", callback_data="list_promos")],
            [InlineKeyboardButton("🎫 Создать еще", callback_data="create_promo")],
            [InlineKeyboardButton("🔙 В админ-панель", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(success_text, reply_markup=reply_markup, parse_mode='HTML')

    except sqlite3.IntegrityError:
        await query.edit_message_text(
            f"❌ Промокод <code>{promo_data['code']}</code> уже существует!",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"❌ Ошибка создания промокода: {e}")
        await query.edit_message_text(f"❌ Ошибка при создании промокода: {str(e)}")

async def show_my_promocodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает использованные промокоды пользователя"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    used_promocodes = get_user_used_promocodes(user_id)

    if not used_promocodes:
        text = "🎫 Вы еще не использовали ни одного промокода"
    else:
        text = "🎫 Использованные промокоды:\n\n"
        for i, promo in enumerate(used_promocodes, 1):
            text += (
                f"{i}. Код: {promo['code']}\n"
                f"   📅 Дата: {promo['used_date'][:16]}\n"
                f"   💰 Скидка: {promo['discount_amount']:.2f}₽\n"
                f"   🛒 Заказ: {promo['order_type']}\n"
                f"   ──────────────────\n"
            )

    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data="profile_back")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def complete_promo_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает создание промокода и сохраняет в БД"""
    try:
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
            return

        if not context.user_data.get('promo_creation'):
            await update.message.reply_text("❌ Данные создания промокода не найдены.")
            return

        promo_data = context.user_data['promo_creation']

        logger.info(f"🔴🔴🔴 ЗАВЕРШЕНИЕ СОЗДАНИЯ ПРОМОКОДА: {promo_data}")

        # Используем принудительное создание
        success, message = create_promo_code_force(
            code=promo_data['code'],
            discount_percent=promo_data['discount_percent'],
            discount_amount=promo_data.get('discount_amount', 0),
            max_uses=promo_data['max_uses'],
            valid_until=promo_data.get('valid_until'),
            created_by=ADMIN_ID,
            gift_amount=promo_data.get('gift_amount', 0),
            gift_type=promo_data.get('gift_type', 'balance')
        )

        if success:
            # Очищаем данные создания
            del context.user_data['promo_creation']

            # Формируем информацию о промокоде
            type_names = {
                'stars': '⭐ звёзд',
                'ton': '💎 TON',
                'premium': '🌟 Premium',
                'gift': '🎁 подарков',
                'balance': '💰 пополнения баланса',
                'all': '🎫 всех товаров'
            }

            promo_info = (
                f"✅ ПРОМОКОД УСПЕШНО СОЗДАН!\n\n"
                f"🎫 Код: <code>{promo_data['code']}</code>\n"
                f"📊 Тип: {type_names.get(promo_data['type'], promo_data['type'])}\n"
                f"💯 Скидка: {promo_data['discount_percent']}%\n"
                f"🔢 Использований: {promo_data['max_uses']}\n"
            )

            if promo_data.get('valid_until'):
                promo_info += f"⏰ Действует до: {promo_data['valid_until']}\n"

            keyboard = [
                [InlineKeyboardButton("📋 Список промокодов", callback_data="list_promos")],
                [InlineKeyboardButton("➕ Создать еще", callback_data="create_promo")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_main")]
            ]

            await update.message.reply_text(
                promo_info,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )

            # ПРОВЕРЯЕМ, ЧТО ПРОМОКОД ДЕЙСТВИТЕЛЬНО СОЗДАН
            check_promo = get_promo_code(promo_data['code'])
            if check_promo:
                logger.info(f"✅ Промокод {promo_data['code']} успешно проверен в БД")
            else:
                logger.error(f"❌ Промокод {promo_data['code']} не найден после создания!")

        else:
            await update.message.reply_text(
                f"❌ Ошибка при создании промокода:\n{message}\n\n"
                "Попробуйте создать промокод заново.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Попробовать снова", callback_data="create_promo"),
                    InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_main")
                ]])
            )

    except Exception as e:
        logger.error(f"❌ Ошибка при завершении создания промокода: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при создании промокода. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_main")
            ]])
        )

def create_promo_code_force(code: str, discount_percent: float = 0, discount_amount: float = 0,
                           min_amount: float = 0, max_uses: int = 1, valid_until: str = None,
                           created_by: int = ADMIN_ID, gift_amount: float = 0, gift_type: str = 'balance'):
    """Создает промокод, принудительно обновляя существующий"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

        logger.info(f"🔴🔴🔴 ПРИНУДИТЕЛЬНОЕ СОЗДАНИЕ ПРОМОКОДА: {code}")

        # УДАЛЯЕМ СУЩЕСТВУЮЩИЙ ПРОМОКОД ЕСЛИ ЕСТЬ
        cursor.execute('DELETE FROM promo_codes WHERE code = ?', (code.upper(),))
        deleted_count = cursor.rowcount
        if deleted_count > 0:
            logger.info(f"🔴 Удален существующий промокод {code}")

        # СОЗДАЕМ НОВЫЙ ПРОМОКОД С is_active = 1
        cursor.execute('''
        INSERT INTO promo_codes
        (code, discount_percent, discount_amount, min_amount, max_uses, valid_until,
         created_date, created_by, gift_amount, gift_type, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (code.upper(), discount_percent, discount_amount, min_amount,
              max_uses, valid_until, now, created_by, gift_amount, gift_type))

        conn.commit()
        conn.close()

        logger.info(f"✅ Промокод {code} успешно создан (принудительно, is_active=1)")
        return True, "Промокод успешно создан"

    except Exception as e:
        logger.error(f"❌ Ошибка при принудительном создании промокода {code}: {e}")
        if conn:
            conn.close()
        return False, f"Ошибка: {str(e)}"

async def list_promocodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список всех промокодов - УПРОЩЕННАЯ РАБОЧАЯ ВЕРСИЯ"""
    try:
        query = update.callback_query
        await query.answer()

        if query.from_user.id != ADMIN_ID:
            await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
            return

        # Простая версия без сложных запросов
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        # Простой запрос к таблице promo_codes
        cursor.execute('''
        SELECT code, discount_percent, max_uses, used_count, is_active
        FROM promo_codes
        ORDER BY created_date DESC
        LIMIT 50
        ''')

        promos = cursor.fetchall()
        conn.close()

        if not promos:
            text = "📭 Нет созданных промокодов."
            keyboard = [
                [InlineKeyboardButton("➕ Создать промокод", callback_data="create_promo")],
                [InlineKeyboardButton("🔙 Назад", callback_data="admin_promocodes")]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        text = "📋 СПИСОК ПРОМОКОДОВ:\n\n"

        for promo in promos:
            code, discount, max_uses, used_count, is_active = promo
            status = "✅" if is_active else "❌"

            text += f"{status} <code>{code}</code>\n"
            text += f"   Скидка: {discount}% | Использовано: {used_count}/{max_uses if max_uses > 0 else '∞'}\n"
            text += "   ─────────────────────\n"

        text += f"\n📊 Всего: {len(promos)} промокодов"

        keyboard = [
            [InlineKeyboardButton("➕ Создать новый", callback_data="create_promo")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="list_promos")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_promocodes")]
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"❌ Ошибка в list_promocodes: {e}")
        await query.edit_message_text(
            "❌ Ошибка загрузки списка промокодов. Проверьте структуру базы данных.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="admin_promocodes")]
            ])
        )

async def force_reset_promo_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительный сброс состояния создания промокода"""
    if update.effective_user.id != ADMIN_ID:
        return

    if 'promo_creation' in context.user_data:
        del context.user_data['promo_creation']
        logger.info("🔧 Принудительно сброшено состояние создания промокода")

    await update.message.reply_text(
        "🔧 Состояние создания промокода сброшено. Можно начинать заново.",
        reply_markup=get_admin_keyboard()
    )

async def process_balance_replenishment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод суммы для пополнения баланса"""
    user_id = update.message.from_user.id

    if user_id not in awaiting_balance_amount:
        return

    try:
        amount = float(update.message.text.replace(',', '.'))

        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть больше 0")
            return

        if amount > 100000:
            await update.message.reply_text("❌ Максимальная сумма пополнения: 100,000₽")
            return

        del awaiting_balance_amount[user_id]

        await send_admin_notification(context, user_id, f"Начинает пополнение баланса на {amount:.2f}₽")

        pending_payments[user_id] = {
            "amount": amount,
            "is_balance_replenishment": True,
            "timestamp": get_moscow_time()
        }

        text = (
            f"💰 Пополнение баланса на {amount:.2f}₽\n\n"
            "💳 Способы оплаты:\n"
            f"1. ЮMoney: `{YM_ACCOUNT}`\n"
            f"2. СБП (Т-Банк): `{SBP_PHONE}`\n"
            "3. Карты:\n"
        )

        for bank, number in CARD_NUMBERS.items():
            text += f"   - {bank}: `{number}`\n"

        text += (
            "\n⏳ После оплаты:\n"
            "- Через ЮMoney: баланс пополнится автоматически\n"
            "- На карту или СБП: отправьте скриншот чека в этот чат"
        )

        keyboard = [
            [InlineKeyboardButton("💳 Оплатить через ЮMoney", url=f"https://yoomoney.ru/quickpay/confirm.xml?receiver={YM_ACCOUNT}&quickpay-form=small&targets=Пополнение баланса&sum={amount}&label=balance_{amount}")],
            [InlineKeyboardButton("📱 Оплатить через СБП", callback_data="sbp_payment_balance")],
            [InlineKeyboardButton("📲 Оплатить на карту", callback_data="card_payment_balance")],
            [InlineKeyboardButton("🔙 Назад", callback_data="profile_back")]
        ]

        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите корректную сумму")

# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user = update.effective_user
        logger.info(f"🎯 START команда от пользователя {user.id}")

        # Обрабатываем реферальный код если есть
        referred_by = None
        if context.args and len(context.args) > 0:
            ref_code = context.args[0]
            # Находим ID пользователя по реферальному коду
            referred_by = get_user_id_by_referral_code(ref_code)
            if referred_by:
                logger.info(f"🎯 Пользователь {user.id} пришел по реферальной ссылке от {referred_by}")
            else:
                logger.warning(f"⚠️ Не найден реферер для кода: {ref_code}")

        # Добавляем пользователя
        is_new_user = add_user_simple(user.id, user.username, user.full_name, referred_by)

        # 🔴 УВЕДОМЛЯЕМ РЕФЕРЕРА О НОВОМ РЕФЕРАЛЕ
        if is_new_user and referred_by:
            try:
                await context.bot.send_message(
                    referred_by,
                    f"🎉 У вас новый реферал!\n\n"
                    f"👤 Пользователь: {user.full_name or 'Без имени'}\n"
                    f"📛 Username: @{user.username or 'Нет username'}\n\n"
                    f"Теперь вы будете получать 5% с его покупок! 💰"
                )
                logger.info(f"✅ Реферер {referred_by} уведомлен о новом реферале {user.id}")
            except Exception as e:
                logger.error(f"❌ Не удалось уведомить реферера {referred_by}: {e}")

        # Отправляем сообщение
        await update.message.reply_text(
            """🔥 Добро пожаловать в бота для покупки звёзд/premium и TON!

🌍 Можете посмотреть наши проекты: akkaunti-shop.pro/projects

🔗 Переходник: akkaunti-shop.pro/stars-shop17

👇Выберите действие:""",
            reply_markup=get_main_menu_keyboard()
        )

        logger.info(f"✅ START команда успешно выполнена для {user.id}")

    except Exception as e:
        logger.error(f"❌ Ошибка в команде start: {e}")
        # Аварийное сообщение если что-то пошло не так
        await update.message.reply_text(
            """🔥 Добро пожаловать в бота для покупки звёзд/premium и TON!

🌍 Можете посмотреть наши проекты: akkaunti-shop.ru/projects

🔗 Переходник: https://akkaunti-shop.pro/stars-shop17

👇Выберите действие:""",
            reply_markup=get_main_menu_keyboard()
        )

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return

    await update.message.reply_text(
        "👨‍💻 Админ-панель:",
        reply_markup=get_admin_keyboard()
    )

# ИСПРАВЛЕННАЯ ФУНКЦИЯ - статистика с кнопками "Сделать меньше" и "Прибавить выручку"
async def show_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Получаем расширенную статистику
    hourly_stats = get_hourly_sales_stats()
    daily_stats = get_daily_sales_stats()
    total_stats = get_total_sales_stats()
    total_users, active_today, blocked_users, total_stars, total_premium, total_ton = get_user_stats()

    moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

    # Рассчитываем конверсию
    conversion_rate = (active_today / total_users * 100) if total_users > 0 else 0

    stats_text = (
        f"📊 РАСШИРЕННАЯ СТАТИСТИКА (МСК: {moscow_time})\n\n"

        f"⏰ ЗА ПОСЛЕДНИЙ ЧАС:\n"
        f"⭐ Звёзд продано: {hourly_stats['stars']} шт\n"
        f"🌟 Premium продано: {hourly_stats['premium']} шт\n"
        f"💎 TON продано: {hourly_stats['ton']:.2f} TON\n"
        f"💰 Выручка: {hourly_stats['revenue']:.2f}₽\n\n"

        f"📅 ЗА ПОСЛЕДНИЕ 24 ЧАСА:\n"
        f"⭐ Звёзд продано: {daily_stats['stars']} шт\n"
        f"🌟 Premium продано: {daily_stats['premium']} шт\n"
        f"💎 TON продано: {daily_stats['ton']:.2f} TON\n"
        f"💰 Выручка: {daily_stats['revenue']:.2f}₽\n\n"

        f"📊 ОБЩАЯ СТАТИСТИКА:\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🟢 Активных за сегодня: {active_today}\n"
        f"📊 Конверсия: {conversion_rate:.1f}%\n"
        f"🚫 Заблокировали бота: {blocked_users}\n"
        f"⭐ Всего звёзд продано: {total_stats['stars']} шт\n"
        f"🌟 Всего Premium продано: {total_stats['premium']} шт\n"
        f"💎 Всего TON продано: {total_stats['ton']:.2f} TON\n"
        f"💰 Общая выручка: {total_stats['revenue']:.2f}₽"
    )

    # ДОБАВЛЯЕМ КНОПКИ "СДЕЛАТЬ МЕНЬШЕ" и "ПРИБАВИТЬ ВЫРУЧКУ"
    keyboard = [
        [InlineKeyboardButton("📉 Уменьшить выручку", callback_data="decrease_revenue"),
         InlineKeyboardButton("📈 Увеличить выручку", callback_data="increase_revenue")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
    ]

    await query.edit_message_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# НОВАЯ ФУНКЦИЯ - уменьшение выручки
async def decrease_revenue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    # Уменьшаем выручку на 10%
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    # Уменьшаем выручку во всех записях sales_stats
    cursor.execute('UPDATE sales_stats SET revenue = revenue * 0.9')

    # Уменьшаем статистику покупок пользователей
    cursor.execute('UPDATE users SET stars_purchased = stars_purchased * 0.9')
    cursor.execute('UPDATE users SET premium_purchased = premium_purchased * 0.9')
    cursor.execute('UPDATE users SET ton_purchased = ton_purchased * 0.9')

    conn.commit()
    conn.close()

    await query.edit_message_text(
        "✅ Выручка и статистика уменьшены на 10%",
        reply_markup=get_admin_keyboard()
    )
    logger.info("✅ Выручка уменьшена на 10%")

# НОВАЯ ФУНКЦИЯ - увеличение выручки
async def increase_revenue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    # Увеличиваем выручку на 10%
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    # Увеличиваем выручку во всех записях sales_stats
    cursor.execute('UPDATE sales_stats SET revenue = revenue * 1.1')

    # Увеличиваем статистику покупок пользователей
    cursor.execute('UPDATE users SET stars_purchased = stars_purchased * 1.1')
    cursor.execute('UPDATE users SET premium_purchased = premium_purchased * 1.1')
    cursor.execute('UPDATE users SET ton_purchased = ton_purchased * 1.1')

    conn.commit()
    conn.close()

    await query.edit_message_text(
        "✅ Выручка и статистика увеличены на 10%",
        reply_markup=get_admin_keyboard()
    )
    logger.info("✅ Выручка увеличена на 10%")

# ИСПРАВЛЕННАЯ ФУНКЦИЯ - подтверждение заказов с кнопкой подтвердить все
async def show_pending_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    logger.info(f"🔴🔴🔴 ВЫЗВАНА show_pending_orders")

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM pending_orders WHERE status = "pending" ORDER BY order_id DESC LIMIT 10')
    pending_orders = cursor.fetchall()
    conn.close()

    logger.info(f"🔴🔴🔴 Найдено заказов: {len(pending_orders)}")

    if not pending_orders:
        await query.edit_message_text(
            "✅ Нет заказов, ожидающих подтверждения",
            reply_markup=get_admin_keyboard()
        )
        return

    orders_text = "📋 ЗАКАЗЫ ОЖИДАЮТ ПОДТВЕРЖДЕНИЯ:\n\n"
    keyboard = []

    for order in pending_orders:
        order_info = {
            'order_id': order[0],
            'user_id': order[1],
            'username': order[2],
            'full_name': order[3],
            'order_type': order[4],
            'amount': order[5],
            'cost': order[6],
            'friend_username': order[11],
            'is_balance_replenishment': order[12]
        }

        order_type_text = ""
        if order_info['is_balance_replenishment']:
            order_type_text = f"💰 Пополнение баланса на {order_info['amount']}₽"
        elif order_info['order_type'] == "stars":
            order_type_text = f"⭐ {order_info['amount']} звёзд"
        elif order_info['order_type'] == "ton":
            order_type_text = f"💎 {order_info['amount']} TON"
        elif order_info['order_type'] == "premium":
            order_type_text = f"🌟 Premium на {order_info['amount']}"

        # Добавляем информацию о подарке если есть
        gift_info = ""
        if order_info['friend_username']:
            gift_info = f"🎁 Подарок для: {order_info['friend_username']}\n"

        orders_text += (
            f"🆔 ЗАКАЗ #{order_info['order_id']}\n"
            f"👤 @{order_info['username']} ({order_info['full_name']})\n"
            f"🆔 ID: {order_info['user_id']}\n"
            f"{gift_info}"
            f"📦 {order_type_text}\n"
            f"💰 {order_info['cost']:.1f}₽\n"
            f"⏰ {order[9]}\n"
            f"────────────────────\n"
        )

        # 🔴🔴🔴 ВАЖНО: СОЗДАЕМ КНОПКИ ДЛЯ КАЖДОГО ЗАКАЗА 🔴🔴🔴
        confirm_callback = f"confirm_order_{order_info['order_id']}"
        reject_callback = f"reject_order_{order_info['order_id']}"

        logger.info(f"🎯 Создана кнопка подтверждения: {confirm_callback}")

        keyboard.append([
            InlineKeyboardButton(f"✅ Подтвердить #{order_info['order_id']}", callback_data=confirm_callback),
            InlineKeyboardButton(f"❌ Отклонить #{order_info['order_id']}", callback_data=reject_callback)
        ])

    # ДОБАВЛЯЕМ КНОПКУ ДЛЯ ПОДТВЕРЖДЕНИЯ ВСЕХ ЗАКАЗОВ
    keyboard.append([InlineKeyboardButton("✅ Подтвердить ВСЕ заказы", callback_data="confirm_all_orders")])
    keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data="admin_confirm_orders")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_stats")])

    await query.edit_message_text(
        orders_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ИСПРАВЛЕННАЯ ФУНКЦИЯ - подтверждение всех заказов сразу
async def confirm_all_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    logger.info(f"🔴🔴🔴 confirm_all_orders ВЫЗВАНА пользователем {update.effective_user.id}")

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    # Получаем все ожидающие заказы
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM pending_orders WHERE status = "pending"')
    pending_orders = cursor.fetchall()
    conn.close()

    logger.info(f"🔴🔴🔴 Найдено заказов для подтверждения: {len(pending_orders)}")

    if not pending_orders:
        await query.edit_message_text(
            "✅ Нет заказов для подтверждения",
            reply_markup=get_admin_keyboard()
        )
        return

    confirmed_count = 0
    failed_count = 0
    referral_bonuses = 0  # 🔴 СЧЕТЧИК РЕФЕРАЛЬНЫХ БОНУСОВ

    for order in pending_orders:
        order_info = {
            'order_id': order[0],
            'user_id': order[1],
            'username': order[2],
            'full_name': order[3],
            'order_type': order[4],
            'amount': order[5],
            'cost': order[6],
            'friend_username': order[11],
            'is_balance_replenishment': order[12]
        }

        try:
            # Обновляем статус заказа
            update_order_status(order_info['order_id'], "confirmed")

            # Обрабатываем заказ в зависимости от типа
            if order_info['is_balance_replenishment']:
                # Пополнение баланса - ИСПРАВЛЕННАЯ ВЕРСИЯ
                conn = sqlite3.connect('bot.db')
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE users SET balance = balance + ? WHERE user_id = ?',
                    (order_info['amount'], order_info['user_id'])
                )
                conn.commit()

                # Получаем новый баланс для лога
                cursor.execute('SELECT balance FROM users WHERE user_id = ?', (order_info['user_id'],))
                result = cursor.fetchone()
                new_balance = result[0] if result else 0
                conn.close()

                logger.info(f"✅ Баланс пользователя {order_info['user_id']} пополнен на {order_info['amount']}₽ | новый баланс: {new_balance}₽")
            elif order_info['friend_username']:
                # Подарок
                update_user_purchase_stats(order_info['user_id'], f"gift_{order_info['order_type']}", order_info['amount'])
                record_sale(f"gift_{order_info['order_type']}", order_info['amount'], order_info['cost'])
            else:
                # Обычная покупка
                update_user_purchase_stats(order_info['user_id'], order_info['order_type'], order_info['amount'])
                record_sale(order_info['order_type'], order_info['amount'], order_info['cost'])

            # 🔴🔴🔴 ДОБАВЛЯЕМ РЕФЕРАЛЬНЫЙ БОНУС ДЛЯ ЛЮБОГО ЗАКАЗА 🔴🔴🔴
            if order_info.get('cost', 0) > 0:
                success = await process_referral_bonus(order_info['order_id'], order_info['user_id'], order_info['cost'], context)
                if success:
                    referral_bonuses += 1
                    logger.info(f"💰 Реферальный бонус начислен для заказа {order_info['order_id']}")

            # 🔴🔴🔴 ОБНОВЛЯЕМ СТАТИСТИКУ ПРИШЕДШИХ ПОЛЬЗОВАТЕЛЕЙ 🔴🔴🔴
            try:
                conn_ref = sqlite3.connect('bot.db')
                cursor_ref = conn_ref.cursor()

                # Находим реферера пользователя
                cursor_ref.execute('SELECT referred_by FROM users WHERE user_id = ?', (order_info['user_id'],))
                referrer_result = cursor_ref.fetchone()

                if referrer_result and referrer_result[0]:
                    referrer_id = referrer_result[0]

                    # Обновляем статистику реферера - увеличиваем счетчик completed_referrals
                    cursor_ref.execute('''
                    UPDATE users
                    SET completed_referrals = completed_referrals + 1
                    WHERE user_id = ?
                    ''', (referrer_id,))

                    # Обновляем реферальную запись - отмечаем как активную
                    cursor_ref.execute('''
                    UPDATE referrals
                    SET is_active = 1,
                        completed_orders = completed_orders + 1
                    WHERE referred_id = ? AND referrer_id = ?
                    ''', (order_info['user_id'], referrer_id))

                    conn_ref.commit()
                    logger.info(f"📊 Обновлена статистика для реферера {referrer_id}")

                conn_ref.close()
            except Exception as e:
                logger.error(f"❌ Ошибка обновления статистики пришедших: {e}")

            # Уведомляем пользователя
            try:
                order_type_text = ""
                if order_info['is_balance_replenishment']:
                    order_type_text = f"пополнение баланса на {order_info['amount']}₽"
                    message_text = (
                        f"🎉 Ваш баланс пополнен!\n\n"
                        f"💰 Сумма: {order_info['amount']}₽\n"
                        f"💳 Новый баланс: {get_user_balance(order_info['user_id']):.2f}₽\n\n"
                        f"Спасибо за пополнение! ❤️"
                    )
                elif order_info['friend_username']:
                    if order_info['order_type'] == "stars":
                        order_type_text = f"{order_info['amount']} звёзд"
                    elif order_info['order_type'] == "ton":
                        order_type_text = f"{order_info['amount']} TON"
                    elif order_info['order_type'] == "premium":
                        order_type_text = f"Telegram Premium на {order_info['amount']}"

                    message_text = (
                        f"🎉 Ваш подарок подтвержден!\n\n"
                        f"🎁 Для: {order_info['friend_username']}\n"
                        f"📦 Подарок: {order_type_text}\n"
                        f"💰 Сумма: {order_info['cost']:.1f}₽\n\n"
                        f"Спасибо за покупку! ❤️"
                    )
                else:
                    if order_info['order_type'] == "stars":
                        order_type_text = f"{order_info['amount']} звёзд"
                    elif order_info['order_type'] == "ton":
                        order_type_text = f"{order_info['amount']} TON"
                    elif order_info['order_type'] == "premium":
                        order_type_text = f"Telegram Premium на {order_info['amount']}"

                    message_text = (
                        f"🎉 Ваш заказ подтвержден!\n\n"
                        f"📦 Вы получили: {order_type_text}\n"
                        f"💰 Сумма: {order_info['cost']:.1f}₽\n\n"
                        f"Спасибо за покупку! ❤️"
                    )

                await context.bot.send_message(order_info['user_id'], message_text)
                confirmed_count += 1

                logger.info(f"✅ Заказ #{order_info['order_id']} подтвержден, пользователь {order_info['user_id']} уведомлен")

            except Exception as e:
                logger.error(f"❌ Не удалось уведомить пользователя {order_info['user_id']}: {e}")
                failed_count += 1

        except Exception as e:
            logger.error(f"❌ Ошибка подтверждения заказа #{order_info['order_id']}: {e}")
            failed_count += 1

    # Формируем результат
    result_text = (
        f"✅ Подтверждение всех заказов завершено!\n\n"
        f"▪️ Успешно подтверждено: {confirmed_count}\n"
        f"▪️ Ошибок: {failed_count}\n"
        f"▪️ Начислено реферальных бонусов: {referral_bonuses}\n"
        f"▪️ Всего обработано: {len(pending_orders)}"
    )

    # Создаем клавиатуру для возврата
    keyboard = [
        [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
        [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
    ]

    await query.edit_message_text(
        result_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    # Логируем итоги
    logger.info(f"✅ Подтверждено {confirmed_count} заказов из {len(pending_orders)}, ошибок: {failed_count}, реферальных бонусов: {referral_bonuses}")

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int):
    query = update.callback_query
    await query.answer()

    logger.info(f"🎯 НАЧАЛО confirm_order для заказа #{order_id}")

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    try:
        # 🔴🔴🔴 ИСПРАВЛЕНИЕ: Правильное управление соединением с базой данных 🔴🔴🔴
        conn = sqlite3.connect('bot.db', timeout=30.0)  # Увеличиваем timeout
        conn.execute("PRAGMA busy_timeout = 30000")  # 30 секунд timeout
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM pending_orders WHERE order_id = ?', (order_id,))
        order = cursor.fetchone()

        if not order:
            await query.edit_message_text(f"❌ Заказ #{order_id} не найден")
            conn.close()
            return

        # Создаем словарь с информацией о заказе
        order_info = {
            'order_id': order[0],
            'user_id': order[1],
            'username': order[2],
            'full_name': order[3],
            'order_type': order[4],
            'amount': order[5],
            'cost': order[6],
            'friend_username': order[11],
            'is_balance_replenishment': order[12],
            'is_promo_creation': order[14] if len(order) > 14 else False
        }

        # 🔴🔴🔴 ЗАЩИТА ОТ ПОВТОРНОЙ АКТИВАЦИИ: проверяем статус заказа 🔴🔴🔴
        if order[8] == 'confirmed':  # order[8] - это статус заказа
            logger.warning(f"⚠️ Попытка повторной активации уже подтвержденного заказа #{order_id}")
            await query.edit_message_text(
                f"⚠️ Заказ #{order_id} уже был подтвержден ранее!\n\n"
                f"❌ Повторная активация невозможна.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
                    [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
                ])
            )
            conn.close()
            return

        # 🔴🔴🔴 ДОБАВЛЯЕМ ОБРАБОТКУ ПОПОЛНЕНИЯ БАЛАНСА 🔴🔴🔴
        if order_info['is_balance_replenishment']:
            # Это пополнение баланса
            logger.info(f"🎯 Подтверждение пополнения баланса для пользователя {order_info['user_id']} на {order_info['cost']}₽")

            # Обновляем статус заказа
            cursor.execute('UPDATE pending_orders SET status = ? WHERE order_id = ?', ('confirmed', order_id))

            # 🔴🔴🔴 ИСПРАВЛЕННЫЙ КОД: используем тот же подход что в confirm_all_orders
            # Получаем текущий баланс
            cursor.execute('SELECT balance FROM users WHERE user_id = ?', (order_info['user_id'],))
            current_balance_result = cursor.fetchone()
            current_balance = current_balance_result[0] if current_balance_result else 0.0

            # Пополняем баланс
            cursor.execute(
                'UPDATE users SET balance = balance + ? WHERE user_id = ?',
                (order_info['cost'], order_info['user_id'])
            )

            # Получаем новый баланс
            cursor.execute('SELECT balance FROM users WHERE user_id = ?', (order_info['user_id'],))
            new_balance_result = cursor.fetchone()
            new_balance = new_balance_result[0] if new_balance_result else 0.0

            conn.commit()
            conn.close()

            # Уведомляем пользователя
            try:
                await context.bot.send_message(
                    order_info['user_id'],
                    f"🎉 Ваш баланс пополнен!\n\n"
                    f"💰 Сумма: {order_info['cost']:.2f}₽\n"
                    f"💳 Баланс был: {current_balance:.2f}₽\n"
                    f"💳 Баланс стал: {new_balance:.2f}₽\n\n"
                    f"Спасибо за пополнение! ❤️",
                    reply_markup=get_main_menu_keyboard()
                )
            except Exception as e:
                logger.error(f"❌ Не удалось уведомить пользователя {order_info['user_id']}: {e}")

            # Обновляем сообщение админа
            await query.edit_message_text(
                f"✅ Пополнение баланса #{order_id} подтверждено!\n\n"
                f"👤 Пользователь: @{order_info['username']}\n"
                f"💰 Сумма: {order_info['cost']:.1f}₽\n"
                f"💳 Баланс был: {current_balance:.1f}₽\n"
                f"💳 Баланс стал: {new_balance:.1f}₽\n\n"
                f"✅ Средства зачислены на баланс",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
                    [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
                ])
            )

            # 🔴🔴🔴 ДОБАВЛЯЕМ РЕФЕРАЛЬНЫЙ БОНУС ЗА ПОПОЛНЕНИЕ БАЛАНСА 🔴🔴🔴
            if order_info.get('cost', 0) > 0:
                success = await process_referral_bonus(order_id, order_info['user_id'], order_info['cost'], context)
                if success:
                    logger.info(f"💰 Реферальный бонус начислен за пополнение баланса {order_id}")

            return

        # 🔴🔴🔴 ДОБАВЛЯЕМ ОБРАБОТКУ СОЗДАНИЯ ПРОМОКОДА 🔴🔴🔴
        if order_info['is_promo_creation']:
            # Это заказ на создание промокода
            logger.info(f"🎯 Подтверждение создания промокода для пользователя {order_info['user_id']}")

            # Обновляем статус заказа
            cursor.execute('UPDATE pending_orders SET status = ? WHERE order_id = ?', ('confirmed', order_id))
            conn.commit()
            conn.close()

            # Уведомляем пользователя
            try:
                await context.bot.send_message(
                    order_info['user_id'],
                    f"🎉 Ваш заказ на создание промокода подтвержден!\n\n"
                    f"💰 Сумма: {order_info['cost']:.2f}₽\n\n"
                    f"Теперь вы можете создать свой промокод в разделе 'Мои промокоды'",
                    reply_markup=get_main_menu_keyboard()
                )
            except Exception as e:
                logger.error(f"❌ Не удалось уведомить пользователя {order_info['user_id']}: {e}")

            # Обновляем сообщение админа
            await query.edit_message_text(
                f"✅ Заказ на создание промокода #{order_id} подтвержден!\n\n"
                f"👤 Пользователь: @{order_info['username']}\n"
                f"💰 Сумма: {order_info['cost']:.1f}₽\n\n"
                f"✅ Пользователь может создать промокод",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
                    [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
                ])
            )
            return

        # 🔴🔴🔴 ДОБАВЛЯЕМ ОБРАБОТКУ СОЗДАНИЯ ЧЕКОВ 🔴🔴🔴
        if order_info['order_type'].startswith('check_'):
            # Это создание чека (не активация!)
            logger.info(f"🎯 Подтверждение создания чека для пользователя {order_info['user_id']}")

            # Обновляем статус заказа
            cursor.execute('UPDATE pending_orders SET status = ? WHERE order_id = ?', ('confirmed', order_id))

            # Чек УЖЕ создан в базе при оформлении заказа, просто уведомляем пользователя
            check_type = order_info['order_type'].replace('check_', '')

            # Уведомляем пользователя о создании чека
            try:
                type_text = get_check_type_text(check_type)
                if check_type == "premium":
                    description = f"🌟 Telegram Premium на {order_info['amount']}"
                else:
                    unit = "звёзд" if check_type == "stars" else "TON"
                    description = f"{type_text} {order_info['amount']} {unit}"

                # Получаем код чека из friend_username (там сохраняется код при создании)
                check_code = order_info['friend_username']

                # Создаем красивый текст с эмодзи в зависимости от типа чека
                check_emoji = ""
                if check_type == "stars":
                    check_emoji = "⭐"
                elif check_type == "ton":
                    check_emoji = "💎"
                elif check_type == "premium":
                    check_emoji = "🌟"

                await context.bot.send_message(
                    order_info['user_id'],
                    f"🎉 {check_emoji} Чек полностью получен!\n\n"
                    f"📦 Тип чека: {description}\n"
                    f"🎫 Код чека: <code>{check_code}</code>\n\n"
                    f"🎁 Вы успешно получили заказ!",
                    parse_mode="HTML",
                    reply_markup=get_main_menu_keyboard()
                )
            except Exception as e:
                logger.error(f"❌ Не удалось уведомить пользователя {order_info['user_id']}: {e}")

            conn.commit()
            conn.close()

            # Обновляем сообщение админа
            await query.edit_message_text(
                f"✅ Создание чека #{order_id} подтверждено!\n\n"
                f"👤 Пользователь: @{order_info['username']}\n"
                f"📦 Тип чека: {check_type}\n"
                f"💰 Сумма: {order_info['cost']:.1f}₽\n\n"
                f"✅ Чек создан и готов к использованию",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
                    [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
                ])
            )
            return

        # 🔴🔴🔴 ИСПРАВЛЕННАЯ ОБРАБОТКА АКТИВАЦИИ ЧЕКОВ С ПОЛНОЙ ЗАЩИТОЙ 🔴🔴🔴
        elif order_info['order_type'].startswith('check_activation_'):
            # Это активация чека (когда кто-то получает чек)
            check_code = order_info['friend_username']
            logger.info(f"🎯 Активация чека {check_code} для пользователя {order_info['user_id']}")

            # 🔴🔴🔴 ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА: проверяем статус чека в базе 🔴🔴🔴
            check = get_check_by_code(check_code)
            if check and check.get('activated'):
                logger.warning(f"⚠️ Чек {check_code} уже был активирован ранее!")
                await query.edit_message_text(
                    f"⚠️ Чек {check_code} уже был активирован!\n\n"
                    f"❌ Повторная активация невозможна.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
                        [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
                    ])
                )
                conn.close()
                return

            # Обновляем статус заказа
            cursor.execute('UPDATE pending_orders SET status = ? WHERE order_id = ?', ('confirmed', order_id))

            # Активируем чек
            activate_check(check_code, order_info['user_id'])

            # Получаем информацию о чеке
            check = get_check_by_code(check_code)
            if check:
                # Начисляем товар пользователю
                if check['check_type'] == "stars":
                    update_user_purchase_stats(order_info['user_id'], "stars", check['amount'])
                    record_sale("stars", check['amount'], check['cost'])
                elif check['check_type'] == "ton":
                    update_user_purchase_stats(order_info['user_id'], "ton", check['amount'])
                    record_sale("ton", check['amount'], check['cost'])
                elif check['check_type'] == "premium":
                    update_user_purchase_stats(order_info['user_id'], "premium", 1)
                    record_sale("premium", 1, check['cost'])

            conn.commit()
            conn.close()

            # Уведомляем пользователя - ТОЛЬКО ФАКТ АКТИВАЦИИ
            try:
                if check['check_type'] == "premium":
                    description = f"Telegram Premium"
                    emoji = "🌟"
                elif check['check_type'] == "stars":
                    description = f"{check['amount']} звёзд"
                    emoji = "⭐"
                else:
                    description = f"{check['amount']} TON"
                    emoji = "💎"

                await context.bot.send_message(
                    order_info['user_id'],
                    f"🎉 Чек активирован! Вы получили {description} {emoji}",
                    reply_markup=get_main_menu_keyboard()
                )
            except Exception as e:
                logger.error(f"❌ Не удалось уведомить пользователя {order_info['user_id']}: {e}")

            # 🔴🔴🔴 ВАЖНОЕ ДОБАВЛЕНИЕ: НАЧИСЛЯЕМ РЕФЕРАЛЬНЫЙ БОНУС ПОСЛЕ АКТИВАЦИИ ЧЕКА 🔴🔴🔴
            if order_info.get('cost', 0) > 0:
                # Начисляем реферальный бонус (1% от суммы) с передачей context для уведомлений
                success = await process_referral_bonus(order_id, order_info['user_id'], order_info['cost'], context)
                if success:
                    logger.info(f"💰 Реферальный бонус начислен для активации чека {order_id}")

            # Обновляем сообщение админа
            await query.edit_message_text(
                f"✅ Активация чека #{order_id} подтверждена!\n\n"
                f"👤 Пользователь: @{order_info['username']}\n"
                f"🎫 Код чека: {check_code}\n"
                f"💰 Сумма: {order_info['cost']:.1f}₽\n\n"
                f"✅ Чек активирован, товар начислен",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
                    [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
                ])
            )
            return

        # 🔴🔴🔴 ПРОДОЛЖАЕМ СТАРУЮ ЛОГИКУ ДЛЯ ОБЫЧНЫХ ЗАКАЗОВ 🔴🔴🔴

        # Проверяем наличие is_balance_payment
        if len(order) > 13:
            order_info['is_balance_payment'] = order[13]
        else:
            order_info['is_balance_payment'] = False

        logger.info(f"🎯 Информация о заказе: {order_info}")

        # 🔴🔴🔴 ИСПРАВЛЕНИЕ: ПОЛУЧАЕМ БАЛАНС ЗАРАНЕЕ 🔴🔴🔴
        current_balance = get_user_balance(order_info['user_id'])
        new_balance = current_balance  # Изначально устанавливаем текущий баланс

        # ОБНОВЛЯЕМ СТАТУС ЗАКАЗА
        cursor.execute('UPDATE pending_orders SET status = ? WHERE order_id = ?', ('confirmed', order_id))
        conn.commit()
        conn.close()

        # 🔴🔴🔴 ОСНОВНАЯ ЛОГИКА: СПИСАНИЕ СРЕДСТВ И НАЧИСЛЕНИЕ ТОВАРА 🔴🔴🔴

        if order_info['is_balance_replenishment']:
            # ПОПОЛНЕНИЕ БАЛАНСА - НАЧИСЛЯЕМ СРЕДСТВА
            logger.info(f"🎯 Пополнение баланса для пользователя {order_info['user_id']} на {order_info['amount']}₽")
            new_balance = update_user_balance(order_info['user_id'], order_info['amount'])

            # УВЕДОМЛЯЕМ ПОЛЬЗОВАТЕЛЯ
            try:
                await context.bot.send_message(
                    order_info['user_id'],
                    f"🎉 Ваш баланс пополнен!\n\n"
                    f"💰 Сумма: {order_info['amount']}₽\n"
                    f"💳 Новый баланс: {new_balance:.2f}₽\n\n"
                    f"Спасибо за пополнение! ❤️",
                    reply_markup=get_main_menu_keyboard()
                )
                logger.info(f"🎯 Уведомление отправлено пользователю {order_info['user_id']}")
            except Exception as e:
                logger.error(f"❌ Не удалось уведомить пользователя {order_info['user_id']}: {e}")

            # 🔴🔴🔴 ДОБАВЛЯЕМ РЕФЕРАЛЬНЫЙ БОНУС ЗА ПОПОЛНЕНИЕ БАЛАНСА 🔴🔴🔴
            if order_info.get('cost', 0) > 0:
                success = await process_referral_bonus(order_id, order_info['user_id'], order_info['cost'], context)
                if success:
                    logger.info(f"💰 Реферальный бонус начислен за пополнение баланса {order_id}")

        else:
            # 🔴🔴🔴 ОБЫЧНЫЙ ЗАКАЗ - ВСЕГДА СПИСЫВАЕМ СРЕДСТВА С БАЛАНСА 🔴🔴🔴
            logger.info(f"🎯 Баланс пользователя {order_info['user_id']}: {current_balance}₽, стоимость заказа: {order_info['cost']}₽")

            # ВСЕГДА ПРОВЕРЯЕМ ДОСТАТОЧНОСТЬ СРЕДСТВ
            if current_balance >= order_info['cost']:
                # СПИСЫВАЕМ СРЕДСТВА С БАЛАНСА
                new_balance = update_user_balance(order_info['user_id'], -order_info['cost'])
                logger.info(f"🎯 Средства списаны, новый баланс: {new_balance}₽")

                # НАЧИСЛЯЕМ ТОВАР
                await process_order_delivery(context, order_info)

                # УВЕДОМЛЯЕМ ПОКУПАТЕЛЯ
                await send_success_notification(context, order_info)

                # 🔴🔴🔴 ВАЖНОЕ ИСПРАВЛЕНИЕ: ДОБАВЛЯЕМ РЕФЕРАЛЬНЫЙ БОНУС ДЛЯ ОБЫЧНЫХ ЗАКАЗОВ 🔴🔴🔴
                if order_info.get('cost', 0) > 0 and not order_info.get('is_balance_replenishment'):
                    # Начисляем реферальный бонус (5% от суммы) с передачей context для уведомлений
                    success = await process_referral_bonus(order_id, order_info['user_id'], order_info['cost'], context)
                    if success:
                        logger.info(f"💰 Реферальный бонус начислен для заказа {order_id}")
                    else:
                        logger.info(f"ℹ️ Реферальный бонус не начислен для заказа {order_id} (нет реферера)")

            else:
                # НЕДОСТАТОЧНО СРЕДСТВ
                logger.error(f"❌ Недостаточно средств: {current_balance}₽ < {order_info['cost']}₽")
                await context.bot.send_message(
                    order_info['user_id'],
                    f"❌ Недостаточно средств на балансе!\n\n"
                    f"💳 Ваш баланс: {current_balance:.2f}₽\n"
                    f"💰 Требовалось: {order_info['cost']:.2f}₽\n\n"
                    f"Пополните баланс и попробуйте снова."
                )

                # 🔴🔴🔴 ИСПРАВЛЕНИЕ: НОВОЕ СОЕДИНЕНИЕ ДЛЯ ОБНОВЛЕНИЯ СТАТУСА 🔴🔴🔴
                try:
                    conn_retry = sqlite3.connect('bot.db', timeout=30.0)
                    conn_retry.execute("PRAGMA busy_timeout = 30000")
                    cursor_retry = conn_retry.cursor()
                    cursor_retry.execute('UPDATE pending_orders SET status = ? WHERE order_id = ?', ('pending', order_id))
                    conn_retry.commit()
                    conn_retry.close()
                except Exception as db_error:
                    logger.error(f"❌ Ошибка при возврате заказа в ожидание: {db_error}")

                await query.edit_message_text(
                    f"❌ Заказ #{order_id} НЕ подтвержден!\n\n"
                    f"👤 Пользователь: @{order_info['username']}\n"
                    f"💰 Сумма: {order_info['cost']:.1f}₽\n"
                    f"💳 Баланс пользователя: {current_balance:.1f}₽\n\n"
                    f"❌ Недостаточно средств на балансе!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
                        [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
                    ])
                )
                return

        # 🔴🔴🔴 ИСПРАВЛЕНИЕ: ГАРАНТИРУЕМ ЧТО new_balance НЕ None 🔴🔴🔴
        if new_balance is None:
            new_balance = get_user_balance(order_info['user_id'])
            logger.warning(f"⚠️ new_balance был None, получен из базы: {new_balance}")

        # ОБНОВЛЯЕМ СООБЩЕНИЕ АДМИНА
        admin_message = (
            f"✅ Заказ #{order_id} подтвержден!\n\n"
            f"👤 Пользователь: @{order_info['username']}\n"
            f"💰 Сумма: {order_info['cost']:.1f}₽\n"
            f"📦 Тип: {order_info['order_type']}\n"
            f"💳 Списание с баланса: ✅\n"
            f"💳 Новый баланс: {new_balance:.1f}₽\n\n"
            f"✅ Покупатель уведомлен"
        )

        await query.edit_message_text(
            admin_message,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
                [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
            ])
        )

        logger.info(f"✅ Заказ #{order_id} успешно подтвержден и обработан")

    except sqlite3.OperationalError as db_error:
        logger.error(f"❌ Ошибка базы данных в confirm_order: {db_error}")
        await query.edit_message_text(
            f"❌ Ошибка базы данных при подтверждении заказа #{order_id}\n\n"
            f"Ошибка: {str(db_error)}\n\n"
            f"Попробуйте еще раз через несколько секунд.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
                [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
            ])
        )
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ Ошибка в confirm_order: {e}")
        logger.error(f"❌ Traceback: {traceback.format_exc()}")

        await query.edit_message_text(
            f"❌ Ошибка при подтверждении заказа #{order_id}\n\n"
            f"Ошибка: {str(e)}\n\n"
            f"Проверьте логи для деталей.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
                [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
            ])
        )

# НОВАЯ ФУНКЦИЯ - пополнение баланса пользователя админом
async def admin_add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс пополнения баланса пользователя админом"""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    keyboard = [
        [InlineKeyboardButton("❌ Отменить", callback_data="admin_stats")]
    ]

    await query.edit_message_text(
        "💰 Пополнение баланса пользователя\n\n"
        "🔍 Введите username или ID пользователя:\n\n"
        "❌ Для отмены нажмите кнопку ниже",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    awaiting_user_search[update.effective_user.id] = True

async def process_admin_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает поиск пользователя для пополнения баланса"""
    user_id = update.message.from_user.id

    if user_id not in awaiting_user_search or user_id != ADMIN_ID:
        return

    search_term = update.message.text.strip()
    user = find_user_by_username_or_id(search_term)

    if not user:
        await update.message.reply_text("❌ Пользователь не найден")
        del awaiting_user_search[user_id]
        return

    # Сохраняем найденного пользователя в context
    context.user_data['balance_user'] = user

    keyboard = [
        [InlineKeyboardButton("❌ Отменить", callback_data="admin_stats")]
    ]

    await update.message.reply_text(
        f"👤 Найден пользователь:\n"
        f"📛 Имя: {user['full_name'] or 'Не указано'}\n"
        f"🔗 Юзернейм: @{user['username'] or 'Не указан'}\n"
        f"🆔 ID: {user['user_id']}\n"
        f"💰 Текущий баланс: {user['balance']:.2f}₽\n\n"
        f"💵 Введите сумму для пополнения:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    del awaiting_user_search[user_id]
    awaiting_balance_amount[user_id] = True
    context.user_data['admin_balance'] = True

async def process_admin_balance_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод суммы для пополнения баланса админом"""
    user_id = update.message.from_user.id

    if user_id not in awaiting_balance_amount or user_id != ADMIN_ID:
        return

    try:
        amount = float(update.message.text.replace(',', '.'))

        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть больше 0")
            return

        target_user = context.user_data.get('balance_user')
        if not target_user:
            await update.message.reply_text("❌ Ошибка: пользователь не найден")
            return

        # Пополняем баланс
        update_user_balance(target_user['user_id'], amount)

        new_balance = get_user_balance(target_user['user_id'])

        await update.message.reply_text(
            f"✅ Баланс пользователя успешно пополнен!\n\n"
            f"👤 Пользователь: @{target_user['username']} (ID: {target_user['user_id']})\n"
            f"💰 Сумма: {amount:.2f}₽\n"
            f"💳 Новый баланс: {new_balance:.2f}₽",
            reply_markup=get_admin_keyboard()
        )

        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                target_user['user_id'],
                f"🎉 Ваш баланс пополнен администратором!\n\n"
                f"💰 Сумма: {amount:.2f}₽\n"
                f"💳 Новый баланс: {new_balance:.2f}₽"
            )
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить пользователя: {e}")

    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите корректную сумму")

    # Очищаем состояния
    if user_id in awaiting_balance_amount:
        del awaiting_balance_amount[user_id]
    if 'balance_user' in context.user_data:
        del context.user_data['balance_user']
    if 'admin_balance' in context.user_data:
        del context.user_data['admin_balance']

# НОВАЯ ФУНКЦИЯ - отображение списка пользователей
async def show_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE, page=0):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    users, total_users = get_all_users_paginated(page)

    if not users:
        await query.edit_message_text(
            "📭 В базе данных нет пользователей",
            reply_markup=get_admin_keyboard()
        )
        return

    users_text = f"👥 ВСЕ ПОЛЬЗОВАТЕЛИ (страница {page + 1})\n\n"
    users_text += f"📊 Всего пользователей: {total_users}\n\n"

    for i, user in enumerate(users, start=1):
        user_id, username, full_name, reg_date, last_activity, is_blocked, balance = user

        # Форматируем даты
        reg_date_formatted = reg_date[:16] if reg_date else "Неизвестно"
        last_activity_formatted = last_activity[:16] if last_activity else "Неактивен"

        # Статус блокировки
        status = "🚫 Заблокирован" if is_blocked else "✅ Активен"

        # Юзернейм
        username_display = f"@{username}" if username else "Без юзернейма"

        users_text += (
            f"{i + page * 10}. {username_display}\n"
            f"   📛 Имя: {full_name or 'Не указано'}\n"
            f"   🆔 ID: {user_id}\n"
            f"   💰 Баланс: {balance:.2f}₽\n"
            f"   📅 Регистрация: {reg_date_formatted}\n"
            f"   ⏰ Активность: {last_activity_formatted}\n"
            f"   📊 Статус: {status}\n"
            f"   ──────────────────\n"
        )

    # Создаем клавиатуру пагинации
    keyboard = []

    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"users_page_{page-1}"))

    nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{(total_users + 9) // 10}", callback_data="current_page"))

    if (page + 1) * 10 < total_users:
        nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"users_page_{page+1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    # Кнопки действий
    keyboard.extend([
        [InlineKeyboardButton("🔄 Обновить", callback_data=f"users_page_{page}")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 В админ-панель", callback_data="back_to_main")]
    ])

    await query.edit_message_text(
        users_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

# ИСПРАВЛЕННЫЕ ОБРАБОТЧИКИ - подтверждение/отклонение заказов с правильным уведомлением пользователя
async def publish_check_to_channel(context: ContextTypes.DEFAULT_TYPE, check_data: dict, photo_file_id: str = None):
    """Публикует чек в канал/группу с кнопкой 'Получить'"""
    try:
        # ID канала или группы куда публиковать чеки
        CHANNEL_ID = "@your_channel_username"  # Замените на ваш канал

        type_text = get_check_type_text(check_data['check_type'])

        # Определяем эмодзи и описание в зависимости от типа чека
        if check_data['check_type'] == "premium":
            description = f"🌟 Telegram Premium"
            emoji = "🌟"
            title = "🌟 ЧЕК НА PREMIUM"
        elif check_data['check_type'] == "stars":
            description = f"⭐ {check_data['amount']} звёзд"
            emoji = "⭐"
            title = "⭐ ЧЕК НА ЗВЁЗДЫ"
        else:  # ton
            description = f"💎 {check_data['amount']} TON"
            emoji = "💎"
            title = "💎 ЧЕК НА TON"

        caption = (
            f"{title}\n\n"
            f"📦 Содержимое: {description}\n"
            f"💰 Стоимость: {check_data['cost']:.2f}₽\n"
            f"🎫 Код: {check_data['check_code']}\n\n"
            f"👇 Нажмите кнопку ниже чтобы получить"
        )

        keyboard = [
            [InlineKeyboardButton(f"{emoji} ПОЛУЧИТЬ ЧЕК", callback_data=f"claim_check_{check_data['check_code']}")]
        ]

        # Если есть фото - отправляем с фото, иначе просто текст
        if photo_file_id:
            message = await context.bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photo_file_id,
                caption=caption,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            message = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=caption,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        # Обновляем message_id в базе данных
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE checks SET message_id = ? WHERE check_code = ?',
                      (message.message_id, check_data['check_code']))
        conn.commit()
        conn.close()

        logger.info(f"✅ Чек {check_data['check_code']} опубликован в канале")

    except Exception as e:
        logger.error(f"❌ Ошибка публикации чека в канале: {e}")

async def process_order_delivery(context: ContextTypes.DEFAULT_TYPE, order_info: dict):
    """Упрощенная версия начисления товара"""
    try:
        logger.info(f"🎯 Начисление товара: {order_info['order_type']} x {order_info['amount']} для пользователя {order_info['user_id']}")

        # ПРОСТО ЛОГИРУЕМ, ЧТОБЫ УБЕДИТЬСЯ ЧТО ФУНКЦИЯ ВЫЗЫВАЕТСЯ
        if order_info['order_type'] == 'stars':
            logger.info(f"⭐ Начисляем {order_info['amount']} звёзд пользователю {order_info['user_id']}")
        elif order_info['order_type'] == 'ton':
            logger.info(f"⚡ Начисляем {order_info['amount']} TON пользователю {order_info['user_id']}")
        elif order_info['order_type'] == 'premium':
            logger.info(f"👑 Активируем Premium пользователю {order_info['user_id']}")

    except Exception as e:
        logger.error(f"❌ Ошибка в process_order_delivery: {e}")

async def send_success_notification(context: ContextTypes.DEFAULT_TYPE, order_info: dict, new_balance: float = None):
    """Отправляет уведомление пользователю об успешной покупке - версия с 3 аргументами"""
    try:
        logger.info(f"🎯 Отправка уведомления пользователю {order_info['user_id']}")

        # Если баланс не передан, получаем текущий
        if new_balance is None:
            new_balance = get_user_balance(order_info['user_id'])

        # Определяем текст в зависимости от типа заказа
        order_type_text = {
            'stars': '⭐ Звёзды',
            'ton': '⚡ TON',
            'premium': '👑 Premium'
        }.get(order_info['order_type'], order_info['order_type'])

        if order_info.get('friend_username'):
            # УВЕДОМЛЕНИЕ ДЛЯ ПОДАРКА
            message_text = (
                f"🎉 Ваш подарок отправлен!\n\n"
                f"👤 Для: @{order_info['friend_username']}\n"
                f"🎁 Подарок: {order_type_text} - {order_info['amount']} шт\n"
                f"💰 Сумма: {order_info['cost']:.2f}₽\n"
                f"💳 Ваш баланс: {new_balance:.2f}₽\n\n"
                f"Спасибо за покупку! ❤️"
            )
        else:
            # УВЕДОМЛЕНИЕ ДЛЯ ОБЫЧНОЙ ПОКУПКИ
            message_text = (
                f"🎉 Покупка успешно завершена!\n\n"
                f"📦 Товар: {order_type_text} - {order_info['amount']} шт\n"
                f"💰 Сумма: {order_info['cost']:.2f}₽\n"
                f"💳 Ваш баланс: {new_balance:.2f}₽\n\n"
                f"Спасибо за покупку! ❤️"
            )

        await context.bot.send_message(
            order_info['user_id'],
            message_text,
            reply_markup=get_main_menu_keyboard()
        )

        logger.info(f"✅ Уведомление отправлено пользователю {order_info['user_id']}")

    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления пользователю {order_info['user_id']}: {e}")

def get_order_type_text(order_type: str) -> str:
    """Возвращает текстовое описание типа заказа"""
    type_map = {
        'stars': '⭐ Звёзды',
        'ton': '⚡ TON',
        'premium': '👑 Premium'
    }
    return type_map.get(order_type, order_type)

async def process_gift_delivery(context: ContextTypes.DEFAULT_TYPE, order_info: dict):
    """Обрабатывает доставку подарка"""
    try:
        # Здесь должна быть логика нахождения user_id друга по username
        # и начисления подарка
        friend_username = order_info['friend_username']
        logger.info(f"🎁 Подарок для @{friend_username}: {order_info['order_type']} x {order_info['amount']}")

        # TODO: Реализовать логику нахождения user_id по username и начисления подарка

    except Exception as e:
        logger.error(f"❌ Ошибка обработки подарка для {order_info['friend_username']}: {e}")

async def process_product_delivery(context: ContextTypes.DEFAULT_TYPE, order: dict):
    """Начисляет товар пользователю"""
    try:
        user_id = order['user_id']

        if order['order_type'] == 'stars':
            # Начисляем звезды
            current_stars = get_user_stars(user_id)
            update_user_stars(user_id, current_stars + order['amount'])

        elif order['order_type'] == 'ton':
            # Начисляем TON (здесь должна быть интеграция с кошельком)
            pass

        elif order['order_type'] == 'premium':
            # Активируем премиум
            activate_premium(user_id, order.get('period', '1month'))

    except Exception as e:
        logger.error(f"❌ Ошибка начисления товара пользователю {order['user_id']}: {e}")

async def process_gift_to_friend(context: ContextTypes.DEFAULT_TYPE, order: dict):
    """Направляет подарок другу"""
    try:
        friend_username = order['friend_username']
        # Здесь логика нахождения user_id друга по username и начисления подарка
        # ...

    except Exception as e:
        logger.error(f"❌ Ошибка отправки подарка другу {order['friend_username']}: {e}")

async def reject_order(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    # Получаем информацию о заказе
    order = get_pending_order(order_id)
    if not order:
        await query.edit_message_text("❌ Заказ не найден")
        return

    # Обновляем статус заказа
    update_order_status(order_id, "rejected")

    # Уведомляем пользователя
    try:
        await context.bot.send_message(
            order['user_id'],
            f"❌ Ваш заказ отклонен\n\n"
            f"💰 Сумма: {order['cost']:.1f}₽\n\n"
            f"📞 Свяжитесь с поддержкой для уточнения деталей: {SUPPORT_USERNAME}"
        )
        logger.info(f"✅ Пользователь {order['user_id']} уведомлен об отклонении заказа")
    except Exception as e:
        logger.error(f"❌ Не удалось уведомить пользователя {order['user_id']}: {e}")

    # Обновляем сообщение админа
    await query.edit_message_text(
        f"❌ Заказ #{order_id} отклонен!\n\n"
        f"👤 Пользователь: @{order['username']}\n"
        f"💰 Сумма: {order['cost']:.1f}₽",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
            [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
        ])
    )

    logger.info(f"❌ Заказ #{order_id} отклонен админом")

async def admin_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной перезапуск бота через админ-панель"""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
    await query.edit_message_text(
        f"🔄 Перезапуск бота выполнен (МСК: {moscow_time})\n"
        f"✅ Бот продолжает работу",
        reply_markup=get_admin_keyboard()
    )
    logger.info("✅ Ручной перезапуск бота выполнен")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной запрос расширенной статистики"""
    logger.info(f"🔹🔹🔹 ОТЛАДКА: Вызвана команда /stats от пользователя {update.effective_user.id}")

    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return

    try:
        # Получаем статистику за разные периоды
        hourly_stats = get_hourly_sales_stats()
        daily_stats = get_daily_sales_stats()
        total_stats = get_total_sales_stats()

        # ИСПРАВЛЕНИЕ: используем get_system_stats вместо get_user_stats
        user_stats = get_system_stats()

        total_users, active_today, blocked_users, total_stars, total_premium, total_ton = user_stats

        moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

        # Рассчитываем средние значения
        hourly_avg_revenue = hourly_stats['revenue']
        daily_avg_revenue = daily_stats['revenue'] / 24 if daily_stats['revenue'] > 0 else 0

        # Рассчитываем конверсию (активные пользователи за сегодня / всего пользователей)
        conversion_rate = (active_today / total_users * 100) if total_users > 0 else 0

        # Формируем сообщение со статистикой
        stats_message = (
            f"📊 РАСШИРЕННАЯ СТАТИСТИКА (МСК: {moscow_time})\n\n"

            f"⏰ ЗА ПОСЛЕДНИЙ ЧАС:\n"
            f"⭐ Звёзд продано: {hourly_stats['stars']} шт\n"
            f"🌟 Premium продано: {hourly_stats['premium']} шт\n"
            f"💎 TON продано: {hourly_stats['ton']:.2f} TON\n"
            f"💰 Выручка: {hourly_stats['revenue']:.2f}₽\n"
            f"📈 Средняя выручка в час: {hourly_avg_revenue:.2f}₽\n\n"

            f"📅 ЗА ПОСЛЕДНИЕ 24 ЧАСА:\n"
            f"⭐ Звёзд продано: {daily_stats['stars']} шт\n"
            f"🌟 Premium продано: {daily_stats['premium']} шт\n"
            f"💎 TON продано: {daily_stats['ton']:.2f} TON\n"
            f"💰 Выручка: {daily_stats['revenue']:.2f}₽\n"
            f"📈 Средняя выручка в час: {daily_avg_revenue:.2f}₽\n\n"

            f"📊 ОБЩАЯ СТАТИСТИКА:\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"🟢 Активных за сегодня: {active_today}\n"
            f"📊 Конверсия: {conversion_rate:.1f}%\n"
            f"🚫 Заблокировали бота: {blocked_users}\n"
            f"⭐ Всего звёзд продано: {total_stats['stars']} шт\n"
            f"🌟 Всего Premium продано: {total_stats['premium']} шт\n"
            f"💎 Всего TON продано: {total_stats['ton']:.2f} TON\n"
            f"💰 Общая выручка: {total_stats['revenue']:.2f}₽\n\n"

            f"🔄 Бот работает стабильно"
        )

        # Отправляем статистику в текущий чат (где была введена команда)
        await update.message.reply_text(stats_message)
        logger.info("✅ Расширенная статистика отправлена админу")

    except Exception as e:
        logger.error(f"❌ Ошибка отправки расширенной статистики: {e}")
        # Отправляем упрощенную статистику в случае ошибки
        try:
            # ИСПРАВЛЕНИЕ: также используем get_system_stats здесь
            total_users, active_today, blocked_users, total_stars, total_premium, total_ton = get_system_stats()
            daily_stats = get_daily_sales_stats()

            await update.message.reply_text(
                f"📊 УПРОЩЕННАЯ СТАТИСТИКА (МСК: {get_moscow_time().strftime('%Y-%m-%d %H:%M:%S')})\n"
                f"👥 Пользователей: {total_users}\n"
                f"🟢 Активных за сегодня: {active_today}\n"
                f"🚫 Заблокировано: {blocked_users}\n"
                f"💰 Выручка за 24ч: {daily_stats['revenue']:.2f}₽\n"
                f"❌ Ошибка детальной статистики: {e}"
            )
        except Exception as inner_e:
            logger.error(f"❌ Ошибка отправки упрощенной статистики: {inner_e}")
            await update.message.reply_text(f"❌ Критическая ошибка получения статистики: {inner_e}")

async def show_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Получаем расширенную статистику
    hourly_stats = get_hourly_sales_stats()
    daily_stats = get_daily_sales_stats()
    total_stats = get_total_sales_stats()

    # ИСПРАВЛЕНИЕ: используем get_system_stats вместо get_user_stats
    user_stats = get_system_stats()

    total_users, active_today, blocked_users, total_stars, total_premium, total_ton = user_stats

    moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

    # Рассчитываем конверсию
    conversion_rate = (active_today / total_users * 100) if total_users > 0 else 0

    stats_text = (
        f"📊 РАСШИРЕННАЯ СТАТИСТИКА (МСК: {moscow_time})\n\n"

        f"⏰ ЗА ПОСЛЕДНИЙ ЧАС:\n"
        f"⭐ Звёзд продано: {hourly_stats['stars']} шт\n"
        f"🌟 Premium продано: {hourly_stats['premium']} шт\n"
        f"💎 TON продано: {hourly_stats['ton']:.2f} TON\n"
        f"💰 Выручка: {hourly_stats['revenue']:.2f}₽\n\n"

        f"📅 ЗА ПОСЛЕДНИЕ 24 ЧАСА:\n"
        f"⭐ Звёзд продано: {daily_stats['stars']} шт\n"
        f"🌟 Premium продано: {daily_stats['premium']} шт\n"
        f"💎 TON продано: {daily_stats['ton']:.2f} TON\n"
        f"💰 Выручка: {daily_stats['revenue']:.2f}₽\n\n"

        f"📊 ОБЩАЯ СТАТИСТИКА:\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🟢 Активных за сегодня: {active_today}\n"
        f"📊 Конверсия: {conversion_rate:.1f}%\n"
        f"🚫 Заблокировали бота: {blocked_users}\n"
        f"⭐ Всего звёзд продано: {total_stats['stars']} шт\n"
        f"🌟 Всего Premium продано: {total_stats['premium']} шт\n"
        f"💎 Всего TON продано: {total_stats['ton']:.2f} TON\n"
        f"💰 Общая выручка: {total_stats['revenue']:.2f}₽"
    )

    # ДОБАВЛЯЕМ КНОПКИ "СДЕЛАТЬ МЕНЬШЕ" и "ПРИБАВИТЬ ВЫРУЧКУ"
    keyboard = [
        [InlineKeyboardButton("📉 Уменьшить выручку", callback_data="decrease_revenue"),
         InlineKeyboardButton("📈 Увеличить выручку", callback_data="increase_revenue")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
    ]

    await query.edit_message_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def check_bot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка работы бота"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return

    moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
    await update.message.reply_text(
        f"🤖 Проверка бота (МСК: {moscow_time})\n"
        f"✅ Бот работает нормально\n"
        f"📊 Используйте /stats для получения статистики\n"
        f"👨‍💻 Используйте /admin для админ-панели"
    )

# ПРОСТАЯ И РАБОЧАЯ РАССЫЛКА С КНОПКОЙ ВЫХОДА
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    keyboard = [
        [InlineKeyboardButton("❌ Отменить рассылку", callback_data="cancel_broadcast")]
    ]

    await query.edit_message_text(
        "📢 Введите сообщение для рассылки:\n\n"
        "❌ Для отмены нажмите кнопку ниже",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['broadcast'] = True
    # ИНИЦИАЛИЗИРУЕМ флаг активной рассылки
    context.user_data['broadcast_active'] = True
    logger.info("✅ Режим рассылки активирован")

# НОВАЯ ФУНКЦИЯ - отмена рассылки
async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    # Очищаем состояние рассылки
    context.user_data['broadcast'] = False
    context.user_data['broadcast_active'] = False

    await query.edit_message_text(
        "❌ Рассылка отменена",
        reply_markup=get_admin_keyboard()
    )
    logger.info("✅ Рассылка отменена админом")

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, не отменили ли рассылку И не является ли это командой
    if (not context.user_data.get('broadcast') or
        (update.message.text and update.message.text.startswith('/'))):
        await update.message.reply_text(
            "ℹ️ Рассылка была отменена",
            reply_markup=get_admin_keyboard()
        )
        return

    if context.user_data.get('broadcast') and update.message.from_user.id == ADMIN_ID:
        message_text = update.message.text
        users = get_all_users()

        # УБЕДИТЕЛЬНО очищаем состояние рассылки
        context.user_data['broadcast'] = False

        # УБЕДИТЕЛЬНО устанавливаем флаг активной рассылки
        context.user_data['broadcast_active'] = True
        logger.info(f"🚀 Начинаем рассылку для {len(users)} пользователей")

        # Создаем сообщение с кнопкой отмены
        keyboard = [
            [InlineKeyboardButton("⏹️ Остановить рассылку", callback_data="stop_broadcast")]
        ]

        progress = await update.message.reply_text(
            f"🔄 Рассылаю {len(users)} пользователям...\nОтправлено: 0/{len(users)}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        sent = 0
        failed = 0

        # Добавляем возможность остановки во время рассылки
        for user in users:
            # Проверяем, не была ли рассылка остановлена
            if not context.user_data.get('broadcast_active', True):
                logger.info("⏹️ Рассылка остановлена пользователем")
                break

            try:
                await context.bot.send_message(user, message_text)
                sent += 1

                # Обновляем прогресс каждые 10 сообщений
                if sent % 10 == 0:
                    try:
                        await progress.edit_text(
                            f"🔄 Рассылаю...\nОтправлено: {sent}/{len(users)}",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    except Exception as e:
                        logger.error(f"Ошибка обновления прогресса: {e}")

            except Exception as e:
                failed += 1
                logger.error(f"Ошибка отправки пользователю {user}: {e}")

        # Очищаем флаг активной рассылки ПОСЛЕ завершения
        context.user_data['broadcast_active'] = False
        logger.info(f"✅ Рассылка завершена. Успешно: {sent}, Ошибок: {failed}")

        await progress.edit_text(
            f"✅ Рассылка завершена!\n\n"
            f"▪️ Всего пользователей: {len(users)}\n"
            f"▪️ Успешно: {sent}\n"
            f"▪️ Не удалось: {failed}",
            reply_markup=get_admin_keyboard()
        )

# НОВАЯ ФУНКЦИЯ - остановка рассылки во время выполнения
async def stop_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    # Устанавливаем флаг остановки
    context.user_data['broadcast_active'] = False
    context.user_data['broadcast'] = False

    await query.edit_message_text(
        "⏹️ Рассылка остановлена!",
        reply_markup=get_admin_keyboard()
    )
    logger.info("✅ Рассылка остановлена админом во время выполнения")

# ИСПРАВЛЕННАЯ ФУНКЦИЯ - отмена оплаты (убрана кнопка, оставлено только текстовое сообщение)
async def cancel_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовой команды отмены"""
    user_id = update.message.from_user.id
    logger.info(f"🔹🔹🔹 ОТЛАДКА: Получена текстовая команда отмены от {user_id}")

    # Очищаем все состояния пользователя
    if user_id in awaiting_receipts:
        del awaiting_receipts[user_id]
        logger.info(f"✅ awaiting_receipts удален для {user_id}")

    if user_id in awaiting_friend_username:
        del awaiting_friend_username[user_id]
        logger.info(f"✅ awaiting_friend_username удален для {user_id}")

    if user_id in pending_payments:
        del pending_payments[user_id]
        logger.info(f"✅ pending_payments удален для {user_id}")

    # Очищаем временные данные о подарках
    delete_temp_gift(user_id)
    logger.info(f"✅ Временные подарки удалены для {user_id}")

    # Очищаем user_data
    if 'current_gift' in context.user_data:
        del context.user_data['current_gift']
    if f'gift_{user_id}' in context.user_data:
        del context.user_data[f'gift_{user_id}']

    await update.message.reply_text(
        "✅ Оплата отменена. Выберите действие:",
        reply_markup=get_main_menu_keyboard()
    )
    logger.info(f"✅ Оплата отменена для пользователя {user_id}")

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ К сожалению я не смог распознать Вашу команду. Воспользуйтесь кнопками в меню или отправьте /start",
        reply_markup=get_main_menu_keyboard()
    )

# НОВЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С ПРОМОКОДАМИ
async def show_promocodes_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню управления промокодами для админа"""
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ Доступ запрещен")
        return

    # Получаем статистику промокодов
    promos = get_all_promo_codes()
    active_promos = [p for p in promos if p.get('is_active', True)]
    total_uses = sum(p.get('used_count', 0) for p in promos)

    text = (
        "🎫 Управление промокодами\n\n"
        f"📊 Статистика:\n"
        f"• Всего промокодов: {len(promos)}\n"
        f"• Активных: {len(active_promos)}\n"
        f"• Использовано раз: {total_uses}\n\n"
        "Выберите действие:"
    )

    keyboard = [
        [InlineKeyboardButton("📋 Список промокодов", callback_data="list_promos")],
        [InlineKeyboardButton("➕ Создать промокод", callback_data="create_promo")],
        [InlineKeyboardButton("🔙 Назад в админ-панель", callback_data="admin_back")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def create_promo_code_detailed(update: Update, context: ContextTypes.DEFAULT_TYPE, promo_type: str):
    """Создание промокода с детальными настройками"""
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    # Сохраняем тип промокода
    context.user_data['promo_type'] = promo_type
    context.user_data['awaiting_promo'] = True

    type_names = {
        'stars': 'звёзд',
        'ton': 'TON',
        'premium': 'Premium',
        'gift': 'подарков'
    }

    await query.edit_message_text(
        f"🎫 Создание промокода для {type_names.get(promo_type, promo_type)}\n\n"
        "Введите данные промокода в формате:\n"
        "`НАЗВАНИЕ ПРОМОКОДА|ПРОЦЕНТ СКИДКИ|МАКСИМАЛЬНОЕ КОЛИЧЕСТВО ИСПОЛЬЗОВАНИЙ`\n\n"
        "Пример:\n"
        "`SUMMER25|25|100` - промокод SUMMER25 даёт 25% скидку, можно использовать 100 раз\n\n"
        "❌ Для отмены отправьте 'отмена'",
        parse_mode="Markdown"
    )

async def process_promo_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает создание промокода"""
    if not context.user_data.get('awaiting_promo'):
        return

    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return

    try:
        parts = update.message.text.split()
        if len(parts) < 6:
            await update.message.reply_text("❌ Недостаточно параметров. Используйте формат: КОД ПРОЦЕНТ СУММА МИНИМУМ ЛИМИТ [ДАТА] [ПОДАРОК] [ТИП]")
            return

        code = parts[0].upper()
        discount_percent = float(parts[1])
        discount_amount = float(parts[2])
        min_amount = float(parts[3])
        max_uses = int(parts[4])
        valid_until = parts[5] if len(parts) > 5 else None
        gift_amount = float(parts[6]) if len(parts) > 6 else 0
        gift_type = parts[7] if len(parts) > 7 else 'balance'

        if create_promo_code(code, discount_percent, discount_amount, min_amount, max_uses, valid_until, ADMIN_ID, gift_amount, gift_type):
            await update.message.reply_text(
                f"✅ Промокод создан!\n\n"
                f"🎫 Код: <code>{code}</code>\n"
                f"📊 Скидка: {discount_percent}% + {discount_amount}₽\n"
                f"💰 Мин. сумма: {min_amount}₽\n"
                f"🔢 Лимит: {max_uses} использований\n"
                f"📅 Действует до: {valid_until or 'не ограничено'}\n"
                f"🎁 Подарок: {gift_amount} {gift_type}",
                parse_mode="HTML",
                reply_markup=get_admin_keyboard()
            )
        else:
            await update.message.reply_text("❌ Промокод с таким кодом уже существует")

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка создания промокода: {e}")

    context.user_data['awaiting_promo'] = False

async def apply_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Применение промокода"""
    user_id = update.message.from_user.id
    promo_code = update.message.text.strip().upper()

    # Проверяем промокод в базе
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM promocodes WHERE code = ? AND (expires_at IS NULL OR expires_at > datetime("now")) AND uses_left > 0',
        (promo_code,)
    )
    promo = cursor.fetchone()

    if not promo:
        await update.message.reply_text(
            "❌ Промокод не найден, истек или достиг лимита использований",
            reply_markup=get_main_menu_keyboard()
        )
        return

    promo_info = {
        'id': promo[0],
        'code': promo[1],
        'discount_percent': promo[2],
        'max_uses': promo[3],
        'uses_left': promo[4],
        'promo_type': promo[5],
        'created_at': promo[6],
        'expires_at': promo[7]
    }

    # Проверяем тип промокода
    order_type = context.user_data.get('applying_promo_for', 'stars')
    if promo_info['promo_type'] != 'all' and promo_info['promo_type'] != order_type:
        await update.message.reply_text(
            f"❌ Этот промокод предназначен для {promo_info['promo_type']}, а вы покупаете {order_type}",
            reply_markup=get_main_menu_keyboard()
        )
        return

    # Сохраняем примененный промокод
    applied_promocodes[user_id] = promo_info['code']

    await update.message.reply_text(
        f"✅ Промокод применен!\n\n"
        f"🎫 Код: {promo_info['code']}\n"
        f"📊 Скидка: {promo_info['discount_percent']}%\n"
        f"🔄 Осталось использований: {promo_info['uses_left']}\n\n"
        f"Скидка будет применена при оформлении заказа.",
        reply_markup=get_main_menu_keyboard()
    )

    # Очищаем состояние
    context.user_data['awaiting_promo_input'] = False
    context.user_data['applying_promo_for'] = None

async def cancel_promo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очищает состояния ввода промокода"""
    user_id = update.message.from_user.id

    # Сохраняем тип товара для логирования
    product_type = context.user_data.get('promo_product_type')

    # Очищаем глобальные состояния
    if user_id in awaiting_promo_code:
        del awaiting_promo_code[user_id]

    # Очищаем user_data
    for key in ['applying_promo_for', 'awaiting_promo_input', 'promo_product_type']:
        if key in context.user_data:
            del context.user_data[key]

    logger.info(f"🎫 Отмена ввода промокода для {user_id}, тип был: {product_type}")

    await update.message.reply_text(
        "✅ Ввод промокода отменен",
        reply_markup=get_main_menu_keyboard()
    )

async def show_correct_menu_after_promo(update: Update, context: ContextTypes.DEFAULT_TYPE, product_type: str, promo_code: str):
    """Показывает правильное меню после применения промокода"""

    promo = get_promo_code(promo_code)
    discount_text = f" (скидка {promo['discount_percent']}%)" if promo and promo['discount_percent'] > 0 else ""

    logger.info(f"🎫 Показ меню для типа: {product_type} с промокодом: {promo_code}")

    # Очищаем состояния ввода перед показом меню
    context.user_data.pop('awaiting_promo_input', None)

    try:
        if product_type == "stars":
            await show_star_packages_with_discount(update, context, promo_code)
        elif product_type == "ton":
            await show_ton_options_with_discount(update, context, promo_code)
        elif product_type == "premium":
            await show_premium_options_with_discount(update, context, promo_code)
        elif product_type == "gift":
            await show_gift_options_with_discount(update, context, promo_code)
        elif product_type == "gift_stars":
            await show_gift_star_packages_with_discount(update, context, promo_code)
        elif product_type == "gift_ton":
            await show_gift_ton_packages_with_discount(update, context, promo_code)
        elif product_type == "gift_premium":
            await show_gift_premium_options_with_discount(update, context, promo_code)
        else:
            # Если неизвестный тип, показываем главное меню
            await update.message.reply_text(
                f"✅ Промокод {promo_code} применен{discount_text}\n\n"
                f"Тип товара: {get_promo_type_name(product_type)}",
                reply_markup=get_main_menu_keyboard()
            )
    except Exception as e:
        logger.error(f"❌ Ошибка при показе меню после промокода: {e}")
        await update.message.reply_text(
            f"✅ Промокод {promo_code} применен{discount_text}\n\n"
            "Возврат в главное меню...",
            reply_markup=get_main_menu_keyboard()
        )

def get_promo_type_name(order_type: str) -> str:
    """Возвращает читаемое название типа товара для промокода"""
    type_names = {
        'stars': '⭐ звёзд',
        'ton': '💎 TON',
        'premium': '🌟 Premium',
        'gift': '🎁 подарков',
        'gift_stars': '⭐ звёзд в подарок',
        'gift_ton': '💎 TON в подарок',
        'gift_premium': '🌟 Premium в подарок',
        'balance': '💰 пополнения баланса',
        'all': '🎫 всех товаров'
    }
    return type_names.get(order_type, order_type)

async def universal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Универсальная функция отмены для всех состояний"""
    user_id = update.message.from_user.id

    logger.info(f"🔹 Универсальная отмена для {user_id}")

    # Очищаем ВСЕ состояния
    states_cleared = []

    # 1. Очищаем промокоды
    if user_id in awaiting_promo_code:
        del awaiting_promo_code[user_id]
        states_cleared.append("промокод")

    # 2. Очищаем чеки
    if user_id in awaiting_receipts:
        del awaiting_receipts[user_id]
        states_cleared.append("чек")

    # 3. Очищаем юзернеймы для подарков
    if user_id in awaiting_friend_username:
        del awaiting_friend_username[user_id]
        states_cleared.append("подарок")

    # 4. Очищаем ввод количеств
    if user_id in awaiting_custom_stars:
        del awaiting_custom_stars[user_id]
        states_cleared.append("звёзды")

    if user_id in awaiting_custom_ton:
        del awaiting_custom_ton[user_id]
        states_cleared.append("TON")

    # 5. Очищаем конвертацию
    if user_id in conversion_data:
        del conversion_data[user_id]
        states_cleared.append("конвертацию")

    # 6. Очищаем баланс
    if user_id in awaiting_balance_amount:
        del awaiting_balance_amount[user_id]
        states_cleared.append("баланс")

    if user_id in awaiting_user_search:
        del awaiting_user_search[user_id]
        states_cleared.append("поиск пользователя")

    # 7. Очищаем user_data
    user_data_cleared = []
    keys_to_clear = ['applying_promo_for', 'awaiting_promo_input', 'promo_product_type',
                    'admin_balance', 'balance_user', 'current_gift', 'is_gift',
                    'promo_creation', 'broadcast']

    for key in keys_to_clear:
        if key in context.user_data:
            del context.user_data[key]
            user_data_cleared.append(key)

    # 8. Очищаем временные подарки
    delete_temp_gift(user_id)

    logger.info(f"✅ Очищены состояния: {states_cleared}")

    await update.message.reply_text(
        "✅ Все операции отменены. Возврат в главное меню.",
        reply_markup=get_main_menu_keyboard()
    )

async def show_gift_options_with_discount(update: Update, context: ContextTypes.DEFAULT_TYPE, promo_code: str):
    """Показывает меню подарков с примененным промокодом"""
    user_id = update.message.from_user.id

    # Сохраняем примененный промокод для подарков
    applied_promocodes[user_id] = promo_code

    keyboard = [
        [InlineKeyboardButton("⭐ Подарить звёзды", callback_data="gift_stars")],
        [InlineKeyboardButton("💎 Подарить TON", callback_data="gift_ton")],
        [InlineKeyboardButton("🌟 Подарить Premium", callback_data="gift_premium")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
    ]

    promo_info = ""
    promo = get_promo_code(promo_code)
    if promo and promo['discount_percent'] > 0:
        promo_info = f"\n🎫 Применен промокод {promo_code} - скидка {promo['discount_percent']}%"
    elif promo and promo['discount_amount'] > 0:
        promo_info = f"\n🎫 Применен промокод {promo_code} - скидка {promo['discount_amount']}₽"

    await update.message.reply_text(
        f"🎁 Выберите что хотите подарить другу:{promo_info}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_star_packages_with_discount(update: Update, context: ContextTypes.DEFAULT_TYPE, promo_code: str):
    """Показывает пакеты звезд со скидкой"""
    user_id = update.message.from_user.id

    # Сохраняем примененный промокод
    applied_promocodes[user_id] = promo_code

    star_options = [50, 75, 100, 150, 200, 250, 300, 350, 400, 450,
                   500, 550, 600, 650, 700, 800, 900, 1000, 1500, 2000, 3000, 5000, 10000]

    keyboard = []
    for i in range(0, len(star_options), 2):
        row = []
        if i < len(star_options):
            stars = star_options[i]
            original_cost = stars * STAR_PRICE
            final_cost, discount, message = calculate_discount(original_cost, promo_code, user_id)

            if discount > 0:
                price_text = f"{final_cost:.1f}₽ (-{discount:.1f}₽)"
            else:
                price_text = f"{final_cost:.1f}₽"

            price_text = price_text.replace(".0₽", "₽")
            row.append(InlineKeyboardButton(f"{stars} звёзд - {price_text}", callback_data=f"stars_{stars}"))

        if i+1 < len(star_options):
            stars = star_options[i+1]
            original_cost = stars * STAR_PRICE
            final_cost, discount, message = calculate_discount(original_cost, promo_code, user_id)

            if discount > 0:
                price_text = f"{final_cost:.1f}₽ (-{discount:.1f}₽)"
            else:
                price_text = f"{final_cost:.1f}₽"

            price_text = price_text.replace(".0₽", "₽")
            row.append(InlineKeyboardButton(f"{stars} звёзд - {price_text}", callback_data=f"stars_{stars}"))

        if row:
            keyboard.append(row)

    keyboard.append([InlineKeyboardButton("✨ Другое количество", callback_data="custom_stars")])

    promo_info = ""
    promo = get_promo_code(promo_code)
    if promo and promo['discount_percent'] > 0:
        promo_info = f"🎫 Применен промокод {promo_code} - скидка {promo['discount_percent']}%"
    elif promo and promo['discount_amount'] > 0:
        promo_info = f"🎫 Применен промокод {promo_code} - скидка {promo['discount_amount']}₽"

    await update.message.reply_text(
        f"⭐ Выберите количество звёзд:\n"
        f"💰 Цена за 1 звезду: {STAR_PRICE}₽\n\n"
        f"{promo_info}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_gift_star_packages_with_discount(update: Update, context: ContextTypes.DEFAULT_TYPE, promo_code: str):
    """Показывает пакеты звезд для подарка со скидкой"""
    user_id = update.message.from_user.id

    # Сохраняем примененный промокод
    applied_promocodes[user_id] = promo_code

    star_options = [50, 75, 100, 150, 200, 250, 300, 350, 400, 450,
                   500, 550, 600, 650, 700, 800, 900, 1000, 1500, 2000, 3000, 5000, 10000]

    keyboard = []
    for i in range(0, len(star_options), 2):
        row = []
        if i < len(star_options):
            stars = star_options[i]
            original_cost = stars * STAR_PRICE
            final_cost, discount, message = calculate_discount(original_cost, promo_code, user_id)

            if discount > 0:
                price_text = f"{final_cost:.1f}₽ (-{discount:.1f}₽)"
            else:
                price_text = f"{final_cost:.1f}₽"

            price_text = price_text.replace(".0₽", "₽")
            row.append(InlineKeyboardButton(f"{stars} звёзд - {price_text}", callback_data=f"gift_stars_{stars}"))

        if i+1 < len(star_options):
            stars = star_options[i+1]
            original_cost = stars * STAR_PRICE
            final_cost, discount, message = calculate_discount(original_cost, promo_code, user_id)

            if discount > 0:
                price_text = f"{final_cost:.1f}₽ (-{discount:.1f}₽)"
            else:
                price_text = f"{final_cost:.1f}₽"

            price_text = price_text.replace(".0₽", "₽")
            row.append(InlineKeyboardButton(f"{stars} звёзд - {price_text}", callback_data=f"gift_stars_{stars}"))

        if row:
            keyboard.append(row)

    keyboard.append([InlineKeyboardButton("✨ Другое количество", callback_data="gift_custom_stars")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="gift_back")])

    promo_info = ""
    promo = get_promo_code(promo_code)
    if promo and promo['discount_percent'] > 0:
        promo_info = f"🎫 Применен промокод {promo_code} - скидка {promo['discount_percent']}%"
    elif promo and promo['discount_amount'] > 0:
        promo_info = f"🎫 Применен промокод {promo_code} - скидка {promo['discount_amount']}₽"

    await update.message.reply_text(
        f"⭐ Выберите количество звёзд для подарка:\n"
        f"💰 Цена за 1 звезду: {STAR_PRICE}₽\n\n"
        f"{promo_info}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_ton_options_with_discount(update: Update, context: ContextTypes.DEFAULT_TYPE, promo_code: str):
    """Показывает варианты покупки TON с примененным промокодом"""
    user_id = update.effective_user.id
    promo = get_promo_code(promo_code)

    if not promo:
        await show_ton_options(update, context)
        return

    discount_percent = promo['discount_percent']

    text = (
        f"💎 <b>Покупка TON</b>\n\n"
        f"🎫 Применен промокод: <code>{promo_code}</code>\n"
        f"📉 Скидка: {discount_percent}%\n\n"
        "👇 Выберите количество TON:"
    )

    keyboard = [
        [InlineKeyboardButton(f"1 TON ({(1 * (1 - discount_percent/100)):.2f} TON после скидки)", callback_data=f"ton_1")],
        [InlineKeyboardButton(f"5 TON ({(5 * (1 - discount_percent/100)):.2f} TON после скидки)", callback_data=f"ton_5")],
        [InlineKeyboardButton(f"10 TON ({(10 * (1 - discount_percent/100)):.2f} TON после скидки)", callback_data=f"ton_10")],
        [InlineKeyboardButton("🎫 Ввести другой промокод", callback_data="enter_promo_ton")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_premium_options_with_discount(update: Update, context: ContextTypes.DEFAULT_TYPE, promo_code: str):
    """Показывает варианты Premium с примененным промокодом"""
    user_id = update.effective_user.id
    promo = get_promo_code(promo_code)

    if not promo:
        await show_premium_options(update, context)
        return

    discount_percent = promo['discount_percent']

    text = (
        f"🌟 <b>Telegram Premium</b>\n\n"
        f"🎫 Применен промокод: <code>{promo_code}</code>\n"
        f"📉 Скидка: {discount_percent}%\n\n"
        "👇 Выберите период:"
    )

    keyboard = [
        [InlineKeyboardButton("1 месяц", callback_data="premium_1")],
        [InlineKeyboardButton("1 год", callback_data="premium_12")],
        [InlineKeyboardButton("🎫 Ввести другой промокод", callback_data="enter_promo_premium")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_gift_ton_packages_with_discount(update: Update, context: ContextTypes.DEFAULT_TYPE, promo_code: str):
    """Показывает пакеты TON для подарка со скидкой"""
    user_id = update.message.from_user.id

    # Сохраняем примененный промокод
    applied_promocodes[user_id] = promo_code

    ton_options = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 25, 30, 35, 40, 45, 50, 55, 60, 70, 80, 90, 100]

    keyboard = []
    for i in range(0, len(ton_options), 3):
        row = []
        for j in range(3):
            if i + j < len(ton_options):
                ton = ton_options[i + j]
                # ИСПРАВЛЕНИЕ: используем фиксированную цену TON_PRICE для расчетов стоимости
                original_cost = ton * TON_PRICE  # Фиксированная цена для покупок
                final_cost, discount, message = calculate_discount(original_cost, promo_code, user_id)

                if discount > 0:
                    price_text = f"{final_cost:.1f}₽"
                else:
                    price_text = f"{final_cost:.1f}₽"

                price_text = price_text.replace(".0₽", "₽")
                row.append(InlineKeyboardButton(f"{ton} TON", callback_data=f"gift_ton_{ton}"))
        if row:
            keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⚡ Другое количество", callback_data="gift_custom_ton")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="gift_back")])

    promo_info = ""
    promo = get_promo_code(promo_code)
    if promo and promo['discount_percent'] > 0:
        promo_info = f"🎫 Применен промокод {promo_code} - скидка {promo['discount_percent']}%"
    elif promo and promo['discount_amount'] > 0:
        promo_info = f"🎫 Применен промокод {promo_code} - скидка {promo['discount_amount']}₽"

    await update.message.reply_text(
        f"⚡ Выберите количество TON для подарка:\n"
        f"💰 Курс: 1 TON = {TON_PRICE}₽\n\n"
        f"{promo_info}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def process_gift_star_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE, stars: int):
    """Обрабатывает выбор звезд для подарка - ВСЕГДА показывает способы оплаты"""
    query = update.callback_query
    user_id = query.from_user.id

    # Проверяем баланс пользователя
    user_balance = get_user_balance(user_id)

    # Проверяем примененный промокод
    original_cost = stars * STAR_PRICE
    promo_code = applied_promocodes.get(user_id)

    if promo_code:
        final_cost, discount, message = calculate_discount(original_cost, promo_code, user_id)
        if discount > 0:
            cost = final_cost
            # Используем промокод
            use_promo_code(promo_code, user_id, "gift_stars", original_cost, discount, final_cost)
            # Удаляем примененный промокод
            del applied_promocodes[user_id]
        else:
            cost = original_cost
    else:
        cost = original_cost

    # ВСЕГДА сохраняем во временную базу и просим ввести юзернейм
    # НЕ списываем баланс сразу!

    # Сохраняем во временную базу данных
    save_temp_gift(
        user_id=user_id,
        gift_type="stars",
        amount=stars,
        period="",
        cost=cost
    )

    await query.edit_message_text(
        f"🎁 Вы выбрали подарок: {stars} звёзд\n\n"
        f"💰 Сумма к оплате: {cost:.1f}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        "📝 Теперь введите юзернейм друга (например: @username или просто username):\n\n"
        "❌ Для отмены отправьте 'отмена'"
    )

    awaiting_friend_username[user_id] = True

async def process_gift_ton_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE, ton_amount: float):
    """Обрабатывает выбор TON для подарка"""
    query = update.callback_query
    user_id = query.from_user.id

    # Проверяем баланс пользователя
    user_balance = get_user_balance(user_id)

    # Проверяем примененный промокод
    original_cost = ton_amount * TON_PRICE
    promo_code = applied_promocodes.get(user_id)

    if promo_code:
        final_cost, discount, message = calculate_discount(original_cost, promo_code, user_id)
        if discount > 0:
            cost = final_cost
            # Используем промокод
            use_promo_code(promo_code, user_id, "gift_ton", original_cost, discount, final_cost)
            # Удаляем примененный промокод
            del applied_promocodes[user_id]
        else:
            cost = original_cost
    else:
        cost = original_cost

    # Сохраняем во временную базу данных
    save_temp_gift(
        user_id=user_id,
        gift_type="ton",
        amount=ton_amount,
        period="",
        cost=cost
    )

    await query.edit_message_text(
        f"🎁 Вы выбрали подарок: {ton_amount} TON\n\n"
        f"💰 Сумма к оплате: {cost:.1f}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        "📝 Теперь введите юзернейм друга (например: @username или просто username):\n\n"
        "❌ Для отмена отправьте 'отмена'"
    )

    awaiting_friend_username[user_id] = True

async def process_gift_premium_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE, period: str):
    """Обрабатывает выбор Premium для подарка"""
    query = update.callback_query
    user_id = query.from_user.id

    # Проверяем баланс пользователя
    user_balance = get_user_balance(user_id)

    # Проверяем примененный промокод
    original_amount = PREMIUM_PRICES[period]
    promo_code = applied_promocodes.get(user_id)

    if promo_code:
        final_amount, discount, message = calculate_discount(original_amount, promo_code, user_id)
        if discount > 0:
            amount = final_amount
            # Используем промокод
            use_promo_code(promo_code, user_id, "gift_premium", original_amount, discount, final_amount)
            # Удаляем примененный промокод
            del applied_promocodes[user_id]
        else:
            amount = original_amount
    else:
        amount = original_amount

    # Сохраняем во временную базу данных
    save_temp_gift(
        user_id=user_id,
        gift_type="premium",
        amount=0,
        period=period,
        cost=amount
    )

    await query.edit_message_text(
        f"🎁 Вы выбрали подарок: Telegram Premium на {period}\n\n"
        f"💰 Сумма к оплате: {amount}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        "📝 Теперь введите юзернейм друга (например: @username или просто username):\n\n"
        "❌ Для отмена отправьте 'отмена'"
    )

    awaiting_friend_username[user_id] = True

async def process_balance_payment_stars(update: Update, context: ContextTypes.DEFAULT_TYPE, stars: int):
    """Обработка оплаты звезд с баланса"""
    query = update.callback_query
    await query.answer("⏳ Обрабатываем оплату с баланса...")

    user_id = query.from_user.id
    user_balance = get_user_balance(user_id)

    # Рассчитываем сумму
    amount = stars * STAR_PRICE

    # Проверяем баланс
    if user_balance < amount:
        try:
            await query.edit_message_text(
                f"❌ Недостаточно средств на балансе!\n\n"
                f"💳 Ваш баланс: {user_balance:.2f}₽\n"
                f"💰 Требуется: {amount:.2f}₽\n\n"
                f"Пополните баланс и попробуйте снова.",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"❌ Ошибка edit_message_text: {e}")
            await context.bot.send_message(
                query.message.chat.id,
                f"❌ Недостаточно средств на балансе!\n\n"
                f"💳 Ваш баланс: {user_balance:.2f}₽\n"
                f"💰 Требуется: {amount:.2f}₽\n\n"
                f"Пополните баланс и попробуйте снова.",
                reply_markup=get_main_menu_keyboard()
            )
        return

    # СОЗДАЕМ ЗАКАЗ В ОЖИДАНИИ ПОДТВЕРЖДЕНИЯ
    user = await context.bot.get_chat(user_id)

    order_id = save_pending_order(
        user_id=user_id,
        username=user.username,
        full_name=user.full_name,
        order_type="stars",
        amount=stars,
        cost=amount,
        receipt_message_id=query.message.message_id,
        is_balance_replenishment=False
    )

    # Сообщение для пользователя
    success_message = (
        f"✅ Заказ создан!\n\n"
        f"⭐ Вы заказали: {stars} звёзд\n"
        f"💰 Сумма к списанию: {amount:.2f}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        f"⏳ Заказ отправлен на подтверждение администратору.\n"
        f"Обычно это занимает 1-15 минут.\n\n"
        f"📞 Вы получите уведомление, когда заказ будет выполнен.\n\n"
        f"Спасибо за покупку! ❤️"
    )

    try:
        await query.edit_message_text(
            success_message,
            reply_markup=get_main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"❌ Ошибка edit_message_text: {e}")
        await context.bot.send_message(
            query.message.chat.id,
            success_message,
            reply_markup=get_main_menu_keyboard()
        )

    # Отправляем уведомление админу
    try:
        moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        admin_message = (
            f"💰 НОВЫЙ ЗАКАЗ С БАЛАНСА!\n\n"
            f"👤 Пользователь: @{user.username}\n"
            f"📛 Имя: {user.full_name}\n"
            f"🆔 ID: {user_id}\n\n"
            f"📦 Заказ: ⭐ {stars} звёзд\n"
            f"💰 Сумма: {amount:.1f}₽\n"
            f"💳 Баланс пользователя: {user_balance:.2f}₽\n"
            f"⏰ Время (МСК): {moscow_time}\n\n"
            f"✅ Баланс достаточен для списания"
        )

        admin_msg = await context.bot.send_message(
            ADMIN_ID,
            admin_message,
            reply_markup=get_order_confirmation_keyboard(order_id)
        )

        update_order_status(order_id, "pending", admin_msg.message_id)
        logger.info(f"✅ Заказ #{order_id} создан для пользователя {user_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления админу: {e}")

async def process_balance_payment_ton(update: Update, context: ContextTypes.DEFAULT_TYPE, ton_amount: float):
    """Обработка оплаты TON с баланса"""
    query = update.callback_query
    await query.answer("⏳ Обрабатываем оплату с баланса...")

    user_id = query.from_user.id
    user_balance = get_user_balance(user_id)

    # Рассчитываем сумму
    amount = ton_amount * TON_PRICE

    # Проверяем баланс
    if user_balance < amount:
        try:
            await query.edit_message_text(
                f"❌ Недостаточно средств на балансе!\n\n"
                f"💳 Ваш баланс: {user_balance:.2f}₽\n"
                f"💰 Требуется: {amount:.2f}₽\n\n"
                f"Пополните баланс и попробуйте снова.",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"❌ Ошибка edit_message_text: {e}")
            await context.bot.send_message(
                query.message.chat.id,
                f"❌ Недостаточно средств на балансе!\n\n"
                f"💳 Ваш баланс: {user_balance:.2f}₽\n"
                f"💰 Требуется: {amount:.2f}₽\n\n"
                f"Пополните баланс и попробуйте снова.",
                reply_markup=get_main_menu_keyboard()
            )
        return

    # СОЗДАЕМ ЗАКАЗ В ОЖИДАНИИ ПОДТВЕРЖДЕНИЯ
    user = await context.bot.get_chat(user_id)

    order_id = save_pending_order(
        user_id=user_id,
        username=user.username,
        full_name=user.full_name,
        order_type="ton",
        amount=ton_amount,
        cost=amount,
        receipt_message_id=query.message.message_id,
        is_balance_replenishment=False
    )

    # Сообщение для пользователя
    success_message = (
        f"✅ Заказ создан!\n\n"
        f"💎 Вы заказали: {ton_amount} TON\n"
        f"💰 Сумма к списанию: {amount:.2f}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        f"⏳ Заказ отправлен на подтверждение администратору.\n"
        f"Обычно это занимает 1-15 минут.\n\n"
        f"📞 Вы получите уведомление, когда заказ будет выполнен.\n\n"
        f"Спасибо за покупку! ❤️"
    )

    try:
        await query.edit_message_text(
            success_message,
            reply_markup=get_main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"❌ Ошибка edit_message_text: {e}")
        await context.bot.send_message(
            query.message.chat.id,
            success_message,
            reply_markup=get_main_menu_keyboard()
        )

    # Отправляем уведомление админу
    try:
        moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        admin_message = (
            f"💰 НОВЫЙ ЗАКАЗ С БАЛАНСА!\n\n"
            f"👤 Пользователь: @{user.username}\n"
            f"📛 Имя: {user.full_name}\n"
            f"🆔 ID: {user_id}\n\n"
            f"📦 Заказ: 💎 {ton_amount} TON\n"
            f"💰 Сумма: {amount:.1f}₽\n"
            f"💳 Баланс пользователя: {user_balance:.2f}₽\n"
            f"⏰ Время (МСК): {moscow_time}\n\n"
            f"✅ Баланс достаточен для списания"
        )

        admin_msg = await context.bot.send_message(
            ADMIN_ID,
            admin_message,
            reply_markup=get_order_confirmation_keyboard(order_id)
        )

        update_order_status(order_id, "pending", admin_msg.message_id)
        logger.info(f"✅ Заказ #{order_id} создан для пользователя {user_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления админу: {e}")

async def process_balance_payment_premium(update: Update, context: ContextTypes.DEFAULT_TYPE, period: str):
    """Обработка оплаты Premium с баланса"""
    query = update.callback_query
    await query.answer("⏳ Обрабатываем оплату с баланса...")

    user_id = query.from_user.id
    user_balance = get_user_balance(user_id)

    # Рассчитываем сумму
    amount = PREMIUM_PRICES[period]

    # Проверяем баланс
    if user_balance < amount:
        try:
            await query.edit_message_text(
                f"❌ Недостаточно средств на балансе!\n\n"
                f"💳 Ваш баланс: {user_balance:.2f}₽\n"
                f"💰 Требуется: {amount:.2f}₽\n\n"
                f"Пополните баланс и попробуйте снова.",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"❌ Ошибка edit_message_text: {e}")
            await context.bot.send_message(
                query.message.chat.id,
                f"❌ Недостаточно средств на балансе!\n\n"
                f"💳 Ваш баланс: {user_balance:.2f}₽\n"
                f"💰 Требуется: {amount:.2f}₽\n\n"
                f"Пополните баланс и попробуйте снова.",
                reply_markup=get_main_menu_keyboard()
            )
        return

    # СОЗДАЕМ ЗАКАЗ В ОЖИДАНИИ ПОДТВЕРЖДЕНИЯ
    user = await context.bot.get_chat(user_id)

    order_id = save_pending_order(
        user_id=user_id,
        username=user.username,
        full_name=user.full_name,
        order_type="premium",
        amount=1,  # 1 подписка
        cost=amount,
        receipt_message_id=query.message.message_id,
        is_balance_replenishment=False
    )

    # Сообщение для пользователя
    success_message = (
        f"✅ Заказ создан!\n\n"
        f"🌟 Вы заказали: Telegram Premium на {period}\n"
        f"💰 Сумма к списанию: {amount:.2f}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        f"⏳ Заказ отправлен на подтверждение администратору.\n"
        f"Обычно это занимает 1-15 минут.\n\n"
        f"📞 Вы получите уведомление, когда заказ будет выполнен.\n\n"
        f"Спасибо за покупку! ❤️"
    )

    try:
        await query.edit_message_text(
            success_message,
            reply_markup=get_main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"❌ Ошибка edit_message_text: {e}")
        await context.bot.send_message(
            query.message.chat.id,
            success_message,
            reply_markup=get_main_menu_keyboard()
        )

    # Отправляем уведомление админу
    try:
        moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        admin_message = (
            f"💰 НОВЫЙ ЗАКАЗ С БАЛАНСА!\n\n"
            f"👤 Пользователь: @{user.username}\n"
            f"📛 Имя: {user.full_name}\n"
            f"🆔 ID: {user_id}\n\n"
            f"📦 Заказ: 🌟 Telegram Premium на {period}\n"
            f"💰 Сумма: {amount:.1f}₽\n"
            f"💳 Баланс пользователя: {user_balance:.2f}₽\n"
            f"⏰ Время (МСК): {moscow_time}\n\n"
            f"✅ Баланс достаточен для списания"
        )

        admin_msg = await context.bot.send_message(
            ADMIN_ID,
            admin_message,
            reply_markup=get_order_confirmation_keyboard(order_id)
        )

        update_order_status(order_id, "pending", admin_msg.message_id)
        logger.info(f"✅ Заказ #{order_id} создан для пользователя {user_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления админу: {e}")

async def process_balance_payment_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка оплаты подарка с баланса"""
    query = update.callback_query
    await query.answer("⏳ Обрабатываем оплату с баланса...")

    user_id = query.from_user.id

    # Получаем информацию о подарке
    gift_info = get_temp_gift(user_id)
    if not gift_info:
        gift_info = context.user_data.get('current_gift')
    if not gift_info:
        gift_info = context.user_data.get(f'gift_{user_id}')

    if not gift_info:
        try:
            await query.edit_message_text("❌ Ошибка: информация о подарке не найдена.")
        except Exception as e:
            logger.error(f"❌ Ошибка edit_message_text: {e}")
            await context.bot.send_message(
                query.message.chat.id,
                "❌ Ошибка: информация о подарке не найдена."
            )
        return

    user_balance = get_user_balance(user_id)
    cost = gift_info['cost']

    # Проверяем баланс
    if user_balance < cost:
        try:
            await query.edit_message_text(
                f"❌ Недостаточно средств на балансе!\n\n"
                f"💳 Ваш баланс: {user_balance:.2f}₽\n"
                f"💰 Требуется: {cost:.2f}₽\n\n"
                f"Пополните баланс и попробуйте снова.",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"❌ Ошибка edit_message_text: {e}")
            await context.bot.send_message(
                query.message.chat.id,
                f"❌ Недостаточно средств на балансе!\n\n"
                f"💳 Ваш баланс: {user_balance:.2f}₽\n"
                f"💰 Требуется: {cost:.2f}₽\n\n"
                f"Пополните баланс и попробуйте снова.",
                reply_markup=get_main_menu_keyboard()
            )
        return

    # СОЗДАЕМ ЗАКАЗ В ОЖИДАНИИ ПОДТВЕРЖДЕНИЯ
    user = await context.bot.get_chat(user_id)

    order_id = save_pending_order(
        user_id=user_id,
        username=user.username,
        full_name=user.full_name,
        order_type=f"gift_{gift_info['type']}",
        amount=gift_info["amount"],
        cost=cost,
        receipt_message_id=query.message.message_id,
        friend_username=gift_info.get("friend_username", ""),
        is_balance_replenishment=False
    )

    # Создаем описание подарка
    gift_description = get_gift_description(gift_info)

    # Сообщение для пользователя
    success_message = (
        f"✅ Заказ подарка создан!\n\n"
        f"🎁 Подарок для: {gift_info.get('friend_username', 'Не указан')}\n"
        f"📦 Подарок: {gift_description}\n"
        f"💰 Сумма к списанию: {cost:.2f}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        f"⏳ Заказ отправлен на подтверждение администратору.\n"
        f"Обычно это занимает 1-15 минут.\n\n"
        f"📞 Вы получите уведомление, когда подарок будет отправлен.\n\n"
        f"Спасибо за покупку! ❤️"
    )

    try:
        await query.edit_message_text(
            success_message,
            reply_markup=get_main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"❌ Ошибка edit_message_text: {e}")
        await context.bot.send_message(
            query.message.chat.id,
            success_message,
            reply_markup=get_main_menu_keyboard()
        )

    # Очищаем временные данные
    delete_temp_gift(user_id)
    if 'current_gift' in context.user_data:
        del context.user_data['current_gift']
    if f'gift_{user_id}' in context.user_data:
        del context.user_data[f'gift_{user_id}']

    # Отправляем уведомление админу
    try:
        moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        admin_message = (
            f"💰 НОВЫЙ ЗАКАЗ ПОДАРКА С БАЛАНСА!\n\n"
            f"👤 Пользователь: @{user.username}\n"
            f"📛 Имя: {user.full_name}\n"
            f"🆔 ID: {user_id}\n\n"
            f"🎁 Подарок: {gift_description}\n"
            f"👥 Для: {gift_info.get('friend_username', 'Не указан')}\n"
            f"💰 Сумма: {cost:.1f}₽\n"
            f"💳 Баланс пользователя: {user_balance:.2f}₽\n"
            f"⏰ Время (МСК): {moscow_time}\n\n"
            f"✅ Баланс достаточен для списания"
        )

        admin_msg = await context.bot.send_message(
            ADMIN_ID,
            admin_message,
            reply_markup=get_order_confirmation_keyboard(order_id)
        )

        update_order_status(order_id, "pending", admin_msg.message_id)
        logger.info(f"✅ Заказ подарка #{order_id} создан для пользователя {user_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления админу: {e}")

def get_gift_description(gift_info: dict) -> str:
    """Возвращает описание подарка"""
    if gift_info["type"] == "stars":
        return f"⭐ {gift_info['amount']} звёзд"
    elif gift_info["type"] == "ton":
        return f"💎 {gift_info['amount']} TON"
    elif gift_info["type"] == "premium":
        return f"🌟 Telegram Premium на {gift_info['period']}"
    return "Неизвестный подарок"

async def show_premium_options_with_discount(update: Update, context: ContextTypes.DEFAULT_TYPE, promo_code: str):
    """Показывает пакеты Premium со скидкой"""
    user_id = update.message.from_user.id

    # Сохраняем примененный промокод
    applied_promocodes[user_id] = promo_code

    keyboard = []
    for period, price in PREMIUM_PRICES.items():
        original_cost = price
        final_cost, discount, message = calculate_discount(original_cost, promo_code, user_id)

        if discount > 0:
            price_text = f"{final_cost:.1f}₽ (-{discount:.1f}₽)"
        else:
            price_text = f"{final_cost:.1f}₽"

        price_text = price_text.replace(".0₽", "₽")
        keyboard.append([InlineKeyboardButton(f"🌟 {period} - {price_text}", callback_data=f"premium_{period}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="premium_back")])

    promo_info = ""
    promo = get_promo_code(promo_code)
    if promo and promo['discount_percent'] > 0:
        promo_info = f"🎫 Применен промокод {promo_code} - скидка {promo['discount_percent']}%"
    elif promo and promo['discount_amount'] > 0:
        promo_info = f"🎫 Применен промокод {promo_code} - скидка {promo['discount_amount']}₽"

    await update.message.reply_text(
        f"🌟 Telegram Premium подписка:\n\n"
        f"{promo_info}\n\n"
        "Выберите срок подписки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_gift_premium_options_with_discount(update: Update, context: ContextTypes.DEFAULT_TYPE, promo_code: str):
    """Показывает пакеты Premium для подарка со скидкой"""
    user_id = update.message.from_user.id

    # Сохраняем примененный промокод
    applied_promocodes[user_id] = promo_code

    keyboard = []
    for period, price in PREMIUM_PRICES.items():
        original_cost = price
        final_cost, discount, message = calculate_discount(original_cost, promo_code, user_id)

        if discount > 0:
            price_text = f"{final_cost:.1f}₽ (-{discount:.1f}₽)"
        else:
            price_text = f"{final_cost:.1f}₽"

        price_text = price_text.replace(".0₽", "₽")
        keyboard.append([InlineKeyboardButton(f"🌟 {period} - {price_text}", callback_data=f"gift_premium_{period}")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="gift_back")])

    promo_info = ""
    promo = get_promo_code(promo_code)
    if promo and promo['discount_percent'] > 0:
        promo_info = f"🎫 Применен промокод {promo_code} - скидка {promo['discount_percent']}%"
    elif promo and promo['discount_amount'] > 0:
        promo_info = f"🎫 Применен промокод {promo_code} - скидка {promo['discount_amount']}₽"

    await update.message.reply_text(
        f"🌟 Выберите Telegram Premium подписку для подарка:\n\n"
        f"{promo_info}\n\n"
        "Выберите срок подписки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ИСПРАВЛЕННЫЕ ФУНКЦИИ - оплата криптовалютой с правильной навигацией
async def show_crypto_payment_info(update: Update, context: ContextTypes.DEFAULT_TYPE, payment_type: str = "stars"):
    """Показывает информацию для оплаты криптовалютой"""
    query = update.callback_query
    user_id = query.from_user.id

    # Получаем информацию о платеже
    payment_info = pending_payments.get(user_id, {})
    amount = payment_info.get('amount', 0)

    text = (
        f"₿ Оплата криптовалютой\n\n"
        f"💰 Сумма к оплате: {amount:.1f}₽\n\n"
        f"💎 Кошельки для оплаты:\n\n"
        f"<b>TON</b>:\n"
        f"<code>{CRYPTO_WALLETS['TON']}</code>\n\n"
        f"<b>USDT</b> (TRC-20):\n"
        f"<code>{CRYPTO_WALLETS['USDT']}</code>\n\n"
        f"📌 После оплаты:\n"
        f"1. Сделайте скриншот перевода\n"
        f"2. Отправьте его в этот чат\n"
        f"3. Заказ будет обработан в течение 5-15 минут\n\n"
        f"💡 Рекомендуем использовать TON для быстрой обработки"
    )

    # ИСПРАВЛЕНО: Используем переданный payment_type для определения кнопки
    back_button = None
    if payment_type == "stars":
        back_button = InlineKeyboardButton("🔙 Назад", callback_data="buy_back")
    elif payment_type == "ton":
        back_button = InlineKeyboardButton("🔙 Назад", callback_data="ton_back")
    elif payment_type == "premium":
        back_button = InlineKeyboardButton("🔙 Назад", callback_data="premium_back")
    else:
        back_button = InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")

    keyboard = [
        [back_button]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    awaiting_receipts[user_id] = True

# НОВАЯ ФУНКЦИЯ - оплата криптовалютой для подарков
async def show_gift_crypto_payment_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    logger.info(f"🔹🔹🔹 ОТЛАДКА: Нажата кнопка Крипто для подарка, user_id: {user_id}")

    # УЛУЧШЕННАЯ ЛОГИКА ПОЛУЧЕНИЯ ДАННЫХ О ПОДАРКЕ
    gift_info = None

    # 1. Пробуем получить из базы данных
    gift_info = get_temp_gift(user_id)
    logger.info(f"🔹🔹🔹 ОТЛАДКА: gift_info из БД: {gift_info}")

    # 2. Если нет в БД, пробуем из user_data
    if not gift_info:
        gift_info = context.user_data.get('current_gift')
        logger.info(f"🔹🔹🔹 ОТЛАДКА: gift_info из user_data current_gift: {gift_info}")

    # 3. Если все еще нет, пробуем по ключу user_id
    if not gift_info:
        gift_info = context.user_data.get(f'gift_{user_id}')
        logger.info(f"🔹🔹🔹 ОТЛАДКА: gift_info из user_data gift_{user_id}: {gift_info}")

    if not gift_info:
        logger.error(f"❌ ОТЛАДКА: gift_info не найден для пользователя {user_id}")
        await query.edit_message_text("❌ Ошибка: информация о подарке не найдена.")
        return

    await send_admin_notification(context, user_id, f"Выбрал оплату криптовалютой для подарка {gift_info['friend_username']}")

    text = (
        f"₿ Оплата криптовалютой\n\n"
        f"🎁 Подарок для {gift_info['friend_username']}:\n"
    )

    if gift_info["type"] == "stars":
        text += f"⭐ {gift_info['amount']} звёзд\n"
    elif gift_info["type"] == "ton":
        text += f"💎 {gift_info['amount']} TON\n"
    elif gift_info["type"] == "premium":
        text += f"🌟 Telegram Premium на {gift_info['period']}\n"

    text += f"💰 Сумма к оплате: {gift_info['cost']:.1f}₽\n\n"
    text += f"💎 Кошельки для оплаты:\n\n"
    text += f"<b>TON</b>:\n"
    text += f"<code>{CRYPTO_WALLETS['TON']}</code>\n\n"
    text += f"<b>USDT</b> (TRC-20):\n"
    text += f"<code>{CRYPTO_WALLETS['USDT']}</code>\n\n"
    text += (
        "📌 После оплаты:\n"
        "1. Сделайте скриншот перевода\n"
        "2. Отправьте его в этот чат\n"
        "3. Подарок будет отправлен в течение 5-15 минут\n\n"
        "💡 Рекомендуем использовать TON для быстрой обработки"
    )

    # КНОПКИ С ПРАВИЛЬНЫМИ ОБРАБОТЧИКАМИ
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data="gift_back")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    awaiting_receipts[user_id] = True

# НОВАЯ ФУНКЦИЯ - меню продажи аккаунтов
async def show_accounts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню продажи аккаунтов"""
    user = update.effective_user
    update_user_activity(user.id)

    text = (
        "🛍️ Продажа аккаунтов Telegram/VK и не только!\n\n"

        "🔍 Все остальные страницы сайта смотрите через основной домен:\n"
        "🌍 Akkaunti-Shop.pro\n\n"

        "🌐 Переходник на сайт:\n"
        "👉 akkaunti-shop.pro/buy-telegram-vk-accounts\n\n"

        "🌐 Вы можете купить аккаунты через:\n\n"
        "💻 Личный кабинет на сайте:\n"
        "👉 akkaunti-shop.pro/lichnyj-kabinet\n\n"

        "📱 Напрямую в Telegram:\n"
        "👉 @KIRG_17\n"
        "👉 @manager_k17\n\n"
    )

    keyboard = [
        [InlineKeyboardButton("💻 Личный кабинет", url="https://akkaunti-shop.pro/lichnyj-kabinet")],
        [
            InlineKeyboardButton("💬 Написать KIRG_17", url="https://t.me/KIRG_17"),
            InlineKeyboardButton("💬 Написать manager_k17", url="https://t.me/manager_k17")
        ]
    ]

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# НОВЫЕ ФУНКЦИИ ДЛЯ ВВОДА ПРОИЗВОЛЬНОГО КОЛИЧЕСТВА ЗВЕЗД И TON С ОГРАНИЧЕНИЯМИ
async def request_custom_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос произвольного количества звезд с ограничением минимум 50"""
    query = update.callback_query
    await query.answer()

    awaiting_custom_stars[query.from_user.id] = True

    await query.edit_message_text(
        "✨ Введите нужное количество звёзд:\n\n"
        "💰 Цена за 1 звезду: 1.40₽\n"
        "⚠️ Минимальное количество: 50 звёзд\n\n"
        "❌ Для отмены отправьте 'отмена'"
    )

async def request_gift_custom_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос произвольного количества звезд для подарка с ограничением минимум 50"""
    query = update.callback_query
    await query.answer()

    awaiting_custom_stars[query.from_user.id] = True
    context.user_data['is_gift'] = True

    await query.edit_message_text(
        "✨ Введите нужное количество звёзд для подарка:\n\n"
        "💰 Цена за 1 звезду: 1.40₽\n"
        "⚠️ Минимальное количество: 50 звёзд\n\n"
        "❌ Для отмены отправьте 'отмена'"
    )

async def request_custom_ton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос произвольного количества TON с ограничением целых чисел"""
    query = update.callback_query
    await query.answer()

    awaiting_custom_ton[query.from_user.id] = True

    await query.edit_message_text(
        "⚡ Введите нужное количество TON:\n\n"
        "💰 Курс: 1 TON = 200₽\n"
        "⚠️ Только целые числа (1, 2, 3...)\n\n"
        "❌ Для отмена отправьте 'отмена'"
    )

async def request_gift_custom_ton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос произвольного количества TON для подарка с ограничением целых чисел"""
    query = update.callback_query
    await query.answer()

    awaiting_custom_ton[query.from_user.id] = True
    context.user_data['is_gift'] = True

    await query.edit_message_text(
        "⚡ Введите нужное количество TON для подарка:\n\n"
        "💰 Курс: 1 TON = 200₽\n"
        "⚠️ Только целые числа (1, 2, 3...)\n\n"
        "❌ Для отмены отправьте 'отмена'"
    )

# ИСПРАВЛЕННАЯ ФУНКЦИЯ - обработка ввода произвольного количества звезд
async def process_custom_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод произвольного количества звезд с проверкой ограничений"""
    user_id = update.message.from_user.id

    if update.message.text.lower() in ['отмена', 'cancel', 'отменить']:
        if user_id in awaiting_custom_stars:
            del awaiting_custom_stars[user_id]
        await update.message.reply_text(
            "✅ Ввод отменен",
            reply_markup=get_main_menu_keyboard()
        )
        return

    try:
        # УЛУЧШЕННЫЙ ПАРСИНГ ЧИСЕЛ
        user_input = update.message.text.replace(',', '.').replace(' ', '')
        cleaned_input = ''.join(char for char in user_input if char.isdigit() or char == '.')

        if not cleaned_input:
            await update.message.reply_text("❌ Пожалуйста, введите корректное число")
            return

        stars = int(float(cleaned_input))

        if stars < 50:
            await update.message.reply_text("❌ Минимальное количество звёзд: 50")
            return
        if stars > 100000:
            await update.message.reply_text("❌ Максимальное количество звёзд: 100,000")
            return

        if user_id in awaiting_custom_stars:
            del awaiting_custom_stars[user_id]

        is_gift = context.user_data.get('is_gift', False)

        if is_gift:
            # Для подарка
            await process_gift_star_purchase_custom(update, context, stars)
        else:
            # Для обычной покупки - ВСЕГДА показываем способы оплаты
            await process_star_purchase_custom(update, context, stars)

    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите целое число (например: 50, 100, 500)")

async def process_star_purchase_custom(update: Update, context: ContextTypes.DEFAULT_TYPE, stars: int):
    """Обрабатывает покупку произвольного количества звезд - ВСЕГДА показывает способы оплаты"""
    user_id = update.message.from_user.id

    # Проверяем баланс пользователя (только для информации)
    user_balance = get_user_balance(user_id)

    # Рассчитываем сумму
    amount = stars * STAR_PRICE

    # ВСЕГДА показываем способы оплаты, даже если баланса хватает
    await send_admin_notification(context, user_id, f"Начинает оплату {stars} звёзд на сумму {amount:.1f}₽")

    pending_payments[user_id] = {
        "amount": amount,
        "stars": stars,
        "timestamp": get_moscow_time()
    }

    text = (
        f"⭐ Вы выбрали {stars} звёзд\n"
        f"💰 Сумма к оплате: {amount:.1f}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        "💳 Способы оплаты:\n"
    )

    # Информация о балансе (только для отображения)
    if user_balance >= amount:
        balance_info = f"✅ Достаточно средств на балансе\n"
    else:
        balance_info = f"❌ Недостаточно средств на балансе\n"

    text += balance_info

    # Все способы оплаты
    keyboard = [
        [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_payment_stars_{stars}")],
        [InlineKeyboardButton("💳 Оплатить через ЮMoney", url=f"https://yoomoney.ru/quickpay/confirm.xml?receiver={YM_ACCOUNT}&quickpay-form=small&targets=Звёзды {stars} шт&sum={amount}&label=stars_{stars}")],
        [InlineKeyboardButton("📱 Оплатить через СБП", callback_data="sbp_payment")],
        [InlineKeyboardButton("📲 Оплатить на карту", callback_data="card_payment")],
        [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data="crypto_payment")]
    ]

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# НОВАЯ ФУНКЦИЯ - обработка произвольного количества звезд для подарка
async def process_gift_star_purchase_custom(update: Update, context: ContextTypes.DEFAULT_TYPE, stars: int):
    """Обрабатывает подарок произвольного количества звезд"""
    user_id = update.message.from_user.id

    # Проверяем баланс пользователя
    user_balance = get_user_balance(user_id)

    # Проверяем примененный промокод
    original_cost = stars * STAR_PRICE
    promo_code = applied_promocodes.get(user_id)

    if promo_code:
        final_cost, discount, message = calculate_discount(original_cost, promo_code, user_id)
        if discount > 0:
            cost = final_cost
            # Используем промокод
            use_promo_code(promo_code, user_id, "gift_stars", original_cost, discount, final_cost)
            # Удаляем примененный промокод
            del applied_promocodes[user_id]
        else:
            cost = original_cost
    else:
        cost = original_cost

    # Проверяем, достаточно ли баланса
    if user_balance >= cost:
        # Оплата с баланса
        update_user_balance(user_id, -cost)
        update_user_purchase_stats(user_id, "gift_stars", stars)
        record_sale("gift_stars", stars, cost)

        await update.message.reply_text(
            f"🎉 Подарок успешно отправлен!\n\n"
            f"⭐ Вы подарили: {stars} звёзд\n"
            f"💰 Списано с баланса: {cost:.2f}₽\n"
            f"💳 Новый баланс: {get_user_balance(user_id):.2f}₽\n\n"
            f"Спасибо за покупку! ❤️",
            reply_markup=get_main_menu_keyboard()
        )
        return

    # Сохраняем во временную базу данных
    save_temp_gift(
        user_id=user_id,
        gift_type="stars",
        amount=stars,
        period="",
        cost=cost
    )

    await update.message.reply_text(
        f"🎁 Вы выбрали подарок: {stars} звёзд\n\n"
        f"💰 Сумма к оплате: {cost:.1f}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        "📝 Теперь введите юзернейм друга (например: @username или просто username):\n\n"
        "❌ Для отмены отправьте 'отмена'"
    )

    awaiting_friend_username[user_id] = True

# ИСПРАВЛЕННАЯ ФУНКЦИЯ - обработка ввода произвольного количества TON
async def process_custom_ton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод произвольного количества TON с проверкой ограничений"""
    user_id = update.message.from_user.id

    if update.message.text.lower() in ['отмена', 'cancel', 'отменить']:
        if user_id in awaiting_custom_ton:
            del awaiting_custom_ton[user_id]
        await update.message.reply_text(
            "✅ Ввод отменен",
            reply_markup=get_main_menu_keyboard()
        )
        return

    try:
        # УЛУЧШЕННЫЙ ПАРСИНГ ЧИСЕЛ
        user_input = update.message.text.replace(',', '.').replace(' ', '')
        cleaned_input = ''.join(char for char in user_input if char.isdigit() or char == '.')

        if not cleaned_input:
            await update.message.reply_text("❌ Пожалуйста, введите корректное число")
            return

        # Проверяем, что введено целое число
        ton_amount = float(cleaned_input)
        if ton_amount != int(ton_amount):
            await update.message.reply_text("❌ Пожалуйста, введите целое число TON (например: 1, 2, 10)")
            return

        ton_amount = int(ton_amount)

        if ton_amount <= 0:
            await update.message.reply_text("❌ Количество TON должно быть больше 0")
            return
        if ton_amount > 1000:
            await update.message.reply_text("❌ Максимальное количество TON: 1,000")
            return

        if user_id in awaiting_custom_ton:
            del awaiting_custom_ton[user_id]

        is_gift = context.user_data.get('is_gift', False)

        if is_gift:
            # Для подарка
            await process_gift_ton_purchase_custom(update, context, ton_amount)
        else:
            # Для обычной покупки - ВСЕГДА показываем способы оплаты
            await process_ton_purchase_custom(update, context, ton_amount)

    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите целое число (например: 1, 5, 10)")

async def process_ton_purchase_custom(update: Update, context: ContextTypes.DEFAULT_TYPE, ton_amount: float):
    """Обрабатывает покупку произвольного количества TON - ВСЕГДА показывает способы оплаты"""
    user_id = update.message.from_user.id

    # Проверяем баланс пользователя (только для информации)
    user_balance = get_user_balance(user_id)

    # Проверяем примененный промокод
    original_amount = ton_amount * TON_PRICE
    promo_code = applied_promocodes.get(user_id)

    if promo_code:
        final_amount, discount, message = calculate_discount(original_amount, promo_code, user_id)
        if discount > 0:
            amount = final_amount
            # Используем промокод
            use_promo_code(promo_code, user_id, "ton", original_amount, discount, final_amount)
            # Удаляем примененный промокод
            del applied_promocodes[user_id]
        else:
            amount = original_amount
    else:
        amount = original_amount

    # ВСЕГДА показываем способы оплаты, даже если баланса хватает
    await send_admin_notification(context, user_id, f"Начинает оплату {ton_amount} TON на сумму {amount:.1f}₽")

    pending_payments[user_id] = {
        "amount": amount,
        "ton_amount": ton_amount,
        "timestamp": get_moscow_time(),
        "is_ton": True
    }

    text = (
        f"⚡ Вы выбрали {ton_amount} TON\n"
        f"💰 Сумма к оплате: {amount:.1f}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        "💳 Способы оплаты:\n"
    )

    # Добавляем информацию о балансе только для информации
    if user_balance >= amount:
        balance_info = f"✅ Достаточно средств на балансе\n"
    else:
        balance_info = f"❌ Недостаточно средств на балансе\n"

    text += balance_info

    # КЛАВИАТУРА со всеми способами оплаты
    keyboard = [
        [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_payment_ton_{ton_amount}")],
        [InlineKeyboardButton("💳 Оплатить через ЮMoney", url=f"https://yoomoney.ru/quickpay/confirm.xml?receiver={YM_ACCOUNT}&quickpay-form=small&targets=TON {ton_amount}&sum={amount}&label=ton_{ton_amount}")],
        [InlineKeyboardButton("📱 Оплатить через СБП", callback_data="sbp_payment_ton")],
        [InlineKeyboardButton("📲 Оплатить на карту", callback_data="card_payment_ton")],
        [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data="crypto_payment_ton")]
    ]

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# НОВАЯ ФУНКЦИЯ - обработка произвольного количества TON для подарка
async def process_gift_ton_purchase_custom(update: Update, context: ContextTypes.DEFAULT_TYPE, ton_amount: float):
    """Обрабатывает подарок произвольного количества TON"""
    user_id = update.message.from_user.id

    # Проверяем баланс пользователя
    user_balance = get_user_balance(user_id)

    # Проверяем примененный промокод
    original_cost = ton_amount * TON_PRICE
    promo_code = applied_promocodes.get(user_id)

    if promo_code:
        final_cost, discount, message = calculate_discount(original_cost, promo_code, user_id)
        if discount > 0:
            cost = final_cost
            # Используем промокод
            use_promo_code(promo_code, user_id, "gift_ton", original_cost, discount, final_cost)
            # Удаляем примененный промокод
            del applied_promocodes[user_id]
        else:
            cost = original_cost
    else:
        cost = original_cost

    # Проверяем, достаточно ли баланса
    if user_balance >= cost:
        # Оплата с баланса
        update_user_balance(user_id, -cost)
        update_user_purchase_stats(user_id, "gift_ton", ton_amount)
        record_sale("gift_ton", ton_amount, cost)

        await update.message.reply_text(
            f"🎉 Подарок успешно отправлен!\n\n"
            f"💎 Вы подарили: {ton_amount} TON\n"
            f"💰 Списано с баланса: {cost:.2f}₽\n"
            f"💳 Новый баланс: {get_user_balance(user_id):.2f}₽\n\n"
            f"Спасибо за покупку! ❤️",
            reply_markup=get_main_menu_keyboard()
        )
        return

    # Сохраняем во временную базу данных
    save_temp_gift(
        user_id=user_id,
        gift_type="ton",
        amount=ton_amount,
        period="",
        cost=cost
    )

    await update.message.reply_text(
        f"🎁 Вы выбрали подарок: {ton_amount} TON\n\n"
        f"💰 Сумма к оплате: {cost:.1f}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        "📝 Теперь введите юзернейм друга (например: @username или просто username):\n\n"
        "❌ Для отмена отправьте 'отмена'"
    )

    awaiting_friend_username[user_id] = True

# НОВАЯ ФУНКЦИЯ - скрытие клавиатуры при нажатии на пустое место
async def hide_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скрывает клавиатуру при нажатии на пустое место или отправке любого необрабатываемого контента"""
    user = update.effective_user
    update_user_activity(user.id)

    # Проверяем, есть ли активная клавиатура
    if update.message.text or update.message.photo or update.message.document:
        # Если есть текст или медиа - это обрабатываемые сообщения, не скрываем клавиатуру
        return

    # Если это нажатие на пустое место (не текст, не медиа, не команда) - скрываем клавиатуру
    await update.message.reply_text(
        "Клавиатура скрыта. Используйте /start чтобы вернуть меню.",
        reply_markup=ReplyKeyboardRemove()
    )
    logger.info(f"✅ Клавиатура скрыта для пользователя {user.id}")

# НОВАЯ ФУНКЦИЯ - команда для скрытия клавиатуры
async def hide_keyboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для скрытия клавиатуры"""
    await update.message.reply_text(
        "Клавиатура скрыта. Используйте /start чтобы вернуть меню.",
        reply_markup=ReplyKeyboardRemove()
    )
    logger.info(f"✅ Клавиатура скрыта по команде для пользователя {update.effective_user.id}")

# ИСПРАВЛЕННАЯ ФУНКЦИЯ обработки меню
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    update_user_activity(user.id)

    text = update.message.text

    logger.info(f"🔹🔹🔹 ОБРАБОТКА МЕНЮ: user_id={user.id}, text='{text}'")

   # 🔴 ДОБАВЛЕНО: Детальное логирование для команды курсов
    if "курс" in text.lower() or "💹" in text:
        logger.info(f"🎯 ОБНАРУЖЕНА КОМАНДА КУРСОВ: '{text}'")
        logger.info(f"🎯 СРАВНЕНИЕ: text='{text}' == '💹 Актуальные курсы' -> {text == '💹 Актуальные курсы'}")
        logger.info(f"🎯 Длина текста: {len(text)}, длина эталона: {len('💹 Актуальные курсы')}")

    # Дополнительная отладка - сравнение посимвольно
    if len(text) == len('💹 Актуальные курсы'):
        for i, (char1, char2) in enumerate(zip(text, '💹 Актуальные курсы')):
            if char1 != char2:
                logger.info(f"🎯 РАЗЛИЧИЕ на позиции {i}: '{char1}' (код: {ord(char1)}) != '{char2}' (код: {ord(char2)})")

    # СБРАСЫВАЕМ состояние рассылки при ЛЮБОЙ команде
    if text and text.startswith('/'):
        context.user_data['broadcast'] = False
        context.user_data['broadcast_active'] = False
        logger.info(f"✅ Состояние рассылки сброшено при команде: {text}")

    # СНАЧАЛА проверяем ОТМЕНУ в любом состоянии
    if text and text.lower() in ['отмена', 'cancel', 'отменить']:
        logger.info(f"🔹 Обработка отмены для пользователя {user.id}")
        await cancel_payment_handler(update, context)
        return

    # ОБРАБОТКА КОМАНД АДМИНА
    if text and text.startswith('/'):
        logger.info(f"🔹 Обработка команды: {text}")
        if text == "/admin" and user.id == ADMIN_ID:
            await admin_panel(update, context)
            return
        elif text == "/stats" and user.id == ADMIN_ID:
            await stats_command(update, context)
            return
        elif text == "/check" and user.id == ADMIN_ID:
            await check_bot_command(update, context)
            return
        elif text == "/debug_orders" and user.id == ADMIN_ID:
            await debug_orders_command(update, context)
            return
        elif text == "/debug_state" and user.id == ADMIN_ID:
            await debug_state(update, context)
            return
        elif text == "/hide":
            await hide_keyboard_command(update, context)
            return
        elif text == "/start":
            await start(update, context)
            return
        else:
            await unknown_command(update, context)
            return

    # 🔴 ВАЖНО: Сначала проверяем ВСЕ специальные состояния
    special_states = [
        (awaiting_receipts, "awaiting_receipts"),
        (awaiting_friend_username, "awaiting_friend_username"),
        (awaiting_promo_code, "awaiting_promo_code"),
        (awaiting_custom_stars, "awaiting_custom_stars"),
        (awaiting_custom_ton, "awaiting_custom_ton"),
        (conversion_data, "conversion_data"),
        (awaiting_balance_amount, "awaiting_balance_amount"),
        (awaiting_user_search, "awaiting_user_search"),
        (awaiting_promo_creation, "awaiting_promo_creation")
    ]

    for state_dict, state_name in special_states:
        if user.id in state_dict:
            logger.info(f"🔹 Обнаружено специальное состояние: {state_name} для пользователя {user.id}")

            if state_name == "awaiting_receipts":
                if text and not (update.message.photo or update.message.document):
                    await update.message.reply_text(
                        "📎 Пожалуйста, отправьте скриншот чека об оплате.\n\n"
                        "Если хотите отменить оплату, отправьте слово 'отмена'",
                        reply_markup=get_cancel_keyboard()
                    )
                    return
                else:
                    await handle_receipt(update, context)
                    return

            elif state_name == "awaiting_friend_username":
                await handle_friend_username(update, context)
                return

            elif state_name == "awaiting_promo_code":
                await process_promo_input(update, context)
                return

            elif state_name == "awaiting_custom_stars":
                await process_custom_stars(update, context)
                return

            elif state_name == "awaiting_custom_ton":
                await process_custom_ton(update, context)
                return

            elif state_name == "conversion_data":
                await process_conversion_input(update, context)
                return

            elif state_name == "awaiting_balance_amount":
                if context.user_data.get('admin_balance'):
                    await process_admin_balance_amount(update, context)
                else:
                    await process_balance_replenishment(update, context)
                return

            elif state_name == "awaiting_user_search":
                await process_admin_balance(update, context)
                return

            elif state_name == "awaiting_promo_creation":
                await process_my_promo_creation(update, context)
                return

    # Проверяем состояния в context.user_data
    if context.user_data.get('awaiting_promo') and user.id == ADMIN_ID:
        logger.info(f"🔹 Админ создает промокод")
        await process_promo_creation(update, context)
        return

     # 🔴 ТЕПЕРЬ ОБРАБАТЫВАЕМ ОБЫЧНЫЕ КОМАНДЫ МЕНЮ
    logger.info(f"🔹 Обработка обычной команды меню: '{text}'")

    # Словарь команд меню - ДОЛЖЕН БЫТЬ ПРОПЕРНО ОТСТУПЛЕН
    menu_commands = {
        "⭐ Купить звёзды": show_star_packages,
        "💎 Купить TON": show_ton_options,
        "ℹ️ Помощь": show_help,
        "🎁 Сделать подарок": show_gift_options_menu,
        "🌟 Telegram Premium": show_premium_options,
        "🛍️ Продажа аккаунтов": show_accounts_menu,
        "💱 Актуальные курсы": show_currency_rates,
        "👤 Мой профиль": show_user_profile,
        "🏠 Главное меню": start,
        "В меню": start,
        "меню": start,
        "главное меню": start
    }

    if text in menu_commands:
        logger.info(f"✅ Выполнение команды меню: {text}")
        await menu_commands[text](update, context)
        return

    # Если команда не распознана
    logger.warning(f"⚠️ Неизвестная команда: '{text}'")
    await unknown_command(update, context)

async def show_gift_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню подарков для callback"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await send_admin_notification(context, user_id, "Выбирает подарок другу")

    keyboard = [
        [InlineKeyboardButton("⭐ Подарить звёзды", callback_data="gift_stars")],
        [InlineKeyboardButton("💎 Подарить TON", callback_data="gift_ton")],
        [InlineKeyboardButton("🌟 Подарить Premium", callback_data="gift_premium")],
        [InlineKeyboardButton("🎫 Ввести промокод", callback_data="enter_promo_gift")]
    ]

    await query.edit_message_text(
        "🎁 Выберите что хотите подарить другу:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_gift_options_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню подарков для текстового сообщения"""
    user_id = update.message.from_user.id
    await send_admin_notification(context, user_id, "Выбирает подарок другу")

    keyboard = [
        [InlineKeyboardButton("⭐ Подарить звёзды", callback_data="gift_stars")],
        [InlineKeyboardButton("💎 Подарить TON", callback_data="gift_ton")],
        [InlineKeyboardButton("🌟 Подарить Premium", callback_data="gift_premium")],
        [InlineKeyboardButton("🎫 Ввести промокод", callback_data="enter_promo_gift")]
    ]

    await update.message.reply_text(
        "🎁 Выберите что хотите подарить другу:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_star_packages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await send_admin_notification(context, user_id, "Выбирает количество звёзд")

    star_options = [50, 75, 100, 150, 200, 250, 300, 350, 400, 450,
                   500, 550, 600, 650, 700, 800, 900, 1000, 1500, 2000, 3000, 5000, 10000]

    keyboard = []
    for i in range(0, len(star_options), 2):
        row = []
        if i < len(star_options):
            stars = star_options[i]
            cost = stars * STAR_PRICE
            price_text = f"{cost:.1f}₽".replace(".0₽", "₽")
            row.append(InlineKeyboardButton(f"{stars} звёзд - {price_text}", callback_data=f"stars_{stars}"))
        if i+1 < len(star_options):
            stars = star_options[i+1]
            cost = stars * STAR_PRICE
            price_text = f"{cost:.1f}₽".replace(".0₽", "₽")
            row.append(InlineKeyboardButton(f"{stars} звёзд - {price_text}", callback_data=f"stars_{stars}"))
        if row:
            keyboard.append(row)

    keyboard.append([InlineKeyboardButton("✨ Другое количество", callback_data="custom_stars")])
    keyboard.append([InlineKeyboardButton("🎫 Ввести промокод", callback_data="enter_promo")])

    await update.message.reply_text(
        "⭐ Выберите количество звёзд:\n"
        f"💰 Цена за 1 звезду: {STAR_PRICE}₽",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_gift_star_packages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает пакеты звезд для подарка"""
    query = update.callback_query
    user_id = query.from_user.id
    await send_admin_notification(context, user_id, "Выбирает звёзды в подарок")

    star_options = [50, 75, 100, 150, 200, 250, 300, 350, 400, 450,
                   500, 550, 600, 650, 700, 800, 900, 1000, 1500, 2000, 3000, 5000, 10000]

    keyboard = []
    for i in range(0, len(star_options), 2):
        row = []
        if i < len(star_options):
            stars = star_options[i]
            cost = stars * STAR_PRICE
            price_text = f"{cost:.1f}₽".replace(".0₽", "₽")
            row.append(InlineKeyboardButton(f"{stars} звёзд - {price_text}", callback_data=f"gift_stars_{stars}"))
        if i+1 < len(star_options):
            stars = star_options[i+1]
            cost = stars * STAR_PRICE
            price_text = f"{cost:.1f}₽".replace(".0₽", "₽")
            row.append(InlineKeyboardButton(f"{stars} звёзд - {price_text}", callback_data=f"gift_stars_{stars}"))
        if row:
            keyboard.append(row)

    keyboard.append([InlineKeyboardButton("✨ Другое количество", callback_data="gift_custom_stars")])
    keyboard.append([InlineKeyboardButton("🎫 Ввести промокод", callback_data="enter_promo_gift_stars")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="gift_back")])

    await query.edit_message_text(
        "⭐ Выберите количество звёзд для подарка:\n"
        f"💰 Цена за 1 звезду: {STAR_PRICE}₽",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_ton_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await send_admin_notification(context, user_id, "Выбирает количество TON")

    # Полный прайс TON
    ton_options = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 25, 30, 35, 40, 45, 50, 55, 60, 70, 80, 90, 100]

    keyboard = []
    # Создаем строки по 3 кнопки в каждой
    for i in range(0, len(ton_options), 3):
        row = []
        for j in range(3):
            if i + j < len(ton_options):
                ton = ton_options[i + j]
                cost = ton * TON_PRICE
                row.append(InlineKeyboardButton(f"{ton} TON", callback_data=f"ton_{ton}"))
        if row:
            keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⚡ Другое количество", callback_data="custom_ton")])
    keyboard.append([InlineKeyboardButton("🎫 Ввести промокод", callback_data="enter_promo_ton")])

    await update.message.reply_text(
        "💎 Выберите количество TON:\n"
        f"💰 Курс: 1 TON = {TON_PRICE}₽\n\n"
        "💎 TON придет на ваш юзернейм",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_gift_ton_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает пакеты TON для подарка"""
    query = update.callback_query
    user_id = query.from_user.id
    await send_admin_notification(context, user_id, "Выбирает TON в подарок")

    ton_options = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22, 25, 30, 35, 40, 45, 50, 55, 60, 70, 80, 90, 100]

    keyboard = []
    for i in range(0, len(ton_options), 3):
        row = []
        for j in range(3):
            if i + j < len(ton_options):
                ton = ton_options[i + j]
                cost = ton * TON_PRICE
                row.append(InlineKeyboardButton(f"{ton} TON", callback_data=f"gift_ton_{ton}"))
        if row:
            keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⚡ Другое количество", callback_data="gift_custom_ton")])
    keyboard.append([InlineKeyboardButton("🎫 Ввести промокод", callback_data="enter_promo_gift_ton")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="gift_back")])

    await query.edit_message_text(
        "⚡ Выберите количество TON для подарка:\n"
        f"💰 Курс: 1 TON = {TON_PRICE}₽",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🆘 Помощь и поддержка:\n\n"
        "⏳ После оплаты звёзды/TON или telegram premium приходят в течение 1-5 минут\n"
        "🔍 Если покупка не пришла, проверьте:\n"
        "  - Создан ли у Вас юзернейм\n"
        "  - Корректность реквизитов при оплате\n"
        "  - Совпадение суммы платежа\n"
        "  - Наличие скриншота чека (при оплате на карту или СБП)\n\n"
        f"📩 По всем вопросам обращайтесь к {SUPPORT_USERNAME}\n"
        "Мы всегда готовы помочь!"
    )
    await update.message.reply_text(help_text)

async def show_premium_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for period, price in PREMIUM_PRICES.items():
        keyboard.append([InlineKeyboardButton(f"🌟 {period} - {price}₽", callback_data=f"premium_{period}")])
    keyboard.append([InlineKeyboardButton("🎫 Ввести промокод", callback_data="enter_promo_premium")])

    await update.message.reply_text(
        "🌟 Telegram Premium подписка:\n\n"
        "Выберите срок подписки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_gift_premium_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает пакеты Premium для подарка"""
    query = update.callback_query
    keyboard = []
    for period, price in PREMIUM_PRICES.items():
        keyboard.append([InlineKeyboardButton(f"🌟 {period} - {price}₽", callback_data=f"gift_premium_{period}")])
    keyboard.append([InlineKeyboardButton("🎫 Ввести промокод", callback_data="enter_promo_gift_premium")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="gift_back")])

    await query.edit_message_text(
        "🌟 Выберите Telegram Premium подписку для подарка:\n\n"
        "Выберите срок подписки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ОБНОВЛЕННЫЕ ОБРАБОТЧИКИ ПЛАТЕЖЕЙ С УЧЕТОМ БАЛАНСА
async def process_star_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE, stars: int):
    user = update.callback_query.from_user if update.callback_query else update.message.from_user
    user_id = user.id

    # Проверяем баланс пользователя
    user_balance = get_user_balance(user_id)

    # Проверяем примененный промокод
    original_amount = stars * STAR_PRICE
    promo_code = applied_promocodes.get(user_id)

    if promo_code:
        final_amount, discount, message = calculate_discount(original_amount, promo_code, user_id)
        if discount > 0:
            amount = final_amount
            # Используем промокод
            use_promo_code(promo_code, user_id, "stars", original_amount, discount, final_amount)
            # Удаляем примененный промокод
            del applied_promocodes[user_id]
        else:
            amount = original_amount
    else:
        amount = original_amount

    # УБИРАЕМ автоматическое списание баланса - оставляем только проверку
    # Баланс будет списываться только после подтверждения админом

    await send_admin_notification(context, user_id, f"Начинает оплату {stars} звёзд на сумму {amount:.1f}₽")

    pending_payments[user_id] = {
        "amount": amount,
        "stars": stars,
        "timestamp": get_moscow_time()
    }

    text = (
        f"⭐ Вы выбрали {stars} звёзд\n"
        f"💰 Сумма к оплате: {amount:.1f}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        "💳 Способы оплаты:\n"
    )

    # Добавляем информацию о балансе только для информации
    if user_balance >= amount:
        balance_info = f"✅ Достаточно средств на балансе\n"
    else:
        balance_info = f"❌ Недостаточно средств на балансе\n"

    text += balance_info

    # ИСПРАВЛЕННАЯ КЛАВИАТУРА
    keyboard = [
        [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_payment_stars_{stars}")],
        [InlineKeyboardButton("💳 Оплатить через ЮMoney", url=f"https://yoomoney.ru/quickpay/confirm.xml?receiver={YM_ACCOUNT}&quickpay-form=small&targets=Звёзды {stars} шт&sum={amount}&label=stars_{stars}")],
        [InlineKeyboardButton("📱 Оплатить через СБП", callback_data="sbp_payment")],
        [InlineKeyboardButton("📲 Оплатить на карту", callback_data="card_payment")],
        [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data="crypto_payment")]
    ]

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def process_ton_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE, ton_amount: float):
    user = update.callback_query.from_user if update.callback_query else update.message.from_user
    user_id = user.id

    # Проверяем баланс пользователя
    user_balance = get_user_balance(user_id)

    # Проверяем примененный промокод
    original_amount = ton_amount * TON_PRICE
    promo_code = applied_promocodes.get(user_id)

    if promo_code:
        final_amount, discount, message = calculate_discount(original_amount, promo_code, user_id)
        if discount > 0:
            amount = final_amount
            # Используем промокод
            use_promo_code(promo_code, user_id, "ton", original_amount, discount, final_amount)
            # Удаляем примененный промокод
            del applied_promocodes[user_id]
        else:
            amount = original_amount
    else:
        amount = original_amount

    # УБИРАЕМ автоматическое списание баланса - оставляем только проверку
    # Баланс будет списываться только после подтверждения админом

    await send_admin_notification(context, user_id, f"Начинает оплату {ton_amount} TON на сумму {amount:.1f}₽")

    pending_payments[user_id] = {
        "amount": amount,
        "ton_amount": ton_amount,
        "timestamp": get_moscow_time(),
        "is_ton": True
    }

    text = (
        f"⚡ Вы выбрали {ton_amount} TON\n"
        f"💰 Сумма к оплате: {amount:.1f}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        "💳 Способы оплаты:\n"
    )

    # Добавляем информацию о балансе только для информации
    if user_balance >= amount:
        balance_info = f"✅ Достаточно средств на балансе\n"
    else:
        balance_info = f"❌ Недостаточно средств на балансе\n"

    text += balance_info

    # ИСПРАВЛЕННАЯ КЛАВИАТУРА
    keyboard = [
        [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_payment_ton_{ton_amount}")],
        [InlineKeyboardButton("💳 Оплатить через ЮMoney", url=f"https://yoomoney.ru/quickpay/confirm.xml?receiver={YM_ACCOUNT}&quickpay-form=small&targets=TON {ton_amount}&sum={amount}&label=ton_{ton_amount}")],
        [InlineKeyboardButton("📱 Оплатить через СБП", callback_data="sbp_payment_ton")],
        [InlineKeyboardButton("📲 Оплатить на карту", callback_data="card_payment_ton")],
        [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data="crypto_payment_ton")]
    ]

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def process_premium_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, period: str):
    user = update.callback_query.from_user
    user_id = user.id

    # Проверяем баланс пользователя
    user_balance = get_user_balance(user_id)

    # Проверяем примененный промокод
    original_amount = PREMIUM_PRICES[period]
    promo_code = applied_promocodes.get(user_id)

    if promo_code:
        final_amount, discount, message = calculate_discount(original_amount, promo_code, user_id)
        if discount > 0:
            amount = final_amount
            # Используем промокод
            use_promo_code(promo_code, user_id, "premium", original_amount, discount, final_amount)
            # Удаляем примененный промокод
            del applied_promocodes[user_id]
        else:
            amount = original_amount
    else:
        amount = original_amount

    # УБИРАЕМ автоматическое списание баланса - оставляем только проверку
    # Баланс будет списываться только после подтверждения админом

    await send_admin_notification(
        context,
        user_id,
        f"Начинает оплату Telegram Premium на {period} за {amount}₽"
    )

    pending_payments[user_id] = {
        "amount": amount,
        "period": period,
        "timestamp": get_moscow_time(),
        "is_premium": True
    }

    text = (
        f"🌟 Вы выбрали Telegram Premium на {period}\n"
        f"💰 Сумма к оплате: {amount}₽\n"
        f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"
        "💳 Способы оплаты:\n"
    )

    # Добавляем информацию о балансе только для информации
    if user_balance >= amount:
        balance_info = f"✅ Достаточно средств на балансе\n"
    else:
        balance_info = f"❌ Недостаточно средств на балансе\n"

    text += balance_info

    # ИСПРАВЛЕННАЯ КЛАВИАТУРА
    keyboard = [
        [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_payment_premium_{period}")],
        [InlineKeyboardButton("💳 Оплатить через ЮMoney", url=f"https://yoomoney.ru/quickpay/confirm.xml?receiver={YM_ACCOUNT}&quickpay-form=small&targets=Telegram Premium {period}&sum={amount}&label=premium_{period}")],
        [InlineKeyboardButton("📱 Оплатить через СБП", callback_data="sbp_payment")],
        [InlineKeyboardButton("📲 Оплатить на карту", callback_data="card_payment")],
        [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data="crypto_payment_premium")]
    ]

    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_friend_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    # Проверяем, не хочет ли пользователь отменить
    if update.message.text.lower() in ['отмена', 'cancel', 'отменить']:
        await cancel_payment_handler(update, context)
        return

    # ОЧИЩАЕМ awaiting_receipts если пользователь возвращается к вводу юзернейма
    if user_id in awaiting_receipts:
        del awaiting_receipts[user_id]
        logger.info(f"🔹🔹🔹 ОТЛАДКА: awaiting_receipts удален для {user_id}")

    # ПРИНИМАЕМ ЛЮБОЙ ТЕКСТ КАК ЮЗЕРНЕЙМ БЕЗ ЛЮБЫХ ПРОВЕРОК
    username_input = update.message.text.strip()

    logger.info(f"🔹🔹🔹 ОТЛАДКА: Получен юзернейм: '{username_input}' от пользователя {user_id}")

    # Форматируем юзернейм для отображения (добавляем @ если нет)
    formatted_username = username_input
    if not username_input.startswith('@'):
        formatted_username = f"@{username_input}"

    # Получаем информацию о подарке из временной базы данных
    gift_info = get_temp_gift(user_id)
    logger.info(f"🔹🔹🔹 ОТЛАДКА: gift_info из БД: {gift_info}")

    if not gift_info:
        logger.error(f"❌ Не найдена информация о подарке для пользователя {user_id}")
        await update.message.reply_text("❌ Ошибка: информация о подарке не найдена. Начните заново.")
        if user_id in awaiting_friend_username:
            del awaiting_friend_username[user_id]
        return

    # Обновляем подарок с юзернеймом
    gift_info["friend_username"] = formatted_username
    save_temp_gift(
        user_id=user_id,
        gift_type=gift_info["type"],
        amount=gift_info["amount"],
        period=gift_info["period"],
        cost=gift_info["cost"],
        friend_username=formatted_username
    )

    logger.info(f"🔹🔹🔹 ОТЛАДКА: Обновленный gift_info: {gift_info}")

    # ДУБЛИРУЕМ В user_data для надежности
    context.user_data['current_gift'] = gift_info
    context.user_data[f'gift_{user_id}'] = gift_info

    # Очищаем флаг ДО отправки сообщений
    if user_id in awaiting_friend_username:
        del awaiting_friend_username[user_id]
        logger.info(f"🔹🔹🔹 ОТЛАДКА: awaiting_friend_username удален для {user_id}")

    # Отправляем уведомление админу о создании подарка
    try:
        await send_gift_notification(context, user_id, gift_info)
        logger.info(f"✅ Уведомление админу отправлено")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомления админу: {e}")

    # ПОКАЗЫВАЕМ ИНФОРМАЦИЮ ДЛЯ ОПЛАТЫ С КНОПКОЙ "СПИСАТЬ С БАЛАНСА"
    await show_gift_payment_options(update.message, context, gift_info)

async def show_gift_payment_options(message, context: ContextTypes.DEFAULT_TYPE, gift_info: dict):
    """Показывает варианты оплаты для подарка с кнопкой списания с баланса"""
    try:
        user_id = message.from_user.id
        logger.info(f"🔹 Начало show_gift_payment_options для {user_id}")

        # Проверяем баланс пользователя
        user_balance = get_user_balance(user_id)

        # Создаем описание подарка
        text = f"🎁 Подарок для {gift_info['friend_username']} создан!\n\n"

        if gift_info["type"] == "stars":
            text += f"⭐ {gift_info['amount']} звёзд\n"
        elif gift_info["type"] == "ton":
            text += f"💎 {gift_info['amount']} TON\n"
        elif gift_info["type"] == "premium":
            text += f"🌟 Telegram Premium на {gift_info['period']}\n"

        text += f"💰 Сумма к оплате: {gift_info['cost']:.1f}₽\n"
        text += f"💳 Ваш баланс: {user_balance:.2f}₽\n\n"

        # ИСПРАВЛЕННАЯ КЛАВИАТУРА - правильный callback_data
        keyboard = [
            [InlineKeyboardButton("💳 Списать с баланса", callback_data="balance_payment_gift")],
            [InlineKeyboardButton("💳 Оплатить через ЮMoney", url=f"https://yoomoney.ru/quickpay/confirm.xml?receiver={YM_ACCOUNT}&quickpay-form=small&targets=Подарок&sum={gift_info['cost']}")],
            [InlineKeyboardButton("📱 Оплатить через СБП", callback_data="show_gift_sbp_info")],
            [InlineKeyboardButton("📲 Оплатить на карту", callback_data="show_gift_card_info")],
            [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data="show_gift_crypto_info")],
            [InlineKeyboardButton("🔙 Назад", callback_data="gift_back")]
        ]

        # Отправляем сообщение с кнопками
        await message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        logger.info(f"✅ Сообщение с кнопками оплаты отправлено пользователю {user_id}")

    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА в show_gift_payment_options: {e}")
        await message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")

async def show_gift_payment_info(message, context: ContextTypes.DEFAULT_TYPE, gift_info: dict):
    try:
        user_id = message.from_user.id
        logger.info(f"🔹 Начало show_gift_payment_info для {user_id}")

        # Создаем описание для ЮMoney
        description = ""
        text = f"🎁 Подарок для {gift_info['friend_username']} создан!\n\n"

        if gift_info["type"] == "stars":
            description = f"Подарок {gift_info['amount']} звёзд"
            text += f"⭐ {gift_info['amount']} звёзд\n"
        elif gift_info["type"] == "ton":
            description = f"Подарок {gift_info['amount']} TON"
            text += f"💎{gift_info['amount']} TON\n"
        elif gift_info["type"] == "premium":
            description = f"Подарок Premium {gift_info['period']}"
            text += f"🌟 Telegram Premium на {gift_info['period']}\n"

        text += f"💰 Сумма к оплате: {gift_info['cost']:.1f}₽\n"

        # СОЗДАЕМ ПРАВИЛЬНУЮ ССЫЛКУ ДЛЯ ЮMONEY
        try:
            # Формируем правильный URL для быстрой оплаты
            yoomoney_url = f"https://yoomoney.ru/quickpay/confirm.xml"
            params = {
                'receiver': YM_ACCOUNT,
                'quickpay-form': 'small',
                'targets': description,
                'sum': gift_info['cost'],
                'formcomment': description,
                'short-dest': description,
                'label': f"gift_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            }

            # Кодируем параметры
            encoded_params = urllib.parse.urlencode(params)
            yoomoney_url = f"{yoomoney_url}?{encoded_params}"
            logger.info(f"🔹 URL для ЮMoney создан: {yoomoney_url}")
        except Exception as e:
            logger.error(f"❌ Ошибка создания URL для ЮMoney: {e}")
            # Альтернативный простой URL
            yoomoney_url = f"https://yoomoney.ru/to/{YM_ACCOUNT}/{gift_info['cost']}"

        # ВАЖНО: Сохраняем информацию о подарке в user_data для кнопок
        context.user_data['current_gift'] = gift_info
        context.user_data[f'gift_{user_id}'] = gift_info
        logger.info(f"🔹 Подарок сохранен в user_data для кнопок: {gift_info}")

        # РАЗДЕЛЬНЫЕ КНОПКИ ДЛЯ КАЖДОГО СПОСОБА ОПЛАТЫ С ПРАВИЛЬНЫМИ ОБРАБОТЧИКАМИ
        keyboard = [
            [InlineKeyboardButton("💳 Оплатить через ЮMoney", url=yoomoney_url)],
            [InlineKeyboardButton("📱 Оплатить через СБП", callback_data="show_gift_sbp_info")],
            [InlineKeyboardButton("💳 Оплатить на карту", callback_data="show_gift_card_info")],
            [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data="show_gift_crypto_info")],
            [InlineKeyboardButton("🔙 Назад", callback_data="gift_back")]
        ]

        # Отправляем сообщение с кнопками (БЕЗ parse_mode)
        await message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        logger.info(f"✅ Сообщение с кнопками оплаты отправлено пользователю {user_id}")

    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА в show_gift_payment_info: {e}")
        # Простой вариант без кнопок
        try:
            await message.reply_text(
                f"🎁 Подарок для {gift_info['friend_username']} создан!\n\n"
                f"💰 Сумма к оплате: {gift_info['cost']:.1f}₽\n\n"
                "💳 Для оплаты используйте реквизиты:\n"
                f"ЮMoney: {YM_ACCOUNT}\n"
                f"СБП: {SBP_PHONE}\n"
                "Карты:\n"
                f"Альфа-Банк: {CARD_NUMBERS['Альфа-Банк']}\n"
                f"Тинькофф: {CARD_NUMBERS['Тинькофф']}\n"
                f"Сбер: {CARD_NUMBERS['Сбер']}\n\n"
                "После оплаты отправьте скриншот чека.\n\n"
                "❌ Для отмены отправьте 'отмена'"
            )
        except Exception as inner_e:
            logger.error(f"❌ Ошибка отправки простого сообщения: {inner_e}")

# ИСПРАВЛЕННЫЕ ФУНКЦИИ - показ информации об оплате с правильной навигацией
async def show_gift_sbp_payment_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    logger.info(f"🔹🔹🔹 ОТЛАДКА: Нажата кнопка СБП, user_id: {user_id}")

    # УЛУЧШЕННАЯ ЛОГИКА ПОЛУЧЕНИЯ ДАННЫХ О ПОДАРКЕ
    gift_info = None

    # 1. Пробуем получить из базы данных
    gift_info = get_temp_gift(user_id)
    logger.info(f"🔹🔹🔹 ОТЛАДКА: gift_info из БД: {gift_info}")

    # 2. Если нет в БД, пробуем из user_data
    if not gift_info:
        gift_info = context.user_data.get('current_gift')
        logger.info(f"🔹🔹🔹 ОТЛАДКА: gift_info из user_data current_gift: {gift_info}")

    # 3. Если все еще нет, пробуем по ключу user_id
    if not gift_info:
        gift_info = context.user_data.get(f'gift_{user_id}')
        logger.info(f"🔹🔹🔹 ОТЛАДКА: gift_info из user_data gift_{user_id}: {gift_info}")

    if not gift_info:
        logger.error(f"❌ ОТЛАДКА: gift_info не найден для пользователя {user_id}")
        await query.edit_message_text("❌ Ошибка: информация о подарке не найдена.")
        return

    await send_admin_notification(context, user_id, f"Выбрал оплату через СБП для подарка {gift_info['friend_username']}")

    text = (
        "📱 Оплата через СБП (Система быстрых платежей):\n\n"
        f"▪️ Номер телефона: <code>{SBP_PHONE}</code> (Т-Банк)\n"
        f"💰 Сумма к оплате: {gift_info['cost']:.1f}₽\n\n"
        f"🎁 Подарок для {gift_info['friend_username']}:\n"
    )

    if gift_info["type"] == "stars":
        text += f"⭐ {gift_info['amount']} звёзд\n"
    elif gift_info["type"] == "ton":
        text += f"💎 {gift_info['amount']} TON\n"
    elif gift_info["type"] == "premium":
        text += f"🌟 Telegram Premium на {gift_info['period']}\n"

    text += (
        "\n📌 После оплаты:\n"
        "1. Сделайте скриншот чека\n"
        "2. Отправьте его в этот чат\n"
        "3. Подарок будет отправлен в течение 5 минут\n\n"
        "🎁 Подарок будет отправлен на юзернейм пользователя, который вы указали"
    )

    # КНОПКИ С ПРАВИЛЬНЫМИ ОБРАБОТЧИКАМИ
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data="gift_back")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    awaiting_receipts[user_id] = True

async def show_gift_card_payment_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    logger.info(f"🔹🔹🔹 ОТЛАДКА: Нажата кнопка Карта, user_id: {user_id}")

    # УЛУЧШЕННАЯ ЛОГИКА ПОЛУЧЕНИЯ ДАННЫХ О ПОДАРКЕ
    gift_info = None

    # 1. Пробуем получить из базы данных
    gift_info = get_temp_gift(user_id)
    logger.info(f"🔹🔹🔹 ОТЛАДКА: gift_info из БД: {gift_info}")

    # 2. Если нет в БД, пробуем из user_data
    if not gift_info:
        gift_info = context.user_data.get('current_gift')
        logger.info(f"🔹🔹🔹 ОТЛАДКА: gift_info из user_data current_gift: {gift_info}")

    # 3. Если все еще нет, пробуем по ключу user_id
    if not gift_info:
        gift_info = context.user_data.get(f'gift_{user_id}')
        logger.info(f"🔹🔹🔹 ОТЛАДКА: gift_info из user_data gift_{user_id}: {gift_info}")

    if not gift_info:
        logger.error(f"❌ ОТЛАДКА: gift_info не найден для пользователя {user_id}")
        await query.edit_message_text("❌ Ошибка: информация о подарке не найдена.")
        return

    await send_admin_notification(context, user_id, f"Выбрал оплату на карту для подарка {gift_info['friend_username']}")

    text = "💳 Перевод на карту:\n\n"
    for bank, number in CARD_NUMBERS.items():
        # Убираем пробелы для удобного копирования
        clean_number = number.replace(" ", "")
        text += f"▪️ {bank}: <code>{clean_number}</code>\n"

    text += f"\n💰 Сумма к оплате: {gift_info['cost']:.1f}₽\n\n"
    text += f"🎁 Подарок для {gift_info['friend_username']}:\n"

    if gift_info["type"] == "stars":
        text += f"⭐ {gift_info['amount']} звёзд\n"
    elif gift_info["type"] == "ton":
        text += f"💎 {gift_info['amount']} TON\n"
    elif gift_info["type"] == "premium":
        text += f"🌟 Telegram Premium на {gift_info['period']}\n"

    text += (
        "\n📌 После оплаты:\n"
        "1. Сделайте скриншот чека\n"
        "2. Отправьте его в этот чат\n"
        "3. Подарок будет отправлен в течение 5 минут\n\n"
        "🎁 Подарок будет отправлен на юзернейм пользователя, который вы указали"
    )

    # КНОПКИ С ПРАВИЛЬНЫМИ ОБРАБОТЧИКАМИ
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data="gift_back")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    awaiting_receipts[user_id] = True

async def show_sbp_payment_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    # Получаем информацию о платеже
    payment_info = pending_payments.get(user_id, {})
    amount = payment_info.get('amount', 0)

    await send_admin_notification(context, user_id, "Выбрал оплату через СБП")

    text = (
        "📱 Оплата через СБП (Система быстрых платежей):\n\n"
        f"▪️ Номер телефона: <code>{SBP_PHONE}</code> (Т-Банк)\n"
        f"💰 Сумма к оплате: {amount:.1f}₽\n\n"
        "📌 После оплаты:\n"
        "1. Сделайте скриншот чека\n"
        "2. Отправьте его в этот чат\n"
        "3. Звёзды/TON/подписка будут зачислены в течение 5 минут\n\n"
    )

    # ИСПРАВЛЕНО: Динамически определяем правильную кнопку "Назад"
    back_button = None
    if 'is_premium' in payment_info:
        back_button = InlineKeyboardButton("🔙 Назад", callback_data="premium_back")
    elif 'is_ton' in payment_info:
        back_button = InlineKeyboardButton("🔙 Назад", callback_data="ton_back")
    else:
        back_button = InlineKeyboardButton("🔙 Назад", callback_data="buy_back")

    keyboard = [
        [back_button]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    awaiting_receipts[user_id] = True

async def show_card_payment_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    # Получаем информацию о платеже
    payment_info = pending_payments.get(user_id, {})
    amount = payment_info.get('amount', 0)

    await send_admin_notification(context, user_id, "Выбрал оплату на карту")

    text = "💳 Перевод на карту:\n\n"
    for bank, number in CARD_NUMBERS.items():
        # Убираем пробелы для удобного копирования
        clean_number = number.replace(" ", "")
        text += f"▪️ {bank}: <code>{clean_number}</code>\n"

    text += f"\n💰 Сумма к оплате: {amount:.1f}₽\n\n"
    text += (
        "📌 После оплаты:\n"
        "1. Сделайте скриншот чека\n"
        "2. Отправьте его в этот чат\n"
        "3. Звёзды/TON/подписка будут зачислены в течение 5 минут\n\n"
    )

    # ИСПРАВЛЕНО: Динамически определяем правильную кнопку "Назад"
    back_button = None
    if 'is_premium' in payment_info:
        back_button = InlineKeyboardButton("🔙 Назад", callback_data="premium_back")
    elif 'is_ton' in payment_info:
        back_button = InlineKeyboardButton("🔙 Назад", callback_data="ton_back")
    else:
        back_button = InlineKeyboardButton("🔙 Назад", callback_data="buy_back")

    keyboard = [
        [back_button]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    awaiting_receipts[user_id] = True

# ИСПРАВЛЕННАЯ ФУНКЦИЯ обработки чеков - теперь пересылает файл админу
async def handle_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает получение чека об оплате - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    user_id = update.message.from_user.id

    logger.info(f"🔹🔹🔹 ОТЛАДКА: Получено сообщение от {user_id} в handle_receipt")
    logger.info(f"🔹🔹🔹 ОТЛАДКА: Тип сообщения: фото={bool(update.message.photo)}, документ={bool(update.message.document)}")
    logger.info(f"🔹🔹🔹 ОТЛАДКА: awaiting_receipts состояние: {user_id in awaiting_receipts}")

    # 🔴 ВАЖНО: Проверяем, находится ли пользователь в состоянии ожидания чека
    if user_id not in awaiting_receipts:
        logger.info(f"🔹 Пользователь {user_id} не в состоянии awaiting_receipts")
        # Если это не чек, возможно, это обычное сообщение
        await handle_message(update, context)
        return

    if update.message.photo or update.message.document:
        logger.info(f"🔹 Пользователь {user_id} отправил скриншот чека")

        # 🔴 УЛУЧШЕННЫЙ ПОИСК ИНФОРМАЦИИ О ЗАКАЗЕ
        order_info = None

        # 1. Сначала проверяем pending_payments (обычные покупки)
        payment_info = pending_payments.get(user_id, {})
        logger.info(f"🔹🔹🔹 ОТЛАДКА: payment_info из pending_payments: {payment_info}")

        if payment_info:
            if payment_info.get('is_balance_replenishment'):
                order_info = {
                    "type": "balance",
                    "amount": payment_info.get('amount', 0),
                    "cost": payment_info.get('amount', 0),
                    "is_balance_replenishment": True
                }
                logger.info("🔹 Определен тип: ПОПОЛНЕНИЕ БАЛАНСА")
            elif payment_info.get('is_premium'):
                order_info = {
                    "type": "premium",
                    "amount": 1,
                    "cost": payment_info.get('amount', 0),
                    "period": payment_info.get('period', '')
                }
                logger.info("🔹 Определен тип: PREMIUM")
            elif payment_info.get('is_ton'):
                order_info = {
                    "type": "ton",
                    "amount": payment_info.get('ton_amount', 0),
                    "cost": payment_info.get('amount', 0)
                }
                logger.info("🔹 Определен тип: TON")
            else:
                order_info = {
                    "type": "stars",
                    "amount": payment_info.get('stars', 0),
                    "cost": payment_info.get('amount', 0)
                }
                logger.info("🔹 Определен тип: STARS")

        # 2. Если не нашли в pending_payments, проверяем подарки
        if not order_info:
            gift_info = get_temp_gift(user_id)
            logger.info(f"🔹🔹🔹 ОТЛАДКА: gift_info из БД: {gift_info}")

            if gift_info:
                order_info = {
                    "type": f"gift_{gift_info['type']}",
                    "amount": gift_info['amount'],
                    "cost": gift_info['cost'],
                    "friend_username": gift_info.get('friend_username', ''),
                    "period": gift_info.get('period', '')
                }
                logger.info(f"🔹 Определен тип: ПОДАРОК {gift_info['type']}")

        # 3. Если все еще не нашли, проверяем активные чеки пользователя
        if not order_info:
            user_checks = get_user_checks(user_id)
            active_checks = [c for c in user_checks if not c['is_activated']]
            logger.info(f"🔹🔹🔹 ОТЛАДКА: Активных чеков пользователя: {len(active_checks)}")

            if active_checks:
                # Берем последний активный чек пользователя
                latest_check = active_checks[0]
                order_info = {
                    "type": f"check_{latest_check['check_type']}",
                    "amount": latest_check['amount'],
                    "cost": latest_check['cost'],
                    "check_code": latest_check['check_code'],
                    "is_check": True
                }
                logger.info(f"🔹 Определен тип: ЧЕК {latest_check['check_type']}")

        # 4. Если вообще не нашли информацию, создаем общий заказ
        if not order_info:
            order_info = {
                "type": "unknown",
                "amount": 0,
                "cost": 0,
                "is_unknown": True
            }
            logger.warning("🔹 Тип заказа: НЕИЗВЕСТЕН")

        # 🔴 ОТПРАВЛЯЕМ ЧЕК АДМИНУ С ПРАВИЛЬНОЙ ИНФОРМАЦИЕЙ
        logger.info(f"🔹🔹🔹 ОТПРАВКА АДМИНУ: {order_info}")
        await send_receipt_to_admin(context, user_id, order_info, update.message)

        # 🔴 УВЕДОМЛЯЕМ ПОЛЬЗОВАТЕЛЯ
        await update.message.reply_text(
            "✅ Чек получен! Заказ отправлен на проверку.\n\n"
            "⏳ Обычно проверка занимает 1-15 минут.\n"
            "📞 Если возникли вопросы, обращайтесь к поддержке."
        )

        # 🔴 ОЧИЩАЕМ СОСТОЯНИЯ
        if user_id in awaiting_receipts:
            del awaiting_receipts[user_id]
            logger.info(f"✅ awaiting_receipts удален для {user_id}")

        if user_id in pending_payments:
            del pending_payments[user_id]
            logger.info(f"✅ pending_payments удален для {user_id}")

        # Очищаем временные данные о подарках
        delete_temp_gift(user_id)
        logger.info(f"✅ Временные подарки удалены для {user_id}")

    else:
        # Если пользователь отправил текст вместо чека
        if update.message.text and update.message.text.lower() in ['отмена', 'cancel', 'отменить']:
            await cancel_payment_handler(update, context)
        else:
            await update.message.reply_text(
                "📎 Пожалуйста, отправьте скриншот или фото чека об оплате.\n\n"
                "Если хотите отменить оплату, отправьте слово 'отмена'",
                reply_markup=get_cancel_keyboard()
            )

async def check_payment(context: ContextTypes.DEFAULT_TYPE) -> None:
    # Упрощенная версия без JobQueue
    pass

async def process_check_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод количества/периода для чека"""
    user_id = update.message.from_user.id

    if not context.user_data.get('awaiting_check_amount'):
        return

    check_type = context.user_data.get('current_check_type')
    user_input = update.message.text.strip()

    try:
        if check_type == "premium":
            # Обработка периода для Premium
            period_map = {
                '3 месяца': '3 месяца',
                '6 месяцев': '6 месяцев',
                '1 год': '1 год',
                '3': '3 месяца',
                '6': '6 месяцев',
                '12': '1 год',
                'год': '1 год'
            }

            if user_input.lower() not in period_map:
                await update.message.reply_text(
                    "❌ Неверный срок подписки. Используйте: 3 месяца, 6 месяцев, 1 год\n\n"
                    "Попробуйте еще раз:"
                )
                return

            period = period_map[user_input.lower()]
            amount = 1
            cost = PREMIUM_PRICES[period]

        else:
            # Обработка количества для stars и ton
            user_input = user_input.replace(',', '.').replace(' ', '')
            cleaned_input = ''.join(char for char in user_input if char.isdigit() or char == '.')

            if not cleaned_input:
                await update.message.reply_text("❌ Пожалуйста, введите корректное число")
                return

            amount = float(cleaned_input)

            if check_type == "stars":
                if amount < 50:
                    await update.message.reply_text("❌ Минимальное количество звёзд: 50")
                    return
                cost = amount * STAR_PRICE
            elif check_type == "ton":
                if amount <= 0:
                    await update.message.reply_text("❌ Количество TON должно быть больше 0")
                    return
                cost = amount * TON_PRICE

        # Сохраняем данные чека
        context.user_data['current_check'] = {
            'type': check_type,
            'amount': amount,
            'cost': cost,
            'period': period if check_type == "premium" else ""
        }

        # Очищаем состояние
        context.user_data['awaiting_check_amount'] = False
        if 'current_check_type' in context.user_data:
            del context.user_data['current_check_type']

        # Показываем подтверждение
        type_text = get_check_type_text(check_type)

        if check_type == "premium":
            description = f"🌟 Telegram Premium на {period}"
        else:
            unit = "звёзд" if check_type == "stars" else "TON"
            description = f"{type_text} {amount} {unit}"

        text = (
            f"🧾 Подтверждение создания чека\n\n"
            f"📦 Содержимое чека: {description}\n"
            f"💰 Стоимость: {cost:.2f}₽\n\n"
            f"💡 После оплаты вы получите уникальный код чека, который можно отправить любому пользователю.\n\n"
            f"Выберите способ оплаты:"
        )

        # Генерируем временный код для кнопок
        temp_code = f"temp_{user_id}_{datetime.now().strftime('%H%M%S')}"
        context.user_data['temp_check_code'] = temp_code

        keyboard = [
            [InlineKeyboardButton("💳 Оплатить через ЮMoney", callback_data=f"pay_check_{temp_code}")],
            [InlineKeyboardButton("📱 Оплатить через СБП", callback_data=f"sbp_check_{temp_code}")],
            [InlineKeyboardButton("📲 Оплатить на карту", callback_data=f"card_check_{temp_code}")],
            [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data=f"crypto_check_{temp_code}")],
            [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_check_{temp_code}")],
            [InlineKeyboardButton("🔙 Отменить", callback_data="cancel_check")]
        ]

        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    except ValueError:
        await update.message.reply_text("❌ Пожалуйста, введите корректное число")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    callback_data = query.data

    # 🔴🔴🔴 ДОБАВЛЕНО: ПРОВЕРКА БЛОКИРОВКИ ПОЛЬЗОВАТЕЛЯ
    if is_user_blocked(user_id):
        logger.info(f"🚫 Заблокированный пользователь {user_id} попытался использовать кнопку: {callback_data}")
        await query.edit_message_text(
            "🚫 Ваш аккаунт заблокирован!\n\n"
            "📞 Для разблокировки обратитесь к @KIRG_17 или @MANAGER_K17"
        )
        return

    logger.info(f"🔴🔴🔴 ОБРАБОТКА КНОПКИ: user_id={user_id}, callback_data='{callback_data}'")

    # 🔴🔴🔴 ВАЖНО: ПРАВИЛЬНЫЙ ПОРЯДОК ОБРАБОТЧИКОВ БЕЗ КОНФЛИКТОВ

    # 1. ПЕРВЫМИ - КРИТИЧЕСКИ ВАЖНЫЕ ОБРАБОТЧИКИ (подтверждение заказов)
    if callback_data.startswith("confirm_order_"):
        logger.info(f"🎯 ОБНАРУЖЕНА КНОПКА ПОДТВЕРЖДЕНИЯ: {callback_data}")
        order_id = int(callback_data.split("_")[2])
        await confirm_order(update, context, order_id)
        return

    elif callback_data.startswith("reject_order_"):
        logger.info(f"🎯 ОБНАРУЖЕНА КНОПКА ОТКЛОНЕНИЯ: {callback_data}")
        order_id = int(callback_data.split("_")[2])
        await reject_order(update, context, order_id)
        return

    elif callback_data == "confirm_all_orders":
        logger.info("🎯 ОБНАРУЖЕНА КНОПКА ПОДТВЕРЖДЕНИЯ ВСЕХ ЗАКАЗОВ")
        await confirm_all_orders(update, context)
        return

    # 🔴🔴🔴 ДОБАВЛЕНО: ОБРАБОТЧИКИ ВЫВОДА СРЕДСТВ (ДОЛЖНЫ БЫТЬ ВЫШЕ)
    elif callback_data == "withdraw_menu":
        logger.info("🔴 ОБРАБОТКА withdraw_menu")
        await show_withdrawal_menu(update, context)
        return

    elif callback_data.startswith("withdraw_"):
        logger.info(f"🔴 ОБРАБОТКА withdraw: {callback_data}")
        await handle_withdraw_method(update, context)
        return

    elif callback_data == "withdraw_history":
        logger.info("🔴 ОБРАБОТКА withdraw_history")
        await show_withdrawal_history(update, context)
        return

    # 🔴🔴🔴 ДОБАВЛЕНО: ОБРАБОТЧИК ОТМЕНЫ ВЫВОДА
    elif callback_data == "cancel_withdrawal":
        logger.info("🔴 ОБРАБОТКА cancel_withdrawal")
        # Очищаем состояние вывода
        if 'awaiting_withdrawal' in context.user_data:
            context.user_data['awaiting_withdrawal'] = False
        if 'awaiting_withdrawal_details' in context.user_data:
            context.user_data['awaiting_withdrawal_details'] = False
        if 'withdrawal_amount' in context.user_data:
            context.user_data['withdrawal_amount'] = None
        if 'withdraw_method' in context.user_data:
            context.user_data['withdraw_method'] = None

        await show_withdrawal_menu(update, context)
        return

    # 🔴🔴🔴 ДОБАВЛЕНО: ОБРАБОТЧИКИ ОДОБРЕНИЯ/ОТКЛОНЕНИЯ ВЫВОДА
    elif callback_data.startswith("approve_withdraw_"):
        logger.info(f"🔴 ОБРАБОТКА approve_withdraw: {callback_data}")
        # ИСПРАВЛЕНИЕ: вызываем без параметров, т.к. функции сами парсят callback_data
        await approve_withdrawal(update, context)
        return

    elif callback_data.startswith("reject_withdraw_"):
        logger.info(f"🔴 ОБРАБОТКА reject_withdraw: {callback_data}")
        # ИСПРАВЛЕНИЕ: вызываем без параметров, т.к. функции сами парсят callback_data
        await reject_withdrawal(update, context)
        return

    # 🔴🔴🔴 ДОБАВЛЕНО: ОБРАБОТЧИКИ ОПЛАТЫ ЧЕКОВ
    elif callback_data.startswith("pay_check_"):
        logger.info(f"🔴 ОБРАБОТКА pay_check: {callback_data}")
        check_code = callback_data.replace("pay_check_", "")
        await process_check_payment_callback(update, context, "yoomoney", check_code)
        return

    elif callback_data.startswith("sbp_check_"):
        logger.info(f"🔴 ОБРАБОТКА sbp_check: {callback_data}")
        check_code = callback_data.replace("sbp_check_", "")
        await process_check_payment_callback(update, context, "sbp", check_code)
        return

    elif callback_data.startswith("card_check_"):
        logger.info(f"🔴 ОБРАБОТКА card_check: {callback_data}")
        check_code = callback_data.replace("card_check_", "")
        await process_check_payment_callback(update, context, "card", check_code)
        return

    elif callback_data.startswith("crypto_check_"):
        logger.info(f"🔴 ОБРАБОТКА crypto_check: {callback_data}")
        check_code = callback_data.replace("crypto_check_", "")
        await process_check_payment_callback(update, context, "crypto", check_code)
        return

    elif callback_data.startswith("balance_check_"):
        logger.info(f"🔴 ОБРАБОТКА balance_check: {callback_data}")
        check_code = callback_data.replace("balance_check_", "")
        await process_check_payment_callback(update, context, "balance", check_code)
        return

    # 🔴🔴🔴 ДОБАВЛЕНО: ОБРАБОТЧИК ДЛЯ КНОПКИ "НАЗАД" В ЧЕКАХ
    elif callback_data.startswith("back_to_payment_"):
        logger.info(f"🔴 ОБРАБОТКА back_to_payment: {callback_data}")
        check_code = callback_data.replace("back_to_payment_", "")

        # Получаем информацию о чеке
        check = get_check_by_code(check_code)
        if not check:
            await query.edit_message_text("❌ Чек не найден")
            return

        # Показываем меню выбора способов оплаты
        type_text = get_check_type_text(check['check_type'])
        if check['check_type'] == "premium":
            description = f"🌟 Telegram Premium"
        else:
            unit = "звёзд" if check['check_type'] == "stars" else "TON"
            description = f"{type_text} {check['amount']} {unit}"

        text = (
            f"🧾 Подтверждение создания чека\n\n"
            f"📦 Содержимое чека: {description}\n"
            f"💰 Стоимость: {check['cost']:.2f}₽\n"
            f"🎫 Код чека: {check_code}\n\n"
            f"💡 После оплаты вы получите этот код, который можно отправить любому пользователю.\n\n"
            f"Выберите способ оплаты:"
        )

        keyboard = [
            [InlineKeyboardButton("💳 Оплатить через ЮMoney", callback_data=f"pay_check_{check_code}")],
            [InlineKeyboardButton("📱 Оплатить через СБП", callback_data=f"sbp_check_{check_code}")],
            [InlineKeyboardButton("📲 Оплатить на карту", callback_data=f"card_check_{check_code}")],
            [InlineKeyboardButton("₿ Оплатить криптовалютой", callback_data=f"crypto_check_{check_code}")],
            [InlineKeyboardButton("💳 Списать с баланса", callback_data=f"balance_check_{check_code}")],
            [InlineKeyboardButton("🔙 Отменить", callback_data="cancel_check")]
        ]

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # 🔴🔴🔴 ДОБАВЛЕНО: ОБРАБОТЧИКИ РЕФЕРАЛЬНОЙ ПРОГРАММЫ
    elif callback_data == "referral_program":
        logger.info("🔴 ОБРАБОТКА referral_program")
        await show_referral_program(update, context)
        return

    elif callback_data == "ref_history":
        logger.info("🔴 ОБРАБОТКА ref_history")
        await show_referral_history(update, context)
        return

    elif callback_data == "admin_ref_stats":
        logger.info("🔴 ОБРАБОТКА admin_ref_stats")
        await show_admin_referral_stats(update, context)
        return

    # 2. ВТОРЫМИ - ОСНОВНАЯ НАВИГАЦИЯ (главное меню, профиль и т.д.)
    elif callback_data == "back_to_main":
        logger.info("🔴 ОБРАБОТКА back_to_main")
        await query.edit_message_text(
            "🔥 Добро пожаловать в бота для покупки звёзд/premium и TON!\n\n👇Выберите действие:",
            reply_markup=get_main_menu_keyboard()
        )
        return

    elif callback_data == "admin_back":
        logger.info("🔴 ОБРАБОТКА admin_back")
        await query.edit_message_text(
            "👨‍💻 Админ-панель:",
            reply_markup=get_admin_keyboard()
        )
        return

    elif callback_data == "profile_back":
        logger.info("🔴 ОБРАБОТКА profile_back")
        await show_user_profile_callback(update, context)
        return

    # 3. ТРЕТЬИМИ - АДМИН-ПАНЕЛЬ
    elif callback_data == "admin_stats":
        logger.info("🔴 ОБРАБОТКА admin_stats")
        await show_admin_stats(update, context)
        return

    elif callback_data == "admin_confirm_orders":
        logger.info("🔴 ОБРАБОТКА admin_confirm_orders")
        await show_pending_orders(update, context)
        return

    elif callback_data == "admin_all_users":
        logger.info("🔴 ОБРАБОТКА admin_all_users")
        await show_all_users(update, context, page=0)
        return

    elif callback_data.startswith("users_page_"):
        page = int(callback_data.split("_")[2])
        logger.info(f"🔴 ОБРАБОТКА users_page_{page}")
        await show_all_users(update, context, page)
        return

    elif callback_data == "admin_add_balance":
        logger.info("🔴 ОБРАБОТКА admin_add_balance")
        await admin_add_balance(update, context)
        return

    elif callback_data == "broadcast":
        logger.info("🔴 ОБРАБОТКА broadcast")
        await start_broadcast(update, context)
        return

    elif callback_data == "cancel_broadcast":
        logger.info("🔴 ОБРАБОТКА cancel_broadcast")
        await cancel_broadcast(update, context)
        return

    elif callback_data == "stop_broadcast":
        logger.info("🔴 ОБРАБОТКА stop_broadcast")
        await stop_broadcast(update, context)
        return

    elif callback_data == "admin_restart":
        logger.info("🔴 ОБРАБОТКА admin_restart")
        await admin_restart(update, context)
        return

    # 4. ЧЕТВЕРТЫМИ - ОСНОВНЫЕ КНОПКИ ПОКУПОК (звезды, TON, premium)
    elif callback_data == "buy_stars":
        logger.info("🔴 ОБРАБОТКА buy_stars")
        await show_star_packages(update, context)
        return

    elif callback_data == "buy_ton":
        logger.info("🔴 ОБРАБОТКА buy_ton")
        await show_ton_options(update, context)
        return

    elif callback_data == "buy_premium":
        logger.info("🔴 ОБРАБОТКА buy_premium")
        await show_premium_options(update, context)
        return

    elif callback_data.startswith("stars_"):
        stars = int(callback_data.split("_")[1])
        await process_star_purchase(update, context, stars)
        return

    elif callback_data.startswith("ton_"):
        ton_amount = float(callback_data.split("_")[1])
        await process_ton_purchase(update, context, ton_amount)
        return

    elif callback_data.startswith("premium_"):
        period = callback_data.split("_")[1]
        await process_premium_payment(update, context, period)
        return

    elif callback_data == "custom_stars":
        await request_custom_stars(update, context)
        return

    elif callback_data == "custom_ton":
        await request_custom_ton(update, context)
        return

    # 5. ПЯТЫМИ - ОПЛАТА С БАЛАНСА
    elif callback_data.startswith("balance_payment_"):
        logger.info(f"🔴 ОБРАБОТКА balance_payment: {callback_data}")

        if callback_data.startswith("balance_payment_stars_"):
            stars = int(callback_data.split("_")[3])
            await process_balance_payment_stars(update, context, stars)
            return

        elif callback_data.startswith("balance_payment_ton_"):
            ton_amount = float(callback_data.split("_")[3])
            await process_balance_payment_ton(update, context, ton_amount)
            return

        elif callback_data.startswith("balance_payment_premium_"):
            period = callback_data.split("_")[3]
            await process_balance_payment_premium(update, context, period)
            return

        elif callback_data == "balance_payment_gift":
            await process_balance_payment_gift(update, context)
            return

    # 6. ШЕСТЫМИ - ПОДАРКИ
    elif callback_data == "make_gift":
        logger.info("🔴 ОБРАБОТКА make_gift")
        await show_gift_options(update, context)
        return

    elif callback_data == "gift_stars":
        logger.info("🔴 ОБРАБОТКА gift_stars")
        await show_gift_star_packages(update, context)
        return

    elif callback_data == "gift_ton":
        logger.info("🔴 ОБРАБОТКА gift_ton")
        await show_gift_ton_options(update, context)
        return

    elif callback_data == "gift_premium":
        logger.info("🔴 ОБРАБОТКА gift_premium")
        await show_gift_premium_options(update, context)
        return

    elif callback_data.startswith("gift_stars_"):
        stars = int(callback_data.split("_")[2])
        await process_gift_star_purchase(update, context, stars)
        return

    elif callback_data.startswith("gift_ton_"):
        ton_amount = float(callback_data.split("_")[2])
        await process_gift_ton_purchase(update, context, ton_amount)
        return

    elif callback_data.startswith("gift_premium_"):
        period = callback_data.split("_")[2]
        await process_gift_premium_purchase(update, context, period)
        return

    elif callback_data == "gift_custom_stars":
        await request_gift_custom_stars(update, context)
        return

    elif callback_data == "gift_custom_ton":
        await request_gift_custom_ton(update, context)
        return

    elif callback_data == "gift_back":
        logger.info("🔴 ОБРАБОТКА gift_back")
        await show_gift_options(update, context)
        return

    # 7. СЕДЬМЫМИ - ЧЕКИ (ИСПРАВЛЕННАЯ ВЕРСИЯ)
    elif callback_data == "my_checks":
        logger.info("🔴 ОБРАБОТКА my_checks")
        await show_my_checks(update, context)
        return

    elif callback_data == "create_check_menu":
        logger.info("🔴 ОБРАБОТКА create_check_menu")
        await show_create_check_menu(update, context)
        return

    elif callback_data.startswith("create_check_"):
        check_type = callback_data.split('_')[2]
        logger.info(f"🔴 ОБРАБОТКА create_check_{check_type}")
        await start_create_check(update, context, check_type)
        return

    elif callback_data == "activate_check":
        logger.info("🔴 ОБРАБОТКА activate_check")
        await activate_user_check(update, context)
        return

    elif callback_data.startswith("claim_check_"):
        check_code = callback_data.split('_')[2]
        logger.info(f"🔴 ОБРАБОТКА получения чека: {check_code}")
        await claim_check(update, context, check_code)
        return

    elif callback_data == "cancel_check":
        logger.info("🔴 ОБРАБОТКА cancel_check")
        await cancel_check_creation(update, context)
        return

    elif callback_data == "checks_back":
        logger.info("🔴 ОБРАБОТКА checks_back")
        await show_my_checks(update, context)
        return

    # 8. ВОСЬМЫМИ - ПРОМОКОДЫ
    elif callback_data == "admin_promocodes":
        logger.info("🔴 ОБРАБОТКА admin_promocodes")
        await show_promocodes_menu(update, context)
        return

    elif callback_data == "list_promos":
        logger.info("🔴 ОБРАБОТКА list_promos")
        await list_promocodes(update, context)
        return

    elif callback_data == "create_promo":
        logger.info("🔴 ОБРАБОТКА create_promo")
        await create_promo_step_by_step(update, context)
        return

    elif callback_data == "enter_promo":
        logger.info("🔴 ОБРАБОТКА enter_promo для звезд")
        await enter_promo_code(update, context, "stars")
        return

    elif callback_data == "enter_promo_ton":
        logger.info("🔴 ОБРАБОТКА enter_promo_ton")
        await enter_promo_code(update, context, "ton")
        return

    elif callback_data == "enter_promo_premium":
        logger.info("🔴 ОБРАБОТКА enter_promo_premium")
        await enter_promo_code(update, context, "premium")
        return

    elif callback_data == "enter_promo_gift":
        logger.info("🔴 ОБРАБОТКА enter_promo_gift")
        await enter_promo_code(update, context, "gift")
        return

    elif callback_data == "my_promocodes":
        await show_my_promocodes(update, context)
        return

    # 9. ДЕВЯТЫМИ - КОНВЕРТЕР ВАЛЮТ
    elif callback_data == "currency_rates":
        logger.info("🔴 ОБРАБОТКА currency_rates")
        await show_currency_rates(update, context)
        return

    elif callback_data == "currency_converter":
        logger.info("🔴 ОБРАБОТКА currency_converter")
        await show_currency_converter(update, context)
        return

    elif callback_data == "refresh_rates":
        logger.info("🔴 ОБРАБОТКА refresh_rates")
        await refresh_currency_rates(update, context)
        return

    elif callback_data in ["convert_usd_rub", "convert_eur_rub", "convert_ton_rub", "convert_usdt_rub",
                          "convert_rub_usd", "convert_rub_eur", "convert_rub_ton", "convert_rub_usdt"]:
        logger.info(f"🔴 ОБРАБОТКА конвертации: {callback_data}")
        await start_currency_conversion(update, context, callback_data)
        return

    elif callback_data == "show_rates":
        logger.info("🔴 ОБРАБОТКА show_rates")
        await show_currency_rates(update, context)
        return

    # 10. ДЕСЯТЫМИ - ОПЛАТА (обычные способы)
    elif callback_data in ["card_payment", "card_payment_ton"]:
        await show_card_payment_info(update, context)
        return

    elif callback_data in ["sbp_payment", "sbp_payment_ton"]:
        await show_sbp_payment_info(update, context)
        return

    elif callback_data == "card_payment_balance":
        await show_card_payment_info(update, context)
        return

    elif callback_data == "sbp_payment_balance":
        await show_sbp_payment_info(update, context)
        return

    elif callback_data == "show_gift_card_info":
        await show_gift_card_payment_info(update, context)
        return

    elif callback_data == "show_gift_sbp_info":
        await show_gift_sbp_payment_info(update, context)
        return

    elif callback_data == "show_gift_crypto_info":
        await show_gift_crypto_payment_info(update, context)
        return

    elif callback_data == "crypto_payment":
        await show_crypto_payment_info(update, context, "stars")
        return

    elif callback_data == "crypto_payment_ton":
        await show_crypto_payment_info(update, context, "ton")
        return

    elif callback_data == "crypto_payment_premium":
        await show_crypto_payment_info(update, context, "premium")
        return

    # 11. НАВИГАЦИЯ ПО ПОКУПКАМ
    elif callback_data == "buy_back":
        logger.info("🔴 ОБРАБОТКА buy_back")
        await show_star_packages(update, context)
        return

    elif callback_data == "ton_back":
        logger.info("🔴 ОБРАБОТКА ton_back")
        await show_ton_options(update, context)
        return

    elif callback_data == "premium_back":
        logger.info("🔴 ОБРАБОТКА premium_back")
        await show_premium_options(update, context)
        return

    # 12. ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ
    elif callback_data == "replenish_balance":
        await replenish_balance(update, context)
        return

    # 🔴 ДОБАВЛЕН ОБРАБОТЧИК ДЛЯ АКТИВАЦИИ ЧЕКА ИЗ ПРОФИЛЯ
    elif callback_data == "activate_check":
        logger.info("🔴 ОБРАБОТКА activate_check из профиля")
        await activate_check_from_profile(update, context)
        return

    elif callback_data == "my_promocodes":
        await show_my_promocodes(update, context)
        return

    # 13. СТАТИСТИКА ВЫРУЧКИ
    elif callback_data == "decrease_revenue":
        await decrease_revenue(update, context)
        return

    elif callback_data == "increase_revenue":
        await increase_revenue(update, context)
        return

    # ЕСЛИ НИ ОДИН ОБРАБОТЧИК НЕ СРАБОТАЛ
    else:
        logger.warning(f"⚠️ Неизвестный callback_data: {callback_data}")
        await query.edit_message_text(
            "❌ Неизвестная команда. Возврат в главное меню...",
            reply_markup=get_main_menu_keyboard()
        )
        return

 # Команда для отладки заказов
async def debug_orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для отладки заказов"""
    if update.effective_user.id != ADMIN_ID:
        return

    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    # Проверяем pending_orders
    cursor.execute('SELECT COUNT(*) FROM pending_orders WHERE status = "pending"')
    pending_count = cursor.fetchone()[0]

    # Проверяем структуру таблицы
    cursor.execute("PRAGMA table_info(pending_orders)")
    table_info = cursor.fetchall()

    conn.close()

    debug_text = f"""
🐛 ОТЛАДКА БАЗЫ ДАННЫХ:

📋 pending_orders:
- Заказов в ожидании: {pending_count}
- Структура таблицы: {[col[1] for col in table_info]}
"""

    await update.message.reply_text(debug_text)

async def process_check_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод кода чека для активации"""
    user_id = update.message.from_user.id
    check_code = update.message.text.strip().upper()

    if check_code.lower() in ['отмена', 'cancel', 'отменить']:
        context.user_data['awaiting_check_code_input'] = False
        await update.message.reply_text(
            "✅ Активация чека отменена",
            reply_markup=get_main_menu_keyboard()
        )
        return

    # Проверяем чек
    check = get_check_by_code(check_code)

    if not check:
        await update.message.reply_text(
            "❌ Чек не найден или уже активирован\n\n"
            "Проверьте код и попробуйте еще раз:"
        )
        return

    if check['is_activated']:
        await update.message.reply_text(
            "❌ Этот чек уже был активирован\n\n"
            "Введите другой код:"
        )
        return

    # Создаем заказ в ожидании для админского подтверждения
    user = await context.bot.get_chat(user_id)
    creator = await context.bot.get_chat(check['creator_id'])

    order_id = save_pending_order(
        user_id=user_id,
        username=user.username,
        full_name=user.full_name,
        order_type=f"check_activation_{check['check_type']}",
        amount=check['amount'],
        cost=0,  # Чек уже оплачен создателем
        receipt_message_id=update.message.message_id,
        is_balance_replenishment=False,
        friend_username=check_code
    )

    # Уведомляем пользователя
    type_text = get_check_type_text(check['check_type'])

    if check['check_type'] == "premium":
        description = f"🌟 Telegram Premium"
    else:
        unit = "звёзд" if check['check_type'] == "stars" else "TON"
        description = f"{type_text} {check['amount']} {unit}"

    await update.message.reply_text(
        f"🎉 Чек принят в обработку!\n\n"
        f"📦 Вы активировали: {description}\n"
        f"🎫 Код чека: {check_code}\n\n"
        f"⏳ Заказ отправлен на подтверждение администратору.\n"
        f"Обычно это занимает 1-15 минут.\n\n"
        f"📞 Вы получите уведомление, когда чек будет активирован.\n\n"
        f"Спасибо за использование нашего сервиса! ❤️",
        reply_markup=get_main_menu_keyboard()
    )

    # Отправляем уведомление админу с кнопками подтверждения
    moscow_time = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

    admin_message = (
        f"🎫 АКТИВАЦИЯ ЧЕКА!\n\n"
        f"👤 Активатор: @{user.username} (ID: {user_id})\n"
        f"👤 Создатель: @{creator.username} (ID: {check['creator_id']})\n"
        f"🎫 Код чека: {check_code}\n"
        f"📦 Содержимое: {description}\n"
        f"💰 Стоимость: {check['cost']:.2f}₽ (уже оплачено)\n"
        f"⏰ Время (МСК): {moscow_time}\n\n"
        f"✅ Подтвердите активацию чека:"
    )

    admin_msg = await context.bot.send_message(
        ADMIN_ID,
        admin_message,
        reply_markup=get_order_confirmation_keyboard(order_id)
    )

    update_order_status(order_id, "pending", admin_msg.message_id)

    # Очищаем состояние
    context.user_data['awaiting_check_code_input'] = False

    logger.info(f"✅ Запрос на активацию чека {check_code} создан (заказ #{order_id})")

async def confirm_check_activation(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int):
    """Подтверждает активацию чека администратором"""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return

    # Получаем информацию о заказе активации чека
    order = get_pending_order(order_id)
    if not order:
        await query.edit_message_text("❌ Заказ не найден")
        return

    # Получаем информацию о чеке по коду
    check_code = order['friend_username']  # В этом поле хранится код чека
    check = get_check_by_code(check_code)

    if not check:
        await query.edit_message_text("❌ Чек не найден")
        return

    if check['is_activated']:
        await query.edit_message_text("❌ Этот чек уже был активирован ранее")
        return

    # Активируем чек в базе данных
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()

    try:
        # Обновляем статус чека
        activated_date = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
        UPDATE checks
        SET is_activated = 1, activated_by = ?, activated_date = ?, status = 'activated'
        WHERE check_code = ?
        ''', (order['user_id'], activated_date, check_code))

        # Обновляем статус заказа
        update_order_status(order_id, "confirmed")

        conn.commit()

        # Уведомляем пользователя об успешной активации
        try:
            user = await context.bot.get_chat(order['user_id'])
            type_text = get_check_type_text(check['check_type'])

            if check['check_type'] == "premium":
                description = f"🌟 Telegram Premium"
            else:
                unit = "звёзд" if check['check_type'] == "stars" else "TON"
                description = f"{type_text} {check['amount']} {unit}"

            message_text = (
                f"🎉 Чек успешно активирован!\n\n"
                f"📦 Вы получили: {description}\n"
                f"🎫 Код чека: {check_code}\n\n"
                f"Спасибо за использование нашего сервиса! ❤️"
            )

            await context.bot.send_message(
                order['user_id'],
                message_text,
                reply_markup=get_main_menu_keyboard()
            )

            # Уведомляем создателя чека об активации
            await notify_check_creator(context, check, order['user_id'])

        except Exception as e:
            logger.error(f"❌ Ошибка уведомления пользователя: {e}")

        # Обновляем сообщение админа
        await query.edit_message_text(
            f"✅ Чек активирован!\n\n"
            f"🎫 Код: {check_code}\n"
            f"👤 Активатор: @{order['username']}\n"
            f"📦 Содержимое: {description}\n"
            f"💰 Стоимость: {check['cost']:.2f}₽",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 К списку заказов", callback_data="admin_confirm_orders")],
                [InlineKeyboardButton("🔙 В админ-панель", callback_data="admin_stats")]
            ])
        )

        logger.info(f"✅ Чек {check_code} активирован пользователем {order['user_id']}")

    except Exception as e:
        logger.error(f"❌ Ошибка активации чека: {e}")
        await query.edit_message_text(f"❌ Ошибка активации чека: {e}")

    finally:
        conn.close()

    # 🔴 Проверяем состояние активации чека
    if context.user_data.get('awaiting_check_activation'):
       logger.info(f"🔹 Пользователь {user_id} активирует чек")
       await process_check_activation(update, context)
       return

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Основной обработчик всех входящих сообщений"""
    user_id = update.message.from_user.id
    message_text = update.message.text

    # Обновляем активность пользователя
    update_user_activity(user_id)

    logger.info(f"🔹🔹🔹 ОСНОВНОЙ ОБРАБОТЧИК: user_id={user_id}, текст='{message_text}'")

    # 🔴 ВАЖНО: Сначала проверяем команды отмены
    if message_text and message_text.lower() in ['отмена', 'cancel', 'отменить']:
        await universal_cancel(update, context)
        return

    # 🔴🔴🔴 ДОБАВЛЕНО: ОБРАБОТКА СОЗДАНИЯ ПРОМОКОДА АДМИНОМ
    if user_id == ADMIN_ID and context.user_data.get('promo_creation'):
        promo_data = context.user_data['promo_creation']
        current_step = promo_data.get('step')

        logger.info(f"🎫 ОБРАБОТКА СОЗДАНИЯ ПРОМОКОДА: шаг {current_step}, данные: {promo_data}")

        if current_step == 1:  # Ввод кода промокода
            await process_promo_code_input(update, context)
            return
        elif current_step == 2:  # Ввод процента скидки
            await process_promo_discount_input(update, context)
            return
        elif current_step == 3:  # Ввод количества использований
            await process_promo_uses_input(update, context)
            return

    # 🔴🔴🔴 ДОБАВЛЕНО: ОБРАБОТКА ВВОДА СУММЫ ДЛЯ ВЫВОДА
    if context.user_data.get('awaiting_withdrawal'):
        logger.info(f"🔴 ОБРАБОТКА ВВОДА СУММЫ ВЫВОДА для пользователя {user_id}")
        await process_withdrawal_amount(update, context)
        return

    # 🔴🔴🔴 ДОБАВЛЕНО: ОБРАБОТКА ВВОДА РЕКВИЗИТОВ ДЛЯ ВЫВОДА
    if context.user_data.get('awaiting_withdrawal_details'):
        logger.info(f"🔴 ОБРАБОТКА ВВОДА РЕКВИЗИТОВ ВЫВОДА для пользователя {user_id}")
        await process_withdrawal_details(update, context)
        return

    # 🔴 ВАЖНО: Затем проверяем специальные состояния
    special_states = [
        (awaiting_receipts, "awaiting_receipts"),
        (awaiting_friend_username, "awaiting_friend_username"),
        (awaiting_promo_code, "awaiting_promo_code"),
        (awaiting_custom_stars, "awaiting_custom_stars"),
        (awaiting_custom_ton, "awaiting_custom_ton"),
        (conversion_data, "conversion_data"),
        (awaiting_balance_amount, "awaiting_balance_amount"),
        (awaiting_user_search, "awaiting_user_search"),
        (awaiting_promo_creation, "awaiting_promo_creation")
    ]

    for state_dict, state_name in special_states:
        if user_id in state_dict:
            logger.info(f"🔹 Обнаружено специальное состояние: {state_name} для пользователя {user_id}")

            if state_name == "awaiting_receipts":
                if message_text and not (update.message.photo or update.message.document):
                    await update.message.reply_text(
                        "📎 Пожалуйста, отправьте скриншот чека об оплате.\n\n"
                        "Если хотите отменить оплату, отправьте слово 'отмена'",
                        reply_markup=get_cancel_keyboard()
                    )
                    return
                else:
                    await handle_receipt(update, context)
                    return

            elif state_name == "awaiting_friend_username":
                await handle_friend_username(update, context)
                return

            elif state_name == "awaiting_promo_code":
                await process_promo_input(update, context)
                return

            elif state_name == "awaiting_custom_stars":
                await process_custom_stars(update, context)
                return

            elif state_name == "awaiting_custom_ton":
                await process_custom_ton(update, context)
                return

            elif state_name == "conversion_data":
                await process_conversion_input(update, context)
                return

            elif state_name == "awaiting_balance_amount":
                if context.user_data.get('admin_balance'):
                    await process_admin_balance_amount(update, context)
                else:
                    await process_balance_replenishment(update, context)
                return

            elif state_name == "awaiting_user_search":
                await process_admin_balance(update, context)
                return

            elif state_name == "awaiting_promo_creation":
                await process_my_promo_creation(update, context)
                return

    # 🔴 Проверяем состояния в context.user_data
    if context.user_data.get('awaiting_promo') and user_id == ADMIN_ID:
        logger.info(f"🔹 Админ создает промокод")
        await process_promo_creation(update, context)
        return

    # 🔴 Проверяем состояния для чеков
    if context.user_data.get('awaiting_check_activation'):
        logger.info(f"🔹 Пользователь {user_id} активирует чек")
        await process_check_activation(update, context)
        return

    if context.user_data.get('awaiting_check_amount'):
        logger.info(f"🔹 Пользователь {user_id} вводит количество для чека")
        await process_check_amount_input(update, context)
        return

    if context.user_data.get('awaiting_check_photo'):
        logger.info(f"🔹 Пользователь {user_id} отправляет фото для чека")
        await process_check_photo(update, context)
        return

    if context.user_data.get('awaiting_check_code_input'):
        logger.info(f"🔹 Пользователь {user_id} вводит код чека для активации")
        await process_check_code_input(update, context)
        return

    # 🔴 Проверяем рассылку
    if context.user_data.get('broadcast') and user_id == ADMIN_ID:
        logger.info(f"🔹 Админ {user_id} делает рассылку")
        await process_broadcast(update, context)
        return

    # 🔴 ТЕПЕРЬ ОБРАБАТЫВАЕМ ОБЫЧНЫЕ КОМАНДЫ МЕНЮ
    logger.info(f"🔹 Обработка обычной команды меню: '{message_text}'")

    # Словарь команд меню
    menu_commands = {
        "⭐ Купить звёзды": show_star_packages,
        "💎 Купить TON": show_ton_options,
        "ℹ️ Помощь": show_help,
        "🎁 Сделать подарок": show_gift_options_menu,
        "🌟 Telegram Premium": show_premium_options,
        "🛍️ Продажа аккаунтов": show_accounts_menu,
        "💱 Актуальные курсы": show_currency_rates,
        "👤 Мой профиль": show_user_profile,
        "🏠 Главное меню": start,
        "В меню": start,
        "меню": start,
        "главное меню": start,
        "начать": start
    }

    if message_text in menu_commands:
        logger.info(f"✅ Выполнение команды меню: {message_text}")
        try:
            await menu_commands[message_text](update, context)
        except Exception as e:
            logger.error(f"❌ Ошибка выполнения команды {message_text}: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при выполнении команды. Попробуйте еще раз.",
                reply_markup=get_main_menu_keyboard()
            )
        return

    # 🔴 Если команда не распознана
    logger.warning(f"⚠️ Неизвестная команда: '{message_text}'")
    await unknown_command(update, context)

async def debug_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отладочная команда для проверки состояния"""
    if update.effective_user.id != ADMIN_ID:
        return

    state_info = {
        'broadcast': context.user_data.get('broadcast', False),
        'broadcast_active': context.user_data.get('broadcast_active', False),
        'awaiting_promo': context.user_data.get('awaiting_promo', False)
    }

    # Получаем информацию о состояниях пользователя
    user_id = update.effective_user.id
    user_states = {
        'awaiting_receipts': user_id in awaiting_receipts,
        'awaiting_friend_username': user_id in awaiting_friend_username,
        'awaiting_promo_code': user_id in awaiting_promo_code,
        'awaiting_custom_stars': user_id in awaiting_custom_stars,
        'awaiting_custom_ton': user_id in awaiting_custom_ton,
        'conversion_data': user_id in conversion_data,
        'awaiting_balance_amount': user_id in awaiting_balance_amount,
        'awaiting_user_search': user_id in awaiting_user_search,
        'awaiting_promo_creation': user_id in awaiting_promo_creation,
    }

    await update.message.reply_text(
        f"🔧 СОСТОЯНИЕ СИСТЕМЫ:\n"
        f"📢 Рассылка: {state_info['broadcast']}\n"
        f"🔄 Рассылка активна: {state_info['broadcast_active']}\n"
        f"🎫 Ожидание промокода: {state_info['awaiting_promo']}\n"
        f"💾 user_data keys: {list(context.user_data.keys())}\n\n"
        f"👤 СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЯ:\n"
        f"📎 Ожидание чека: {user_states['awaiting_receipts']}\n"
        f"👥 Ожидание юзернейма: {user_states['awaiting_friend_username']}\n"
        f"🎫 Ожидание промокода: {user_states['awaiting_promo_code']}\n"
        f"⭐ Ожидание звезд: {user_states['awaiting_custom_stars']}\n"
        f"💎 Ожидание TON: {user_states['awaiting_custom_ton']}\n"
        f"💱 Конвертация: {user_states['conversion_data']}\n"
        f"💰 Ожидание баланса: {user_states['awaiting_balance_amount']}\n"
        f"🔍 Поиск пользователя: {user_states['awaiting_user_search']}\n"
        f"🎁 Создание промо: {user_states['awaiting_promo_creation']}"
    )

async def debug_promo_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отладочная команда для проверки состояния создания промокода"""
    if update.effective_user.id != ADMIN_ID:
        return

    promo_data = context.user_data.get('promo_creation', {})
    await update.message.reply_text(
        f"🔧 СОСТОЯНИЕ СОЗДАНИЯ ПРОМОКОДА:\n"
        f"Шаг: {promo_data.get('step', 'не установлен')}\n"
        f"Тип: {promo_data.get('type', 'не установлен')}\n"
        f"Код: {promo_data.get('code', 'не установлен')}\n"
        f"Скидка: {promo_data.get('discount_percent', 0)}%\n"
        f"Все ключи user_data: {list(context.user_data.keys())}"
    )
async def handle_admin_promo_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает создание промокода админом"""
    try:
        if not context.user_data.get('promo_creation'):
            await update.message.reply_text("❌ Процесс создания промокода не активен")
            return

        promo_data = context.user_data['promo_creation']
        current_step = promo_data.get('step', 1)

        logger.info(f"🎯 Обработка создания промокода, шаг {current_step}")

        if current_step == 1:
            await process_promo_code_input(update, context)
        elif current_step == 2:
            await process_promo_discount_input(update, context)
        elif current_step == 3:
            await process_promo_uses_input(update, context)
        else:
            await update.message.reply_text("❌ Неизвестный шаг процесса")

    except Exception as e:
        logger.error(f"❌ Ошибка в handle_admin_promo_creation: {e}")
        await update.message.reply_text("❌ Ошибка при создании промокода")

async def debug_promo_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет состояние промокодов"""
    user_id = update.effective_user.id

    states = {
        'awaiting_promo_code': user_id in awaiting_promo_code,
        'applying_promo_for': context.user_data.get('applying_promo_for'),
        'awaiting_promo_input': context.user_data.get('awaiting_promo_input'),
        'promo_product_type': context.user_data.get('promo_product_type')
    }

    await update.message.reply_text(
        f"🔧 Состояние промокодов для {user_id}:\n"
        f"• awaiting_promo_code: {states['awaiting_promo_code']}\n"
        f"• applying_promo_for: {states['applying_promo_for']}\n"
        f"• awaiting_promo_input: {states['awaiting_promo_input']}\n"
        f"• promo_product_type: {states['promo_product_type']}\n\n"
        f"💾 user_data: {list(context.user_data.keys())}"
    )

async def force_reset_promo_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительный сброс состояния создания промокода"""
    if update.effective_user.id != ADMIN_ID:
        return

    if 'promo_creation' in context.user_data:
        del context.user_data['promo_creation']
        logger.info("🔧 Принудительно сброшено состояние создания промокода")

    await update.message.reply_text(
        "🔧 Состояние создания промокода сброшено. Можно начинать заново.",
        reply_markup=get_admin_keyboard()
    )

async def replenish_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс пополнения баланса"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("❌ Отменить пополнение", callback_data="profile_back")]
    ]

    await query.edit_message_text(
        "💰 Пополнение баланса\n\n"
        "💵 Введите сумму для пополнения (в рублях):\n\n"
        '❌ Для отмены нажмите кнопку ниже, а лучше отправьте слово "Отмена"',  # ← Одинарные внешние кавычки
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    awaiting_balance_amount[query.from_user.id] = True

async def check_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить конкретный промокод"""
    if update.effective_user.id != ADMIN_ID:
        return

    if context.args:
        code = context.args[0].upper()
        promo = get_promo_code(code)

        if promo:
            await update.message.reply_text(
                f"✅ Промокод {code} найден:\n"
                f"Скидка: {promo['discount_percent']}%\n"
                f"Использований: {promo['used_count']}/{promo['max_uses']}\n"
                f"Активен: {'Да' if promo['is_active'] else 'Нет'}"
            )
        else:
            await update.message.reply_text(f"❌ Промокод {code} не найден или неактивен")
    else:
        await update.message.reply_text("Использование: /check_promo CODE")

async def debug_current_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка текущего состояния пользователя"""
    user_id = update.message.from_user.id

    states = {
        'awaiting_receipts': user_id in awaiting_receipts,
        'awaiting_friend_username': user_id in awaiting_friend_username,
        'awaiting_promo_code': user_id in awaiting_promo_code,
        'awaiting_custom_stars': user_id in awaiting_custom_stars,
        'awaiting_custom_ton': user_id in awaiting_custom_ton,
        'conversion_data': user_id in conversion_data,
        'awaiting_balance_amount': user_id in awaiting_balance_amount,
        'awaiting_user_search': user_id in awaiting_user_search,
        'promo_creation': bool(context.user_data.get('promo_creation')),
        'broadcast': bool(context.user_data.get('broadcast')),
    }

    active_states = [state for state, active in states.items() if active]

    text = f"🔧 ТЕКУЩЕЕ СОСТОЯНИЕ пользователя {user_id}:\n\n"
    if active_states:
        text += "Активные состояния:\n" + "\n".join(f"• {state}" for state in active_states)
    else:
        text += "❌ Нет активных состояний"

    await update.message.reply_text(text)

async def fix_promo_system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрое исправление системы промокодов"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет доступа")
        return

    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        # 1. Удаляем дублирующую таблицу
        cursor.execute("DROP TABLE IF EXISTS promocodes")

        # 2. Пересоздаем основную таблицу с правильной структурой
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS promo_codes (
            promo_id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            discount_percent REAL DEFAULT 0,
            discount_amount REAL DEFAULT 0,
            min_amount REAL DEFAULT 0,
            max_uses INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            valid_until TEXT,
            is_active INTEGER DEFAULT 1,
            created_date TEXT,
            created_by INTEGER,
            gift_amount REAL DEFAULT 0,
            gift_type TEXT DEFAULT 'balance'
        )
        ''')

        # 3. Создаем тестовый промокод
        now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
        INSERT OR IGNORE INTO promo_codes
        (code, discount_percent, max_uses, used_count, is_active, created_date)
        VALUES (?, ?, ?, 0, 1, ?)
        ''', ("TESTFIX10", 10, 100, now))

        conn.commit()
        conn.close()

        await update.message.reply_text(
            "✅ Система промокодов исправлена!\n"
            "• Удалена дублирующая таблица\n"
            "• Создана единая таблица promo_codes\n"
            "• Тестовый промокод TESTFIX10 создан\n\n"
            "Теперь можно создавать промокоды через админ-панель!"
        )

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def quick_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрое создание промокода через команду"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет доступа")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /quick_promo CODE DISCOUNT_PERCENT [MAX_USES]\n"
            "Примеры:\n"
            "/quick_promo TEST10 10 - 10% скидка, 100 использований\n"
            "/quick_promo SUMMER25 25 50 - 25% скидка, 50 использований"
        )
        return

    code = context.args[0].upper()
    discount_percent = float(context.args[1])
    max_uses = int(context.args[2]) if len(context.args) > 2 else 100

    success, message = create_promo_code(
        code=code,
        discount_percent=discount_percent,
        max_uses=max_uses
    )

async def show_all_checks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все активные чеки"""
    user_id = update.effective_user.id

    checks = get_active_checks(20)

    if not checks:
        await update.message.reply_text("📭 На данный момент нет активных чеков")
        return

    text = "🎁 АКТИВНЫЕ ЧЕКИ:\n\n"
    for check in checks:
        type_text = get_check_type_text(check['check_type'])
        if check['check_type'] == "premium":
            description = f"🌟 Telegram Premium"
        else:
            unit = "звёзд" if check['check_type'] == "stars" else "TON"
            description = f"{type_text} {check['amount']} {unit}"

        text += f"• {description} - {check['cost']:.2f}₽\n"
        text += f"  Код: {check['check_code']}\n"
        text += f"  ──────────────────\n"

    await update.message.reply_text(text)

async def cancel_check_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Упрощенная версия отмены с диагностикой"""
    query = update.callback_query
    user_id = query.from_user.id

    logger.info(f"🔴 ОТМЕНА ЧЕКА пользователем {user_id}")

    # Сначала отвечаем на callback query
    try:
        await query.answer("✅ Отменено")
        logger.info(f"✅ Callback query answered for user {user_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка в query.answer: {e}")

    # Очищаем состояния
    states_cleared = []
    for key in list(context.user_data.keys()):
        if any(check_word in key.lower() for check_word in ['check', 'awaiting', 'current']):
            del context.user_data[key]
            states_cleared.append(key)

    logger.info(f"🔴 Очищены состояния: {states_cleared}")

    # Пытаемся отредактировать сообщение
    try:
        await query.edit_message_text(
            text="🎯 Активация чека отменена",
            reply_markup=None
        )
        logger.info(f"✅ Сообщение отредактировано для user {user_id}")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось отредактировать сообщение: {e}")

    # Всегда отправляем новое сообщение с меню
    try:
        message = await context.bot.send_message(
            chat_id=user_id,
            text="Вы вернулись в главное меню:",
            reply_markup=get_main_menu_keyboard()
        )
        logger.info(f"✅ Новое меню отправлено для user {user_id}, message_id: {message.message_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки меню: {e}")

async def cancel_check_creation_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Упрощенная текстовая отмена"""
    user_id = update.message.from_user.id
    logger.info(f"🔴 ТЕКСТОВАЯ ОТМЕНА ЧЕКА для пользователя {user_id}")

    # Очищаем состояния
    states_to_clear = [
        'awaiting_check_activation', 'awaiting_check_amount', 'awaiting_check_photo',
        'awaiting_check_code_input', 'current_check_type', 'current_check_amount',
        'current_check_code', 'check_creation_type', 'check_creation_amount'
    ]

    cleared = []
    for state in states_to_clear:
        if state in context.user_data:
            del context.user_data[state]
            cleared.append(state)

    logger.info(f"🔴 Очищены: {cleared}")

    # Отправляем подтверждение отмены
    try:
        message = await update.message.reply_text(
            "✅ Активация чека отменена\n\nВозврат в главное меню:",
            reply_markup=get_main_menu_keyboard()
        )
        logger.info(f"✅ Текст отмены отправлен, message_id: {message.message_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки текста отмены: {e}")
        # Пробуем альтернативный способ
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ Активация чека отменена",
                reply_markup=get_main_menu_keyboard()
            )
        except Exception as e2:
            logger.error(f"❌ Критическая ошибка: {e2}")

async def universal_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Универсальная функция отмены для всех процессов"""
    user_id = update.message.from_user.id
    logger.info(f"🔴 УНИВЕРСАЛЬНАЯ ОТМЕНА для пользователя {user_id}")

    # 🔴 ОТМЕНА АКТИВАЦИИ ЧЕКА
    if (context.user_data.get('awaiting_check_activation') or
        context.user_data.get('awaiting_check_amount') or
        context.user_data.get('awaiting_check_photo') or
        context.user_data.get('awaiting_check_code_input')):
        await cancel_check_creation_text(update, context)
        return

    # 🔴 ОТМЕНА ВЫВОДА СРЕДСТВ
    if (context.user_data.get('awaiting_withdrawal') or
        context.user_data.get('awaiting_withdrawal_details')):
        await cancel_withdrawal_process(update, context)
        return

    # 🔴 ОТМЕНА СОЗДАНИЯ ПРОМОКОДА
    if context.user_data.get('promo_creation'):
        del context.user_data['promo_creation']
        await update.message.reply_text(
            "✅ Создание промокода отменено.",
            reply_markup=get_admin_keyboard()
        )
        return

    # 🔴 ОТМЕНА ВВОДА ПРОМОКОДА
    if user_id in awaiting_promo_code:
        del awaiting_promo_code[user_id]
        # Очищаем user_data
        for key in ['applying_promo_for', 'awaiting_promo_input', 'promo_product_type']:
            if key in context.user_data:
                del context.user_data[key]
        await update.message.reply_text(
            "✅ Ввод промокода отменен.",
            reply_markup=get_main_menu_keyboard()
        )
        return

    # 🔴 ОТМЕНА РАССЫЛКИ
    if context.user_data.get('broadcast'):
        await cancel_broadcast(update, context)
        return

    # 🔴 ОТМЕНА ДРУГИХ ПРОЦЕССОВ
    states_to_check = [
        (awaiting_receipts, "ожидания чека"),
        (awaiting_friend_username, "ввода username"),
        (awaiting_custom_stars, "ввода звезд"),
        (awaiting_custom_ton, "ввода TON"),
        (conversion_data, "конвертации валют"),
        (awaiting_balance_amount, "пополнения баланса"),
        (awaiting_user_search, "поиска пользователя"),
        (awaiting_promo_creation, "создания промокода")
    ]

    for state_dict, state_name in states_to_check:
        if user_id in state_dict:
            del state_dict[user_id]
            await update.message.reply_text(
                f"✅ Процесс {state_name} отменен.",
                reply_markup=get_main_menu_keyboard()
            )
            return

    # 🔴 ОТМЕНА ПО УМОЛЧАНИЮ
    await update.message.reply_text(
        "✅ Действие отменено.\n\n👇 Возврат в главное меню:",
        reply_markup=get_main_menu_keyboard()
    )

async def block_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для блокировки пользователя по username или user_id"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет доступа к этой команде")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Использование: /block <username/user_id> <причина>\n\n"
            "Примеры:\n"
            "/block @username Спам\n"
            "/block 12345678 Нарушение правил"
        )
        return

    try:
        target = context.args[0]
        reason = ' '.join(context.args[1:])

        logger.info(f"🔴 Попытка блокировки: {target}, причина: {reason}")

        # Определяем что ввел пользователь - username или user_id
        user_id = None

        if target.startswith('@'):
            # Это username
            username = target[1:]  # Убираем @
            user_id = get_user_id_by_username(username)
            if not user_id:
                await update.message.reply_text(f"❌ Пользователь @{username} не найден в базе")
                return
        else:
            # Это user_id
            try:
                user_id = int(target)
            except ValueError:
                await update.message.reply_text("❌ Неверный формат. Используйте @username или user_id")
                return

        # Проверяем существование пользователя
        user_info = get_user_info(user_id)
        logger.info(f"🔴 Информация о пользователе: {user_info}")

        if user_info['username'] == 'Не найден':
            await update.message.reply_text("❌ Пользователь не найден в базе")
            return

        # Блокируем пользователя
        success = block_user(user_id, reason, update.effective_user.id)

        if success:
            # Уведомляем пользователя о блокировке
            try:
                await context.bot.send_message(
                    user_id,
                    f"🚫 Ваш аккаунт заблокирован!\n\n"
                    f"📋 Причина: {reason}\n\n"
                    f"📞 Для разблокировки обратитесь к @KIRG_17 или @MANAGER_K17"
                )
                logger.info(f"✅ Уведомление о блокировке отправлено пользователю {user_id}")
            except Exception as e:
                logger.error(f"❌ Не удалось уведомить пользователя о блокировке: {e}")

            await update.message.reply_text(
                f"✅ Пользователь заблокирован!\n\n"
                f"👤 ID: {user_id}\n"
                f"👤 Имя: {user_info['full_name']}\n"
                f"📛 Username: @{user_info['username']}\n"
                f"📋 Причина: {reason}"
            )
        else:
            await update.message.reply_text("❌ Ошибка при блокировке пользователя")

    except Exception as e:
        logger.error(f"❌ Критическая ошибка в block_user_command: {e}")
        await update.message.reply_text(f"❌ Критическая ошибка: {e}")

async def unblock_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для разблокировки пользователя по username или user_id"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет доступа к этой команде")
        return

    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "❌ Использование: /unblock <username/user_id>\n\n"
            "Примеры:\n"
            "/unblock @username\n"
            "/unblock 12345678"
        )
        return

    try:
        target = context.args[0]

        # Определяем что ввел пользователь - username или user_id
        user_id = None

        if target.startswith('@'):
            # Это username
            username = target[1:]  # Убираем @
            user_id = get_user_id_by_username(username)
            if not user_id:
                await update.message.reply_text(f"❌ Пользователь @{username} не найден в базе")
                return
        else:
            # Это user_id
            try:
                user_id = int(target)
            except ValueError:
                await update.message.reply_text("❌ Неверный формат. Используйте @username или user_id")
                return

        # Проверяем, заблокирован ли пользователь
        if not is_user_blocked(user_id):
            await update.message.reply_text("❌ Пользователь не заблокирован")
            return

        # Разблокируем пользователя
        success = unblock_user(user_id)

        if success:
            # Уведомляем пользователя о разблокировке
            try:
                await context.bot.send_message(
                    user_id,
                    "✅ Ваш аккаунт разблокирован!\n\n"
                    "Теперь вы снова можете пользоваться ботом."
                )
                logger.info(f"✅ Уведомление о разблокировке отправлено пользователю {user_id}")
            except Exception as e:
                logger.error(f"❌ Не удалось уведомить пользователя о разблокировке: {e}")

            await update.message.reply_text(f"✅ Пользователь {user_id} разблокирован")
        else:
            await update.message.reply_text("❌ Ошибка при разблокировке пользователя")

    except Exception as e:
        logger.error(f"❌ Критическая ошибка в unblock_user_command: {e}")
        await update.message.reply_text(f"❌ Критическая ошибка: {e}")

def get_user_id_by_username(username):
    """Находит ID пользователя по username"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('SELECT user_id FROM users WHERE username = ?', (username,))
        result = cursor.fetchone()

        conn.close()
        return result[0] if result else None

    except Exception as e:
        logger.error(f"❌ Ошибка поиска пользователя по username {username}: {e}")
        return None

def block_user(user_id, reason="Не указана", blocked_by_admin_id=None):
    """Блокирует пользователя"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        now = get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

        logger.info(f"🔴 Создание подключения к БД для блокировки пользователя {user_id}")

        # Сначала проверяем есть ли уже запись
        cursor.execute('SELECT user_id FROM blocked_users WHERE user_id = ?', (user_id,))
        existing = cursor.fetchone()

        if existing:
            # Обновляем существующую запись
            cursor.execute('''
            UPDATE blocked_users
            SET blocked_date = ?, reason = ?, blocked_by_admin_id = ?, is_blocked = 1, unblocked_date = NULL
            WHERE user_id = ?
            ''', (now, reason, blocked_by_admin_id, user_id))
            logger.info(f"🔴 Обновлена существующая запись блокировки для {user_id}")
        else:
            # Создаем новую запись
            cursor.execute('''
            INSERT INTO blocked_users
            (user_id, blocked_date, reason, blocked_by_admin_id, is_blocked)
            VALUES (?, ?, ?, ?, 1)
            ''', (user_id, now, reason, blocked_by_admin_id))
            logger.info(f"🔴 Создана новая запись блокировки для {user_id}")

        conn.commit()
        conn.close()
        logger.info(f"✅ Пользователь {user_id} заблокирован. Причина: {reason}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка блокировки пользователя {user_id}: {e}")
        return False

def unblock_user(user_id):
    """Разблокирует пользователя"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        UPDATE blocked_users
        SET is_blocked = 0, unblocked_date = ?
        WHERE user_id = ? AND is_blocked = 1
        ''', (get_moscow_time().strftime("%Y-%m-%d %H:%M:%S"), user_id))

        conn.commit()
        conn.close()
        logger.info(f"🟢 Пользователь {user_id} разблокирован")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка разблокировки пользователя {user_id}: {e}")
        return False

def is_user_blocked(user_id):
    """Проверяет, заблокирован ли пользователь"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        SELECT is_blocked, reason, blocked_date, blocked_by_admin_id
        FROM blocked_users
        WHERE user_id = ? AND is_blocked = 1
        ''', (user_id,))

        result = cursor.fetchone()
        conn.close()

        return bool(result)
    except Exception as e:
        logger.error(f"❌ Ошибка проверки блокировки пользователя {user_id}: {e}")
        return False

def get_blocked_users():
    """Получает список заблокированных пользователей"""
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute('''
        SELECT bu.user_id, bu.blocked_date, bu.reason, bu.blocked_by_admin_id,
               u.username, u.full_name
        FROM blocked_users bu
        LEFT JOIN users u ON bu.user_id = u.user_id
        WHERE bu.is_blocked = 1
        ORDER BY bu.blocked_date DESC
        ''')

        blocked_users = cursor.fetchall()
        conn.close()

        result = []
        for user in blocked_users:
            result.append({
                'user_id': user[0],
                'blocked_date': user[1],
                'reason': user[2],
                'blocked_by_admin_id': user[3],
                'username': user[4] or 'Нет username',
                'full_name': user[5] or 'Неизвестно'
            })

        return result
    except Exception as e:
        logger.error(f"❌ Ошибка получения списка заблокированных пользователей: {e}")
        return []

async def show_blocked_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список заблокированных пользователей"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ У вас нет доступа к этой команде")
        return

    blocked_users = get_blocked_users()

    if not blocked_users:
        await update.message.reply_text("📋 Список заблокированных пользователей пуст")
        return

    text = "🔴 ЗАБЛОКИРОВАННЫЕ ПОЛЬЗОВАТЕЛИ:\n\n"

    for i, user in enumerate(blocked_users, 1):
        admin_info = get_user_info(user['blocked_by_admin_id'])
        admin_name = admin_info['full_name'] if admin_info['full_name'] != 'Ошибка' else 'Система'

        text += (
            f"{i}. 👤 {user['full_name']} (@{user['username']})\n"
            f"   🆔 ID: {user['user_id']}\n"
            f"   📋 Причина: {user['reason']}\n"
            f"   🕒 Дата: {user['blocked_date'][:16]}\n"
            f"   👨‍💼 Заблокировал: {admin_name}\n"
            f"   ──────────────────\n"
        )

    await update.message.reply_text(text)

# Добавьте проверку блокировки в начале обработки сообщений
async def check_user_blocked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет, заблокирован ли пользователь"""
    user_id = update.effective_user.id

    if is_user_blocked(user_id):
        logger.info(f"🚫 Заблокированный пользователь {user_id} попытался использовать бота")

        # Отправляем сообщение только если это не callback query
        if update.message:
            await update.message.reply_text(
                "🚫 Ваш аккаунт заблокирован!\n\n"
                "📞 Для разблокировки обратитесь к @KIRG_17 или @MANAGER_K17"
            )

        return True
    return False

# ГЛАВНАЯ ФУНКЦИЯ
def main() -> None:
    # Создаем приложение
    application = ApplicationBuilder().token(TOKEN).build()

    # Инициализация базы данных
    init_db()

    # 🔴 ДОБАВЛЕНО: Инициализация таблицы checks
    print("🔧 Инициализация таблицы checks...")
    init_checks_db()

    # 🔴 ДОБАВЛЕНО: Инициализация таблицы blocked_users
    print("🔧 Инициализация таблицы blocked_users...")
    create_blocked_users_table()

    # 🔴 ДОБАВЛЕНО: Проверка структуры таблицы (для отладки)
    def check_table_structure():
        """Проверяет структуру таблицы checks"""
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(checks)")
        columns = cursor.fetchall()

        print("📊 Структура таблицы checks:")
        for column in columns:
            print(f"  {column[1]} ({column[2]})")

        conn.close()

    check_table_structure()

    # 🔴🔴🔴 ВАЖНО: ПРАВИЛЬНЫЙ ПОРЯДОК ОБРАБОТЧИКОВ 🔴🔴🔴

    # 1. Обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_click))

    # 2. Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("check", check_bot_command))
    application.add_handler(CommandHandler("debug_orders", debug_orders_command))
    application.add_handler(CommandHandler("hide", hide_keyboard_command))
    application.add_handler(CommandHandler("debug_state", debug_state))
    application.add_handler(CommandHandler("debug_promo", debug_promo_state))
    application.add_handler(CommandHandler("reset_promo", force_reset_promo_state))
    application.add_handler(CommandHandler("check_promo", check_promo))
    application.add_handler(CommandHandler("debug_state", debug_current_state))
    application.add_handler(CommandHandler("fix_promo_system", fix_promo_system))
    application.add_handler(CommandHandler("quick_promo", quick_promo))
    application.add_handler(CommandHandler("simple_promo", create_simple_promo))
    application.add_handler(CommandHandler("checks", show_all_checks))
    application.add_handler(CommandHandler("block", block_user_command))
    application.add_handler(CommandHandler("unblock", unblock_user_command))
    application.add_handler(CommandHandler("blocked_list", show_blocked_users))

    # 3. Основной обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 4. Обработчики медиа-сообщений (чеки)
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_message))

    # 5. Обработчик для скрытия клавиатуры
    application.add_handler(MessageHandler(
        filters.ALL & ~filters.TEXT & ~filters.PHOTO & ~filters.Document.ALL & ~filters.COMMAND,
        hide_keyboard
    ))

    # Запускаем бота
    logger.info("🤖 Бот запущен и готов к работе!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()