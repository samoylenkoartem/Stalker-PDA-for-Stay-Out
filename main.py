import os
import platform
import queue
import random
import sqlite3 as sq
import threading
import time
import tkinter as tk
from datetime import datetime, timezone

import pygetwindow as gw
import pytesseract as pts
from dotenv import load_dotenv
from fuzzywuzzy import fuzz
from groq import Groq
from PIL import ImageGrab

if platform.system() == "Windows":
    pts.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise ValueError("GROQ_API_KEY is missing! Create a .env file with your key.")

# Инициализация ИИ
client = Groq(api_key=api_key)

KEYWORDS = ["Уро", "Ранил", "Убил", "Погиб", "Аномал"]

# Получение информации об окне игры
def get_window_info(x_start=None, x_end=None, y_length=None, y_end=None):
    """
Возвращает координаты и размеры окна игры Stay Out через pygetwindow.
- Если аргументы не переданы — возвращает (left, top, width, height) окна.
- Если переданы смещения — возвращает абсолютные координаты на экране.
"""
    try:
        window = gw.getWindowsWithTitle("Stay Out")
        if not window:
            print("Запусти игру")
            return None
        windows = window[0]
        if windows.isMinimized:
            time.sleep(1)
            return None
        if x_start is None and x_end is None and y_length is None:
                return (windows.left, windows.top, windows.width, windows.height)
        X_START = windows.left + x_start
        X_END = windows.left + x_end
        Y_LENGTH = windows.top + y_length
        if y_end is not None:
            Y_END = windows.top + y_end
            return (X_START, X_END, Y_LENGTH, Y_END)
        else:
            return (X_START, X_END, Y_LENGTH)
    except IndexError:
        print("Ошибка: окно не найдено")
        return None
    except Exception as e:  # noqa: BLE001
        print(f"Неизвестная ошибка: {e}")
        return None

# Функция настройки интерфейса
def start_tracker():
    """ Обработчик нажатия кнопки запуска в Tkinter:
    1. Считывает ключевые слова из текстового поля интерфейса.
    2. Очищает их от лишних пробелов и разбивает через запятую в список GLOBAL KEYWORDS.
    3. Закрывает окно Tkinter (root.destroy()), чтобы свернуть интерфейс 
       и освободить ресурсы для работы основных потоков.
    """
    
    global KEYWORDS
    text = text_field.get("1.0",tk.END).strip()
    KEYWORDS = text.split(',')
    KEYWORDS = [elem.strip() for elem in KEYWORDS]
    root.destroy()

# Функция симуляции чата
def emulate_chat():
    """ 
    Поток-симулятор (используется для тестов без запущенной игры):
    Генерирует случайные текстовые строки из тестового набора FAKE_CHAT и имитирует задержки реального игрового чата, чтобы проверить, 
    как система обрабатывает и фильтрует входящий поток сообщений.
    """
    lines = random.sample(FAKE_CHAT, k=random.randint(7, 10))  # type: ignore # noqa: F821
    return '\n'.join(lines)

# Генерация ИИ-отчёта (Сидорович)
def generate_ai_report():
    """ Генерирует тактический отчёт за текущий день через Groq API.
Читает все события из game_logs за сегодня и передаёт в промпт.
Вызывается один раз при завершении сессии. """
    con = sq.connect("stayout.db")
    cursor = con.cursor()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    query = "SELECT event_type, hp_value FROM game_logs WHERE timestamp LIKE ? ORDER BY rowid DESC"
    cursor.execute(query, (f"{today}%",))
    
    logs = cursor.fetchall()
    con.close()
    
    if not logs: return "Рейд был тихим."
    
    log_text = "\n".join([f"- {row[0]}: {row[1]}% HP" for row in logs])
    
    prompt = f"""
    Ты — бортовой ИИ КПК сталкера. Вот лог всех моих действий за сегодня:
    {log_text}
    
    Проанализируй эти данные и напиши отчет. Если событий много, не перечисляй каждое, а сделай общие выводы:
    1. Общая динамика: насколько тяжело прошел день?
    2. Хроника: когда были самые опасные моменты (падения HP)?
    Стиль: Технический, циничный, краткий.
    """
    
    chat = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.1-8b-instant",
    )
    return chat.choices[0].message.content

#Запуск приложения
a = ', '.join(KEYWORDS)
root = tk.Tk()
root.title("Настройки КПК Сталкера")

text_field = tk.Text(root, height=10, width=40)
text_field.insert("1.0", a)
text_field.pack()

button = tk.Button(root, text="Старт", command=start_tracker)
button.pack()

root.mainloop()

class Database:
    def __init__(self, file="stayout.db", data_queue=None):
        self._file = file
        self._q = data_queue if data_queue is not None else queue.Queue()
        con = sq.connect(self._file)
        con.execute("CREATE TABLE IF NOT EXISTS game_logs (timestamp TEXT, event_type TEXT, hp_value INTEGER, location TEXT, damage_source TEXT)")
        con.close()
    def log_event(self, event_type, hp_value, location = None, damage_source = None):
        con = sq.connect(self._file)
        cursor = con.cursor()
        cursor.execute(
            "INSERT INTO game_logs(timestamp, event_type, hp_value, location, damage_source) VALUES(?, ?, ?, ?, ?)",
            (datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), event_type, hp_value, location, damage_source)
        )
        con.commit()
        con.close()

    def db_worker(self):
        while True:
            item = self._q.get()
            if item is None:
                break

            event_type, hp_value, location, damage_source = item
            self.log_event(event_type, hp_value, location, damage_source)

            self._q.task_done()

class GameWindow:
    def __init__(self):
        self._left = None
        self._top = None
        self._width = None
        self._height = None
        self.update()
    def update(self):
        try:
            #TODO: исправить windows
            windows = gw.getWindowsWithTitle("Stay Out")
            if windows:
                window = windows[0]
                if window.isMinimized:
                    time.sleep(1)
                    return False
                self._left = window.left
                self._top = window.top
                self._width = window.width
                self._height = window.height
                return True
        except IndexError:
            print("Окно не найдено!")
            return
        except Exception as e:  # noqa: BLE001
            print(f'Ошибка: {e}')
    def get_bbox(self):
        if self._left is None:
            return
        x1 = self._left
        x2 = self._left + self._width
        y1 = self._top
        y2 = self._top + self._height
        return (x1, y1, x2, y2)

class GameScanner:
    def __init__(self, window_obj = None, data_queue = None):
        self._window = window_obj if window_obj is not None else GameWindow()
        self._queue = data_queue if data_queue is not None else queue.Queue()
        self._hp_coords = None
        self._prev_hp = 100
        self._hp_threshold = 5
    def find_hp_bar(self):
        """ Автоматически находит полоску HP на экране путём сканирования пикселей.
        Ищет строку с более чем 50 красными пикселями подряд (r>135, g<80, b<80).
        Возвращает кортеж (x_start, x_end, y_line) — координаты полоски."""
        try:
            red_pixels = 0
            x1, y1, x2, y2 = self._window.get_bbox()

            img = ImageGrab.grab(bbox=(x1, y1, x2, y2)).convert('RGB')
            pixels = img.load()

            width = x2 - x1
            height = y2 - y1    
            
            for y in range(height):
                red_pixels = 0
                for x in range(width):
                    pixel = pixels[x, y]
                    if pixel is None:
                        continue
                    r, g, b = pixel
                    if r > 135 and g < 80 and b < 80: 
                        red_pixels += 1
                    else:
                        red_pixels = 0
                    if red_pixels >= 30:
                        y_line = y
                        x_start = None
                        x_end = None    
                        for x2 in range(width):
                            r2, g2, b2 = pixels[x2, y_line]
                            if r2 > 135 and g2 < 80 and b2 < 80:
                                if x_start is None:
                                    x_start = x2
                                x_end = x2
                        if x_start is not None and x_end is not None:
                            self._hp_coords = (x_start + x1, x_end + x1, y_line + y1)
                            return self._hp_coords
                        else:
                            continue
            return 
        except (OSError, ValueError, TypeError) as e:
            print(f"Finding hp bar is failed: {e}")
        return 
    def get_area_chat(self):
        """ Возвращает координаты области чата в абсолютных пикселях экрана.
    Вычисляет зону относительно размеров окна игры (в процентах)."""
        try:
            left, top, right, bottom = self._window.get_bbox()
            width = right - left
            height = bottom - top
            
        except (TypeError, ValueError):
            return None

        return (
            int(left + width * 0.036),
            int(top + height * 0.333),
            int(left + width * 0.187),
            int(top + height * 0.953)
        )  
    def get_current_hp(self):
        """ Считывает текущий процент HP по координатам hp_coords.
    Подсчитывает красные пиксели на полоске и возвращает процент от максимума."""
        try:
            if self._hp_coords is None:
                return None
            X_START, X_END, Y_LINE = self._hp_coords
            
            red_pixels = 0
            img = ImageGrab.grab(bbox=(X_START, Y_LINE, X_END, Y_LINE + 1)).convert("RGB")
            pixels = img.load()
            
            TOTAL_WIDTH = img.width
            for x in range(TOTAL_WIDTH):
                    r, g, b = pixels[x, 0]
                    if r >= 120 and g < 100 and b < 100:
                        red_pixels += 1
            return int((red_pixels / TOTAL_WIDTH) * 100)
        except (OSError, ValueError) as e:
            print(f"Ошибка считывания HP: {e}")
            return None
    def get_polling_rate(self, hp):
        """ Возвращает задержку между опросами экрана:
    - HP > 30% — стандартный режим 
    - HP <= 30% — критический режим """
        if hp > 30:
            return 0.5 
        else:
            return 0.2
    def capture_chat(self):
        """ Делает скриншот области чата и распознаёт текст через Tesseract OCR.
    Возвращает строку с распознанным текстом или None при ошибке."""
        try:
            X_START, Y_START, X_END, Y_END = self.get_area_chat()
            img = ImageGrab.grab(bbox=(X_START, Y_START, X_END, Y_END))
            text = pts.image_to_string(img, lang='rus', config='--psm 6')
            return text.strip()
        except (OSError, ValueError, RuntimeError) as e:  
            print(f"Capturing chat is failed: {e}")
            return None
    def filter_chat(self, text):
        """ Фильтрует строки чата по ключевым словам через нечёткое сравнение.
    Пороги: 60% для коротких слов (<=5 символов), 85% для длинных.
    Дедуплицирует результат через dict.fromkeys().
    Возвращает список уникальных строк с совпадениями."""
        line = text.split('\n')
        a=[]
        for word in KEYWORDS:
            for l in line:
                part_ratio = fuzz.partial_ratio(word,l)
                if part_ratio >= 60 and len(word) <= 5 or part_ratio >= 85 and len(word) > 5:
                    a.append(l)
        a = dict.fromkeys(a)
        a = list(a)    
        return a
    def monitor_hp(self):
        """ Поток-Производитель для отслеживания полоски ХП:
        - Работает в бесконечном цикле в отдельном потоке.
        - Делает скриншот заданной области экрана (полоски здоровья) с помощью PyAutoGUI.
        - Сравнивает текущий цвет пикселей с шаблоном «здорового» цвета.
        - Если здоровье изменилось сильнее, чем HP_CHANGE_THRESHOLD, формирует 
        кортеж данных и отправляет его в очередь."""
        print("Поток HP запущен.")
        while True:
            try:
                current_percent = self.get_current_hp()
                if current_percent is not None and abs(current_percent - self._prev_hp) >= self._hp_threshold:
                    event_type = "Ранение" if current_percent < self._prev_hp else "Лечение"
                    self._queue.put((event_type, current_percent, None,  None))
                    self._prev_hp = current_percent
                time.sleep(self.get_polling_rate(current_percent or 100))
            except (ValueError, OSError, RuntimeError) as e:
                print(f"HP monitor error: {e}")
    def monitor_chat(self):
        """ Поток-Производитель для распознавания игрового чата:
        - Работает в бесконечном цикле в отдельном потоке.
        - С помощью PIL.ImageGrab делает скриншот зоны чата.
        - Передает картинку в Tesseract OCR для извлечения текста.
        - Проверяет текст на наличие ключевых слов с помощью нечеткого сравнения.
        - Если найдено важное событие, формирует кортеж 
        и без задержек «бросает» его в общую очередь."""
        print("Поток Чата Запущен.")
        last_chat_text = ""
        while True:
            raw_text = self.capture_chat()
            if raw_text:
                filtered_lines = self.filter_chat(raw_text)
                if filtered_lines:
                    chat_text = '\n'.join(filtered_lines)
                    if chat_text != last_chat_text:
                        self._queue.put(("chat_event", self.get_current_hp() or 100,  None, chat_text))  
                        last_chat_text = chat_text
            time.sleep(1.0)

q = queue.Queue()
db = Database(data_queue= q)
Gw = GameWindow()
gs = GameScanner(window_obj = Gw, data_queue = q)

#Запуск скрипта
print("КПК Сталкера запущен...")
print("Ищу полоску HP...")
hp_coords = gs.find_hp_bar()  
if not hp_coords:
    print("Полоска HP не найдена! Запусти игру и перезапусти скрипт.")
else:
    print(f"HP найден: {hp_coords}")
    

thr_hp = threading.Thread(target=gs.monitor_hp,daemon=True)   
thr_chat = threading.Thread(target=gs.monitor_chat, daemon=True)
thr_db = threading.Thread(target=db.db_worker, daemon=True)

thr_hp.start()
thr_chat.start()
thr_db.start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[!] Отключение. Генерирую отчет...")
    print(generate_ai_report())        