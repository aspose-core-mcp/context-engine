from adcs.ingestion.source_adapters import SourceAdapterType, SourceConfig


def test_source_contract_supports_required_adapter_types() -> None:
    git_source = SourceConfig(
        adapter=SourceAdapterType.GIT,
        product="aspose.ocr",
        language="python",
        version="latest",
        path="source-repo-docs/Aspose.OCR",
    )
    filesystem_source = SourceConfig(
        adapter=SourceAdapterType.FILESYSTEM,
        product="aspose.ocr",
        language="python",
        version="latest",
        path="data-docs/aspose.ocr/python/latest/en",
    )

    assert git_source.adapter.value == "git"
    assert filesystem_source.adapter.value == "filesystem"
