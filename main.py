import sys
import os
import threading
import tempfile
from flask import Flask, request, render_template_string, jsonify
from PIL import Image
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap

# --- Конфигурация ---
PORT = 8080
HOST = '0.0.0.0'  # Слушаем все интерфейсы

# --- HTML Шаблон (Frontend) ---
# Адаптирован для мобильных устройств, прост и надежен
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Управление Экраном</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f0f0f5;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 90vh;
            touch-action: manipulation;
        }
        h1 { color: #333; margin-bottom: 40px; text-align: center; }
        .btn-container {
            width: 100%;
            max-width: 400px;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        .btn {
            display: block;
            width: 100%;
            padding: 20px;
            font-size: 18px;
            font-weight: bold;
            color: white;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
            transition: background-color 0.2s;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .btn-load {
            background-color: #007AFF;
        }
        .btn-load:active { background-color: #005ecb; }
        .btn-hide {
            background-color: #FF3B30;
        }
        .btn-hide:active { background-color: #d63329; }
        
        /* Скрытый input для файлов */
        #file-input { display: none; }
        
        #status {
            margin-top: 20px;
            color: #666;
            font-size: 14px;
            min-height: 20px;
        }
    </style>
</head>
<body>
    <h1>Дисплей Сервер</h1>
    
    <div class="btn-container">
        <!-- Кнопка Загрузки -->
        <label for="file-input" class="btn btn-load">Загрузить картинку</label>
        <input type="file" id="file-input" accept="image/*" onchange="uploadFile(this)">

        <!-- Кнопка Скрытия -->
        <button class="btn btn-hide" onclick="hideWindow()">Скрыть</button>
    </div>

    <div id="status"></div>

    <script>
        function uploadFile(input) {
            if (input.files.length === 0) return;
            
            document.getElementById('status').innerText = "Загрузка...";
            
            let formData = new FormData();
            formData.append("file", input.files[0]);

            fetch("/upload", {
                method: "POST",
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'ok') {
                    document.getElementById('status').innerText = "Изображение отображается";
                } else {
                    document.getElementById('status').innerText = "Ошибка: " + data.message;
                }
                input.value = ""; // Сброс для возможности повторной загрузки того же файла
            })
            .catch(error => {
                document.getElementById('status').innerText = "Ошибка сети";
                console.error('Error:', error);
            });
        }

        function hideWindow() {
            fetch("/hide", { method: "POST" })
            .then(response => response.json())
            .then(data => {
                document.getElementById('status').innerText = "Окно скрыто";
            });
        }
    </script>
</body>
</html>
"""

# --- Логика PyQt (GUI) ---

class CommunicationBridge(QObject):
    """Служит мостом между потоком Flask и главным потоком Qt (сигналы)."""
    show_image_signal = pyqtSignal(str)
    hide_window_signal = pyqtSignal()

class KioskViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kiosk Viewer")
        
        # Получаем геометрию экрана
        self.screen = QApplication.primaryScreen()
        self.screen_geometry = self.screen.geometry()
        
        # Настройки окна
        # Qt.WindowStaysOnTopHint - поверх всех окон
        # Qt.FramelessWindowHint - без рамок и заголовка
        # Qt.Tool - не показывать в панели задач (опционально, усиливает эффект "приложения")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setStyleSheet("background-color: black;")
        
        # Центральный виджет
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.label)
        
        # Для обработки вертикальных изображений
        self.using_split_widget = False
        
    def show_image(self, image_path):
        """Слот для приема сигнала показа изображения."""
        try:
            # Загружаем и обрабатываем картинку через Pillow
            img = Image.open(image_path)
            img = img.convert("RGB") # Гарантируем совместимый формат
            
            w, h = img.size
            sw = self.screen_geometry.width()
            sh = self.screen_geometry.height()
            
            # Обработка вертикальных изображений (ширина < высота)
            # Разрезаем пополам по горизонтали и склеиваем в "широкую"
            if w < h:
                # Делим высоту пополам
                half = h // 2
                top_part = img.crop((0, 0, w, half))
                bottom_part = img.crop((0, half, w, h))
                
                # Склеиваем бок о бок (слева верх, справа низ)
                # Новая ширина = w*2, новая высота = half
                new_img = Image.new('RGB', (w * 2, half))
                new_img.paste(top_part, (0, 0))
                new_img.paste(bottom_part, (w, 0))
                img = new_img
            
            # Масштабируем под экран с сохранением пропорций
            # LANCZOS - высокое качество
            img.thumbnail((sw, sh), Image.Resampling.LANCZOS)
            
            # Сохраняем во временный файл для QPixmap
            temp_pixmap_path = os.path.join(tempfile.gettempdir(), "current_kiosk_image.png")
            img.save(temp_pixmap_path, "PNG")
            
            # Загружаем в Qt
            pixmap = QPixmap(temp_pixmap_path)
            self.label.setPixmap(pixmap)
            
            # Показываем окно
            self.showFullScreen()
            
            # Захват ввода (блокировка)
            # На X11 это работает хорошо. На Wayland может потребоваться подтверждение пользователя.
            self.grabKeyboard()
            self.grabMouse()
            self.activateWindow()
            
        except Exception as e:
            print(f"Ошибка обработки изображения: {e}")

    def hide_viewer(self):
        """Слот для скрытия окна."""
        self.releaseKeyboard()
        self.releaseMouse()
        self.hide()

# --- Flask Приложение ---
app = Flask(__name__)
bridge = CommunicationBridge()

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'No selected file'}), 400

    # Сохраняем временно
    temp_dir = tempfile.gettempdir()
    save_path = os.path.join(temp_dir, "upload_temp_img")
    try:
        file.save(save_path)
        # Отправляем сигнал в GUI поток
        bridge.show_image_signal.emit(save_path)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/hide', methods=['POST'])
def hide():
    bridge.hide_window_signal.emit()
    return jsonify({'status': 'hidden'})

def run_flask():
    # Запуск Flask в отдельном потоке
    # use_reloader=False предотвращает двойной запуск при разработке
    app.run(host=HOST, port=PORT, threaded=True, debug=False, use_reloader=False)

if __name__ == '__main__':
    # 1. Инициализируем Qt приложение
    qt_app = QApplication(sys.argv)
    
    # 2. Создаем окно просмотра
    viewer = KioskViewer()
    
    # 3. Соединяем сигналы Flask с окном Qt
    # Qt сигналы безопасно передают управление в главный поток GUI
    bridge.show_image_signal.connect(viewer.show_image)
    bridge.hide_window_signal.connect(viewer.hide_viewer)
    
    # 4. Запускаем Flask в фоновом потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    print(f"Сервер запущен: http://localhost:{PORT}")
    print("Окно просмотра готово. Ожидание команд...")
    
    # 5. Запускаем главный цикл Qt
    sys.exit(qt_app.exec_())