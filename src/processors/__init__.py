"""Document processors with lazy exports for optional parser dependencies."""

from importlib import import_module

__all__ = [
    "PDFParser",
    "TextChunker",
    "TextCleaner",
    "MetadataExtractor"
]


_EXPORTS = {
    "PDFParser": ("src.processors.pdf_parser", "PDFParser"),
    "TextChunker": ("src.processors.text_chunker", "TextChunker"),
    "TextCleaner": ("src.processors.text_cleaner", "TextCleaner"),
    "MetadataExtractor": ("src.processors.metadata_extractor", "MetadataExtractor"),
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute_name = _EXPORTS[name]
    return getattr(import_module(module_name), attribute_name)
