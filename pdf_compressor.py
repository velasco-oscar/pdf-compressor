import os
import json
import logging
from pathlib import Path
import argparse
from datetime import datetime
import pikepdf
from pikepdf import Pdf, PdfImage
from PIL import Image
import io
import sys
import shutil
import tempfile
import subprocess

def setup_logging(verbose=False):
    """Set up logging configuration"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger('pdf_compressor')

def compress_image(image, max_size=1024, quality=85):
    """Compress an image within a PDF"""
    img = Image.open(io.BytesIO(image))
    
    # Resize if larger than max_size while preserving aspect ratio
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        new_size = tuple(int(s * ratio) for s in img.size)
        img = img.resize(new_size, Image.LANCZOS)
    
    output = io.BytesIO()
    
    # Convert RGBA to RGB if needed
    if img.mode == 'RGBA':
        img = img.convert('RGB')
    
    img.save(output, format='JPEG', optimize=True, quality=quality)
    output.seek(0)
    return output.getvalue()

def try_ghostscript_compression(input_path, output_path, compression_level="ebook"):
    """Try to compress PDF using Ghostscript if available"""
    gs_command = 'gswin64c' if os.name == 'nt' else 'gs'
    
    # Different compression levels:
    # /screen - lowest quality (72 dpi)
    # /ebook - medium quality (150 dpi)
    # /printer - good quality (300 dpi)
    # /prepress - high quality (300 dpi) preserving colors
    
    command = [
        gs_command,
        '-sDEVICE=pdfwrite',
        '-dCompatibilityLevel=1.4',
        f'-dPDFSETTINGS=/{compression_level}',
        '-dNOPAUSE',
        '-dQUIET',
        '-dBATCH',
        f'-sOutputFile={output_path}',
        input_path
    ]
    
    try:
        subprocess.run(command, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def compress_pdf_with_pikepdf(input_path, output_path, logger, image_quality=85, image_max_size=1024):
    """Compress a PDF file with pikepdf, focusing on image optimization"""
    try:
        with pikepdf.open(input_path) as pdf:
            # Track if we made any modifications
            modifications_made = False
            
            # Process each page
            for page_num, page in enumerate(pdf.pages):
                # Look for images on the page
                for name, raw_image in list(page.images.items()):
                    # Get the image
                    try:
                        pdfimage = PdfImage(raw_image)
                        
                        # Extract image
                        try:
                            img_bytes = pdfimage.read_bytes()
                            
                            # Compress the image
                            compressed_img_bytes = compress_image(
                                img_bytes, 
                                max_size=image_max_size, 
                                quality=image_quality
                            )
                            
                            # Only replace if we achieved compression
                            if len(compressed_img_bytes) < len(img_bytes):
                                # Replace the image in the PDF
                                img_object = pdf.make_stream(compressed_img_bytes)
                                raw_image.write(img_object, filter=pikepdf.Name.DCTDecode)
                                modifications_made = True
                                logger.debug(f"Compressed image on page {page_num+1}: {len(img_bytes)/1024:.2f}KB -> {len(compressed_img_bytes)/1024:.2f}KB")
                        except pikepdf.PdfError as e:
                            if "unfilterable stream" in str(e):
                                # Try alternate method for unfilterable streams
                                try:
                                    # Special handling for unfilterable images
                                    if hasattr(raw_image, "ColorSpace") and pikepdf.Name.DCTDecode in raw_image.get("/Filter", []):
                                        # Try direct stream compression without full extraction
                                        if raw_image.get("/DecodeParms") is None:
                                            # Attempt to optimize the JPEG quality directly
                                            raw_image.DecodeParms = pikepdf.Dictionary({"Quality": image_quality})
                                            modifications_made = True
                                            logger.debug(f"Applied direct quality setting to image on page {page_num+1}")
                                except Exception as inner_e:
                                    logger.debug(f"Alternative handling failed for image on page {page_num+1}: {str(inner_e)}")
                            else:
                                logger.warning(f"Failed to compress image on page {page_num+1}: {str(e)}")
                    except Exception as e:
                        logger.debug(f"Skipping image on page {page_num+1}: {str(e)}")
                        continue
            
            # Save the PDF with general optimization even if no images were modified
            pdf.save(output_path, 
                     compress_streams=True,
                     preserve_pdfa=False,
                     object_stream_mode=pikepdf.ObjectStreamMode.generate,
                     linearize=True)  # Add linearization (web optimization)
            return True
    except Exception as e:
        logger.error(f"Error compressing {input_path} with pikepdf: {str(e)}")
        return False

def compress_pdf(input_path, output_path, logger, options):
    """Compress a PDF file using multiple methods as needed"""
    
    original_size = os.path.getsize(input_path)
    best_size = original_size
    best_file = None
    
    # Create a temp directory for intermediate files
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_output = os.path.join(temp_dir, "compressed_gs.pdf")
        
        # Try Ghostscript compression first (usually the best)
        if options.get('try_ghostscript', True):
            gs_success = try_ghostscript_compression(
                input_path, 
                temp_output,
                options.get('gs_compression_level', 'ebook')
            )
            
            if gs_success and os.path.exists(temp_output):
                gs_size = os.path.getsize(temp_output)
                if gs_size < best_size:
                    best_size = gs_size
                    best_file = temp_output
                    logger.debug(f"Ghostscript compression successful: {original_size/1024:.2f}KB -> {gs_size/1024:.2f}KB")
        
        # Try pikepdf image optimization
        temp_pikepdf = os.path.join(temp_dir, "compressed_pikepdf.pdf")
        pikepdf_success = compress_pdf_with_pikepdf(
            input_path,
            temp_pikepdf,
            logger, 
            options.get('image_quality', 85),
            options.get('image_max_size', 1024)
        )
        
        if pikepdf_success and os.path.exists(temp_pikepdf):
            pikepdf_size = os.path.getsize(temp_pikepdf)
            if pikepdf_size < best_size:
                best_size = pikepdf_size
                best_file = temp_pikepdf
                logger.debug(f"Pikepdf compression successful: {original_size/1024:.2f}KB -> {pikepdf_size/1024:.2f}KB")
        
        # If we found a better version, use it
        if best_file:
            shutil.copy2(best_file, output_path)
            return True, original_size, best_size
        else:
            # If no compression method worked, just copy the original
            shutil.copy2(input_path, output_path)
            return False, original_size, original_size

def create_error_log(error_files, log_path):
    """Create JSON error log"""
    log_data = {
        "timestamp": datetime.now().isoformat(),
        "error_files": error_files
    }
    
    with open(log_path, 'w') as f:
        json.dump(log_data, f, indent=4)

def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description='Compress PDF files in a directory')
    parser.add_argument('-i', '--input', required=True, help='Input directory containing PDF files')
    parser.add_argument('-o', '--output', help='Output directory for compressed files')
    parser.add_argument('-q', '--quality', type=int, default=85, help='JPEG quality for image compression (1-100)')
    parser.add_argument('-s', '--size', type=int, default=1024, help='Maximum dimension size for images in pixels')
    parser.add_argument('-g', '--ghostscript', choices=['screen', 'ebook', 'printer', 'prepress'], default='ebook',
                      help='Ghostscript compression level (if available)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    args = parser.parse_args()
    
    # Setup logger
    logger = setup_logging(args.verbose)
    
    # Input directory validation
    input_dir = Path(args.input)
    if not input_dir.exists() or not input_dir.is_dir():
        logger.error(f"Input directory does not exist: {input_dir}")
        return 1
    
    # Output directory setup
    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = input_dir / "compressed_pdfs"
    
    output_dir.mkdir(exist_ok=True, parents=True)
    logger.info(f"Compressed PDFs will be saved to: {output_dir}")
    
    # Compression options
    compression_options = {
        'image_quality': args.quality,
        'image_max_size': args.size,
        'try_ghostscript': True,
        'gs_compression_level': args.ghostscript
    }
    
    # Error tracking
    error_files = []
    
    # Process PDF files
    pdf_files = list(input_dir.glob('*.pdf'))
    total_files = len(pdf_files)
    logger.info(f"Found {total_files} PDF files to process")
    
    for i, pdf_file in enumerate(pdf_files, 1):
        logger.info(f"Processing ({i}/{total_files}): {pdf_file.name}")
        
        # Create output path
        output_path = output_dir / f"{pdf_file.stem}_compressed.pdf"
        
        # Compress PDF
        try:
            success, original_size, compressed_size = compress_pdf(
                str(pdf_file), 
                str(output_path), 
                logger,
                compression_options
            )
            
            # Calculate compression statistics
            if success and compressed_size < original_size:
                reduction = (1 - compressed_size / original_size) * 100
                logger.info(f"Compressed {pdf_file.name}: {original_size/1024:.2f} KB → {compressed_size/1024:.2f} KB ({reduction:.2f}% reduction)")
            else:
                logger.info(f"No significant compression achieved for {pdf_file.name}")
        except Exception as e:
            error_files.append(pdf_file.name)
            logger.error(f"Failed to process {pdf_file.name}: {str(e)}")
    
    # Create error log if needed
    if error_files:
        error_log_path = output_dir / "compression_errors.json"
        create_error_log(error_files, error_log_path)
        logger.warning(f"{len(error_files)} files could not be compressed. See {error_log_path} for details.")
    
    logger.info("PDF compression completed")
    return 0

if __name__ == "__main__":
    sys.exit(main())