---
title: Document Class
linktitle: Document
articleTitle: Document
second_title: Aspose.Words for .NET
description: Discover the Aspose.Words.Document class for seamless Word document manipulation. Enhance your projects with powerful features and easy integration.
type: docs
weight: 660
url: /net/aspose.words/document/
---
## Document class

Represents a Word document.

To learn more, visit the [Working with Document](https://docs.aspose.com/words/net/working-with-document/) documentation article.

```csharp
public class Document : DocumentBase
```

## Examples

Shows how to execute a mail merge with data from a DataTable.

```csharp
DataTable table = new DataTable("Test");
table.Columns.Add("CustomerName");
table.Columns.Add("Address");
table.Rows.Add(new object[] { "Thomas Hardy", "120 Hanover Sq., London" });
table.Rows.Add(new object[] { "Paolo Accorti", "Via Monte Bianco 34, Torino" });

// Below are two ways of using a DataTable as the data source for a mail merge.
// 1 -  Use the entire table for the mail merge to create one output mail merge document for every row in the table:
Document doc = CreateSourceDocExecuteDataTable();

doc.MailMerge.Execute(table);

doc.Save(ArtifactsDir + "MailMerge.ExecuteDataTable.WholeTable.docx");

// 2 -  Use one row of the table to create one output mail merge document:
doc = CreateSourceDocExecuteDataTable();

doc.MailMerge.Execute(table.Rows[1]);

doc.Save(ArtifactsDir + "MailMerge.ExecuteDataTable.OneRow.docx");
```

Shows how to execute a mail merge with data from a DataTable (CreateSourceDocExecuteDataTable).

```csharp
/// <summary>
/// Creates a mail merge source document.
/// </summary>
private static Document CreateSourceDocExecuteDataTable()
{
    Document doc = new Document();
    DocumentBuilder builder = new DocumentBuilder(doc);

    builder.InsertField(" MERGEFIELD CustomerName ");
    builder.InsertParagraph();
    builder.InsertField(" MERGEFIELD Address ");

    return doc;
}
```

### See Also

* class [DocumentBase](../documentbase/)
* namespace [Aspose.Words](../../aspose.words/)
* assembly [Aspose.Words](../../)
