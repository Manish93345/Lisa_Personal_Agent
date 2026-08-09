import os
# 🚨 PROTOBUF BYPASS: Gemini aur PaddleOCR ko ek sath chalane ke liye
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

import io
import fitz  # PyMuPDF
from PIL import Image
from paddleocr import PaddleOCR

# ── 🚨 ROBUST INITIALIZATION (GPU with CPU Fallback) ──
def initialize_ocr():
    try:
        print("  [PDF Processor] Attempting to initialize OCR Engine on GPU...")
        # Pehle GPU par try karega
        engine = PaddleOCR(use_angle_cls=True, lang='en', use_gpu=True, show_log=False)
        print("  [PDF Processor] ✅ SUCCESS: OCR is running on blazing-fast GPU!")
        return engine, "GPU"
    except Exception as e:
        print(f"  [PDF Processor] ⚠️ GPU initialization failed: {e}")
        print("  [PDF Processor] 🔄 Falling back to CPU Mode...")
        # Agar error aayi (doosre PC par), toh CPU par fallback karega
        engine = PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False, show_log=False)
        print("  [PDF Processor] ✅ SUCCESS: OCR is running on CPU.")
        return engine, "CPU"

# Initialize global OCR engine
ocr, execution_mode = initialize_ocr()

def extract_pdf_to_markdown(pdf_path: str) -> str:
    """PDF file path leta hai aur poora content Markdown string mein return karta hai."""
    
    if not os.path.exists(pdf_path):
        return f"Error: File not found at {pdf_path}"

    print(f"  [PDF Processor] Reading Document: {os.path.basename(pdf_path)}")
    doc = fitz.open(pdf_path)
    
    markdown_content = f"# Document: {os.path.basename(pdf_path)}\n\n"

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        markdown_content += f"## Page {page_num + 1}\n\n"

        # ── 1. Smart Text Extraction (Headings Fixed for High Accuracy) ──
        blocks = page.get_text("blocks")
        for b in blocks:
            text = b[4].strip()
            if not text: continue
            
            # Smart logic: Short single lines are treated as Headings
            if len(text.split('\n')) == 1 and len(text) < 70:
                 markdown_content += f"### {text}\n\n"
            else:
                 markdown_content += f"{text}\n\n"

        # ── 2. Images & Diagrams (GPU OCR) ──
        image_list = page.get_images(full=True)
        if image_list:
            print(f"  [PDF Processor] Page {page_num + 1}: Found {len(image_list)} images. Blasting through GPU...")
            for img_index, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]

                temp_img_path = f"temp_ocr_img_{page_num}_{img_index}.png"
                try:
                    image = Image.open(io.BytesIO(image_bytes))
                    image.save(temp_img_path)

                    # 🚨 GPU Execution
                    result = ocr.ocr(temp_img_path, cls=True)
                    ocr_text = ""
                    
                    if result and result[0]:
                        for line in result[0]:
                            ocr_text += line[1][0] + " "

                    if ocr_text.strip():
                        markdown_content += f"> **[Diagram/Image OCR]**: {ocr_text.strip()}\n\n"
                        
                except Exception as e:
                    print(f"  [PDF Processor] OCR Error on page {page_num + 1}: {e}")
                finally:
                    if os.path.exists(temp_img_path):
                        os.remove(temp_img_path)

    doc.close()
    print("  [PDF Processor] Extraction Complete! ✅")
    return markdown_content

# ── Standalone Testing (File Saving Logic) ──
if __name__ == "__main__":
    test_pdf = input("PDF ka path daalo test karne ke liye: ").strip()
    test_pdf = test_pdf.strip('"').strip("'").strip('\u202a')
    
    if test_pdf and os.path.exists(test_pdf):
        md_result = extract_pdf_to_markdown(test_pdf)
        
        base_name = os.path.basename(test_pdf).replace('.pdf', '')
        output_file = f"{base_name}_extracted.md"
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(md_result)
            
        print(f"\n🎉 SUCCESS: Data extract ho gaya!")
        print(f"📄 Saved to File: {output_file}")
    else:
        print("❌ Error: Ye path exist nahi karta.")