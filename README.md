# PDF Compressor

A simple CLI tool to batch‐compress PDF files using Ghostscript (and optionally pikepdf).

## Requirements

- Python 3.6+
- Ghostscript installed and on your PATH (`gswin64c` or `gswin32c`)
- (Optional) pikepdf for advanced PDF optimizations (`pip install pikepdf`)

## Installation


1. Install Python dependencies (if you plan to use pikepdf)  
    ```powershell
    pip install -r requirements.txt
    ```

2. Install Ghostscript (any of the following):

   • MSI installer (recommended)  
     – Download from https://www.ghostscript.com/download/gsdnld.html  
     – Run the MSI and check **Add to PATH**

   • Chocolatey (Admin PowerShell)  
     ```powershell
     choco install ghostscript -y
     ```

   • winget  
     ```powershell
     winget install --id Ghostscript.GPL -e
     ```

5. Verify Ghostscript is on your PATH  
    ```powershell
    gswin64c --version
    ```

## Usage

```powershell
python pdf_compressor.py -i <input_dir> [-q <quality>] [-g <preset>] [--dpi <dpi>]

Arguments
-i, --input-dir (required)
Directory containing the PDF files you want to compress.

-q, --quality (default: 60)
JPEG image quality (0–100). Internally mapped to Ghostscript PDFSETTINGS:

60 → /screen
75 → /ebook
90 → /printer
95 → /prepress
-g, --preset (choices: screen, ebook, printer, prepress)
Direct Ghostscript preset. Overrides the -q mapping.

--dpi (default: 150)
Image downsample resolution in DPI.

