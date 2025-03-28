import sys
import requests
import time
import datetime
import os
from PyQt5 import QtWidgets, QtCore, QtGui


class FluxWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(str)  # Mengembalikan image URL
    error = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int, int)

    def __init__(self, prompt, aspect_ratio, quality):
        super().__init__()
        self.prompt = prompt
        self.aspect_ratio = aspect_ratio
        self.quality = quality
        self.cancelled = False

    def run(self):
        try:
            # Langkah 1: Generate gambar dengan Flux Pro Ultra
            url = "https://api.us1.bfl.ai/v1/flux-pro-1.1-ultra"
            flux_api_key = os.environ.get("FLUX_API_KEY")
            if not flux_api_key:
                self.error.emit("Flux API key not set in environment")
                return
            headers = {
                "X-Key": flux_api_key,
                "Content-Type": "application/json"
            }

            data = {
                "prompt": self.prompt,
                "aspect_ratio": self.aspect_ratio,
                "output_format": "jpeg",
                "quality": self.quality,
                "safety_tolerance": "6",
                "raw": "true"
            }

            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()

            initial_data = response.json()
            polling_url = initial_data.get("polling_url")
            if not polling_url:
                self.error.emit("Polling URL tidak ditemukan.")
                return

            max_attempts = 10
            for attempt in range(max_attempts):
                if self.cancelled:
                    return

                self.progress.emit(attempt + 1, max_attempts)
                poll_response = requests.get(polling_url, headers=headers)
                poll_response.raise_for_status()
                poll_data = poll_response.json()

                status = poll_data.get("status")
                if status == "Ready":
                    image_url = poll_data.get("result", {}).get("sample")
                    self.finished.emit(image_url)
                    return
                elif status in ["Request Moderated", "Content Moderated"]:
                    self.error.emit("Permintaan dimoderasi karena konten tidak aman.")
                    return

                time.sleep(5)

            self.error.emit("Timeout: Gambar tidak dihasilkan dalam waktu yang ditentukan.")

        except Exception as e:
            self.error.emit(f"Error Flux API: {str(e)}")


class SDXLWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(str)

    def __init__(self, image_path, prompt, strength=0.5):
        super().__init__()
        self.image_path = image_path
        self.prompt = prompt
        self.strength = strength
        self.huggingface_api_key = os.environ.get("HUGGINGFACE_API_KEY")
        if not self.huggingface_api_key:
            raise Exception("HuggingFace API key not set in environment")
        self.timeout = 120  # Timeout dalam detik
        self.api_url = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-refiner-1.0"

    def run(self):
        try:
            self.progress.emit("Preparing image for SDXL processing...")

            # Baca gambar sebagai binary
            with open(self.image_path, "rb") as img_file:
                image_bytes = img_file.read()

            # Siapkan payload untuk Hugging Face API
            files = {
                "image": ("input.jpg", image_bytes, "image/jpeg"),
            }
            data = {
                "prompt": self.prompt,
                "negative_prompt": "blurry, low quality, distorted",
                "strength": self.strength,
                "num_inference_steps": 30,
                "guidance_scale": 7.5
            }

            headers = {
                "Authorization": f"Bearer {self.huggingface_api_key}"
            }

            self.progress.emit("Sending request to Hugging Face...")
            response = requests.post(
                self.api_url,
                headers=headers,
                files=files,
                data=data,
                timeout=self.timeout
            )

            # Handle response
            if response.status_code == 200:
                self.progress.emit("Processing successful, saving result...")

                # Generate output filename
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = f"sdxl_result_{timestamp}.png"

                # Save the image
                with open(output_path, "wb") as f:
                    f.write(response.content)

                self.finished.emit(output_path)
            else:
                error_msg = f"HTTP Error {response.status_code}"
                try:
                    error_details = response.json()
                    if "error" in error_details:
                        error_msg += f": {error_details['error']}"
                    elif "message" in error_details:
                        error_msg += f": {error_details['message']}"
                except:
                    pass
                raise Exception(error_msg)

        except Exception as e:
            self.error.emit(f"SDXL Error: {str(e)}")


class ImageGeneratorApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.last_prompt = ""
        self.temp_image_path = None
        self.initUI()

    def initUI(self):
        self.setWindowTitle("Flux Pro + SDXL Image Generator")
        self.resize(800, 600)
        layout = QtWidgets.QVBoxLayout(self)

        # Input Prompt
        self.prompt_input = QtWidgets.QTextEdit(self)
        self.prompt_input.setPlaceholderText("Masukkan prompt untuk gambar...")
        self.prompt_input.setMaximumHeight(100)
        layout.addWidget(QtWidgets.QLabel("Prompt:"))
        layout.addWidget(self.prompt_input)

        # Parameter kontrol
        params_layout = QtWidgets.QHBoxLayout()

        self.aspect_ratio = QtWidgets.QComboBox()
        self.aspect_ratio.addItems(["1:1", "4:3", "16:9", "9:16"])
        params_layout.addWidget(QtWidgets.QLabel("Aspect Ratio:"))
        params_layout.addWidget(self.aspect_ratio)

        self.quality = QtWidgets.QComboBox()
        self.quality.addItems(["standard", "high"])
        params_layout.addWidget(QtWidgets.QLabel("Quality:"))
        params_layout.addWidget(self.quality)

        # SDXL Strength
        self.sdxl_strength = QtWidgets.QDoubleSpinBox()
        self.sdxl_strength.setRange(0.1, 0.9)
        self.sdxl_strength.setValue(0.5)
        self.sdxl_strength.setSingleStep(0.1)
        params_layout.addWidget(QtWidgets.QLabel("SDXL Strength:"))
        params_layout.addWidget(self.sdxl_strength)

        layout.addLayout(params_layout)

        # Checkbox untuk SDXL
        self.enable_sdxl = QtWidgets.QCheckBox("Aktifkan SDXL Refinement")
        self.enable_sdxl.setChecked(True)
        layout.addWidget(self.enable_sdxl)

        # Progress bar
        self.progress = QtWidgets.QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)

        # Status label
        self.status_label = QtWidgets.QLabel("Status: Siap")
        layout.addWidget(self.status_label)

        # Tombol kontrol
        button_layout = QtWidgets.QHBoxLayout()
        self.generate_button = QtWidgets.QPushButton("Generate Image", self)
        self.generate_button.clicked.connect(self.on_generate)
        self.cancel_button = QtWidgets.QPushButton("Cancel", self)
        self.cancel_button.clicked.connect(self.cancel_process)
        self.cancel_button.setEnabled(False)
        button_layout.addWidget(self.generate_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        # Log area
        self.log_text = QtWidgets.QTextEdit(self)
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        self.show()

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        self.status_label.setText(f"Status: {message}")
        print(message)

    def validate_inputs(self):
        prompt = self.prompt_input.toPlainText().strip()
        if not prompt:
            QtWidgets.QMessageBox.warning(self, "Warning", "Prompt tidak boleh kosong!")
            return False
        if len(prompt) > 5000:
            QtWidgets.QMessageBox.warning(self, "Warning", "Prompt terlalu panjang (max 5000 karakter)!")
            return False
        return True

    def cancel_process(self):
        if hasattr(self, 'flux_worker'):
            self.flux_worker.cancelled = True
        self.log("Proses pembatalan diminta...")

    def on_generate(self):
        if not self.validate_inputs():
            return

        prompt = self.prompt_input.toPlainText().strip()
        self.last_prompt = prompt

        # Setup worker thread untuk Flux
        self.flux_thread = QtCore.QThread()
        self.flux_worker = FluxWorker(
            prompt,
            self.aspect_ratio.currentText(),
            self.quality.currentText()
        )
        self.flux_worker.moveToThread(self.flux_thread)

        # Connect signals
        self.flux_thread.started.connect(self.flux_worker.run)
        self.flux_worker.finished.connect(self.handle_flux_success)
        self.flux_worker.error.connect(self.handle_error)
        self.flux_worker.progress.connect(self.update_progress)

        # Cleanup thread
        self.flux_worker.finished.connect(self.flux_thread.quit)
        self.flux_worker.error.connect(self.flux_thread.quit)
        self.flux_thread.finished.connect(self.flux_thread.deleteLater)

        # UI state
        self.generate_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.show()
        self.progress.setRange(0, 10)  # Untuk Flux

        self.flux_thread.start()

    def update_progress(self, current, total):
        self.progress.setMaximum(total)
        self.progress.setValue(current)
        self.log(f"Progress: {current}/{total}")

    def handle_flux_success(self, image_url):
        self.log("Berhasil mendapatkan gambar dari Flux, mendownload...")
        try:
            img_response = requests.get(image_url)
            img_response.raise_for_status()

            # Simpan gambar sementara
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.temp_image_path = f"temp_flux_{timestamp}.jpg"
            with open(self.temp_image_path, "wb") as f:
                f.write(img_response.content)

            if self.enable_sdxl.isChecked():
                self.process_with_sdxl(self.temp_image_path)
            else:
                self.show_final_result(self.temp_image_path)

        except Exception as e:
            self.handle_error(f"Gagal mendownload gambar: {str(e)}")

    def process_with_sdxl(self, image_path):
        self.log("Memulai proses SDXL refinement...")

        # Setup worker thread untuk SDXL
        self.sdxl_thread = QtCore.QThread()
        self.sdxl_worker = SDXLWorker(
            image_path,
            self.last_prompt,
            self.sdxl_strength.value()
        )
        self.sdxl_worker.moveToThread(self.sdxl_thread)

        # Connect signals
        self.sdxl_thread.started.connect(self.sdxl_worker.run)
        self.sdxl_worker.finished.connect(self.handle_sdxl_success)
        self.sdxl_worker.error.connect(self.handle_error)
        self.sdxl_worker.progress.connect(self.log)

        # Cleanup thread
        self.sdxl_worker.finished.connect(self.sdxl_thread.quit)
        self.sdxl_worker.error.connect(self.sdxl_thread.quit)
        self.sdxl_thread.finished.connect(self.sdxl_thread.deleteLater)

        # Update progress untuk SDXL
        self.progress.setRange(0, 20)  # Untuk SDXL

        self.sdxl_thread.start()

    def handle_sdxl_success(self, image_path):
        self.log("Proses SDXL selesai!")
        self.show_final_result(image_path)
        # Hapus file temporary jika ada
        if self.temp_image_path and os.path.exists(self.temp_image_path):
            try:
                os.remove(self.temp_image_path)
            except:
                pass

    def show_final_result(self, image_path):
        try:
            pixmap = QtGui.QPixmap(image_path)
            if pixmap.isNull():
                raise Exception("Gagal memuat gambar")

            preview_dialog = QtWidgets.QDialog(self)
            preview_dialog.setWindowTitle("Hasil Akhir")
            preview_dialog.resize(600, 600)

            label = QtWidgets.QLabel(preview_dialog)
            label.setPixmap(pixmap.scaled(550, 550, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

            button_box = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Close,
                parent=preview_dialog
            )
            button_box.accepted.connect(lambda: self.save_image(image_path, preview_dialog))
            button_box.rejected.connect(preview_dialog.reject)

            layout = QtWidgets.QVBoxLayout()
            layout.addWidget(label)
            layout.addWidget(button_box)
            preview_dialog.setLayout(layout)

            preview_dialog.exec_()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Gagal menampilkan hasil: {str(e)}")

        self.reset_ui_state()

    def save_image(self, image_path, dialog):
        options = QtWidgets.QFileDialog.Options()
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Simpan Gambar", "", "JPEG Files (*.jpg);;PNG Files (*.png)", options=options)

        if filename:
            try:
                pixmap = QtGui.QPixmap(image_path)
                pixmap.save(filename)
                self.log(f"Gambar disimpan sebagai: {filename}")
                dialog.accept()
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Gagal menyimpan gambar: {str(e)}")

    def handle_error(self, message):
        QtWidgets.QMessageBox.critical(self, "Error", message)
        self.reset_ui_state()

    def reset_ui_state(self):
        self.generate_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.hide()
        self.status_label.setText("Status: Siap")


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = ImageGeneratorApp()
    sys.exit(app.exec_())