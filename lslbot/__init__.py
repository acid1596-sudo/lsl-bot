"""lslbot: a small AI backend that answers chat requests using ChatGPT or Claude,
and automatically fails over to a local Ollama model when those providers run
out of usage, handing tasks back once the provider's usage resets.
"""

__version__ = "0.1.0"
