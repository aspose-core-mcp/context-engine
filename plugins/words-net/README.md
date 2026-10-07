# Aspose.Words for .NET extractor

This package owns discovery, docs extraction, API extraction normalization, semantic chunking and structured API symbol extraction.
It has no runtime dependency on ADCS or the other product plugin. Its initial
parser/converter/vocabulary are independent copies of the MIT-licensed ADCS
pilot at d00ac79. Keep attribution in LICENSE. Changes are deliberately NOT
synchronized automatically with the engine or sibling package.

Edit docs_extractor.py for docs theme/shortcode handling and
apiref_extractor.py for API reference behavior. The copied parser and converter
are this package's implementation, not imports from the engine. Initial source
prefixes in plugin.json are evaluation configuration; verify them against your
checkout. A layout mismatch fails explicitly; it never expands to another SDK.

Source launcher: `python -I worker.py`. Installed package:
`python -I -m adcs_words_net.worker`. The JSON contract is documented in
../../docs/product-platform-plugins.md. Dependencies and package releases can
be changed independently. Use a dedicated interpreter/container in deployment.
