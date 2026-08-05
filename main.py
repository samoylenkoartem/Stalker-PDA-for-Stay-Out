import os
import platform
import queue
import sqlite3 as sq
import threading
import time
import tkinter as tk
from datetime import datetime, timezone

import cv2
import numpy as np
import pygetwindow as gw
import pytesseract as pts
from dotenv import load_dotenv
from fuzzywuzzy import fuzz
from groq import Groq
from PIL import ImageGrab

#TODO: добавить условие если не Windows
if platform.system() == "Windows":
    pts.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

load_dotenv()

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise ValueError("GROQ_API_KEY is missing! Create a .env file with your key.")

# Инициализация ИИ
client = Groq(api_key=api_key)

q = queue.Queue()
HP_CHANGE_THRESHOLD = 5
KEYWORDS = [
    "Урон", "Ранил", "Убил", "Погиб", "Аномалия", 
    "Радиация", "Кровотечение", "Отравление", "Перелом", 
    "Уничтожил", "Опыт"                                  
]

# Получение информации об окне игры
def get_window_info(x_start=None, x_end=None, y_length=None, y_end=None):
    """ Возвращает координаты и размеры окна игры Stay Out через pygetwindow.
- Если аргументы не переданы — возвращает (left, top, width, height) окна.
- Если переданы смещения — возвращает абсолютные координаты на экране."""
    try:
        #TODO: добавить ручной выбор окна игры
        windows = [w for w in gw.getAllWindows() if 'SO official' in w.title]
        if not windows:
            print("Запусти игру")
            return None
        window = windows[0]
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
    except (OSError, ValueError) as e:
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

# Адаптивная частота опроса 
def get_polling_rate(hp):
    """ Возвращает задержку между опросами экрана (Black Box режим):
- HP > 30% — стандартный режим (0.5 сек)
- HP <= 30% — критический режим (0.2 сек, 5 раз в секунду)"""
    if hp > 30:
        return 0.5 
    else:
        return 0.2

# Автопоиск полоски HP на экране
def find_hp_bar():
#TODO: Позже переписать алгоритм на один проход (Streak Counter) и добавить convert ("RGB")
    """ Поиск полоски HP на экране путём сканирования пикселей.
Ищет строку с более чем 30 красными пикселями подряд.Возвращает кортеж - координаты полоски."""
    try:
        red_pixels = 0
        info = get_window_info()

        if not info:
            print("Окно игры не найдено.")
            return None
        
        left, top, width, height = info

        img = ImageGrab.grab(bbox=(left, top, left + width,top + height)).convert('RGB')
        pixels = img.load()

        for y in range(height):
            red_pixels = 0
            for x in range(width):
                pixel = pixels[x, y]
                if pixel is None:
                    continue
                r, g, b = pixel
                if r > 135 and g < 80 and b < 80: 
                    red_pixels += 1
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
                        return (x_start + left, x_end + left, y_line + top)
                    else:
                        continue
        return None
    except (OSError, ValueError) as e:
        print(f"Неизвестная ошибка: {e}")
        return None
    
# Считывание текущего процента HP
def get_current_hp():
    """Считывает текущий процент HP по координатам.
Подсчитывает красные пиксели на полоске и возвращает процент от максимума."""
    try:
        X_START, X_END, Y_LINE = hp_coords
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

# Определение области чата
def get_area_chat():
    """ Возвращает координаты области чата в абсолютных пикселях экрана.
Вычисляет зону относительно размеров окна игры."""
    try:
        info = get_window_info()
        if not info:
            return None
        left, top, width, height = info
        return (
            #TODO: уйти от абсолютных координат 
            int(left + width * 0.036),
            int(top + height * 0.333),
            int(left + width * 0.187),
            int(top + height * 0.953))
    except (RuntimeError, OSError, TypeError, ValueError) as e:
        print(f"Неизвестная ошибка: {e}")
        return None
     
# Фильтрация чата по ключевым словам
def filter_chat(text):
    #TODO: Переработать идею с фильтрацией чата.
    """ Фильтрование строки чата по ключевым словам через нечёткое сравнение.
Пороги: 80% для коротких слов, 75% для длинных.
Дедуплицирует результат через dict.fromkeys().
Возвращает список уникальных строк с совпадениями."""
    line = text.split('\n')
    arr=[]
    for word in KEYWORDS:
       for l in line:
        part_ratio = fuzz.partial_ratio(word,l)
        if (part_ratio >= 80 and len(word) <= 5) or (part_ratio >= 75 and len(word) > 5):
            arr.append(l)
    arr = dict.fromkeys(arr)
    arr = list(arr)    
    return arr

# Генерация ИИ-отчёта 
def generate_ai_report():
    #TODO: Переписать промпт 
    """ Генерирует тактический отчёт за текущий день через Groq API.
Читает все события из бд за сессию и передаёт в промпт.
Вызывается один раз при завершении сессии."""
    con = sq.connect("stayout.db")
    cursor = con.cursor()
    
    # Берем сегодняшнюю дату
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    query = "SELECT event_type, hp_value FROM game_logs WHERE timestamp LIKE ? ORDER BY rowid DESC"
    cursor.execute(query, (f"{today}%",))
    
    logs = cursor.fetchall()
    con.close()
    
    if not logs: 
        return "Во время сессии событий не было."
    
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

# Функция мониторинга здоровья
prev_hp = 100
def monitor_hp():
    """ Поток-Производитель для отслеживания полоски ХП:
    - Работает в бесконечном цикле в отдельном потоке.
    - Делает скриншот заданной области экрана с помощью PyAutoGUI.
    - Сравнивает текущий цвет пикселей с шаблоном «здорового» цвета.
    - Если здоровье изменилось сильнее, чем HP_CHANGE_THRESHOLD, формирует 
      кортеж данных и отправляет его в очередь."""
    try:
        global prev_hp
        print("Поток HP запущен.")
        while True:
            current_percent = get_current_hp()
            if current_percent is not None and abs(current_percent - prev_hp) >= HP_CHANGE_THRESHOLD :
                    event_type = "Ранение" if current_percent < prev_hp else "Лечение"
                    q.put(("hp_event", event_type, current_percent, None))
                    prev_hp = current_percent
            time.sleep(get_polling_rate(current_percent or 100))
    except Exception as e:
        print(f"Неизвестная ошибка:{e}")

# Функция мониторинга чата
def monitor_chat():
    """ Поток-Производитель для распознавания игрового чата:
    - Работает в бесконечном цикле в отдельном потоке.
    - С помощью PIL.ImageGrab делает скриншот зоны чата.
    - Передает картинку в Tesseract OCR для извлечения текста.
    - Проверяет текст на наличие ключевых слов (KEYWORDS) с помощью нечеткого сравнения (fuzzywuzzy).
    - Если найдено важное событие (например, "Ранил" или "Убит"), формирует кортеж 
      и без задержек «бросает» его в общую очередь."""
    print("Поток Чата Запущен.")
    last_chat_text = ""
    last_img_bytes = None
    try:
        while True:
            area_chat = get_area_chat()
            if area_chat is None:
                time.sleep(1)
                continue
            img = ImageGrab.grab(bbox=area_chat)
            current_img_bytes = img.tobytes()
            if current_img_bytes == last_img_bytes: 
                time.sleep(0.5)
                continue
        
            last_img_bytes = current_img_bytes
            
            # Переводим картинку PIL в массив numpy 
            img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            # Переводим в оттенки серого
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            # Увеличиваем размер (Tesseract лучше читает крупный текст)
            gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            # Применяем бинаризацию (оставляем только яркий текст, фон делаем черным)
            # Порог (200) подбирается под цвет текста чата. Если текст белый - это сработает отлично.
            _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
            # Инвертируем (Tesseract лучше читает черный текст на белом фоне)
            inverted = cv2.bitwise_not(thresh)
            
            raw_text = pts.image_to_string(inverted, lang='rus', config='--psm 6').strip()
            
            if raw_text:
                filtered_lines = filter_chat(raw_text)
                if filtered_lines:
                    chat_text = '\n'.join(filtered_lines)
                    if chat_text != last_chat_text and len(chat_text) > 3:
                        current_hp = get_current_hp()
                        if current_hp is None: 
                            current_hp = 100
                            
                        q.put(("chat_event", "Событие чата", current_hp, chat_text))
                        last_chat_text = chat_text
                        
            time.sleep(0.5)
    except Exception as e:
        print(f"Неизвестная ошибка:{e}")
            
# Поток записи в базу данных
def db_worker():
    """ Поток-Потребитель для работы со SQLite:
    - Единственный поток, который имеет прямой доступ к файлу базы данных.
    - Запускается в бесконечном цикле и ждет данные через блокирующий вызов q.get().
    - Если очередь пуста, поток автоматически засыпает.
    - Как только в очередь падает событие от monitor_hp или monitor_chat, он просыпается,
      распаковывает кортеж, открывает соединение с SQLite, выполняет SQL-запрос 
      INSERT INTO game_logs... и сохраняет изменения.
    - После этого вызывает q.task_done() и ждет следующее событие."""
    try:
        con = sq.connect("stayout.db")
        cursor = con.cursor()
        print("Поток БД Запущен и ждет задач...")
        while True:
            item = q.get()
            if item is None: 
                con.close()
                break
            
            _event_source, event_type, hp_value, damage_source = item
            
            cursor.execute(
                "INSERT INTO game_logs(timestamp, event_type, hp_value, location, damage_source) VALUES(?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), event_type, hp_value, None, damage_source)
            )
            con.commit()
            q.task_done()
    except Exception as e:
        print(f"Неизвестная ошибка {e}")

# Запуск приложения для записи "горячих" слов
root = tk.Tk()
root.title("Настройки КПК Сталкера")

text_field = tk.Text(root, height=10, width=40)
arr = ', '.join(KEYWORDS)
text_field.insert("1.0", arr)
text_field.pack()

button = tk.Button(root, text="Старт", command=start_tracker)
button.pack()

root.mainloop()

# Инициализация БД
con = sq.connect("stayout.db")
con.execute("CREATE TABLE IF NOT EXISTS game_logs (timestamp TEXT, event_type TEXT, hp_value INTEGER, location TEXT, damage_source TEXT)")
con.close()

# Запуск скрипта
print("КПК Сталкера запущен...")
print("Ищу полоску HP...")
hp_coords = find_hp_bar()  
if hp_coords is None:
    print("Полоска HP не найдена! Запусти игру и перезапусти скрипт.")
else:
    print(f"HP найден: {hp_coords}")
    
# Создание и запуск потоков
thr_hp = threading.Thread(target=monitor_hp,daemon=True)   
thr_chat = threading.Thread(target=monitor_chat, daemon=True)
thr_db = threading.Thread(target=db_worker, daemon=True)

thr_hp.start()
thr_chat.start()
thr_db.start()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[!] Отключение. Генерирую отчет...")
    time.sleep(1)
    print(generate_ai_report())        