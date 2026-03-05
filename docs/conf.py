# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# -- Path setup --------------------------------------------------------------
# Add the project root so autodoc can find the package
sys.path.insert(0, os.path.abspath('..'))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'auto_proxy_vpn'
copyright = '2026, Ignasi Rovira'
author = 'Ignasi Rovira'
release = '0.0.1'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',          # Auto-generate docs from docstrings
    'sphinx.ext.napoleon',         # Support NumPy and Google style docstrings
    'sphinx.ext.viewcode',         # Add [source] links to generated docs
    'sphinx.ext.intersphinx',      # Link to external projects (Python, etc.)
    'myst_parser',                 # Parse Markdown (.md) files
]

# MyST settings — enable useful markdown extensions
myst_enable_extensions = [
    'colon_fence',      # ::: directive fences
    'deflist',          # definition lists
    'fieldlist',        # field lists
]
myst_heading_anchors = 3    # Auto-generate anchors for h1-h3

# Markdown file suffixes
source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}

# Napoleon settings (NumPy-style docstrings)
napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False

# Autodoc settings
autodoc_member_order = 'bysource'
autodoc_default_options = {
    'members': True,
    'undoc-members': False,
    'show-inheritance': True,
}

# Intersphinx mappings
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
}

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# Suppress noisy warnings that don't affect the output
suppress_warnings = [
    'myst.xref_missing',      # markdown anchor links (#section) aren't real xrefs
    'myst.header',             # included READMEs start at h2/h3, that's fine
    'myst.iref_ambiguous',     # "license" matches both python data and doc
    'ref.python',              # ambiguous cross-refs for common names (log, credentials)
]

# Map unknown Pygments lexer names to something reasonable
from sphinx.highlighting import lexers
from pygments.lexers import BashLexer
lexers['dotenv'] = BashLexer()

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_title = 'auto proxy vpn'
