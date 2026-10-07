"""Words/.NET API reference extraction; separate from docs theme policy."""

from adcs_words_net.hugo_parser import HugoMarkdownParser


def extract(request):
    return HugoMarkdownParser().parse_document(
        **{
            key: request[key]
            for key in (
                "repo_id",
                "source_path",
                "source_kind",
                "product_id",
                "product_family",
                "relative_repo_path",
                "layout_detection",
            )
        },
        raw_markdown=request["raw_markdown"].removeprefix("\ufeff"),
    )
