import pyautogui
import pygetwindow as gw
import time
import sqlite3 as sq
from datetime import datetime
from groq import Groq
import pytesseract as pts
from PIL import ImageGrab
import platform
import random
from fuzzywuzzy import fuzz
import tkinter as tk
import threading

if platform.system() == "Windows":
    pts.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    
# Инициализация ИИ
client = Groq(api_key='GROQ_API_KEY')

lock = threading.Lock()

HP_CHANGE_THRESHOLD = 5
KEYWORDS = ["Уро", "Ранил", "Убил", "Погиб", "Аномал"]
FAKE_CHAT = [
    "Игрок VasyaPuper нанёс вам Урон 25",
    "Аномалия нанесла Урон 15",
    "Игрок Killer88 Убил вас",
    "Вы Погибли от радиации",
    "Мутант Ранил вас на 30",
    "Игрок StalkerPro нанёс Урон 45",
    "Аномал притяжения нанесла урон 20",
    "Игрок DarkZone Убил вас выстрелом в голову",
    "Вы Погибли в зоне отчуждения",
    "Снайпер Ранил вас на 60",
]

def start_tracker():
    global KEYWORDS
    text = text_field.get("1.0",tk.END).strip()
    KEYWORDS = text.split(',')
    KEYWORDS = [elem.strip() for elem in KEYWORDS]
    root.destroy()

def emulate_chat():
    lines = random.sample(FAKE_CHAT, k=random.randint(7, 10))
    return '\n'.join(lines)

def log_event(event_type, hp_value, location = None, damage_source = None):
    with lock:
        con = sq.connect("stayout.db")
        cursor = con.cursor()
        cursor.execute("INSERT INTO game_logs(timestamp, event_type, hp_value, location, damage_source) VALUES(?, ?, ?, ?, ?)",
                   (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event_type, hp_value, location, damage_source))
        con.commit()
        con.close()
    

def get_polling_rate(hp):
    if hp > 30:
        return 0.5 
    else:
        return 0.2

def get_window_info(x_start=None, x_end=None, y_length=None, y_end=None):
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
    except Exception as e:
        print(f"Неизвестная ошибка: {e}")
        return None
    
def find_hp_bar():
    red_pixels = 0
    left, top, width, height = get_window_info()
    for y in range(top, top+height+1):
        red_pixels = 0
        for x in range(left, left+width+1):
            r, g, b = pyautogui.pixel(x,y)
            if r > 150 and g < 80 and b < 80: red_pixels += 1
            if red_pixels > 50:
                y_line = y
                x_start = None
                x_end = None    
                for x in range(left, left+width+1):
                    r, g, b = pyautogui.pixel(x,y_line)
                    if r > 150 and g < 80 and b < 80 and x_start is None:
                        x_start = x
                    if r > 150 and g < 80 and b < 80:
                        x_end = x
                return(x_start, x_end, y)
    return None

def get_current_hp():
    try:
        X_START, X_END, Y_LINE = hp_coords
        TOTAL_WIDTH = X_END - X_START + 1
        red_pixels = 0
        for x in range(X_START, X_END + 1):
            try:
                r, g, b = pyautogui.pixel(x, Y_LINE)
                if r > 90: red_pixels += 1
            except Exception:
                break
        return int((red_pixels / TOTAL_WIDTH) * 100)
    except Exception as e:
        print(f"Ошибка считывания HP: {e}")
        return None

def get_area_chat():
    try:
        info = get_window_info()
        if not info:
            return None
        left, top, width, height = info
        return (
            int(left + width * 0.036),
            int(top + height * 0.333),
            int(left + width * 0.187),
            int(top + height * 0.953))
    except Exception as e:
        print(f"Неизвестная ошибка: {e}")
        return None
    
def capture_chat():
    try:
        X_START, Y_START, X_END, Y_END = get_area_chat()
        img = ImageGrab.grab(bbox=(X_START, Y_START, X_END, Y_END))
        text = pts.image_to_string(img, lang='rus', config='--psm 6')
        return text.strip()
    except Exception as e:
        print(f"Неизвестная ошибка: {e}")
        return None
    
def filter_chat(text):
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
        
def generate_ai_report():
    con = sq.connect("stayout.db")
    cursor = con.cursor()
    
    # Берем сегодняшнюю дату
    today = datetime.now().strftime("%Y-%m-%d")

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

# Инициализация БД
con = sq.connect("stayout.db")
con.execute("CREATE TABLE IF NOT EXISTS game_logs (timestamp TEXT, event_type TEXT, hp_value INTEGER, location TEXT, damage_source TEXT)")
con.close()

#Запуск скрипта
print("КПК Сталкера запущен...")
print("Ищу полоску HP...")
hp_coords = find_hp_bar()  
if not hp_coords:
    print("Полоска HP не найдена! Запусти игру и перезапусти скрипт.")
else:
    print(f"HP найден: {hp_coords}")
    

event = threading.Event()

def monitor_hp():
    global current_percent, events
    prev_hp = 100
    while True:
        current_percent = get_current_hp()
        if abs(current_percent - prev_hp) >= HP_CHANGE_THRESHOLD:
            events = "Ранение" if current_percent < prev_hp else "Лечение"
            event.set()
            prev_hp = current_percent
        time.sleep(get_polling_rate(current_percent))

def monitor_chat():
    while True:
            event.wait()
            chat_text = '\n'.join(filter_chat(capture_chat()))
            log_event(events, current_percent, None, chat_text or None)
            event.clear()


thr_1 = threading.Thread(target=monitor_hp,daemon=True)   
thr_2 = threading.Thread(target=monitor_chat, daemon=True)   

thr_1.start()
thr_2.start()         
     
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[!] Отключение. Генерирую отчет...")
    print(generate_ai_report())        