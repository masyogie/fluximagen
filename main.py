import sys
import os
import time
import datetime
import requests
import json
import aiohttp
import asyncio
from PyQt5 import QtWidgets, QtCore, QtGui
from pathlib import Path
from cryptography.fernet import Fernet
from functools import lru_cache


class CacheManager:
    """Manages caching of generated images and prompts with encryption."""
    
    def __init__(self):
        self.cache_dir = Path.home() / ".fluximagen" / "cache"
        self.history_file = self.cache_dir / "history.json"
        self.images_dir = self.cache_dir / "images"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize encryption
        self.key_file = self.cache_dir / ".key"
        if not self.key_file.exists():
            self.key = Fernet.generate_key()
            with open(self.key_file, 'wb') as f:
                f.write(self.key)
        else:
            with open(self.key_file, 'rb') as f:
                self.key = f.read()
        self.cipher = Fernet(self.key)
        
        self.history = self._load_history()
    
    def _load_history(self):
        if self.history_file.exists():
            try:
                with open(self.history_file, 'rb') as f:
                    encrypted_data = f.read()
                    decrypted_data = self.cipher.decrypt(encrypted_data)
                    return json.loads(decrypted_data)
            except:
                return {"prompts": [], "favorites": [], "templates": []}
        return {"prompts": [], "favorites": [], "templates": []}
    
    def save_history(self):
        data = json.dumps(self.history).encode()
        encrypted_data = self.cipher.encrypt(data)
        with open(self.history_file, 'wb') as f:
            f.write(encrypted_data)
    
    def add_prompt(self, prompt, params):
        self.history["prompts"].append({
            "prompt": prompt,
            "params": params,
            "timestamp": datetime.datetime.now().isoformat()
        })
        self.save_history()
    
    def add_favorite(self, prompt, params):
        if not any(p["prompt"] == prompt for p in self.history["favorites"]):
            self.history["favorites"].append({
                "prompt": prompt,
                "params": params
            })
            self.save_history()
    
    def add_template(self, name, prompt, params):
        self.history["templates"].append({
            "name": name,
            "prompt": prompt,
            "params": params
        })
        self.save_history()
    
    def get_recent_prompts(self, limit=10):
        return self.history["prompts"][-limit:]
    
    def get_favorites(self):
        return self.history["favorites"]
    
    def get_templates(self):
        return self.history["templates"]
    
    def cache_image(self, image_data, prompt_hash):
        """Cache generated image."""
        image_path = self.images_dir / f"{prompt_hash}.jpg"
        with open(image_path, 'wb') as f:
            f.write(image_data)
        return image_path
    
    @lru_cache(maxsize=100)
    def get_cached_image(self, prompt_hash):
        """Get cached image if exists."""
        image_path = self.images_dir / f"{prompt_hash}.jpg"
        if image_path.exists():
            return image_path
        return None

    def clear_history(self):
        """Clear all history prompts."""
        self.history["prompts"] = []
        self.save_history()
    
    def remove_prompt(self, index):
        """Remove a specific prompt from history."""
        if 0 <= index < len(self.history["prompts"]):
            self.history["prompts"].pop(index)
            self.save_history()


class AsyncFluxAPI:
    """Asynchronous version of Flux API client."""
    
    BASE_URL = "https://api.us1.bfl.ai/v1/flux-pro-1.1-ultra"
    MAX_ATTEMPTS = 10
    POLL_INTERVAL = 5
    
    def __init__(self):
        self.api_key = os.environ.get("FLUX_API_KEY")
        if not self.api_key:
            raise ValueError("FLUX_API_KEY environment variable not set")
        self.session = None
    
    @property
    def headers(self):
        return {
            "X-Key": self.api_key,
            "Content-Type": "application/json"
        }
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def generate_image(self, prompt, aspect_ratio, quality):
        """Generate image with Flux API using async/await."""
        payload = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": "jpeg",
            "quality": quality,
            "safety_tolerance": "6",
            "raw": "true"
        }
        
        async with self.session.post(self.BASE_URL, headers=self.headers, json=payload) as response:
            response.raise_for_status()
            data = await response.json()
            
            polling_url = data.get("polling_url")
            if not polling_url:
                raise ValueError("No polling URL received from API")
            
            for attempt in range(1, self.MAX_ATTEMPTS + 1):
                async with self.session.get(polling_url, headers=self.headers) as poll_response:
                    poll_response.raise_for_status()
                    poll_data = await poll_response.json()
                    
                    status = poll_data.get("status")
                    if status == "Ready":
                        return poll_data.get("result", {}).get("sample")
                    elif status in ["Request Moderated", "Content Moderated"]:
                        raise ValueError("Content moderated as unsafe")
                
                await asyncio.sleep(self.POLL_INTERVAL)
            
            raise TimeoutError("Image generation timed out")


class BatchProcessor:
    """Handles batch processing of multiple images."""
    
    def __init__(self, flux_api, cache_manager):
        self.flux_api = flux_api
        self.cache_manager = cache_manager
    
    async def process_batch(self, prompts, aspect_ratio, quality):
        """Process multiple prompts in parallel."""
        tasks = []
        for prompt in prompts:
            task = asyncio.create_task(
                self.flux_api.generate_image(prompt, aspect_ratio, quality)
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results


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
        self.flux_api = AsyncFluxAPI()
        self.loop = None

    def cancel(self):
        self._cancelled = True

    def run(self):
        """Run the async task in a new event loop."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._run_async())
        except Exception as e:
            self.error.emit(f"Error: {str(e)}")
        finally:
            self.loop.close()

    async def _run_async(self):
        """Async implementation of the worker."""
        try:
            # Step 1: Generate image with Flux
            for attempt in range(1, AsyncFluxAPI.MAX_ATTEMPTS + 1):
                if self._cancelled:
                    return

                self.progress.emit(attempt, AsyncFluxAPI.MAX_ATTEMPTS)

                try:
                    async with self.flux_api as api:
                        image_url = await api.generate_image(
                            self.prompt, self.aspect_ratio, self.quality
                        )
                    break
                except requests.exceptions.RequestException as e:
                    if attempt == AsyncFluxAPI.MAX_ATTEMPTS:
                        raise
                    await asyncio.sleep(AsyncFluxAPI.POLL_INTERVAL)

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
        self.cache_manager = CacheManager()
        self.init_ui()
        self.setup_shortcuts()
        self.load_theme()
        self.setup_batch_processing()

    def setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self, self.start_generation)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Q"), self, self.close)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+D"), self, self.toggle_dark_mode)

    def load_theme(self):
        """Load and apply theme settings."""
        self.is_dark_mode = False
        self.apply_theme()

    def toggle_dark_mode(self):
        """Toggle between light and dark mode."""
        self.is_dark_mode = not self.is_dark_mode
        self.apply_theme()

    def apply_theme(self):
        """Apply current theme to the application."""
        if self.is_dark_mode:
            self.setStyleSheet("""
                QWidget {
                    background-color: #2b2b2b;
                    color: #ffffff;
                }
                QTextEdit, QComboBox {
                    background-color: #3b3b3b;
                    color: #ffffff;
                    border: 1px solid #555555;
                }
                QPushButton {
                    background-color: #0d47a1;
                    color: white;
                    border: none;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #1565c0;
                }
                QPushButton:disabled {
                    background-color: #666666;
                }
            """)
        else:
            self.setStyleSheet("")

    def init_ui(self):
        """Initialize the user interface."""
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

        # Add history management
        history_layout = QtWidgets.QHBoxLayout()
        
        self.history_combo = QtWidgets.QComboBox()
        self.history_combo.setPlaceholderText("Recent prompts")
        self.history_combo.currentIndexChanged.connect(self.load_history_prompt)
        history_layout.addWidget(self.history_combo)
        
        self.favorite_btn = QtWidgets.QPushButton("★")
        self.favorite_btn.setToolTip("Add to favorites")
        self.favorite_btn.clicked.connect(self.add_to_favorites)
        history_layout.addWidget(self.favorite_btn)

        # Add clear and remove buttons
        self.clear_history_btn = QtWidgets.QPushButton("🗑")
        self.clear_history_btn.setToolTip("Clear all history")
        self.clear_history_btn.clicked.connect(self.clear_history)
        history_layout.addWidget(self.clear_history_btn)

        self.remove_prompt_btn = QtWidgets.QPushButton("✕")
        self.remove_prompt_btn.setToolTip("Remove selected prompt")
        self.remove_prompt_btn.clicked.connect(self.remove_selected_prompt)
        history_layout.addWidget(self.remove_prompt_btn)
        
        layout.addLayout(history_layout)

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
        progress.setRange(0, AsyncFluxAPI.MAX_ATTEMPTS)
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
        params = {
            "aspect_ratio": self.aspect_ratio.currentText(),
            "quality": self.quality.currentText()
        }
        
        # Save to history
        self.cache_manager.add_prompt(prompt, params)
        self.update_history_combo()

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

    def load_history_prompt(self, index):
        """Load a prompt from history."""
        if index >= 0:
            prompt_data = self.cache_manager.get_recent_prompts()[index]
            self.prompt_input.setPlainText(prompt_data["prompt"])
            self.aspect_ratio.setCurrentText(prompt_data["params"]["aspect_ratio"])
            self.quality.setCurrentText(prompt_data["params"]["quality"])

    def add_to_favorites(self):
        """Add current prompt to favorites."""
        prompt = self.prompt_input.toPlainText().strip()
        if prompt:
            params = {
                "aspect_ratio": self.aspect_ratio.currentText(),
                "quality": self.quality.currentText()
            }
            self.cache_manager.add_favorite(prompt, params)
            QtWidgets.QMessageBox.information(self, "Success", "Added to favorites!")

    def update_history_combo(self):
        """Update history combo box with recent prompts."""
        self.history_combo.clear()
        for prompt_data in self.cache_manager.get_recent_prompts():
            self.history_combo.addItem(prompt_data["prompt"])

    def setup_batch_processing(self):
        """Setup batch processing UI elements."""
        self.batch_input = QtWidgets.QTextEdit()
        self.batch_input.setPlaceholderText("Enter multiple prompts (one per line)")
        self.batch_input.setMaximumHeight(100)
        
        self.batch_btn = QtWidgets.QPushButton("Process Batch")
        self.batch_btn.clicked.connect(self.start_batch_processing)
        
        # Add to layout
        layout = self.layout()
        layout.insertWidget(2, QtWidgets.QLabel("Batch Processing:"))
        layout.insertWidget(3, self.batch_input)
        layout.insertWidget(4, self.batch_btn)

    def clear_history(self):
        """Clear all history prompts."""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Clear History",
            "Are you sure you want to clear all recent prompts?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self.cache_manager.clear_history()
            self.update_history_combo()
            self.log("History cleared")

    def remove_selected_prompt(self):
        """Remove the currently selected prompt from history."""
        current_index = self.history_combo.currentIndex()
        if current_index >= 0:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Remove Prompt",
                "Are you sure you want to remove this prompt from history?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            
            if reply == QtWidgets.QMessageBox.Yes:
                self.cache_manager.remove_prompt(current_index)
                self.update_history_combo()
                self.log("Prompt removed from history")

    async def process_batch_async(self, prompts):
        """Process batch of prompts asynchronously."""
        async with AsyncFluxAPI() as flux_api:
            processor = BatchProcessor(flux_api, self.cache_manager)
            results = await processor.process_batch(
                prompts,
                self.aspect_ratio.currentText(),
                self.quality.currentText()
            )
            return results

    def start_batch_processing(self):
        """Start batch processing of multiple prompts."""
        prompts = self.batch_input.toPlainText().strip().split('\n')
        prompts = [p.strip() for p in prompts if p.strip()]
        
        if not prompts:
            QtWidgets.QMessageBox.warning(self, "Warning", "No prompts provided!")
            return
        
        self.batch_btn.setEnabled(False)
        self.log(f"Starting batch processing of {len(prompts)} prompts...")
        
        # Run async processing in event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(self.process_batch_async(prompts))
            self.handle_batch_results(results)
        except Exception as e:
            self.handle_error(f"Batch processing failed: {str(e)}")
        finally:
            loop.close()
            self.batch_btn.setEnabled(True)

    def handle_batch_results(self, results):
        """Handle results from batch processing."""
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        error_count = len(results) - success_count
        
        self.log(f"Batch processing completed: {success_count} successful, {error_count} failed")
        
        if success_count > 0:
            QtWidgets.QMessageBox.information(
                self,
                "Batch Processing Complete",
                f"Successfully processed {success_count} images.\n"
                f"Failed to process {error_count} images."
            )


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