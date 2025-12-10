# -*- coding: utf-8 -*-
import os
import requests
from bs4 import BeautifulSoup
import re
import mimetypes
import time
import json
import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QDialog, QListWidget, QListWidgetItem,
    QMessageBox, QFileDialog, QComboBox, QTreeWidget,
    QTreeWidgetItem, QProgressBar
)
from PyQt5.QtCore import Qt
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

INVALID_CHARS = r'<>:"/\|?*'
download_dir = ""  # se setea en main


# -------------------------------------------------------------------
# Utilidades generales
# -------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    name = name.strip()
    for ch in INVALID_CHARS:
        name = name.replace(ch, '')
    return name


def save_log(log_message, log_file="download_log.txt"):
    global download_dir
    if not download_dir:
        log_path = log_file
    else:
        log_path = os.path.join(download_dir, log_file)
    with open(log_path, "a", encoding="utf-8") as log:
        log.write(log_message + "\n")


def create_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        save_log(f"No se pudo crear la carpeta: {path}. Error: {e}")


# -------------------------------------------------------------------
# Login a Moodle
# -------------------------------------------------------------------
def auth_moodle(data: dict) -> requests.Session:
    login = data["login"]
    password = data["password"]
    url_domain = data["url"]  # ej: https://campus.unab.edu.ar

    s = requests.Session()
    r_1 = s.get(url=url_domain + "/login/index.php")
    pattern_auth = r'<input type="hidden" name="logintoken" value="(\w{32})">'
    token_match = re.search(pattern_auth, r_1.text)
    if not token_match:
        raise RuntimeError("No se pudo obtener el logintoken de Moodle.")
    token = token_match.group(1)

    payload = {
        'anchor': '',
        'logintoken': token,
        'username': login,
        'password': password,
        'rememberusername': 1,
    }
    r_2 = s.post(url=url_domain + "/login/index.php", data=payload)

    # Debug básico de errores de login
    counter = 0
    for line in r_2.text.splitlines():
        if "loginerrors" in line or (0 < counter <= 3):
            counter += 1
            print(line)

    return s

def auth_moodle(data: dict) -> requests.Session:
    login = data["login"]
    password = data["password"]
    url_domain = data["url"]  # ej: https://campus.unab.edu.ar

    s = requests.Session()
    # 1) Traer login
    r_1 = s.get(url=url_domain + "/login/index.php")
    pattern_auth = r'<input type="hidden" name="logintoken" value="(\w{32})">'
    token_match = re.search(pattern_auth, r_1.text)
    if not token_match:
        print("No se pudo encontrar logintoken en el formulario de login.")
        return None

    token = token_match.group(1)

    # 2) Post de credenciales
    payload = {
        'anchor': '',
        'logintoken': token,
        'username': login,
        'password': password,
        'rememberusername': 1,
    }
    r_2 = s.post(url=url_domain + "/login/index.php", data=payload, allow_redirects=True)

    # ---- ACA chequeamos si realmente logueó ----

    # a) Si seguimos en la página de login => algo falló
    if "login/index.php" in r_2.url:
        print("Parece que seguimos en la página de login, credenciales incorrectas o error.")
        return None

    # b) Buscar mensajes de error típicos de Moodle
    if "loginerrors" in r_2.text or "Datos erróneos. Por favor inténtelo otra vez." in r_2.text:
        print("Moodle devolvió mensaje de error de login.")
        return None

    # c) También podemos buscar algo que solo aparece cuando estás logueado,
    # por ejemplo el enlace de logout o el nombre del usuario.
    if "logout.php" not in r_2.text and "logout" not in r_2.text:
        # No es perfecto, pero sirve como extra chequeo
        print("No se encontró logout en la página, puede que el login haya fallado.")
        # si querés ser estricto, retornás None:
        # return None

    return s

# -------------------------------------------------------------------
# Obtener lista de cursos desde window.local_mail_navbar_data
# -------------------------------------------------------------------
def get_course_ids(html_content: str) -> list:
    """
    Devuelve lista [(course_id, course_fullname), ...]
    usando el JSON de window.local_mail_navbar_data.
    Si no lo encuentra, intenta el método viejo con .coursebox-content.
    """
    course_info = []
    soup = BeautifulSoup(html_content, "html.parser")

    # Intento 1: JSON en script window.local_mail_navbar_data
    script = soup.find("script", string=re.compile(r"window\.local_mail_navbar_data"))
    data = None
    if script and script.string:
        script_text = script.string
        pattern = r"window\.local_mail_navbar_data\s*=\s*(\{.*\})"
        match = re.search(pattern, script_text, re.DOTALL)
        if match:
            try:
                json_text = match.group(1)
                data = json.loads(json_text)
            except Exception as e:
                print("Error parseando JSON de local_mail_navbar_data:", e)

    if data and "courses" in data:
        for curso in data.get("courses", []):
            course_id = str(curso["id"])
            nombre = curso["fullname"].strip()
            course_info.append((course_id, nombre))
        return course_info

    # Intento 2 (fallback): método viejo basado en HTML
    list_group_items = soup.find_all(class_='coursebox-content')
    for item in list_group_items:
        link = item.find('a', href=True)
        h3 = item.find('h3')
        if not link or not h3:
            continue
        course_id = link['href'].split('=')[-1]
        nombre = h3.text.strip()
        course_info.append((course_id, nombre))

    return course_info


# -------------------------------------------------------------------
# Descarga de recursos individuales (sin barra interna)
# -------------------------------------------------------------------
def download_html_links(html_response, course_folder, session, course_url):
    """
    Recibe la respuesta HTML de un recurso,
    busca pluginfile.php y los descarga.
    """
    soup = BeautifulSoup(html_response.content, 'html.parser')
    links = soup.find_all('a', href=True)

    for link in links:
        href = link['href']
        if 'pluginfile.php' in href:
            if href.startswith("/"):
                parsed = urlparse(course_url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"
            download_resource_simple(href, course_folder, link.text.strip(), session, course_url)


def download_resource_simple(link: str, course_folder: str, nombre: str,
                             session: requests.Session, referer_url: str) -> None:
    """
    Descarga un recurso individual sin barra por bytes (la barra es global por archivo).
    """
    headers = {"Referer": referer_url}
    r_content = session.get(link, headers=headers)

    if not r_content.ok:
        msg = f"No se pudo descargar el enlace: {link}. Status: {r_content.status_code}"
        print(msg)
        save_log(msg)
        return

    content_type = r_content.headers.get('content-type', '')
    base_type = content_type.split(";")[0].strip()
    extension = mimetypes.guess_extension(base_type)
    print("Tipo de contenido:", content_type)

    if content_type == 'application/x-rar-compressed':
        extension = ".rar"
    if "text/html" in content_type:
        extension = ".html"
    if 'text/plain' in content_type:
        extension = ".txt"
    if 'text/csv' in content_type:
        extension = ".csv"

    if extension is None:
        msg = f"No se descargo el enlace: {link}. Tipo de archivo no compatible. ({content_type})"
        print(msg)
        save_log(msg)
        return

    content_filename = None
    content_disposition = r_content.headers.get('Content-Disposition')
    if content_disposition:
        match = re.search(r'filename="(.*?)"', content_disposition)
        if match:
            content_filename = match.group(1)

    if not content_filename:
        nombre_safe = sanitize_filename(nombre)
        content_filename = nombre_safe + extension

    file_path = os.path.join(course_folder, content_filename)

    try:
        with open(file_path, "wb") as f:
            f.write(r_content.content)

        # Si es HTML, puede tener resources pluginfile.php
        if "text/html" in content_type:
            download_html_links(r_content, course_folder, session, referer_url)

        msg = f"Contenido descargado: {content_filename} (en la carpeta {course_folder})"
        print(msg)
        save_log(msg)
    except Exception as e:
        save_log(f"No se pudo descargar el contenido: {content_filename}. Error: {e}")


# -------------------------------------------------------------------
# Obtener links de quiz / assign
# -------------------------------------------------------------------
def obtener_links_lista(page_url: str, session: requests.Session) -> list:
    """
    A partir de una página tipo /mod/quiz/index.php?id=COURSEID
    o /mod/assign/index.php?id=COURSEID, devuelve [(href, texto), ...].
    """
    r_content = session.get(page_url)
    if not r_content.ok:
        print(f"No se pudo acceder a {page_url}")
        return []

    soup = BeautifulSoup(r_content.content, 'html.parser')
    table_rows = soup.find_all('tr')

    links_and_names = []
    for row in table_rows:
        link = row.find('a', href=True)
        if not link:
            continue
        href = link['href']
        name = link.text.strip()
        if not name:
            continue
        links_and_names.append((href, name))

    return links_and_names


# -------------------------------------------------------------------
# Secciones del curso (para recursos por unidad)
# -------------------------------------------------------------------
def get_course_id_from_url(course_url: str) -> str:
    """Saca el id=XXX de la URL del curso."""
    parsed = urlparse(course_url)
    q = parse_qs(parsed.query)
    return q.get("id", [""])[0]


def build_section_url(course_base_url: str, section_number) -> str:
    """
    Construye .../course/view.php?id=407&section=N
    a partir de la URL base SIN section.
    """
    parsed = urlparse(course_base_url)
    q = parse_qs(parsed.query)
    q["section"] = [str(section_number)]
    new_query = urlencode(q, doseq=True)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        ""  # sin fragment
    ))


def get_course_sections(html: str, course_id: str):
    """
    Devuelve [(section_number, section_name), ...]
    pero IGNORA secciones ocultas / deshabilitadas (disabled, dimmed).
    """
    soup = BeautifulSoup(html, "html.parser")
    sections = []

    # Buscar <li> que contienen los tabs de secciones
    for li in soup.find_all("li", class_=lambda c: c and "tab_position" in c):
        
        classes = li.get("class", [])

        # 🔥 Si tiene 'disabled' o 'dimmed', ignorar
        if "disabled" in classes or "dimmed" in classes:
            continue

        # Buscar el enlace interno
        a = li.find("a", href=True)
        if not a:
            continue

        # También ignoramos si el <a> está disabled
        a_classes = a.get("class", [])
        if "disabled" in a_classes:
            continue

        href = a["href"]
        if f"course/view.php?id={course_id}" not in href or "section=" not in href:
            continue

        # Extraer nombre de la sección
        name = a.get_text(strip=True)
        if not name:
            continue

        # Extraer el número de sección
        sec_part = href.split("section=")[-1]
        sec_part = re.split(r"[&#]", sec_part)[0]
        if not sec_part.isdigit():
            continue

        sections.append((sec_part, name))

    # Deduplicar por número
    unique = {}
    for sec, name in sections:
        unique[sec] = name

    ordered = sorted(unique.items(), key=lambda x: int(x[0]))
    return ordered


def collect_section_resources(section_url: str,
                              session: requests.Session,
                              referer_url: str) -> list:
    """
    Solo colecta recursos de una sección (NO descarga), devuelve
    lista de dicts: [{'url': full_url, 'name': name}, ...]
    """
    resp = session.get(section_url)
    if not resp.ok:
        msg = f"No se pudo acceder a la sección: {section_url}"
        print(msg)
        save_log(msg)
        return []

    soup = BeautifulSoup(resp.content, "html.parser")

    candidate_links = []
    for a in soup.find_all("a", href=True):
        href = a['href']
        if "/mod/" in href and "view.php?id=" in href:
            if any(p in href for p in ["/mod/resource/", "/mod/page/", "/mod/url/"]):
                name = a.get_text(strip=True)
                if name:
                    candidate_links.append((href, name))

    seen = set()
    resources = []
    for href, name in candidate_links:
        if href in seen:
            continue
        seen.add(href)

        # Resolver URLs relativas
        if href.startswith("/"):
            parsed = urlparse(referer_url)
            href_full = f"{parsed.scheme}://{parsed.netloc}{href}"
        elif href.startswith("http"):
            href_full = href
        else:
            parsed = urlparse(referer_url)
            href_full = f"{parsed.scheme}://{parsed.netloc}/{href.lstrip('/')}"
        resources.append({"url": href_full, "name": name})

    return resources


def scan_course_resources(course_url: str,
                          course_name: str,
                          session: requests.Session) -> list:
    """
    Escanea el curso y devuelve estructura:
    [
      {
        'section_num': '0',
        'section_name': 'Presentación',
        'section_folder_name': '00 - Presentación',
        'resources': [
           {'url': 'http...', 'name': 'Programa ...'},
           ...
        ]
      },
      ...
    ]
    """
    course_id = get_course_id_from_url(course_url)
    if not course_id:
        raise ValueError(f"No pude obtener el course id desde: {course_url}")

    parsed = urlparse(course_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}/course/view.php?id={course_id}"

    resp = session.get(base_url)
    if not resp.ok:
        msg = f"No se pudo acceder al curso base: {base_url}"
        print(msg)
        save_log(msg)
        return []

    html = resp.text
    sections = get_course_sections(html, course_id)
    if not sections:
        msg = f"No se encontraron secciones para el curso {course_id} en {base_url}"
        print(msg)
        save_log(msg)
        return []

    result = []
    for sec_num, sec_name in sections:
        sec_name_safe = sanitize_filename(sec_name)
        folder_name = f"{str(sec_num).zfill(2)} - {sec_name_safe}"
        section_url = build_section_url(base_url, sec_num)

        res_list = collect_section_resources(section_url, session, section_url)
        result.append({
            "section_num": sec_num,
            "section_name": sec_name,
            "section_folder_name": folder_name,
            "resources": res_list or []
        })

    return result


# -------------------------------------------------------------------
# Diálogo de selección de recursos por curso (árbol)
# -------------------------------------------------------------------
class ResourceSelectionDialog(QDialog):
    """
    Muestra un árbol con secciones y recursos.
    Por defecto todos los recursos están tildados.
    """
    def __init__(self, course_name: str, sections_data: list, parent=None):
        super().__init__(parent)
        self.course_name = course_name
        self.sections_data = sections_data
        self.selected_resources = []  # se llena al aceptar
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(f"Seleccionar recursos - {self.course_name}")
        self.setGeometry(200, 200, 600, 400)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Unidades y recursos")

        # Llenar el árbol
        for sec in self.sections_data:
            sec_text = f"{sec['section_num']} - {sec['section_name']}"
            parent_item = QTreeWidgetItem([sec_text])
            parent_item.setExpanded(True)
            self.tree.addTopLevelItem(parent_item)

            for res in sec.get("resources", []):
                child = QTreeWidgetItem([res["name"]])
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked)  # por defecto tildado
                info = {
                    "url": res["url"],
                    "name": res["name"],
                    "section_folder_name": sec["section_folder_name"]
                }
                child.setData(0, Qt.UserRole, info)
                parent_item.addChild(child)

        self.button_ok = QPushButton("Descargar seleccionados")
        self.button_cancel = QPushButton("Cancelar")

        self.button_ok.clicked.connect(self.accept)
        self.button_cancel.clicked.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(self.tree)
        layout.addWidget(self.button_ok)
        layout.addWidget(self.button_cancel)

        self.setLayout(layout)

    def accept(self):
        self.selected_resources = []

        top_count = self.tree.topLevelItemCount()
        for i in range(top_count):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) == Qt.Checked:
                    info = child.data(0, Qt.UserRole)
                    if info:
                        self.selected_resources.append(info)

        super().accept()

    def get_selected_resources(self):
        return self.selected_resources


# -------------------------------------------------------------------
# UI de selección de cursos + barra de progreso global
# -------------------------------------------------------------------
class CourseSelectionDialog(QDialog):
    def __init__(self, courses, session, parent=None):
        super().__init__(parent)
        self.courses = courses
        self.session = session
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Elegir Cursos")
        self.setGeometry(100, 100, 500, 400)

        self.list_widget = QListWidget()
        for course in self.courses:
            item = QListWidgetItem(course[1])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_widget.addItem(item)

        self.button_download = QPushButton("Elegir cursos para Descargar")
        self.button_download.clicked.connect(self.download_selected_courses)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)

        layout = QVBoxLayout()
        layout.addWidget(self.list_widget)
        layout.addWidget(self.button_download)
        layout.addWidget(self.progress_bar)

        self.setLayout(layout)

    def download_selected_courses(self):
        app = QApplication.instance()

        selected_courses = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected_courses.append(self.courses[i])

        if not selected_courses:
            QMessageBox.warning(self, "Sin selección", "No seleccionaste ningún curso.")
            return

        base_domain = login_dialog.login_data["url"]

        # 1) Construir la lista global de tareas de descarga
        # Cada tarea: {'url', 'folder', 'name', 'referer'}
        tasks = []

        for code, name in selected_courses:
            course_view_url = f"{base_domain}/course/view.php?id={code}"
            quiz_index_url = f"{base_domain}/mod/quiz/index.php?id={code}"
            assign_index_url = f"{base_domain}/mod/assign/index.php?id={code}"

            # Escanear recursos por secciones
            sections_data = scan_course_resources(course_view_url, name, self.session)

            # Diálogo de árbol para seleccionar qué bajar
            if sections_data:
                dlg = ResourceSelectionDialog(name, sections_data, self)
                if dlg.exec_() == QDialog.Accepted:
                    selected_resources = dlg.get_selected_resources()
                else:
                    selected_resources = []
            else:
                selected_resources = []

            # Carpeta base del curso
            curso_folder = os.path.join(download_dir, sanitize_filename(name))
            create_folder(curso_folder)

            # Carpetas de tareas y cuestionarios
            tarea_folder = os.path.join(curso_folder, "tarea")
            create_folder(tarea_folder)
            cuestionarios_folder = os.path.join(curso_folder, "cuestionarios")
            create_folder(cuestionarios_folder)

            # Obtener links de cuestionarios -> agregar tareas
            cuestionarios = obtener_links_lista(quiz_index_url, self.session)
            for link, descripcion in cuestionarios:
                if link.startswith("http"):
                    full_link = link
                else:
                    full_link = f"{base_domain}/{link.lstrip('/')}"
                tasks.append({
                    "url": full_link,
                    "folder": cuestionarios_folder,
                    "name": descripcion,
                    "referer": course_view_url
                })

            # Obtener links de tareas -> agregar tareas
            tareas = obtener_links_lista(assign_index_url, self.session)
            for link, descripcion in tareas:
                if link.startswith("http"):
                    full_link = link
                else:
                    full_link = f"{base_domain}/{link.lstrip('/')}"
                tasks.append({
                    "url": full_link,
                    "folder": tarea_folder,
                    "name": descripcion,
                    "referer": course_view_url
                })

            # Recursos seleccionados por unidad -> agregar tareas
            for res in selected_resources:
                section_folder = os.path.join(curso_folder, res["section_folder_name"])
                create_folder(section_folder)
                tasks.append({
                    "url": res["url"],
                    "folder": section_folder,
                    "name": res["name"],
                    "referer": course_view_url
                })

        # 2) Ejecutar las tareas con barra de progreso global
        total_tasks = len(tasks)
        if total_tasks == 0:
            QMessageBox.information(self, "Nada para descargar",
                                    "No se encontraron archivos para descargar con la selección hecha.")
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, total_tasks)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m archivos")

        completed = 0
        for task in tasks:
            download_resource_simple(
                task["url"],
                task["folder"],
                task["name"],
                self.session,
                task["referer"]
            )
            completed += 1
            self.progress_bar.setValue(completed)
            app.processEvents()

        QMessageBox.information(self, "Descarga Finalizada",
                                "Descarga completa. Info en archivo download_log.txt")
        self.progress_bar.setVisible(False)
        self.close()


# -------------------------------------------------------------------
# Diálogo de login
# -------------------------------------------------------------------
class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.login_data = {
            "login": "",
            "password": "",
            "url": ""  # base domain
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
        self.login_data["login"] = self.input_login.text().strip()
        self.login_data["password"] = self.input_password.text().strip()

        if not self.login_data["login"] or not self.login_data["password"]:
            QMessageBox.warning(self, "Error", "Usuario y contraseña son obligatorios.")
            return

        selected_domain = self.combo_box_domain.currentText()
        if selected_domain == "Campus":
            self.login_data["url"] = "https://campus.unab.edu.ar"
        elif selected_domain == "Extensión":
            self.login_data["url"] = "https://extension.unab.edu.ar"

        self.accept()


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
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
        app_data["url"] = login_dialog.login_data["url"]  # base domain

        session = auth_moodle(data=app_data)
        if session is None:
            QMessageBox.critical(None, "Error de login",
                 "No se pudo iniciar sesión. Revisá usuario/contraseña.")
            sys.exit(1)

        # Elegir directorio de descarga
        download_dir = QFileDialog.getExistingDirectory(
            None,
            "Elegir directorio Trabajo",
            options=QFileDialog.ShowDirsOnly
        )
        if not download_dir:
            QMessageBox.warning(None, "Sin carpeta", "No seleccionaste carpeta de descarga.")
            sys.exit(0)

        # Obtener página principal de cursos
        if "campus.unab.edu.ar" in app_data["url"]:
            r_courses = session.get(app_data["url"] + "/?redirect=0")
        else:
            r_courses = session.get(app_data["url"] + "/?")

        lista_de_cursos = get_course_ids(r_courses.text)

        if not lista_de_cursos:
            QMessageBox.warning(None, "Sin cursos", "No se encontraron cursos.")
            sys.exit(0)

        course_selection_dialog = CourseSelectionDialog(lista_de_cursos, session)
        course_selection_dialog.exec_()

        session.close()

    sys.exit(app.exec_())