import pyautogui
import pygetwindow as gw
import time
import sqlite3 as sq
from datetime import datetime
from groq import Groq


# Инициализация ИИ
client = Groq(api_key='GROQ_API_KEY')


# X_START, X_END, Y_LINE = 6, 335, 55
# TOTAL_WIDTH = X_END - X_START + 1

HP_CHANGE_THRESHOLD = 5

def get_polling_rate(hp):
    if hp > 30:
        return 0.5 
    else:
        return 0.2
    
def get_window_info():
    try:
        window = gw.getWindowsWithTitle("Stay Out")
        if not window:
            print("Запусти игру")
            return None
        windows = window[0]
        if windows.isMinimized:
            time.sleep(1)
            return None
        X_START = windows.left + 6
        X_END = windows.left + 335
        Y_LINE = windows.top + 55
        return (X_START, X_END, Y_LINE)
    except IndexError:
        print("Ошибка: окно не найдено")
        return None
    except Exception as e:
        print(f"Неизвестная ошибка: {e}")
        return None
    
def log_event(event_type, hp_value):
    con = sq.connect("stayout.db")
    cursor = con.cursor()
    cursor.execute("INSERT INTO game_logs(timestamp, event_type, hp_value) VALUES(?, ?, ?)",
                   (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event_type, hp_value))
    con.commit()
    con.close()

def get_current_hp():
    try:
        coords = get_window_info()
        if not coords:
            return None
        X_START, X_END, Y_LINE = coords
        TOTAL_WIDTH = X_END - X_START   + 1
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