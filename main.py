import pyautogui
import pygetwindow as gw
import time
import sqlite3 as sq
from datetime import datetime
from groq import Groq
import pytesseract as pts
from PIL import ImageGrab

# Инициализация ИИ
client = Groq(api_key='GROQ_API_KEY')

pts.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR/tesseract.exe'

# X_START, X_END, Y_LINE = 6, 335, 55
# TOTAL_WIDTH = X_END - X_START + 1

HP_CHANGE_THRESHOLD = 5
KEYWORDS = ["Уро", "Ранил", "Убил", "Погиб", "Аномал"]

def log_event(event_type, hp_value):
    con = sq.connect("stayout.db")
    cursor = con.cursor()
    cursor.execute("INSERT INTO game_logs(timestamp, event_type, hp_value) VALUES(?, ?, ?)",
                   (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event_type, hp_value))
    con.commit()
    con.close()

def get_polling_rate(hp):
    if hp > 30:
        return 0.5 
    else:
        return 0.2

def get_window_info(x_start=None, x_end=None, y_line=None, y_end=None):
    try:
        window = gw.getWindowsWithTitle("Stay Out")
        if not window:
            print("Запусти игру")
            return None
        windows = window[0]
        if windows.isMinimized:
            time.sleep(1)
            return None
        if x_start is None and x_end is None and y_line is None:
                return (windows.left, windows.top, windows.width, windows.height)
        X_START = windows.left + x_start
        X_END = windows.left + x_end
        Y_LINE = windows.top + y_line
        if y_end is not None:
            Y_END = windows.top + y_end
            return (X_START, X_END, Y_LINE, Y_END)
        else:
            return (X_START, X_END, Y_LINE)
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
        X_START, Y_LINE, X_END, Y_END = get_area_chat()
        img = ImageGrab.grab(bbox=(X_START, Y_LINE, X_END, Y_END))
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
        if word in l:
            a.append(l)
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

# Инициализация БД
con = sq.connect("stayout.db")
con.execute("CREATE TABLE IF NOT EXISTS game_logs (timestamp TEXT, event_type TEXT, hp_value INTEGER)")
con.close()

print("КПК Сталкера запущен...")
print("Ищу полоску HP...")
hp_coords = find_hp_bar()  
if not hp_coords:
    print("Полоска HP не найдена! Запусти игру и перезапусти скрипт.")
else:
    print(f"HP найден: {hp_coords}")
    prev_hp = 100

    try:
        while True:
            current_percent = get_current_hp()
            try:
                if abs(current_percent - prev_hp) >= HP_CHANGE_THRESHOLD:
                        event = "Ранение" if current_percent < prev_hp else "Лечение"
                        log_event(event, current_percent)
                        prev_hp = current_percent
                time.sleep(get_polling_rate(prev_hp)) 
            except Exception as e:
                print(f"Ошибка: Игра не запущена {e}")

    except KeyboardInterrupt:
        print("\n[!] Отключение. Генерирую отчет...")
        print("\n=== ОТЧЕТ ИИ-ЛЕТОПИСЦА ===")
        print(generate_ai_report())
