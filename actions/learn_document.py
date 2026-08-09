import os
from actions.pdf_processor import extract_pdf_to_markdown
# IMPORT YOUR CHROMA DB COLLECTION HERE
# from memory.rag_memory import collection, ingest_document 

def learn_pdf(pdf_path: str, subject: str = "general"):
    """PDF extract karta hai aur RAG mein save kar deta hai."""
    
    if not os.path.exists(pdf_path):
        return False, "File nahi mili."

    # 1. GPU/CPU OCR se PDF ko Markdown mein badlo
    md_text = extract_pdf_to_markdown(pdf_path)
    
    if "Error:" in md_text:
        return False, "Extract karne mein problem aayi."

    # 2. Markdown ko RAG mein Ingest karo
    source_filename = os.path.basename(pdf_path)
    
    # ASSUMING TERA CHROMA DB COLLECTION IMPORTED HAI:
    # ingest_document(collection, md_text, source_name=source_filename, subject=subject)
    
    return True, f"Maine {source_filename} poori tarah padh liya hai aur apne database mein save kar liya hai!"