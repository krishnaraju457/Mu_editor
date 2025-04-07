from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLineEdit, QListWidget, QPushButton, QLabel
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
import requests
import os
import zipfile
import shutil

# Constants
LIBRARY_LIST_URL = "https://raw.githubusercontent.com/adafruit/Adafruit_CircuitPython_Bundle/main/circuitpython_library_list.md"
DOCUMENTS_DIR = os.path.join(os.path.expanduser("~"), "Documents")
MU_EDITOR_DIR = os.path.join(DOCUMENTS_DIR, "mu_editor")
LIBRARY_INSTALL_PATH = os.path.join(MU_EDITOR_DIR, "libraries")

# Ensure directories exist
os.makedirs(LIBRARY_INSTALL_PATH, exist_ok=True)

# Utility functions
def fetch_library_list():
    """Fetch the library list from the remote URL."""
    try:
        response = requests.get(LIBRARY_LIST_URL)
        response.raise_for_status()
        libraries = {}
        for line in response.text.splitlines():
            if line.startswith("* ["):
                name = line.split("]")[0].split("[")[-1].replace("Adafruit CircuitPython ", "").strip()
                github_url = line.split("(")[1].split(")")[0]
                libraries[name] = github_url
        return libraries
    except requests.RequestException as e:
        print(f"Error fetching library list: {e}")
        return {}

def download_and_extract_library(library_name, library_url):
    """Download and extract a library ZIP file."""
    zip_url = library_url.replace(".git", "/archive/refs/heads/main.zip")
    zip_path = os.path.join(LIBRARY_INSTALL_PATH, f"{library_name}.zip")
    extract_path = os.path.join(LIBRARY_INSTALL_PATH, library_name)

    if os.path.exists(extract_path):
        return f"Library {library_name} already installed!"

    try:
        # Download ZIP
        response = requests.get(zip_url, stream=True)
        response.raise_for_status()
        with open(zip_path, "wb") as f:
            f.write(response.content)

        # Extract ZIP
        os.makedirs(extract_path, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_path)

        # Handle nested folders
        subfolders = os.listdir(extract_path)
        if len(subfolders) == 1:
            nested_folder = os.path.join(extract_path, subfolders[0])
            for item in os.listdir(nested_folder):
                shutil.move(os.path.join(nested_folder, item), extract_path)
            shutil.rmtree(nested_folder)

        os.remove(zip_path)
        return f"Library {library_name} installed successfully!"
    except Exception as e:
        return f"Error installing {library_name}: {e}"

# Threads
class LibraryFetcher(QThread):
    libraries_fetched = pyqtSignal(dict)

    def run(self):
        libraries = fetch_library_list()
        self.libraries_fetched.emit(libraries)

class LibraryInstaller(QThread):
    progress = pyqtSignal(str)

    def __init__(self, library_name, library_url):
        super().__init__()
        self.library_name = library_name
        self.library_url = library_url

    def run(self):
        message = download_and_extract_library(self.library_name, self.library_url)
        self.progress.emit(message)

# UI
class LibraryManagerUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CircuitPython Library Manager")
        self.setGeometry(100, 100, 400, 500)
        self.libraries = {}

        self.init_ui()
        self.fetch_libraries()

    def init_ui(self):
        layout = QVBoxLayout()

        # Search bar
        self.search_bar = QLineEdit()
        self.search_bar.setFont(QFont("Roboto", 18))
        self.search_bar.setPlaceholderText("Search for a library...")
        self.search_bar.textChanged.connect(self.search_library)
        layout.addWidget(self.search_bar)

        # Library list
        self.list_widget = QListWidget()
        self.list_widget.setFont(QFont("Roboto", 18))
        self.list_widget.setStyleSheet("""
            QListWidget::item { padding: 10px; border: 1px solid white; }
            QListWidget::item:selected { background-color: #652f8f; color: white; }
        """)
        layout.addWidget(self.list_widget)

        # Install button
        self.install_button = QPushButton("Install Selected Library")
        self.install_button.clicked.connect(self.install_selected_library)
        layout.addWidget(self.install_button)

        # Status label
        self.status_label = QLabel("Status: Ready")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def fetch_libraries(self):
        self.status_label.setText("Fetching library list...")
        self.fetcher = LibraryFetcher()
        self.fetcher.libraries_fetched.connect(self.populate_library_list)
        self.fetcher.start()

    def populate_library_list(self, libraries):
        self.libraries = libraries
        self.list_widget.clear()
        self.list_widget.addItems(sorted(self.libraries.keys()))
        self.status_label.setText("Library list loaded.")

    def search_library(self):
        query = self.search_bar.text().strip().lower()
        self.list_widget.clear()
        filtered = [name for name in self.libraries if query in name.lower()] if query else self.libraries.keys()
        self.list_widget.addItems(sorted(filtered))

    def install_selected_library(self):
        selected_item = self.list_widget.currentItem()
        if selected_item:
            library_name = selected_item.text()
            library_url = self.libraries.get(library_name)
            if library_url:
                self.status_label.setText(f"Installing {library_name}...")
                self.installer = LibraryInstaller(library_name, library_url)
                self.installer.progress.connect(self.update_status)
                self.installer.start()

    def update_status(self, message):
        self.status_label.setText(message)