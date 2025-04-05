import sys
import os
import time
import datetime
import requests
from PyQt5 import QtWidgets, QtCore, QtGui


class FluxAPI:
    """Handles all Flux API interactions with proper error handling and retries."""

    BASE_URL = "https://api.us1.bfl.ai/v1/flux-pro-1.1-ultra"
    MAX_ATTEMPTS = 10
    POLL_INTERVAL = 5

    def __init__(self):
        self.api_key = os.environ.get("FLUX_API_KEY")
        if not self.api_key:
            raise ValueError("FLUX_API_KEY environment variable not set")

    @property
    def headers(self):
        return {
            "X-Key": self.api_key,
            "Content-Type": "application/json"
        }

    def generate_image(self, prompt, aspect_ratio, quality):
        """Generate image with Flux API with progress tracking."""
        payload = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": "jpeg",
            "quality": quality,
            "safety_tolerance": "6",
            "raw": "true"
        }

        # Initial request to start generation
        response = requests.post(self.BASE_URL, headers=self.headers, json=payload)
        response.raise_for_status()

        polling_url = response.json().get("polling_url")
        if not polling_url:
            raise ValueError("No polling URL received from API")

        # Poll for results
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            poll_response = requests.get(polling_url, headers=self.headers)
            poll_response.raise_for_status()
            poll_data = poll_response.json()

            status = poll_data.get("status")
            if status == "Ready":
                return poll_data.get("result", {}).get("sample")
            elif status in ["Request Moderated", "Content Moderated"]:
                raise ValueError("Content moderated as unsafe")

            time.sleep(self.POLL_INTERVAL)

        raise TimeoutError("Image generation timed out")


class ImageDownloader:
    """Handles image downloading and temporary file management."""

    @staticmethod
    def download_image(url):
        response = requests.get(url)
        response.raise_for_status()
        return response.content

    @staticmethod
    def save_temp_image(image_data):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_path = f"temp_flux_{timestamp}.jpg"
        with open(temp_path, "wb") as f:
            f.write(image_data)
        return temp_path

    @staticmethod
    def cleanup_temp_file(path):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


class FluxWorker(QtCore.QObject):
    """Worker thread for handling Flux image generation."""

    finished = QtCore.pyqtSignal(str)  # Emits path to saved image
    error = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int, int)  # current, total

    def __init__(self, prompt, aspect_ratio, quality):
        super().__init__()
        self.prompt = prompt
        self.aspect_ratio = aspect_ratio
        self.quality = quality
        self._cancelled = False
        self.flux_api = FluxAPI()

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            # Step 1: Generate image with Flux
            for attempt in range(1, FluxAPI.MAX_ATTEMPTS + 1):
                if self._cancelled:
                    return

                self.progress.emit(attempt, FluxAPI.MAX_ATTEMPTS)

                try:
                    image_url = self.flux_api.generate_image(
                        self.prompt, self.aspect_ratio, self.quality
                    )
                    break
                except requests.exceptions.RequestException as e:
                    if attempt == FluxAPI.MAX_ATTEMPTS:
                        raise
                    time.sleep(FluxAPI.POLL_INTERVAL)

            # Step 2: Download the image
            image_data = ImageDownloader.download_image(image_url)
            temp_path = ImageDownloader.save_temp_image(image_data)

            self.finished.emit(temp_path)

        except Exception as e:
            self.error.emit(f"Error: {str(e)}")


class ImagePreviewDialog(QtWidgets.QDialog):
    """Dialog for previewing and saving generated images."""

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.setWindowTitle("Generated Image Preview")
        self.resize(600, 600)
        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Image display
        self.image_label = QtWidgets.QLabel()
        pixmap = QtGui.QPixmap(self.image_path)
        if pixmap.isNull():
            raise ValueError("Failed to load image")

        self.image_label.setPixmap(
            pixmap.scaled(550, 550, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        )
        layout.addWidget(self.image_label)

        # Button box
        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Close
        )
        self.button_box.accepted.connect(self.save_image)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def save_image(self):
        options = QtWidgets.QFileDialog.Options()
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Image", "",
            "JPEG Files (*.jpg);;PNG Files (*.png)",
            options=options
        )

        if filename:
            try:
                QtGui.QPixmap(self.image_path).save(filename)
                self.parent().log(f"Image saved as: {filename}")
                self.accept()
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Failed to save image: {str(e)}")


class ImageGeneratorApp(QtWidgets.QWidget):
    """Main application window for Flux image generation."""

    def __init__(self):
        super().__init__()
        self.temp_image_path = None
        self.worker_thread = None
        self.worker = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Flux Pro Image Generator")
        self.resize(800, 600)

        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Prompt input
        self.prompt_input = self._create_prompt_input()
        layout.addWidget(QtWidgets.QLabel("Prompt:"))
        layout.addWidget(self.prompt_input)

        # Parameters
        params_layout = self._create_parameter_controls()
        layout.addLayout(params_layout)

        # Progress bar
        self.progress_bar = self._create_progress_bar()
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QtWidgets.QLabel("Status: Ready")
        layout.addWidget(self.status_label)

        # Control buttons
        button_layout = self._create_control_buttons()
        layout.addLayout(button_layout)

        # Log area
        self.log_text = self._create_log_area()
        layout.addWidget(self.log_text)

    def _create_prompt_input(self):
        input_field = QtWidgets.QTextEdit()
        input_field.setPlaceholderText("Enter image prompt...")
        input_field.setMaximumHeight(100)
        return input_field

    def _create_parameter_controls(self):
        layout = QtWidgets.QHBoxLayout()

        # Aspect ratio
        self.aspect_ratio = QtWidgets.QComboBox()
        self.aspect_ratio.addItems(["1:1", "4:3", "16:9", "9:16"])
        layout.addWidget(QtWidgets.QLabel("Aspect Ratio:"))
        layout.addWidget(self.aspect_ratio)

        # Quality
        self.quality = QtWidgets.QComboBox()
        self.quality.addItems(["standard", "high"])
        layout.addWidget(QtWidgets.QLabel("Quality:"))
        layout.addWidget(self.quality)

        return layout

    def _create_progress_bar(self):
        progress = QtWidgets.QProgressBar()
        progress.hide()
        progress.setRange(0, FluxAPI.MAX_ATTEMPTS)
        return progress

    def _create_control_buttons(self):
        layout = QtWidgets.QHBoxLayout()

        self.generate_btn = QtWidgets.QPushButton("Generate Image")
        self.generate_btn.clicked.connect(self.start_generation)
        layout.addWidget(self.generate_btn)

        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_generation)
        self.cancel_btn.setEnabled(False)
        layout.addWidget(self.cancel_btn)

        return layout

    def _create_log_area(self):
        log = QtWidgets.QTextEdit()
        log.setReadOnly(True)
        return log

    def log(self, message):
        """Add timestamped message to log and status bar."""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        self.status_label.setText(f"Status: {message}")

    def validate_inputs(self):
        """Validate user inputs before processing."""
        prompt = self.prompt_input.toPlainText().strip()
        if not prompt:
            QtWidgets.QMessageBox.warning(self, "Warning", "Prompt cannot be empty!")
            return False
        if len(prompt) > 5000:
            QtWidgets.QMessageBox.warning(
                self, "Warning", "Prompt too long (max 5000 characters)!"
            )
            return False
        return True

    def start_generation(self):
        """Start the image generation process."""
        if not self.validate_inputs():
            return

        prompt = self.prompt_input.toPlainText().strip()

        # Setup worker thread
        self.worker_thread = QtCore.QThread()
        self.worker = FluxWorker(
            prompt,
            self.aspect_ratio.currentText(),
            self.quality.currentText()
        )
        self.worker.moveToThread(self.worker_thread)

        # Connect signals
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.handle_success)
        self.worker.error.connect(self.handle_error)
        self.worker.progress.connect(self.update_progress)

        # Cleanup
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.error.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.cleanup_thread)

        # Update UI
        self.generate_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.show()
        self.log("Starting image generation...")

        self.worker_thread.start()

    def cancel_generation(self):
        """Cancel the current generation process."""
        if self.worker:
            self.worker.cancel()
        self.log("Cancellation requested...")

    def cleanup_thread(self):
        """Clean up worker thread resources."""
        if self.worker_thread:
            self.worker_thread.deleteLater()
            self.worker_thread = None
            self.worker = None

    def update_progress(self, current, total):
        """Update progress bar and log."""
        self.progress_bar.setValue(current)
        self.log(f"Progress: {current}/{total}")

    def handle_success(self, image_path):
        """Handle successful image generation."""
        self.temp_image_path = image_path
        self.log("Image generated successfully, showing preview...")

        try:
            preview = ImagePreviewDialog(image_path, self)
            preview.exec_()
        except Exception as e:
            self.handle_error(f"Failed to show preview: {str(e)}")
        finally:
            self.reset_ui()

    def handle_error(self, message):
        """Handle errors during generation."""
        QtWidgets.QMessageBox.critical(self, "Error", message)
        self.log(f"Error: {message}")
        self.reset_ui()

    def reset_ui(self):
        """Reset UI to initial state."""
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.hide()
        self.status_label.setText("Status: Ready")

        # Cleanup temp file if exists
        if self.temp_image_path:
            ImageDownloader.cleanup_temp_file(self.temp_image_path)
            self.temp_image_path = None

    def closeEvent(self, event):
        """Clean up resources when closing the app."""
        if self.worker_thread and self.worker_thread.isRunning():
            self.cancel_generation()
            self.worker_thread.quit()
            self.worker_thread.wait()

        if self.temp_image_path:
            ImageDownloader.cleanup_temp_file(self.temp_image_path)

        event.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    try:
        window = ImageGeneratorApp()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        QtWidgets.QMessageBox.critical(None, "Fatal Error", f"Application failed to start: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()