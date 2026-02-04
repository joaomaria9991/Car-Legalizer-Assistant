import asyncio
from pathlib import Path
import fitz  # PyMuPDF
from PIL import Image
import io
from app.storage.blob_client import BlobClient
from app.models.state import ProcessState

async def create_process_with_split_docs(process_id: str, docs_dir: str = "app/mercedes-data"):
    """PDF→todas_páginas_JPG + PNG/JPG→Blob."""
    
    blob_client = BlobClient()
    process_path = f"processes/{process_id}"
    docs_path = f"{process_path}/docs"
    
    print(f"🚀 Criando processo: {process_id}")
    
    # STATE INICIAL
    initial_state = ProcessState(process_id=process_id, fase_atual="INTAKE_DOCS", docs={}, historico=[], flags={})
    await blob_client.save_state(process_id, initial_state.model_dump())
    print(f"✅ state.json criado")
    
    docs_folder = Path(docs_dir)
    if not docs_folder.exists():
        print(f"❌ Pasta {docs_dir} não existe!")
        return
    
    # 1. IMAGENS DIRETAS (PNG/JPG)
    for img_path in docs_folder.glob("*.[pP][nN][gG]"):
        await process_image_file(blob_client, img_path, docs_path)
    for img_path in docs_folder.glob("*.jpg") or docs_folder.glob("*.jpeg"):
        await process_image_file(blob_client, img_path, docs_path)
    
    # 2. PDFs (TODAS PÁGINAS → JPG)
    for pdf_path in docs_folder.glob("*.pdf"):
        await process_pdf_file(blob_client, pdf_path, docs_path)
    
    print(f"\n🎉 PROCESSO PRONTO! {process_id}")

async def process_image_file(blob_client: BlobClient, img_path: Path, docs_path: str):
    """PNG/JPG direto → JPG otimizado."""
    img_filename = f"{img_path.stem}_page_1.jpg"
    blob_path = f"{docs_path}/{img_filename}"
    
    print(f"🖼️  {img_path.name} → {img_filename}")
    
    img = Image.open(img_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    img_buffer = io.BytesIO()
    img.save(img_buffer, format='JPEG', quality=85, optimize=True)
    
    class FakeUploadFile:
        def __init__(self, content): self.content = content
        async def read(self): return self.content
    
    fake_file = FakeUploadFile(img_buffer.getvalue())
    await blob_client.upload_file(blob_path, fake_file)
    print(f"✅ {img_filename}")

async def process_pdf_file(blob_client: BlobClient, pdf_path: Path, docs_path: str):
    """PDF → TODAS páginas JPG com PyMuPDF."""
    print(f"📄 {pdf_path.name}")
    
    # Abre PDF
    doc = fitz.open(pdf_path)
    
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        
        # Renderiza página → pixmap (150 DPI)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 150 DPI
        
        # Pixmap → PIL Image → JPG
        img = Image.open(io.BytesIO(pix.tobytes("ppm")))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        img_filename = f"{pdf_path.stem}_page_{page_num+1}.jpg"
        blob_path = f"{docs_path}/{img_filename}"
        
        # Otimiza e salva
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='JPEG', quality=85, optimize=True)
        
        class FakeUploadFile:
            def __init__(self, content): self.content = content
            async def read(self): return self.content
        
        fake_file = FakeUploadFile(img_buffer.getvalue())
        await blob_client.upload_file(blob_path, fake_file)
        print(f"✅ {img_filename}")
    
    doc.close()

async def main():
    process_id = "demo-process-001"
    await create_process_with_split_docs(process_id, "app/mercedes-data")

if __name__ == "__main__":
    asyncio.run(main())
