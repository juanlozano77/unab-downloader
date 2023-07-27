import os
import requests
from bs4 import BeautifulSoup
import re
import mimetypes
import sys
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout, QDialog, QListWidget, QListWidgetItem, QMessageBox, QFileDialog
from PyQt5.QtCore import Qt

def save_log(log_message, log_file="download_log.txt"):
    log_file = os.path.join(download_dir, log_file)
    with open(log_file, "a", encoding="utf-8") as log:
        log.write(log_message + "\n")

def create_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        save_log(f"No se pudo crear la carpeta: {path}. Error: {e}")

def auth_moodle(data: dict) -> requests.Session:
    login, password, url_domain = data.values()
    s = requests.Session()
    r_1 = s.get(url=url_domain + "/login/index.php")
    pattern_auth = '<input type="hidden" name="logintoken" value="\w{32}">'
    token = re.findall(pattern_auth, r_1.text)
    token = re.findall("\w{32}", token[0])[0]
    payload = {'anchor': '', 'logintoken': token, 'username': login, 'password': password, 'rememberusername': 1}
    r_2 = s.post(url=url_domain + "/login/index.php", data=payload)
    for i in r_2.text.splitlines():
        if "<title>" in i:
            print(i[15:-8:])
            break
    counter = 0
    for i in r_2.text.splitlines():
        if "loginerrors" in i or (0 < counter <= 3):
            counter += 1
            print(i)
    return s

def get_course_ids(html_content: str, session: requests.Session) -> str:
    course_info = []
    soup = BeautifulSoup(html_content, 'html.parser')
    list_group_items = soup.find_all(class_='coursebox-content')
    for item in list_group_items:
        link = item.find('a')
        course_id = link['href'].split('=')[-1]
        nombre = item.find('h3').text.strip()
        course_info.append((course_id, nombre))

    return course_info

def download_resource(link: str, course_folder: str, nombre: str, session: requests.Session, course_url: str) -> None:
    r_content = session.get(link)

    # Utilizar python-magic para obtener el tipo MIME del archivo
    content_type = r_content.headers.get('content-type')
    extension = mimetypes.guess_extension(content_type)
    
    if content_type =='application/x-rar-compressed':
        extension=".rar"
    if content_type =='text/html; charset=utf-8':
        extension=".html" 
    if content_type =='text/plain; charset=utf-8':
        extension=".txt"    
        
        

    if extension is not None:
        invalid_chars = r'<>:"/\|?*'
        for char in invalid_chars:
            nombre = nombre.replace(char, '')        
        content_filename = nombre + extension
        file_path = os.path.join(course_folder, content_filename)
        try:
            with open(file_path, "wb") as f:
                f.write(r_content.content)
            print(f"Contenido descargado: {content_filename} (en la carpeta {course_folder})")
            save_log(f"Contenido descargado: {content_filename} (en la carpeta {course_folder})")
        except Exception as e:
            save_log(f"No se pudo descargar el contenido: {content_filename}. Error: {e}")
    else:
        print(f"No se descargó el enlace: {link}. Tipo de archivo no compatible.")
        save_log(f"No se descargó el enlace: {link}. Tipo de archivo no compatible.{content_type}")

def download_course_contents(course_url: str, nombre: str, session: requests.Session) -> None:
    r_content = session.get(course_url)
    soup = BeautifulSoup(r_content.content, 'html.parser')
    table_rows = soup.find_all('tr', class_='section')
    table_rows = soup.find_all('tr', class_=['', 'lastrow'])
    links_and_names = []

    # Crear la carpeta del curso directamente dentro de la carpeta de descargas
    nombre = os.path.join(download_dir, nombre)
    create_folder(nombre)

    current_unit_name = None
    unit_folder = nombre

    for row in table_rows:
        unit = row.find('td', class_='c0')
        if unit:
            current_unit_name = unit.text.strip()

        link = row.find('a', href=True)
        if link:
            href = link['href']
            name = link.text.strip()
            
            if current_unit_name != "":
                unit_folder = os.path.join(nombre, current_unit_name)

            create_folder(unit_folder)
            download_resource(href, unit_folder, name, session, course_url)



class CourseSelectionDialog(QDialog):
    def __init__(self, courses):
        super().__init__()
        self.courses = courses
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Elegir Cursos")
        self.setGeometry(100, 100, 400, 300)

        self.list_widget = QListWidget()
        for course in self.courses:
            item = QListWidgetItem(course[1])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_widget.addItem(item)

        self.button_download = QPushButton("Elegir cursos para Descargar")
        self.button_download.clicked.connect(self.download_selected_courses)

        layout = QVBoxLayout()
        layout.addWidget(self.list_widget)
        layout.addWidget(self.button_download)

        self.setLayout(layout)

    def download_selected_courses(self):
        selected_courses = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected_courses.append(self.courses[i])

        for code, name in selected_courses:
            campus_url = f"https://campus.unab.edu.ar/course/resources.php?id={code}"
            download_course_contents(campus_url, name, session)

        QMessageBox.information(self, "Descarga Completa", "Los cursos se descargaron exitosamente!")
        self.close()
        
class LoginDialog(QDialog):     
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.login_data = {
            "login": "",
            "password": ""
        }

    def init_ui(self):
        self.setWindowTitle("Unab Login")
        self.setGeometry(100, 100, 300, 150)

        self.label_login = QLabel("Usuario:")
        self.input_login = QLineEdit()
        self.label_password = QLabel("Password:")
        self.input_password = QLineEdit()
        self.input_password.setEchoMode(QLineEdit.Password)
        self.button_login = QPushButton("Login")
        self.button_login.clicked.connect(self.handle_login)

        layout = QVBoxLayout()
        layout.addWidget(self.label_login)
        layout.addWidget(self.input_login)
        layout.addWidget(self.label_password)
        layout.addWidget(self.input_password)
        layout.addWidget(self.button_login)

        self.setLayout(layout)

    def handle_login(self):
        self.login_data["login"] = self.input_login.text()
        self.login_data["password"] = self.input_password.text()
        self.accept()


if __name__ == "__main__":
    app_data = {
        "login": "",
        "password": "",
        "url": "https://campus.unab.edu.ar/login/index.php"
    }

    app = QApplication(sys.argv)

    # Show the login dialog to get login credentials from the user
    login_dialog = LoginDialog()
    login_dialog.show()
    if login_dialog.exec_() == QDialog.Accepted:
        # Fetch the login data from the LoginDialog
        app_data["login"] = login_dialog.login_data["login"]
        app_data["password"] = login_dialog.login_data["password"]

        # Authenticate the session
        session = auth_moodle(data=app_data)

        # Show the directory selection dialog to get the download directory
        download_dir = QFileDialog.getExistingDirectory(None, "Elegir directorio Trabajo", options=QFileDialog.ShowDirsOnly)

        # Fetch the course list
        r_courses = session.get('https://campus.unab.edu.ar/?redirect=0')
        lista_de_cursos = get_course_ids(r_courses.content, session)

        # Show the course selection dialog to get the courses the user wants to download
        course_selection_dialog = CourseSelectionDialog(lista_de_cursos)
        course_selection_dialog.exec_()

        session.close()

    sys.exit(app.exec_())

