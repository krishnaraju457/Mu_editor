"""
Contains the main Window definition for Mu's UI.

Copyright (c) 2015-2017 Nicholas H.Tollervey and others (see the AUTHORS file).

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import sys
import logging
import serial
import os.path
from PyQt5.QtCore import QSize, Qt, pyqtSignal, QTimer, QIODevice, QThread
from PyQt5.QtWidgets import (QSizePolicy,QToolBar, QAction, QDesktopWidget, QWidget,
                             QVBoxLayout, QTabWidget, QFileDialog, QMessageBox,
                             QLabel, QMainWindow, QStatusBar, QDockWidget,
                             QShortcut, QAction, QLineEdit, QRadioButton, 
                             QComboBox, QPushButton, QFileDialog, QTextEdit, 
                             QCheckBox, QListWidget, QListWidgetItem, QHBoxLayout)
from PyQt5.QtGui import QKeySequence, QStandardItemModel,QFont
from PyQt5.QtSerialPort import QSerialPort
from mu import __version__
from mu.interface.dialogs import ModeSelector, AdminDialog, FindReplaceDialog
from mu.interface.themes import (DayTheme, NightTheme, ContrastTheme,
                                 DEFAULT_FONT_SIZE)
from mu.interface.panes import (DebugInspector, DebugInspectorItem,
                                PythonProcessPane, JupyterREPLPane,
                                MicroPythonREPLPane, FileSystemPane,
                                PlotterPane)
from mu.interface.editor import EditorPane
from mu.resources import load_icon, load_pixmap

# Extra added
from mu.interface.gtts_helper import GTTSHelper
from mu.interface.library_manager import LibraryManagerUI  # Import the LibraryManager
import adafruit_board_toolkit.circuitpython_serial
from google import genai
from google.genai import types
import time
import markdown
from markdown.extensions import fenced_code, codehilite, tables
import re

logger = logging.getLogger(__name__)


class ButtonBar(QToolBar):
    """
    Represents the bar of buttons across the top of the editor and defines
    their behaviour.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setMovable(False)
        self.setIconSize(QSize(64, 64))
        self.setToolButtonStyle(3)
        self.setContextMenuPolicy(Qt.PreventContextMenu)
        self.setObjectName("StandardToolBar")
        self.reset()

    def reset(self):
        """
        Resets the button states.
        """
        self.slots = {}
        self.clear()

    def change_mode(self, mode):
        self.reset()
        self.addAction(name="modes", display_name=_("Mode"),
                       tool_text=_("Change Mu's mode of behaviour."))
        self.addSeparator()
        self.addAction(name="new", display_name=_("New"),
                       tool_text=_("Create a new Python script."))
        self.addAction(name="load", display_name=_("Load"),
                       tool_text=_("Load a Python script."))
        self.addAction(name="save", display_name=_("Save"),
                       tool_text=_("Save the current Python script."))
        self.addSeparator()

        # Add the new "Chat" button
        self.addAction(name="chat", display_name=_("Chat"),
                    tool_text=_("Open the Chat Assistant."))
        self.connect("chat", self.parent().open_chat_dock)  # Connect the action to the handler

        self.addSeparator()

        for action in mode.actions():
            self.addAction(name=action['name'],
                           display_name=action['display_name'],
                           tool_text=action['description'])

        self.addSeparator()
        self.addAction(name="zoom-in", display_name=_('Zoom-in'),
                       tool_text=_("Zoom in (to make the text bigger)."))
        self.addAction(name="zoom-out", display_name=_('Zoom-out'),
                       tool_text=_("Zoom out (to make the text smaller)."))
        self.addAction(name="theme", display_name=_('Theme'),
                       tool_text=_("Toggle theme between day, night or "
                                   "high contrast."))
        self.addSeparator()
        self.addAction(name="check", display_name=_('Check'),
                       tool_text=_("Check your code for mistakes."))
        self.addAction(name="help", display_name=_('Help'),
                       tool_text=_("Show help about Mu in a browser."))
        self.addAction(name="quit", display_name=_('Quit'),
                       tool_text=_("Quit Mu."))

    def set_responsive_mode(self, width, height):
        """
        Compact button bar for when window is very small.
        """
        font_size = DEFAULT_FONT_SIZE
        if width < 940 and height > 600:
            self.setIconSize(QSize(48, 48))
        elif height < 600 and width < 940:
            font_size = 10
            self.setIconSize(QSize(32, 32))
        else:
            self.setIconSize(QSize(64, 64))
        stylesheet = "QWidget{font-size: " + str(font_size) + "px;}"
        self.setStyleSheet(stylesheet)

    def addAction(self, name, display_name, tool_text):
        """
        Creates an action associated with an icon and name and adds it to the
        widget's slots.
        """
        action = QAction(load_icon(name), display_name, self,
                         toolTip=tool_text)
        super().addAction(action)
        self.slots[name] = action

    def connect(self, name, handler, shortcut=None):
        """
        Connects a named slot to a handler function and optional hot-key
        shortcuts.
        """
        self.slots[name].pyqtConfigure(triggered=handler)
        if shortcut:
            self.slots[name].setShortcut(QKeySequence(shortcut))



class FileTabs(QTabWidget):
    """
    Extend the base class so we can override the removeTab behaviour.
    """

    def __init__(self):
        super(FileTabs, self).__init__()
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self.removeTab)
        self.currentChanged.connect(self.change_tab)

    def removeTab(self, tab_id):
        """
        Ask the user before closing the file.
        """
        window = self.nativeParentWidget()
        modified = self.widget(tab_id).isModified()
        if modified:
            msg = ('There is un-saved work, closing the tab will cause you '
                   'to lose it.')
            if window.show_confirmation(msg) == QMessageBox.Cancel:
                return
        super(FileTabs, self).removeTab(tab_id)

    def change_tab(self, tab_id):
        """
        Update the application title to reflect the name of the file in the
        currently selected tab.
        """
        current_tab = self.widget(tab_id)
        window = self.nativeParentWidget()
        if current_tab:
            window.update_title(current_tab.label)
        else:
            window.update_title(None)


class ChatWorker(QThread):
    """Worker thread for handling chat responses."""
    response_ready = pyqtSignal(str)

    def __init__(self, message):
        super().__init__()
        self.message = message
        # Configure markdown with extensions
        self.md = markdown.Markdown(extensions=[
            'fenced_code',
            'codehilite',
            'tables',
            'nl2br'
        ])
        
    def format_code_blocks(self, html):
        """Add syntax highlighting and styling to code blocks"""
        # Add syntax highlighting classes
        html = html.replace('<pre><code>', 
                          '<pre><code class="syntax-highlighted">')
        
        # Add custom styling
        style = """
            <style>
                .syntax-highlighted {
                    background-color: #f8f8f8;
                    padding: 10px;
                    border-radius: 5px;
                    font-family: 'Courier New', monospace;
                    margin: 10px 0;
                }
                code {
                    background-color: #f0f0f0;
                    padding: 2px 4px;
                    border-radius: 3px;
                    font-family: 'Courier New', monospace;
                }
            </style>
        """
        return style + html

    def format_response(self, text):
        """Format the response text with proper markdown parsing"""
        try:
            # Convert markdown to HTML
            html = self.md.convert(text)
            
            # Add code styling
            html = self.format_code_blocks(html)
            
            # Wrap response in a div with styling
            html = f"""
                <div style="font-family: sans-serif; line-height: 1.6;">
                    {html}
                </div>
            """
            
            return html
            
        except Exception as e:
            logger.error(f"Error formatting response: {str(e)}")
            return text

    def run(self):
        try:
            client = genai.Client(api_key="AIzaSyBkxckP-r4rZVQcbj9CeM_M0bvFJhaHfmM")
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                config=types.GenerateContentConfig(
                system_instruction="keep it simple"),
                contents=self.message)
            # Format the response using markdown parser
            formatted_response = self.format_response(response.text.strip())
            self.response_ready.emit(formatted_response)
        except Exception as e:
            self.response_ready.emit(f"Error: {str(e)}")


class Window(QMainWindow):
    """
    Defines the look and characteristics of the application's main window.
    """
    def __init__(self):
        super().__init__()
        self.init_ui()  # Ensure UI setup is done

    title = _("Mu {}").format(__version__)
    icon = "icon"
    timer = None
    usb_checker = None
    serial = None
    repl = None
    plotter = None

    _zoom_in = pyqtSignal(int)
    _zoom_out = pyqtSignal(int)
    close_serial = pyqtSignal()
    write_to_serial = pyqtSignal(bytes)
    data_received = pyqtSignal(bytes)
    open_file = pyqtSignal(str)
    load_theme = pyqtSignal(str)
    
    def init_ui(self):
        menubar = self.menuBar()
        print("added menu")
        # Menu's
        file_menu = menubar.addMenu("File")
        tools_menu = menubar.addMenu("Tools")
        board_menu = menubar.addMenu("Board")

        # Create "Text to Speech" action for "Tools" menu
        tts_action = QAction("Text to Speech", self)
        tts_action.triggered.connect(self.open_tts_tool)

        # Create "Board Info" action for "Board" menu
        board_info_action = QAction("Board Info", self)
        board_info_action.triggered.connect(self.show_board_info)

        # Create "Library Manager" action for "Board" menu
        library_manager_action = QAction("Library Manager", self)
        library_manager_action.triggered.connect(self.show_library_manager)

        file_menu.addAction(tts_action)
        tools_menu.addAction(tts_action)
        
        # Add actions to "Board" menu
        board_menu.addAction(board_info_action)
        board_menu.addAction(library_manager_action)

        # Create actions with shortcuts
        new_action = QAction("New", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self.new_file)

        load_action = QAction("Load", self)
        load_action.setShortcut(QKeySequence.Open)
        load_action.triggered.connect(self.load_file)

        save_action = QAction("Save", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self.save_file)

        # Add actions to File menu
        file_menu.addAction(new_action)
        file_menu.addAction(load_action)
        file_menu.addAction(save_action)
        file_menu.addSeparator()  # Adds a separator line

    def new_file(self):
        QMessageBox.information(self, "New File", "Create a new file...")
        

    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open File", "", "All Files (*)")
        return file_path
    
    def save_file(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save File", "", "All Files (*)")
        return file_path
    
    def show_library_manager(self):
        """Opens the CircuitPython Library Manager when menu is clicked."""
        if not hasattr(self, 'library_manager_window') or not self.library_manager_window.isVisible():
            self.library_manager_window = LibraryManagerUI()
            self.library_manager_window.show()

    def show_board_info(self):
        """
        Display information about the connected CircuitPython board.
        """
        try:
            comports = adafruit_board_toolkit.circuitpython_serial.repl_comports()

            if not comports:
                QMessageBox.warning(self, "Board Info", "No CircuitPython board detected.")
                return

            board_info = "Connected CircuitPython Board:\n\n"
            uname_dict = {}

            for comport in comports:
                # Add basic board info
                board_info += f"Device Path: {comport.device}\n"
                board_info += f"VID: {hex(comport.vid)}\n"
                board_info += f"PID: {hex(comport.pid)}\n"
                board_info += f"Serial Number: {comport.serial_number or 'N/A'}\n\n"

                try:
                    with serial.Serial(comport.device, 115200, timeout=2) as ser:
                        # Clear any existing data
                        ser.reset_input_buffer()
                        
                        # Send commands with proper delays
                        commands = [
                            (b"\x03", 0.1),  # CTRL+C
                            (b"\n\n", 0.2),  # New lines
                            (b"import os\r\n", 0.2),
                            (b"print(os.uname())\r\n", 0.2)
                        ]
                        
                        for cmd, delay in commands:
                            ser.write(cmd)
                            time.sleep(delay)

                        # Read and process output
                        output = ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
                        
                        # Filter and clean output
                        lines = [line.strip() for line in output.splitlines() 
                                if line.strip() and not line.startswith(">>>")]
                        clean_output = " ".join(lines)
                        
                        # Parse uname output
                        if clean_output.startswith("(") and clean_output.endswith(")"):
                            clean_output = clean_output.strip("()")
                            for pair in clean_output.split(", "):
                                key, value = pair.split("=")
                                uname_dict[key.strip()] = value.strip("'")
                        
                        # Format output        
                        formatted_uname = "\n".join(f"{key}: {value}" 
                                                for key, value in uname_dict.items())
                        board_info += f"Board OS Info:\n\n{formatted_uname}"
                    
                except serial.SerialException as e:
                    board_info += f"Error: Could not open serial port - {str(e)}\n"
                except Exception as e:
                    board_info += f"Error: {str(e)}\n"

            # Display info in message box
            QMessageBox.information(self, "Board Info", board_info)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")          

    def open_tts_tool(self):
        """
        Opens the Text to Speech tool in a new tab.
        """
        self.tts_window = QWidget()
        self.tts_window.setWindowTitle("Text to Speech Tool")

        # Layout for the TTS tool
        layout = QVBoxLayout()

        # Text input field
        self.text_input = QLineEdit(self)
        self.text_input.setPlaceholderText("Enter text here...")
        layout.addWidget(self.text_input)
        
        # Language selection combo box
        self.language_combo = QComboBox(self)
        self.language_combo.addItems(["en", "es", "fr", "de", "it"])
        layout.addWidget(self.language_combo)

        # Button to generate TTS
        self.generate_button = QPushButton("Generate Speech", self)
        self.generate_button.clicked.connect(self.generate_speech)
        layout.addWidget(self.generate_button)

            # Set a minimum window size for the TTS window
        self.tts_window.setLayout(layout)
        self.tts_window.setMinimumWidth(400)  # Set minimum width
        self.tts_window.setMinimumHeight(300)  # Set minimum height
        self.tts_window.show()

    def generate_speech(self):
        """
        Generates speech based on user input and selected options.
        """
        text = self.text_input.text()
        language = self.language_combo.currentText()
        if not text:
            # Show a warning if no text is provided
            QMessageBox.warning(self, "Input Error", "Please enter some text.")
            return

        # Create the GTTS Helper instance
        tts_helper = GTTSHelper(language=language)

        # Generate and save the speech
        tts_helper.text_to_speech(text)

    def open_chat_dock(self):
        """
        Opens the Chat Assistant as a dockable widget.
        """
        if not hasattr(self, 'chat_dock') or self.chat_dock is None:
            # Create the chat dock widget
            self.chat_dock = QDockWidget("Chat Assistant", self)
            self.chat_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

            # Create the chat interface
            chat_widget = QWidget()
            chat_widget.setContentsMargins(10, 10, 10, 10)
            layout = QVBoxLayout()
            layout.setContentsMargins(5, 5, 5, 5)

            # Chat display area
            self.chat_display = QTextEdit(chat_widget)
            self.chat_display.setReadOnly(True)
            layout.addWidget(self.chat_display)

            # User input field
            self.chat_input = QLineEdit(chat_widget)
            self.chat_input.setPlaceholderText("Type your message here...")
            self.chat_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #ccc;
                border-radius: 5px;
                padding: 10px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border-color: #5d9bfc;
            }
        """)
            self.chat_input.returnPressed.connect(self.handle_chat_input)
            layout.addWidget(self.chat_input)

            # Add a checkbox to attach code and prompt
            self.attach_code_checkbox = QCheckBox("Attach code", chat_widget)
            self.attach_code_checkbox.setStyleSheet("font-size: 14px;")
            layout.addWidget(self.attach_code_checkbox)

            chat_widget.setLayout(layout)
            self.chat_dock.setWidget(chat_widget)

            # Add the dock to the main window
            self.addDockWidget(Qt.RightDockWidgetArea, self.chat_dock)
            self.chat_dock.setStyleSheet("QDockWidget { background-color: #ffffff; border: 1px solid #ddd; border-radius: 8px; }")

        # Show the dock if it's hidden
        self.chat_dock.show()

    def handle_chat_input(self):
        """
        Handles user input in the chat interface and displays responses.
        """
        user_message = self.chat_input.text().strip()
        if not user_message:
            return

        # Check if code should be attached
        attach_code = self.attach_code_checkbox.isChecked()
        if attach_code:
            editor_content = self.get_editor_content()
            if editor_content:
                user_message += f"\n\n<b>Attached Code:</b>\n{editor_content}"

        # Display user message and clear input
        self.chat_display.append(f'<div style="color: #0078D4; margin-bottom: 10px;"><b>You:</b> {user_message}</div>')
        self.chat_input.clear()
        self.chat_input.setEnabled(False)  # Disable input while processing

        # Create and start worker thread
        self.chat_worker = ChatWorker(user_message)
        self.chat_worker.response_ready.connect(self.handle_chat_response)
        self.chat_worker.finished.connect(lambda: self.chat_input.setEnabled(True))  # Re-enable input when done
        self.chat_worker.start()

    def handle_chat_response(self, response):
        """Handle the chat response from the worker thread."""
        formatted_response = f'<div style="background-color: #f5f5f5; padding: 10px; border-radius: 5px; margin: 10px 0;"><b>Assistant:</b><br>{response}</div>'
        self.chat_display.append(formatted_response)
        # Scroll to the bottom to show latest message
        self.chat_display.verticalScrollBar().setValue(
            self.chat_display.verticalScrollBar().maximum()
        )

    def generate_chat_response(self, message):
        """
        This method is no longer used directly - functionality moved to ChatWorker
        """
        pass
    
    def get_editor_content(self):
        """
        Reads the content of the currently active editor tab.
        """
        current_tab = self.current_tab
        if current_tab:
            # Assuming the EditorPane has a method `toPlainText()` to get the text
            return current_tab.text()
        else:
            QMessageBox.warning(self, "No Active Tab", "There is no active editor tab.")
            return None   
            
    def zoom_in(self):
        """
        Handles zooming in.
        """
        self._zoom_in.emit(2)

    def zoom_out(self):
        """
        Handles zooming out.
        """
        self._zoom_out.emit(2)

    def connect_zoom(self, widget):
        """
        Connects a referenced widget to the zoom related signals.
        """
        self._zoom_in.connect(widget.zoomIn)
        self._zoom_out.connect(widget.zoomOut)

    @property
    def current_tab(self):
        """
        Returns the currently focussed tab.
        """
        return self.tabs.currentWidget()

    def set_read_only(self, is_readonly):
        """
        Set all tabs read-only.
        """
        self.read_only_tabs = is_readonly
        for tab in self.widgets:
            tab.setReadOnly(is_readonly)

    def get_load_path(self, folder, extensions='*'):
        """
        Displays a dialog for selecting a file to load. Returns the selected
        path. Defaults to start in the referenced folder.
        """
        path, _ = QFileDialog.getOpenFileName(self.widget, 'Open file', folder,
                                              extensions)
        logger.debug('Getting load path: {}'.format(path))
        return path

    def get_save_path(self, folder):
        """
        Displays a dialog for selecting a file to save. Returns the selected
        path. Defaults to start in the referenced folder.
        """
        path, _ = QFileDialog.getSaveFileName(self.widget, 'Save file', folder)
        logger.debug('Getting save path: {}'.format(path))
        return path

    def get_microbit_path(self, folder):
        """
        Displays a dialog for locating the location of the BBC micro:bit in the
        host computer's filesystem. Returns the selected path. Defaults to
        start in the referenced folder.
        """
        path = QFileDialog.getExistingDirectory(self.widget,
                                                'Locate BBC micro:bit', folder,
                                                QFileDialog.ShowDirsOnly)
        logger.debug('Getting micro:bit path: {}'.format(path))
        return path

    def add_tab(self, path, text, api, newline):
        """
        Adds a tab with the referenced path and text to the editor.
        """
        new_tab = EditorPane(path, text, newline)
        new_tab.connect_margin(self.breakpoint_toggle)
        new_tab_index = self.tabs.addTab(new_tab, new_tab.label)
        new_tab.set_api(api)

        @new_tab.modificationChanged.connect
        def on_modified():
            modified_tab_index = self.tabs.currentIndex()
            self.tabs.setTabText(modified_tab_index, new_tab.label)
            self.update_title(new_tab.label)

        @new_tab.open_file.connect
        def on_open_file(file):
            # Bubble the signal up
            self.open_file.emit(file)

        self.tabs.setCurrentIndex(new_tab_index)
        self.connect_zoom(new_tab)
        self.set_theme(self.theme)
        new_tab.setFocus()
        if self.read_only_tabs:
            new_tab.setReadOnly(self.read_only_tabs)

    def focus_tab(self, tab):
        index = self.tabs.indexOf(tab)
        self.tabs.setCurrentIndex(index)
        tab.setFocus()

    @property
    def tab_count(self):
        """
        Returns the number of active tabs.
        """
        return self.tabs.count()

    @property
    def widgets(self):
        """
        Returns a list of references to the widgets representing tabs in the
        editor.
        """
        return [self.tabs.widget(i) for i in range(self.tab_count)]

    @property
    def modified(self):
        """
        Returns a boolean indication if there are any modified tabs in the
        editor.
        """
        for widget in self.widgets:
            if widget.isModified():
                return True
        return False

    def on_serial_read(self):
        """
        Called when the connected device is ready to send data via the serial
        connection. It reads all the available data, emits the data_received
        signal with the received bytes and, if appropriate, emits the
        tuple_received signal with the tuple created from the bytes received.
        """
        data = bytes(self.serial.readAll())  # get all the available bytes.
        self.data_received.emit(data)

    def on_stdout_write(self, data):
        """
        Called when either a running script or the REPL write to STDOUT.
        """
        self.data_received.emit(data)

    def open_serial_link(self, port):
        """
        Creates a new serial link instance.
        """
        self.input_buffer = []
        self.serial = QSerialPort()
        self.serial.setPortName(port)
        if self.serial.open(QIODevice.ReadWrite):
            self.serial.dataTerminalReady = True
            if not self.serial.isDataTerminalReady():
                # Using pyserial as a 'hack' to open the port and set DTR
                # as QtSerial does not seem to work on some Windows :(
                # See issues #281 and #302 for details.
                self.serial.close()
                pyser = serial.Serial(port)  # open serial port w/pyserial
                pyser.dtr = True
                pyser.close()
                self.serial.open(QIODevice.ReadWrite)
            self.serial.setBaudRate(115200)
            self.serial.readyRead.connect(self.on_serial_read)
        else:
            msg = _("Cannot connect to device on port {}").format(port)
            raise IOError(msg)

    def close_serial_link(self):
        """
        Close and clean up the currently open serial link.
        """
        if self.serial:
            self.serial.close()
            self.serial = None

    def add_filesystem(self, home, file_manager):
        """
        Adds the file system pane to the application.
        """
        self.fs_pane = FileSystemPane(home)

        @self.fs_pane.open_file.connect
        def on_open_file(file):
            # Bubble the signal up
            self.open_file.emit(file)

        self.fs = QDockWidget(_('Filesystem on micro:bit'))
        self.fs.setWidget(self.fs_pane)
        self.fs.setFeatures(QDockWidget.DockWidgetMovable)
        self.fs.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.fs)
        self.fs_pane.setFocus()
        file_manager.on_list_files.connect(self.fs_pane.on_ls)
        self.fs_pane.list_files.connect(file_manager.ls)
        self.fs_pane.microbit_fs.put.connect(file_manager.put)
        self.fs_pane.microbit_fs.delete.connect(file_manager.delete)
        self.fs_pane.microbit_fs.list_files.connect(file_manager.ls)
        self.fs_pane.local_fs.get.connect(file_manager.get)
        self.fs_pane.local_fs.list_files.connect(file_manager.ls)
        file_manager.on_put_file.connect(self.fs_pane.microbit_fs.on_put)
        file_manager.on_delete_file.connect(self.fs_pane.microbit_fs.on_delete)
        file_manager.on_get_file.connect(self.fs_pane.local_fs.on_get)
        file_manager.on_list_fail.connect(self.fs_pane.on_ls_fail)
        file_manager.on_put_fail.connect(self.fs_pane.on_put_fail)
        file_manager.on_delete_fail.connect(self.fs_pane.on_delete_fail)
        file_manager.on_get_fail.connect(self.fs_pane.on_get_fail)
        self.connect_zoom(self.fs_pane)
        return self.fs_pane

    def add_micropython_repl(self, port, name, force_interrupt=True):
        """
        Adds a MicroPython based REPL pane to the application.
        """
        if not self.serial:
            self.open_serial_link(port)
            if force_interrupt:
                # Send a Control-B / exit raw mode.
                self.serial.write(b'\x02')
                # Send a Control-C / keyboard interrupt.
                self.serial.write(b'\x03')
        repl_pane = MicroPythonREPLPane(serial=self.serial)
        self.data_received.connect(repl_pane.process_bytes)
        self.add_repl(repl_pane, name)

    def add_micropython_plotter(self, port, name, mode):
        """
        Adds a plotter that reads data from a serial connection.
        """
        if not self.serial:
            self.open_serial_link(port)
        plotter_pane = PlotterPane()
        self.data_received.connect(plotter_pane.process_bytes)
        plotter_pane.data_flood.connect(mode.on_data_flood)
        self.add_plotter(plotter_pane, name)

    def add_python3_plotter(self, mode):
        """
        Add a plotter that reads from either the REPL or a running script.
        Since this function will only be called when either the REPL or a
        running script are running (but not at the same time), it'll just grab
        data emitted by the REPL or script via data_received.
        """
        plotter_pane = PlotterPane()
        self.data_received.connect(plotter_pane.process_bytes)
        plotter_pane.data_flood.connect(mode.on_data_flood)
        self.add_plotter(plotter_pane, _('Python3 data tuple'))

    def add_jupyter_repl(self, kernel_manager, kernel_client):
        """
        Adds a Jupyter based REPL pane to the application.
        """
        kernel_manager.kernel.gui = 'qt4'
        kernel_client.start_channels()
        ipython_widget = JupyterREPLPane()
        ipython_widget.kernel_manager = kernel_manager
        ipython_widget.kernel_client = kernel_client
        ipython_widget.on_append_text.connect(self.on_stdout_write)
        self.add_repl(ipython_widget, _('Python3 (Jupyter)'))

    def add_repl(self, repl_pane, name):
        """
        Adds the referenced REPL pane to the application.
        """
        self.repl_pane = repl_pane
        self.repl = QDockWidget(_('{} REPL').format(name))
        self.repl.setWidget(repl_pane)
        self.repl.setFeatures(QDockWidget.DockWidgetMovable)
        self.repl.setAllowedAreas(Qt.BottomDockWidgetArea |
                                  Qt.LeftDockWidgetArea |
                                  Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.repl)
        self.connect_zoom(self.repl_pane)
        self.repl_pane.set_theme(self.theme)
        self.repl_pane.setFocus()

    def add_plotter(self, plotter_pane, name):
        """
        Adds the referenced plotter pane to the application.
        """
        self.plotter_pane = plotter_pane
        self.plotter = QDockWidget(_('{} Plotter').format(name))
        self.plotter.setWidget(plotter_pane)
        self.plotter.setFeatures(QDockWidget.DockWidgetMovable)
        self.plotter.setAllowedAreas(Qt.BottomDockWidgetArea |
                                     Qt.LeftDockWidgetArea |
                                     Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.plotter)
        self.plotter_pane.set_theme(self.theme)
        self.plotter_pane.setFocus()

    def add_python3_runner(self, script_name, working_directory,
                           interactive=False, debugger=False,
                           command_args=None, runner=None, envars=None,
                           python_args=None):
        """
        Display console output for the referenced Python script.

        The script will be run within the workspace_path directory.

        If interactive is True (default is False) the Python process will
        run in interactive mode (dropping the user into the REPL when the
        script completes).

        If debugger is True (default is False) the script will be run within
        a debug runner session. The debugger overrides the interactive flag
        (you cannot run the debugger in interactive mode).

        If there is a list of command_args (the default is None) then these
        will be passed as further arguments into the command run in the
        new process.

        If runner is given, this is used as the command to start the Python
        process.

        If envars is given, these will become part of the environment context
        of the new chlid process.

        If python_args is given, these will be passed as arguments to the
        Python runtime used to launch the child process.
        """
        self.process_runner = PythonProcessPane(self)
        self.runner = QDockWidget(_("Running: {}").format(
                                  os.path.basename(script_name)))
        self.runner.setWidget(self.process_runner)
        self.runner.setFeatures(QDockWidget.DockWidgetMovable)
        self.runner.setAllowedAreas(Qt.BottomDockWidgetArea |
                                    Qt.LeftDockWidgetArea |
                                    Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.runner)
        self.process_runner.start_process(script_name, working_directory,
                                          interactive, debugger, command_args,
                                          envars, runner, python_args)
        self.process_runner.setFocus()
        self.process_runner.on_append_text.connect(self.on_stdout_write)
        self.connect_zoom(self.process_runner)
        return self.process_runner

    def add_debug_inspector(self):
        """
        Display a debug inspector to view the call stack.
        """
        self.debug_inspector = DebugInspector()
        self.debug_model = QStandardItemModel()
        self.debug_inspector.setModel(self.debug_model)
        self.inspector = QDockWidget(_('Debug Inspector'))
        self.inspector.setWidget(self.debug_inspector)
        self.inspector.setFeatures(QDockWidget.DockWidgetMovable)
        self.inspector.setAllowedAreas(Qt.BottomDockWidgetArea |
                                       Qt.LeftDockWidgetArea |
                                       Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.RightDockWidgetArea, self.inspector)
        self.connect_zoom(self.debug_inspector)

    def update_debug_inspector(self, locals_dict):
        """
        Given the contents of a dict representation of the locals in the
        current stack frame, update the debug inspector with the new values.
        """
        excluded_names = ['__builtins__', '__debug_code__',
                          '__debug_script__', ]
        names = sorted([x for x in locals_dict if x not in excluded_names])
        self.debug_model.clear()
        self.debug_model.setHorizontalHeaderLabels([_('Name'), _('Value'), ])
        for name in names:
            try:
                # DANGER!
                val = eval(locals_dict[name])
            except Exception:
                val = None
            if isinstance(val, list):
                # Show a list consisting of rows of position/value
                list_item = DebugInspectorItem(name)
                for i, i_val in enumerate(val):
                    list_item.appendRow([
                        DebugInspectorItem(str(i)),
                        DebugInspectorItem(repr(i_val))
                    ])
                self.debug_model.appendRow([
                    list_item,
                    DebugInspectorItem(_('(A list of {} items.)')
                                       .format(len(val)))
                ])
            elif isinstance(val, dict):
                # Show a dict consisting of rows of key/value pairs.
                dict_item = DebugInspectorItem(name)
                for k, k_val in val.items():
                    dict_item.appendRow([
                        DebugInspectorItem(repr(k)),
                        DebugInspectorItem(repr(k_val))
                    ])
                self.debug_model.appendRow([
                    dict_item,
                    DebugInspectorItem(_('(A dict of {} items.)')
                                       .format(len(val)))
                ])
            else:
                self.debug_model.appendRow([
                    DebugInspectorItem(name),
                    DebugInspectorItem(locals_dict[name]),
                ])

    def remove_filesystem(self):
        """
        Removes the file system pane from the application.
        """
        if hasattr(self, 'fs') and self.fs:
            self.fs_pane = None
            self.fs.setParent(None)
            self.fs.deleteLater()
            self.fs = None

    def remove_repl(self):
        """
        Removes the REPL pane from the application.
        """
        if self.repl:
            self.repl_pane = None
            self.repl.setParent(None)
            self.repl.deleteLater()
            self.repl = None
            if not self.plotter:
                self.close_serial_link()

    def remove_plotter(self):
        """
        Removes the plotter pane from the application.
        """
        if self.plotter:
            self.plotter_pane = None
            self.plotter.setParent(None)
            self.plotter.deleteLater()
            self.plotter = None
            if not self.repl:
                self.close_serial_link()

    def remove_python_runner(self):
        """
        Removes the runner pane from the application.
        """
        if hasattr(self, 'runner') and self.runner:
            self.process_runner = None
            self.runner.setParent(None)
            self.runner.deleteLater()
            self.runner = None

    def remove_debug_inspector(self):
        """
        Removes the debug inspector pane from the application.
        """
        if hasattr(self, 'inspector') and self.inspector:
            self.debug_inspector = None
            self.debug_model = None
            self.inspector.setParent(None)
            self.inspector.deleteLater()
            self.inspector = None

    def set_theme(self, theme):
        """
        Sets the theme for the REPL and editor tabs.
        """
        self.theme = theme
        self.load_theme.emit(theme)
        if theme == 'contrast':
            new_theme = ContrastTheme
            new_icon = 'theme_day'
        elif theme == 'night':
            new_theme = NightTheme
            new_icon = 'theme_contrast'
        else:
            new_theme = DayTheme
            new_icon = 'theme'
        for widget in self.widgets:
            widget.set_theme(new_theme)
        self.button_bar.slots['theme'].setIcon(load_icon(new_icon))
        if hasattr(self, 'repl') and self.repl:
            self.repl_pane.set_theme(theme)
        if hasattr(self, 'plotter') and self.plotter:
            self.plotter_pane.set_theme(theme)

    def show_admin(self, log, settings):
        """
        Display the administrative dialog with referenced content of the log
        and settings. Return a dictionary of the settings that may have been
        changed by the admin dialog.
        """
        admin_box = AdminDialog(self)
        admin_box.setup(log, settings)
        admin_box.exec()
        return admin_box.settings()

    def show_message(self, message, information=None, icon=None):
        """
        Displays a modal message to the user.

        If information is passed in this will be set as the additional
        informative text in the modal dialog.

        Since this mechanism will be used mainly for warning users that
        something is awry the default icon is set to "Warning". It's possible
        to override the icon to one of the following settings: NoIcon,
        Question, Information, Warning or Critical.
        """
        message_box = QMessageBox(self)
        message_box.setText(message)
        message_box.setWindowTitle('Mu')
        if information:
            message_box.setInformativeText(information)
        if icon and hasattr(message_box, icon):
            message_box.setIcon(getattr(message_box, icon))
        else:
            message_box.setIcon(message_box.Warning)
        logger.debug(message)
        logger.debug(information)
        message_box.exec()

    def show_confirmation(self, message, information=None, icon=None):
        """
        Displays a modal message to the user to which they need to confirm or
        cancel.

        If information is passed in this will be set as the additional
        informative text in the modal dialog.

        Since this mechanism will be used mainly for warning users that
        something is awry the default icon is set to "Warning". It's possible
        to override the icon to one of the following settings: NoIcon,
        Question, Information, Warning or Critical.
        """
        message_box = QMessageBox(self)
        message_box.setText(message)
        message_box.setWindowTitle(_('Mu'))
        if information:
            message_box.setInformativeText(information)
        if icon and hasattr(message_box, icon):
            message_box.setIcon(getattr(message_box, icon))
        else:
            message_box.setIcon(message_box.Warning)
        message_box.setStandardButtons(message_box.Cancel | message_box.Ok)
        message_box.setDefaultButton(message_box.Cancel)
        logger.debug(message)
        logger.debug(information)
        return message_box.exec()

    def update_title(self, filename=None):
        """
        Updates the title bar of the application. If a filename (representing
        the name of the file currently the focus of the editor) is supplied,
        append it to the end of the title.
        """
        title = self.title
        if filename:
            title += ' - ' + filename
        self.setWindowTitle(title)

    def autosize_window(self):
        """
        Makes the editor 80% of the width*height of the screen and centres it.
        """
        screen = QDesktopWidget().screenGeometry()
        w = int(screen.width() * 0.8)
        h = int(screen.height() * 0.8)
        self.resize(w, h)
        size = self.geometry()
        self.move((screen.width() - size.width()) // 2,
                  (screen.height() - size.height()) // 2)

    def reset_annotations(self):
        """
        Resets the state of annotations on the current tab.
        """
        self.current_tab.reset_annotations()

    def annotate_code(self, feedback, annotation_type):
        """
        Given a list of annotations about the code in the current tab, add
        the annotations to the editor window so the user can make appropriate
        changes.
        """
        self.current_tab.annotate_code(feedback, annotation_type)

    def show_annotations(self):
        """
        Show the annotations added to the current tab.
        """
        self.current_tab.show_annotations()

    def setup(self, breakpoint_toggle, theme):
        """
        Sets up the window.

        Defines the various attributes of the window and defines how the user
        interface is laid out.
        """
        self.theme = theme
        self.breakpoint_toggle = breakpoint_toggle
        # Give the window a default icon, title and minimum size.
        self.setWindowIcon(load_icon(self.icon))
        self.update_title()
        self.read_only_tabs = False
        self.setMinimumSize(820, 400)
        self.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)

        self.widget = QWidget()

        widget_layout = QVBoxLayout()
        self.widget.setLayout(widget_layout)
        self.button_bar = ButtonBar(self.widget)
        self.tabs = FileTabs()
        self.tabs.setMovable(True)
        self.setCentralWidget(self.tabs)
        self.status_bar = StatusBar(parent=self)
        self.setStatusBar(self.status_bar)
        self.addToolBar(self.button_bar)
        self.show()
        self.autosize_window()

    def resizeEvent(self, resizeEvent):
        """
        Respond to window getting too small for the button bar to fit well.
        """
        size = resizeEvent.size()
        self.button_bar.set_responsive_mode(size.width(), size.height())

    def select_mode(self, modes, current_mode):
        """
        Display the mode selector dialog and return the result.
        """
        mode_select = ModeSelector(self)
        mode_select.setup(modes, current_mode)
        mode_select.exec()
        try:
            return mode_select.get_mode()
        except Exception:
            return None

    def change_mode(self, mode):
        """
        Given a an object representing a mode, recreates the button bar with
        the expected functionality.
        """
        self.button_bar.change_mode(mode)
        # Update the autocomplete / tooltip APIs for each tab to the new mode.
        api = mode.api()
        for widget in self.widgets:
            widget.set_api(api)

    def set_usb_checker(self, duration, callback):
        """
        Sets up a timer that polls for USB changes via the "callback" every
        "duration" seconds.
        """
        self.usb_checker = QTimer()
        self.usb_checker.timeout.connect(callback)
        self.usb_checker.start(duration * 1000)

    def set_timer(self, duration, callback):
        """
        Set a repeating timer to call "callback" every "duration" seconds.
        """
        self.timer = QTimer()
        self.timer.timeout.connect(callback)
        self.timer.start(duration * 1000)  # Measured in milliseconds.

    def stop_timer(self):
        """
        Stop the repeating timer.
        """
        if self.timer:
            self.timer.stop()
            self.timer = None

    def connect_tab_rename(self, handler, shortcut):
        """
        Connect the double-click event on a tab and the keyboard shortcut to
        the referenced handler (causing the Save As dialog).
        """
        self.tabs.shortcut = QShortcut(QKeySequence(shortcut), self)
        self.tabs.shortcut.activated.connect(handler)
        self.tabs.tabBarDoubleClicked.connect(handler)

    def open_directory_from_os(self, path):
        """
        Given the path to a directory, open the OS's built in filesystem
        explorer for that path. Works with Windows, OSX and Linux.
        """
        if sys.platform == 'win32':
            # Windows
            os.startfile(path)
        elif sys.platform == 'darwin':
            # OSX
            os.system('open "{}"'.format(path))
        else:
            # Assume freedesktop.org on unix-y.
            os.system('xdg-open "{}"'.format(path))

    def connect_find_replace(self, handler, shortcut):
        """
        Create a keyboard shortcut and associate it with a handler for doing
        a find and replace.
        """
        self.find_replace_shortcut = QShortcut(QKeySequence(shortcut), self)
        self.find_replace_shortcut.activated.connect(handler)

    def show_find_replace(self, find, replace, global_replace):
        """
        Display the find/replace dialog. If the dialog's OK button was clicked
        return a tuple containing the find term, replace term and global
        replace flag.
        """
        finder = FindReplaceDialog(self)
        finder.setup(find, replace, global_replace)
        if finder.exec():
            return (finder.find(), finder.replace(), finder.replace_flag())

    def replace_text(self, target_text, replace, global_replace):
        """
        Given target_text, replace the first instance after the cursor with
        "replace". If global_replace is true, replace all instances of
        "target". Returns the number of times replacement has occurred.
        """
        if not self.current_tab:
            return 0
        if global_replace:
            counter = 0
            found = self.current_tab.findFirst(target_text, True, True,
                                               False, False, line=0, index=0)
            if found:
                counter += 1
                self.current_tab.replace(replace)
                while self.current_tab.findNext():
                    self.current_tab.replace(replace)
                    counter += 1
            return counter
        else:
            found = self.current_tab.findFirst(target_text, True, True, False,
                                               True)
            if found:
                self.current_tab.replace(replace)
                return 1
            else:
                return 0

    def highlight_text(self, target_text):
        """
        Highlight the first match from the current position of the cursor in
        the current tab for the target_text. Returns True if there's a match.
        """
        if self.current_tab:
            return self.current_tab.findFirst(target_text, True, True, False,
                                              True)
        else:
            return False

    def connect_toggle_comments(self, handler, shortcut):
        """
        Create a keyboard shortcut and associate it with a handler for toggling
        comments on highlighted lines.
        """
        self.toggle_comments_shortcut = QShortcut(QKeySequence(shortcut), self)
        self.toggle_comments_shortcut.activated.connect(handler)

    def toggle_comments(self):
        """
        Toggle comments on/off for all selected line in the currently active
        tab.
        """
        if self.current_tab:
            self.current_tab.toggle_comments()


class StatusBar(QStatusBar):
    """
    Defines the look and behaviour of the status bar along the bottom of the
    UI.
    """
    def __init__(self, parent=None, mode='python'):
        super().__init__(parent)
        self.mode = mode
        # Mode selector.
        self.mode_label = QLabel()
        self.mode_label.setToolTip(_("Mu's current mode of behaviour."))
        self.addPermanentWidget(self.mode_label)
        self.set_mode(mode)
        # Logs viewer
        self.logs_label = QLabel()
        self.logs_label.setObjectName('AdministrationLabel')
        self.logs_label.setPixmap(load_pixmap('logs').scaledToHeight(24))
        self.logs_label.setToolTip(_('Mu Administration'))
        self.addPermanentWidget(self.logs_label)

    def connect_logs(self, handler, shortcut):
        """
        Connect the mouse press event and keyboard shortcut for the log widget
        to the referenced handler function.
        """
        self.logs_label.shortcut = QShortcut(QKeySequence(shortcut),
                                             self.parent())
        self.logs_label.shortcut.activated.connect(handler)
        self.logs_label.mousePressEvent = handler

    def connect_mode(self, handler, shortcut):
        """
        Connect the mouse press event and keyboard shortcut for the mode widget
        to the referenced handler function.
        """
        self.mode_label.shortcut = QShortcut(QKeySequence(shortcut),
                                             self.parent())
        self.mode_label.shortcut.activated.connect(handler)
        self.mode_label.mousePressEvent = handler

    def set_message(self, message, pause=5000):
        """
        Displays a message in the status bar for a certain period of time.
        """
        self.showMessage(message, pause)

    def set_mode(self, mode):
        """
        Updates the mode label to the new mode.
        """
        self.mode_label.setText(mode.capitalize())
