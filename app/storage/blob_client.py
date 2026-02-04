# app/storage/blob_client.py

import os
import json
from typing import Any, Dict, List

from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()

class BlobClient:
    def __init__(self):
        conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not conn_str:
            raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING não definido")
        self.service = BlobServiceClient.from_connection_string(conn_str)
        self.container_name = os.getenv("CONTAINER_NAME", "car-legalizacao")
        self.container = self.service.get_container_client(self.container_name)
        # garante que o container existe
        try:
            self.container.create_container()
        except Exception:
            pass

    async def list_blobs(self, prefix: str = None, include_metadata: bool = False) -> List[Dict[str, Any]]:
        """
        Lista todos os blobs no container.
        
        Args:
            prefix: Filtrar por prefixo (ex: "processes/abc123/")
            include_metadata: Incluir propriedades adicionais dos blobs
            
        Returns:
            Lista de dicionários com nome e propriedades dos blobs
        """
        blobs = []
        try:
            # Configurar generator com prefixo se fornecido
            kwargs = {}
            if prefix:
                kwargs['name_starts_with'] = prefix
            
            blob_list = self.container.list_blobs(**kwargs)
            
            for blob in blob_list:
                blob_info = {
                    'name': blob.name,
                    'size': getattr(blob, 'size', 0)
                }
                
                if include_metadata:
                    blob_info.update({
                        'last_modified': getattr(blob, 'last_modified', None),
                        'content_type': getattr(blob, 'content_settings', {}).get('content_type'),
                        'blob_type': getattr(blob, 'blob_type', None)
                    })
                
                blobs.append(blob_info)
                
        except Exception as e:
            print(f"Erro ao listar blobs: {e}")
            return []
        
        return blobs

    async def get_state(self, process_id: str) -> Dict[str, Any]:
        """
        Lê state.json do Blob e devolve SEMPRE um dict.
        Se não existir, cria um estado inicial.
        """
        blob_name = f"processes/{process_id}/state.json"
        blob = self.container.get_blob_client(blob_name)

        try:
            downloader = blob.download_blob()
            raw = downloader.readall().decode("utf-8")
            state = json.loads(raw)
        except Exception:
            # ainda não existe → criar estado inicial
            state = self._create_initial_state(process_id)
            # opcional: já gravar o estado inicial
            await self.save_state(process_id, state)

        return state

    async def save_state(self, process_id: str, state: Dict[str, Any]) -> None:
        """
        Recebe um dict e grava como JSON no Blob.
        """
        blob_name = f"processes/{process_id}/state.json"
        blob = self.container.get_blob_client(blob_name)
        data = json.dumps(state, ensure_ascii=False)
        blob.upload_blob(data, overwrite=True)

    async def upload_file(self, blob_path: str, file) -> None:
        """
        Guarda um ficheiro (UploadFile) no Blob em blob_path.
        """
        blob = self.container.get_blob_client(blob_path)
        contents = await file.read()
        blob.upload_blob(contents, overwrite=True)

    def _create_initial_state(self, process_id: str) -> Dict[str, Any]:
        return {
            "process_id": process_id,
            "fase_atual": "INTAKE_DOCS",
            "sub_fase": "AGUARDAR_UPLOAD",
            "dados_carro": {},
            "dados_fiscal": {     # ← NOVO
                "declarante": {
                    "nif": None,
                    "nome": None,
                    "morada_fiscal": None
                },
                "entrada_pt": {
                    "data": None,
                    "modo": None  # "conduzir" / "camião"
                },
                "regime_isv": None,  # "normal" / "mudanca_residencia" / etc
                "dav_draft": None,
                "isv_estimado": None
            },
            "docs": {},
            "flags": {},
            "prazos": {},
            "historico": [],
        }
    async def get_blob_as_base64(self, blob_name: str) -> str:
        """
        Lê um blob e retorna o conteúdo em base64.
        
        Args:
            blob_name: Caminho completo do blob (ex: "processes/abc/docs/file.pdf")
            
        Returns:
            Conteúdo do blob em base64 string
        """
        try:
            blob = self.container.get_blob_client(blob_name)
            downloader = blob.download_blob()
            content = downloader.readall()
            import base64
            return base64.b64encode(content).decode('utf-8')
        except Exception as e:
            print(f"Erro ao ler blob {blob_name}: {e}")
            raise

    async def get_blob_as_base64(self, blob_name: str) -> str:
        """
        Lê um blob PDF e retorna base64 com MIME type correto para GPT-4V.
        """
        try:
            blob = self.container.get_blob_client(blob_name)
            downloader = blob.download_blob()
            content = downloader.readall()
            import base64
            base64_data = base64.b64encode(content).decode('utf-8')
            return base64_data  # já sabes que é PDF
        except Exception as e:
            print(f"Erro ao ler blob {blob_name}: {e}")
            raise
    async def get_blob_bytes(self, blob_name: str) -> bytes:
        blob = self.container.get_blob_client(blob_name)
        downloader = blob.download_blob()
        return downloader.readall()
    async def get_blob_bytes(self, blob_name: str) -> bytes:
        """PDF bytes para pdf2image."""
        blob = self.container.get_blob_client(blob_name)
        downloader = blob.download_blob()
        return downloader.readall()
