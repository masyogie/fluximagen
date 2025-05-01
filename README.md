# Flux Image Generator

A desktop application for generating images using Flux AI API with advanced features and optimizations.

## Features

### Core Features
- Image generation using Flux AI API
- Multiple aspect ratio support (1:1, 4:3, 16:9, 9:16)
- Quality selection (standard/high)
- Real-time progress tracking
- Preview and save generated images

### Advanced Features
- **Batch Processing**: Generate multiple images simultaneously
- **Async Processing**: Efficient image generation with async/await
- **History Management**:
  - Recent prompts tracking
  - Favorite prompts
  - Clear history or remove individual prompts
  - Encrypted storage for security

### User Experience
- **Dark Mode**: Toggle with Ctrl+D
- **Keyboard Shortcuts**:
  - Ctrl+Return: Generate image
  - Ctrl+Q: Close application
  - Ctrl+D: Toggle dark mode
- **Modern UI** with progress tracking and status updates

## Installation

1. Clone the repository:
```bash
git clone https://github.com/masyogie/fluximagen.git
cd fluximagen
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up your Flux API key:
```bash
export FLUX_API_KEY="your_api_key_here"
```

## Usage

Run the application:
```bash
python main.py
```

### Basic Usage
1. Enter your prompt in the text field
2. Select desired aspect ratio and quality
3. Click "Generate Image" or press Ctrl+Return
4. Preview and save the generated image

### Batch Processing
1. Enter multiple prompts (one per line) in the batch processing area
2. Click "Process Batch"
3. Monitor progress in the log area

### History Management
- Use the dropdown to access recent prompts
- Click ★ to add prompts to favorites
- Use 🗑 to clear all history
- Use ✕ to remove individual prompts

## Requirements
- Python 3.7+
- PyQt5 >= 5.15.0
- requests >= 2.25.0
- aiohttp >= 3.8.0
- cryptography >= 3.4.0

## Security
- History and cache data are encrypted
- API keys are securely handled via environment variables
- Safe error handling and input validation

## Contributing
Feel free to submit issues and enhancement requests!