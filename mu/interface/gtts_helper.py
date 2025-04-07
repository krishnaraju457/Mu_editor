from gtts import gTTS
from PyQt5.QtWidgets import QFileDialog,QMessageBox

class GTTSHelper:
    def __init__(self, language="en", slow=False, bitrate="16k", output_format="wav"):
        self.language = language
        self.slow = slow
        self.bitrate = bitrate
        self.output_format = output_format

    def text_to_speech(self, text):
        try:
            # Convert text to speech
            tts = gTTS(text=text, lang=self.language, slow=self.slow)
            
            # Ask user to select a save location and filename
            file_path, _ = QFileDialog.getSaveFileName(
                None, "Save Speech as MP3", "", "MP3 Files (*.mp3/*.wav);;All Files (*)")
            
            if file_path:
                # Save the audio file at the selected location
                tts.save(file_path)
                QMessageBox.information(None, "Success", f"Speech saved successfully to {file_path}")
            else:
                QMessageBox.warning(None, "Save Error", "No file selected. Speech not saved.")
                
        except Exception as e:
            QMessageBox.warning(None, "Error", f"An error occurred while generating speech: {e}")
