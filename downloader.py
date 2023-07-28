# -*- coding: utf-8 -*-
import os
import requests
from bs4 import BeautifulSoup
import re
import mimetypes
import time
import sys
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout, QDialog, QListWidget, QListWidgetItem, QMessageBox, QFileDialog,QComboBox
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

def download_html_links(html_response, course_folder, session, course_url):
    soup = BeautifulSoup(html_response.content, 'html.parser')
    links = soup.find_all('a', href=True)
    
    for link in links:
        href = link['href']
        if 'pluginfile.php' in href:
            download_resource(href, course_folder, link.text.strip(), session, course_url)
            
def download_resource(link: str, course_folder: str, nombre: str, session: requests.Session, course_url: str) -> None:
    
    r_content = session.get(link)
    
    content_type = r_content.headers.get('content-type')
    extension = mimetypes.guess_extension(content_type)
    print (content_type)
    if content_type =='application/x-rar-compressed':
        extension=".rar"
    if "text/html" in content_type:
        extension=".html" 
        download_html_links(r_content, course_folder, session, course_url)
    if 'text/plain' in content_type:
        extension=".txt"
    if 'text/csv' in content_type:
        extension=".csv"    
        

    if extension is not None:
        content_filename = None
        content_disposition = r_content.headers.get('Content-Disposition')
        
        if content_disposition:
            
            match = re.search(r'filename="(.*?)"', content_disposition)
            if match:
                content_filename = match.group(1)
                        
        
        if not content_filename:
            content_filename = os.path.basename(link)   
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
        print(f"No se descargo el enlace: {link}. Tipo de archivo no compatible.")
        save_log(f"No se descargo el enlace: {link}. Tipo de archivo no compatible.{content_type}")

def obtener_links_quiz(course_url: str, nombre: str, session: requests.Session) -> None:
    r_content = session.get(course_url)
    soup = BeautifulSoup(r_content.content, 'html.parser')
    table_rows = soup.find_all('tr', class_=['', 'lastrow',None])
    links_and_names = []
        

    for row in table_rows:
        unit = row.find('td', class_='c0')
        if unit:
            current_unit_name = unit.text.strip()

        link = row.find('a', href=True)
        if link:
            href = link['href']
            name = link.text.strip()
            
            links_and_names.append((href, name))
                                   
    return links_and_names

def download_course_contents(course_url: str, nombre: str, session: requests.Session) -> None:
    r_content = session.get(course_url)
    soup = BeautifulSoup(r_content.content, 'html.parser')
    table_rows = soup.find_all('tr', class_=['', 'lastrow'])
    links_and_names = []
    nombre = os.path.join(download_dir, nombre)
    create_folder(nombre)    
    current_unit_name = None
    unit_folder = nombre    

    for row in table_rows:
        unit = row.find('td', class_='c0')
        if unit:
            current_unit_name = unit.text.strip()
            invalid_chars = r'<>:"/\|?*'
            for char in invalid_chars:
                current_unit_name = current_unit_name.replace(char, '')            

        link = row.find('a', href=True)
        if link:
            href = link['href']
            name = link.text.strip()
            invalid_chars = r'<>:"/\|?*'
            for char in invalid_chars:
                name = name.replace(char, '')               
            
            if current_unit_name != "":
                unit_folder = os.path.join(nombre, current_unit_name)

            create_folder(unit_folder)

            try:
                
                tiempo_limite = 300
                start_time = time.time()
                print (href)
                download_resource(href, unit_folder, name, session, course_url)

                elapsed_time = time.time() - start_time
                if elapsed_time > tiempo_limite:
                    print(f"La descarga del recurso '{name}' superó el límite de tiempo de 5 minutos.")
                    save_log(f"La descarga del recurso '{name}' superó el límite de tiempo de 5 minutos.")

            except Exception as e:
                print(f"Error en la descarga del recurso '{name}': {e}")
                save_log(f"Error en la descarga del recurso '{name}': {e}")


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

            campus_url = login_dialog.login_data["url"] + f"/course/resources.php?id={code}"
            campus_quiz = login_dialog.login_data["url"] + f"/mod/quiz/index.php?id={code}"
            campus_assign = login_dialog.login_data["url"] + f"/mod/assign/index.php?id={code}"
            cuestionarios = obtener_links_quiz(campus_quiz, name, session)
            print(cuestionarios)
            tareas = obtener_links_quiz(campus_assign, name, session)

            # Creamos las carpetas para tareas y cuestionarios dentro del curso
            curso_folder = os.path.join(download_dir, name)
            create_folder(curso_folder)
            tarea_folder = os.path.join(curso_folder, "tarea")
            create_folder(tarea_folder)
            cuestionarios_folder = os.path.join(curso_folder, "cuestionarios")
            create_folder(cuestionarios_folder)

            for link, descripcion in cuestionarios:
                campus_quiz = login_dialog.login_data["url"] + '/mod/quiz/' + link
                download_course_contents(campus_quiz, cuestionarios_folder, session)  # Descargamos en carpeta cuestionarios

            for link, descripcion in tareas:
                download_resource(link, tarea_folder, descripcion, session, download_dir)  # Descargamos en carpeta tarea

            download_course_contents(campus_url, curso_folder, session)  # Descargamos en carpeta del curso

        QMessageBox.information(self, "Descarga Finalizada", "Info completa en archivo download_log.txt")
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
        self.setGeometry(100, 100, 300, 200)
    
        self.label_login = QLabel("Usuario:")
        self.input_login = QLineEdit()
        self.label_password = QLabel("Password:")
        self.input_password = QLineEdit()
        self.input_password.setEchoMode(QLineEdit.Password)
    
        self.label_domain = QLabel("Selecciona el dominio:")
        self.combo_box_domain = QComboBox()
        self.combo_box_domain.addItem("Campus")
        self.combo_box_domain.addItem("Extensión")
    
        self.button_login = QPushButton("Login")
        self.button_login.clicked.connect(self.handle_login)
    
        layout = QVBoxLayout()
        layout.addWidget(self.label_login)
        layout.addWidget(self.input_login)
        layout.addWidget(self.label_password)
        layout.addWidget(self.input_password)
        layout.addWidget(self.label_domain)
        layout.addWidget(self.combo_box_domain)
        layout.addWidget(self.button_login)
    
        self.setLayout(layout)
    
    def handle_login(self):
        self.login_data["login"] = self.input_login.text()
        self.login_data["password"] = self.input_password.text()
    
        selected_domain = self.combo_box_domain.currentText()
        if selected_domain == "Campus":
            self.login_data["url"] = "https://campus.unab.edu.ar"
        elif selected_domain == "Extensión":
            self.login_data["url"] = "https://extension.unab.edu.ar"
    
        self.accept()

      
if __name__ == "__main__":
    app_data = {
        "login": "",
        "password": "",
        "url": ""
    }

    app = QApplication(sys.argv)

    login_dialog = LoginDialog()
    login_dialog.show()
    if login_dialog.exec_() == QDialog.Accepted:

        app_data["login"] = login_dialog.login_data["login"]
        app_data["password"] = login_dialog.login_data["password"]
        app_data["url"] = login_dialog.login_data["url"]+"/login/index.php"


        session = auth_moodle(data=app_data)


        download_dir = QFileDialog.getExistingDirectory(None, "Elegir directorio Trabajo", options=QFileDialog.ShowDirsOnly)


        if app_data["url"]=="https://campus.unab.edu.ar/login/index.php":
            r_courses = session.get('https://campus.unab.edu.ar/?redirect=0')
        else:
            r_courses = session.get('https://extension.unab.edu.ar/?')
        lista_de_cursos = get_course_ids(r_courses.content, session)


        course_selection_dialog = CourseSelectionDialog(lista_de_cursos)
        course_selection_dialog.exec_()

        session.close()

    sys.exit(app.exec_())

