"""Words/.NET documentation theme policy; owned by this plugin."""

import re

from adcs_words_net.gist_examples import expand
from adcs_words_net.hugo_parser import HugoMarkdownParser


def extract(request):
    text = request["raw_markdown"].removeprefix("\ufeff")
    text = expand(text)
    # Convert paired Hugo highlight shortcodes to fenced examples before parsing.
    # Unknown shortcodes retain the parser's explicit warnings.
    text = re.sub(
        r'{{[<%]\s*highlight\s+["\']?([\w#+-]+)["\']?[^{}]*[>%]}}',
        lambda match: "```" + match[1],
        text,
    )
    text = re.sub(r"{{[<%]\s*/highlight\s*[>%]}}", "```", text)
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
        raw_markdown=text,
    )
