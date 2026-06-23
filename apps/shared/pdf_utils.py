# file path: apps/shared/pdf_utils.py
def extract_pdf_text(path_or_file) -> str:
    """Extract text from a resume PDF with PyMuPDF."""
    import fitz

    if hasattr(path_or_file, "read"):
        data = path_or_file.read()
        with fitz.open(stream=data, filetype="pdf") as document:
            return "\n".join(page.get_text("text") for page in document).strip()

    with fitz.open(path_or_file) as document:
        return "\n".join(page.get_text("text") for page in document).strip()
