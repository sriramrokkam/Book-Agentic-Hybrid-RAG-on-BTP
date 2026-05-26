"""
agents/srv/vertex_srv.py

Vertex AI initialisation, LLM, and embedding model helpers.
Uses double-checked locking to initialise the SDK exactly once per process.
"""
import os
import threading
import vertexai
from vertexai.generative_models import GenerativeModel
from vertexai.language_models import TextEmbeddingModel
from dotenv import load_dotenv

load_dotenv()

_init_lock = threading.Lock()
_initialized = False


def _ensure_initialized():
    global _initialized
    if not _initialized:
        with _init_lock:
            if not _initialized:
                vertexai.init(
                    project=os.getenv("GCP_PROJECT_ID"),
                    location=os.getenv("GCP_LOCATION", "us-central1"),
                )
                _initialized = True


def get_llm() -> GenerativeModel:
    """Return a Gemini GenerativeModel instance."""
    _ensure_initialized()
    return GenerativeModel("gemini-2.5-flash-preview-05-20")


def get_embedding_model() -> TextEmbeddingModel:
    """Return the text-embedding-004 model."""
    _ensure_initialized()
    return TextEmbeddingModel.from_pretrained("text-embedding-004")


def embed_text(text: str) -> list[float]:
    """
    Embed a single string with text-embedding-004.
    Returns a list of 768 floats.
    """
    model = get_embedding_model()
    embeddings = model.get_embeddings([text])
    return embeddings[0].values  # list of 768 floats


def generate_text(prompt: str) -> str:
    """Generate a text response from Gemini given a prompt string."""
    llm = get_llm()
    response = llm.generate_content(prompt)
    return response.text
