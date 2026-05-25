import re

def clean_text(text: str) -> str:
    text = str(text).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\s\.,;:!?，。；：？！]","",text)
    text = text.replace("\n", " ").replace("\r", "")
    return text

def clean_filename(name: str) -> str:
    return re.sub(r"[\/\\:*?<>|]", "_", name)