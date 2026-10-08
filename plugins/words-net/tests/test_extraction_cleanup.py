"""Offline regressions for the observed mail-merge and Document excerpts."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((PLUGIN / 'plugin.json').read_text())


def extract(kind, raw, tail):
    source = MANIFEST['sources'][kind]
    relative = source['prefix'] + '/' + tail + '/_index.md'
    request = dict(
        contract=MANIFEST['contract'], plugin_id=MANIFEST['plugin_id'],
        product_id=MANIFEST['product_id'], language='net', operation='extract',
        source_kind=kind, repo_id=source['repo_id'], product_family='aspose',
        source_path=source['path'] + '/' + relative, relative_repo_path=relative,
        source_prefix=source['prefix'], layout_detection=source['layout'],
        source_revision='fixture', canonical_base_url=source['canonical_base_url'],
        raw_markdown=raw,
    )
    result = subprocess.run([sys.executable, '-I', str(PLUGIN / 'worker.py')],
                            input=json.dumps(request), capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)['result']


class CleanupTest(unittest.TestCase):
    def test_mail_merge_heading_html_and_code(self):
        output = extract('docs', '''---
title: Types of Mail Merge Operations
url: /net/types-of-mail-merge-operations/
---
## Simple Mail Merge Operation {#simple-mail-merge-operation}
Aspose.Words allows you to execute a <strong>simple mail merge</strong>.
<img src="execute-simple-mail-merge-1.png" alt="template" style="width:300px"/>
{{% alert color="primary" %}}
Use the Execute method.
{{% /alert %}}
{{< highlight csharp >}}
doc.MailMerge.Execute(names, values);
{{< /highlight >}}
''', 'types-of-mail-merge-operation')
        text = '\n'.join(c['text'] for c in output['chunk_records'])
        for artifact in ('{#', 'operation}', '<img', '<strong', '{{%'):
            self.assertNotIn(artifact, text)
        self.assertIn('simple mail merge', text)
        self.assertIn('doc.MailMerge.Execute(names, values);', text)
        for chunk in output['chunk_records']:
            self.assertEqual(chunk['section_anchor'], '#simple-mail-merge-operation')
            self.assertEqual(chunk['canonical_url'],
                             'https://docs.aspose.com/words/net/types-of-mail-merge-operations/')

    def test_document_generated_escapes_and_csharp_literals(self):
        raw = (PLUGIN / 'tests/fixtures/document-real.md').read_text()
        raw = raw.replace('Represents a Word document.', r'Represents a document \(Word\)\.')
        raw = raw.replace('OneRow.docx', r'OneRow\.docx').replace('<summary>', r'\<summary>')
        raw = raw.replace('return doc;', 'var pattern = @"\\d+\\.\\w+";\n    return doc;')
        output = extract('apiref', raw, 'aspose.words/document')
        symbol = output['symbols'][0]
        self.assertEqual(symbol['member_fqn'], 'Aspose.Words.Document')
        self.assertIn('(Word).', symbol['summary'])
        examples = '\n'.join(symbol['payload']['examples'])
        self.assertIn('OneRow.docx', examples)
        self.assertIn('/// <summary>', examples)
        self.assertIn(r'@"\d+\.\w+"', examples)
        self.assertNotIn(r'\<summary>', examples)
        self.assertNotIn(r'OneRow\.', examples)
        self.assertEqual(symbol['canonical_url'],
                         'https://reference.aspose.com/words/net/aspose.words/document/')
        self.assertTrue(symbol['signature'].startswith('public class Document'))


class HeadingCleanupTest(unittest.TestCase):
    def test_conversion_html_headings_preserve_text_and_fenced_literals(self):
        raw = '''---
title: Convert a Document
url: /net/convert-a-document/
---
<h2>Convert Word to PDF</h2>
<h3 class="conversion">Other Examples</h3>
```csharp
builder.InsertHtml("<h2>Heading inside code</h2>");
```
'''
        output = extract('docs', raw, 'convert-a-document')
        text = output['page']['body_plain']
        self.assertIn('Convert Word to PDF', text)
        self.assertIn('Other Examples', text)
        self.assertNotIn('<h2>Convert', text)
        self.assertNotIn('<h3', text)
        self.assertIn('<h2>Heading inside code</h2>', output['page']['code_blocks'][0]['code'])


class SymbolCasingTest(unittest.TestCase):
    def test_declaration_spelling_survives_lowercase_paths_and_overloads(self):
        raw = '''---
title: DocumentBuilder.SetTextFormat Method
---
## DocumentBuilder.SetTextFormat method
```csharp
public void SetTextFormat(string value)
```
```csharp
public void SetTextFormat(int value)
```
## Examples
```csharp
public void SETTEXTFORMAT() {}
```
'''
        output = extract('apiref', raw, 'aspose.words/documentbuilder/settextformat')
        expected = 'Aspose.Words.DocumentBuilder.SetTextFormat'
        self.assertEqual(output['normalized_document']['document']['symbol_fqn'], expected)
        self.assertTrue(all(c['symbol_fqn'] == expected for c in output['chunk_records']))
        self.assertEqual(len(output['symbols']), 2)
        for symbol in output['symbols']:
            self.assertEqual(symbol['name'], 'SetTextFormat')
            self.assertEqual(symbol['member_fqn'], expected)
            self.assertEqual(symbol['parent_fqn'], 'Aspose.Words.DocumentBuilder')
            self.assertTrue(symbol['canonical_url'].endswith('/documentbuilder/settextformat/'))

    def test_declaration_wins_over_lowercase_title(self):
        raw = '''---
title: settextformat
---
```csharp
public void SetTextFormat(string value)
```
'''
        output = extract('apiref', raw, 'aspose.words/documentbuilder/settextformat')
        self.assertEqual(output['symbols'][0]['name'], 'SetTextFormat')

    def test_real_compound_property_heading(self):
        raw = '''---
title: DocumentBuilder.Font
---
## DocumentBuilder.Font property
```csharp
public Font Font { get; }
```
'''
        output = extract('apiref', raw, 'aspose.words/documentbuilder/font')
        self.assertEqual(output['symbols'][0]['member_fqn'], 'Aspose.Words.DocumentBuilder.Font')
