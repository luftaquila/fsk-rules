#!/usr/bin/env python3
"""Convert one KSAE rules LaTeX document to reader HTML and a clause index."""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import pypandoc
from bs4 import BeautifulSoup, Tag


ROOT = Path(__file__).resolve().parent
KOREAN_ORDER = tuple("가나다라마바사아자차카타파하")
LITERAL_TILDE_TOKEN = "FSKASCIITILDE"
RULE_KEY_ANCHOR_PREFIX = "rule-"
RULE_KEY_PATTERN = re.compile(
    r"^formula-(?:technical|competition)\.[a-z0-9]+(?:[.-][a-z0-9]+)*$"
)
RULE_KEY_MAX_LENGTH = 100
FIGURE_PATTERN = re.compile(
    r"\\figwithcaption\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}"
    r"|\\fig\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}"
)


def parse_nested_braces(source: str, start: int) -> tuple[str, int]:
    if start >= len(source) or source[start] != "{":
        raise ValueError("중괄호 블록 시작 위치가 올바르지 않습니다.")
    depth = 0
    for position in range(start, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1 : position], position + 1
    raise ValueError("닫히지 않은 LaTeX 중괄호 블록입니다.")


def parse_aux_file(path: Path) -> dict[str, str]:
    """Read the first displayed value of each LaTeX label."""
    if not path.exists():
        return {}
    source = path.read_text(encoding="utf-8", errors="replace")
    labels: dict[str, str] = {}
    position = 0
    marker = r"\newlabel{"
    while (start := source.find(marker, position)) >= 0:
        name_start = start + len(marker)
        name_end = source.find("}", name_start)
        if name_end < 0:
            break
        name = source[name_start:name_end]
        position = name_end + 1
        if "@cref" in name or position >= len(source) or source[position] != "{":
            continue
        try:
            outer, _ = parse_nested_braces(source, position)
            value, _ = parse_nested_braces(outer, 0)
        except ValueError:
            continue
        value = re.sub(r"\\relax\s*", "", value.replace("{}", ""))
        labels[name] = value.replace("~", " ").replace("{", "").replace("}", "").strip()
    return labels


def resolve_references(source: str, labels: dict[str, str]) -> str:
    def reference(match: re.Match[str]) -> str:
        command, label = match.groups()
        value = labels.get(label, f"[{label}]")
        if command.lower() in {"cref", "figref"}:
            if label.startswith("fig:"):
                value = f"그림 {value}"
            elif label.startswith("section:"):
                value = f"제{value}조"
        anchor = label.replace(":", "-").replace(" ", "-")
        return rf"\hyperlink{{{anchor}}}{{{value}}}"

    source = re.sub(r"\\(figref|[cC]ref|ref)\{([^}]+)\}", reference, source)
    return re.sub(r"\\pageref\{[^}]+\}", "", source)


def validate_rule_key(rule_key: str, document: str) -> None:
    """Reject keys that could not survive renumbering or that no consumer can store."""
    if not RULE_KEY_PATTERN.fullmatch(rule_key):
        raise ValueError(f"잘못된 영구 규정 키: {rule_key}")
    if len(rule_key) > RULE_KEY_MAX_LENGTH:
        raise ValueError(f"영구 규정 키가 {RULE_KEY_MAX_LENGTH}자를 넘음: {rule_key}")
    # A digit-only part is a clause number, ordinal, or year in disguise and
    # would silently break when the document is renumbered.
    body = rule_key.split(".", 1)[1]
    if any(not re.search(r"[a-z]", part) for part in re.split(r"[.-]", body)):
        raise ValueError(f"영구 규정 키에 번호만으로 된 부분이 있음: {rule_key}")
    if not rule_key.startswith(f"{document}."):
        raise ValueError(f"문서와 영구 규정 키가 일치하지 않음: {document}, {rule_key}")


def validate_rule_key_labels(source: str, document: str) -> None:
    """Validate stable keys before generic LaTeX label normalization runs."""
    source_without_comments = re.sub(r"(?<!\\)%.*$", "", source, flags=re.MULTILINE)
    seen: set[str] = set()
    for match in re.finditer(r"\\label\{rule:([^}]*)\}", source_without_comments):
        rule_key = match.group(1)
        validate_rule_key(rule_key, document)
        if rule_key in seen:
            raise ValueError(f"중복 영구 규정 키: {rule_key}")
        seen.add(rule_key)


def expand_deferred_competition_tail(source: str) -> str:
    """Expand the long competition tail kept in a source-order helper macro."""
    declaration = r"\newcommand{\CompetitionRulesTail}"
    start = source.find(declaration)
    if start < 0:
        return source
    body_start = start + len(declaration)
    while body_start < len(source) and source[body_start].isspace():
        body_start += 1
    body, body_end = parse_nested_braces(source, body_start)
    source = source[:start] + source[body_end:]
    body = body.lstrip("%\r\n")
    return source.replace(r"\CompetitionRulesTail", body, 1)


def strip_balanced_command(source: str, command: str) -> str:
    """Remove a one-argument formatting command while preserving its contents."""
    marker = rf"\{command}{{"
    output: list[str] = []
    position = 0
    while (start := source.find(marker, position)) >= 0:
        output.append(source[position:start])
        brace = start + len(marker) - 1
        try:
            contents, end = parse_nested_braces(source, brace)
        except ValueError:
            break
        output.append(contents)
        position = end
    output.append(source[position:])
    return "".join(output)


def strip_color_groups(source: str) -> str:
    r"""Remove ``{\color{name} ...}`` wrappers, including wrappers around list items."""
    marker = r"{\color{"
    while marker in source:
        output: list[str] = []
        position = 0
        changed = False
        while (start := source.find(marker, position)) >= 0:
            output.append(source[position:start])
            color_brace = start + len(r"{\color")
            try:
                _, color_end = parse_nested_braces(source, color_brace)
                _, group_end = parse_nested_braces(source, start)
            except ValueError:
                output.append(source[start:])
                position = len(source)
                break
            output.append(source[color_end : group_end - 1])
            position = group_end
            changed = True
        output.append(source[position:])
        source = "".join(output)
        if not changed:
            break
    return source


def convert_tblr(source: str) -> str:
    """Reduce tabularray tables to syntax Pandoc can consume."""
    begin = r"\begin{tblr}"
    end_marker = r"\end{tblr}"
    output: list[str] = []
    position = 0
    while (start := source.find(begin, position)) >= 0:
        output.append(source[position:start])
        options_start = source.find("{", start + len(begin))
        end = source.find(end_marker, options_start)
        if options_start < 0 or end < 0:
            output.append(source[start:])
            return "".join(output)
        _, content_start = parse_nested_braces(source, options_start)
        contents = source[content_start:end]
        contents = re.sub(r"\\SetCell(?:\[[^]]*\])?\{[^}]*\}\s*", "", contents)
        rows = [row.strip() for row in re.split(r"\\\\", contents) if row.strip()]
        columns = max((len(re.findall(r"(?<!\\)&", row)) + 1 for row in rows), default=1)
        table_body = (" " + r"\\" + "\n").join(rows)
        output.append(
            "\\begin{tabular}{" + "|" + "l|" * columns + "}\n\\hline\n"
            + table_body
            + " " + r"\\" + "\n\\hline\n\\end{tabular}"
        )
        position = end + len(end_marker)
    output.append(source[position:])
    return "".join(output)


def preprocess_tex(source: str) -> str:
    source = expand_deferred_competition_tail(source)
    begin = source.find(r"\begin{document}")
    end = source.rfind(r"\end{document}")
    if begin >= 0:
        source = source[begin + len(r"\begin{document}") : end if end >= 0 else None]

    for command in ("DIFadd", "textb", "pretendard", "pretendardb", "uline"):
        source = strip_balanced_command(source, command)
    source = strip_color_groups(source)
    source = re.sub(r"\\(?:DIFdel|color)\{[^}]*\}", "", source)
    source = re.sub(r"\\(?:this)?pagestyle\{[^}]*\}", "", source)
    source = re.sub(r"\\(?:fontsize\{[^}]*\}\{[^}]*\}|addfontfeatures\{[^}]*\}|selectfont|clearpage)", "", source)
    source = source.replace(r"\RuleIndexStart", "")
    source = source.replace(r"\RuleIndexEnd", r"\hypertarget{rules-index-end}{}")
    # Pandoc treats LaTeX's ``\string~`` as spacing and drops the visible
    # range marker. Keep a plain-text sentinel through the LaTeX reader and
    # restore the literal character after conversion.
    source = source.replace(r"\string~", LITERAL_TILDE_TOKEN)
    source = source.replace(r"\string[", "[").replace(r"\string]", "]")
    source = source.replace("㎠", "cm²").replace("㎟", "mm²")

    chapter = 0
    article = 0

    def number_chapter(match: re.Match[str]) -> str:
        nonlocal chapter
        chapter += 1
        return rf"\chapter{{제{chapter}장 {match.group(1)}}}"

    def number_article(match: re.Match[str]) -> str:
        nonlocal article
        article += 1
        return rf"\section{{제{article}조 ({match.group(1)})}}"

    source = re.sub(r"\\chapter\{([^{}]+)\}", number_chapter, source)
    source = re.sub(r"\\section\{([^{}]+)\}", number_article, source)

    figure = 0

    def convert_figure(match: re.Match[str]) -> str:
        nonlocal figure
        figure += 1
        if match.group(1) is not None:
            asset, caption, _folder, width = match.group(1, 2, 3, 4)
        else:
            asset, _folder, width = match.group(5, 6, 7)
            caption = asset
        target = "fig-" + asset.replace(" ", "-")
        return (
            rf"\begin{{figure}}[H]\hypertarget{{{target}}}{{}}\centering "
            rf"\includegraphics[width={width}\linewidth]{{assets/{asset}.jpg}}"
            rf"\caption{{그림 {figure}. {caption}}}\end{{figure}}"
        )

    source = FIGURE_PATTERN.sub(convert_figure, source)
    source = re.sub(
        r"\\label\{([^}]+)\}",
        lambda match: rf"\hypertarget{{{match.group(1).replace(':', '-').replace(' ', '-')}}}{{}}",
        source,
    )
    source = convert_tblr(source)
    source = re.sub(r"\\chapter\*\{([^}]+)\}", lambda match: rf"\chapter{{{match.group(1)}}}", source)
    return source


def run_pandoc(source: str) -> str:
    with tempfile.TemporaryDirectory(prefix="fsk-rules-") as directory:
        input_path = Path(directory) / "rules.tex"
        input_path.write_text(source, encoding="utf-8")
        command = [
            pypandoc.get_pandoc_path(),
            "--from=latex+raw_tex",
            "--to=html5",
            # Native MathML keeps ordinary parenthesized text out of the math
            # renderer and does not depend on a third-party runtime script.
            # --mathml is supported by both Pandoc 2.x and 3.x.
            "--mathml",
            "--wrap=none",
            str(input_path),
        ]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
        except (FileNotFoundError, OSError) as error:
            raise SystemExit("requirements.txt에 고정된 Pandoc을 설치한 뒤 다시 빌드하세요.") from error
        except subprocess.CalledProcessError as error:
            raise SystemExit(f"pandoc 변환 실패:\n{error.stderr}") from error
        if result.stderr.strip():
            print(result.stderr, file=sys.stderr, end="")
        return result.stdout.replace(LITERAL_TILDE_TOKEN, "~")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def display_node_text(element: Tag) -> str:
    clone = copy.copy(element)
    for annotation in clone.select("math annotation, math annotation-xml"):
        annotation.decompose()
    for math in clone.find_all("math"):
        math.replace_with(math.get_text("", strip=True))
    return normalize_text(clone.get_text(" ", strip=True))


def canonical_node_text(element: Tag) -> str:
    clone = copy.copy(element)
    for button in clone.select("button.anchor-copy"):
        button.decompose()
    for link in clone.select("a[href^='#']"):
        link.clear()
        link.append(f"[ref:{link.get('href')}]")
    return normalize_text(clone.get_text(" ", strip=True))


def canonical_content(element: Tag, asset_dir: Path | None = None) -> tuple[str, str]:
    text = display_node_text(element)
    canonical_text = canonical_node_text(element)
    image_parts: list[str] = []
    if asset_dir:
        for image in element.select("img[src]"):
            filename = Path(image["src"]).name
            image_path = asset_dir / filename
            if image_path.exists():
                digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
                image_parts.append(f"image:sha256:{digest}")
    canonical = "\n".join([canonical_text, *image_parts]).strip()
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return text, f"sha256:{digest}"


def canonical_article(heading: Tag, asset_dir: Path | None = None) -> tuple[str, str]:
    """Hash an article heading together with all of its normative body."""
    nodes: list[Tag] = [heading]
    for sibling in heading.next_siblings:
        if isinstance(sibling, Tag) and sibling.name in {"h1", "h2"}:
            break
        if isinstance(sibling, Tag) and sibling.get("id") == "rules-index-end":
            break
        if isinstance(sibling, Tag):
            nodes.append(sibling)
    text = normalize_text(" ".join(display_node_text(node) for node in nodes))
    text_parts: list[str] = []
    for node in nodes:
        if str(node.get("id", "")).startswith(RULE_KEY_ANCHOR_PREFIX):
            continue
        canonical_text = canonical_node_text(node)
        if node is heading:
            canonical_text = re.sub(r"^제\d+조(?:의\d+)?\s*", "", canonical_text, count=1)
        text_parts.append(canonical_text)
    image_parts: list[str] = []
    if asset_dir:
        for node in nodes:
            for image in node.select("img[src]"):
                filename = Path(image["src"]).name
                image_path = asset_dir / filename
                if image_path.exists():
                    image_parts.append(f"image:sha256:{hashlib.sha256(image_path.read_bytes()).hexdigest()}")
    canonical = "\n".join([*text_parts, *image_parts]).strip()
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return text, f"sha256:{digest}"


def set_machine_heading_id(soup: BeautifulSoup, heading: Tag, machine_id: str) -> None:
    previous = str(heading.get("id")) if heading.get("id") else None
    matches = soup.find_all(id=previous) if previous else []
    if previous and previous != machine_id and all(match is heading for match in matches):
        alias = soup.new_tag("span", id=previous)
        alias["class"] = ["legacy-anchor"]
        heading.insert_before(alias)
    heading["id"] = machine_id
    heading["data-clause-id"] = machine_id


def assign_rule_keys(soup: BeautifulSoup, rules: list[dict], document: str) -> None:
    """Attach explicit ``rule:...`` LaTeX labels to their numbered clauses."""
    entries = {rule["id"]: rule for rule in rules}
    seen: set[str] = set()

    for marker in soup.find_all(id=lambda value: value and str(value).startswith(RULE_KEY_ANCHOR_PREFIX)):
        anchor = str(marker["id"])
        rule_key = anchor[len(RULE_KEY_ANCHOR_PREFIX) :]
        validate_rule_key(rule_key, document)
        if rule_key in seen:
            raise ValueError(f"중복 영구 규정 키: {rule_key}")

        target = marker if marker.get("data-clause-id") else marker.find_parent(attrs={"data-clause-id": True})
        if target is None:
            next_clause = marker.find_next(attrs={"data-clause-id": True})
            if (
                "legacy-anchor" in marker.get("class", [])
                and next_clause is not None
                and next_clause.name == "h2"
            ):
                target = next_clause
            else:
                target = marker.find_previous(attrs={"data-clause-id": True})

        clause_id = str(target.get("data-clause-id", "")) if target else ""
        entry = entries.get(clause_id)
        if entry is None:
            raise ValueError(f"영구 규정 키에 대응하는 조항이 없음: {rule_key}")
        existing_rule_key = str(target.get("data-rule-key", ""))
        if existing_rule_key and existing_rule_key != rule_key:
            raise ValueError(f"하나의 조항에 영구 규정 키가 여러 개임: {clause_id}")

        seen.add(rule_key)
        target["data-rule-key"] = rule_key
        entry["rule_key"] = rule_key


def subsection_letter(number: int) -> str:
    return KOREAN_ORDER[number - 1] if 0 < number <= len(KOREAN_ORDER) else str(number)


def path_citation(article: int, path: tuple[int, ...]) -> str:
    citation = f"제{article}조"
    if len(path) >= 1:
        citation += f" {path[0]}항"
    if len(path) >= 2:
        citation += f" {path[1]}호"
    if len(path) >= 3:
        citation += f" {subsection_letter(path[2])}목"
    if len(path) >= 4:
        citation += " " + "-".join(str(value) for value in path[3:])
    return citation


def path_id(document: str, article: int, path: tuple[int, ...]) -> str:
    components = [document, str(article)]
    for number in path:
        components.append(str(number))
    return "-".join(components)


def iter_direct_ordered_lists(heading: Tag):
    for sibling in heading.next_siblings:
        if isinstance(sibling, Tag) and sibling.name in {"h1", "h2"}:
            return
        if isinstance(sibling, Tag) and sibling.get("id") == "rules-index-end":
            return
        if isinstance(sibling, Tag) and sibling.name == "ol":
            yield sibling


def append_list_entry(
    item: Tag,
    document: str,
    edition: int,
    article: int,
    path: tuple[int, ...],
    entries: list[dict],
    seen: set[str],
    asset_dir: Path | None,
) -> None:
    machine_id = path_id(document, article, path)
    if machine_id in seen:
        raise ValueError(f"중복 조항 ID: {machine_id}")
    seen.add(machine_id)
    item["id"] = machine_id
    item["data-clause-id"] = machine_id
    text, digest = canonical_content(item, asset_dir)
    entries.append(
        {
            "id": machine_id,
            "year": edition,
            "edition": edition,
            "document": document,
            "citation": path_citation(article, path),
            "text": text,
            "href": f"#{machine_id}",
            "content_hash": digest,
        }
    )
    for child in item.find_all("ol", recursive=False):
        for number, nested_item in enumerate(child.find_all("li", recursive=False), start=1):
            append_list_entry(nested_item, document, edition, article, path + (number,), entries, seen, asset_dir)


def is_before(node: Tag, target: Tag) -> bool:
    return any(candidate is target for candidate in node.next_elements)


def annotate_rules(
    fragment: str,
    edition: int,
    document: str,
    asset_dir: Path | None = None,
) -> tuple[BeautifulSoup, list[dict]]:
    soup = BeautifulSoup(fragment, "html.parser")
    entries: list[dict] = []
    seen: set[str] = set()
    chapter = 0
    article = 0
    index_end = soup.find(id="rules-index-end")

    for heading in soup.find_all(["h1", "h2"]):
        normative = index_end is None or is_before(heading, index_end)
        if heading.name == "h1":
            chapter += 1
            set_machine_heading_id(soup, heading, f"{document}-chapter-{chapter}")
            continue
        if not normative:
            continue
        article += 1
        machine_id = f"{document}-{article}"
        if machine_id in seen:
            raise ValueError(f"중복 조항 ID: {machine_id}")
        seen.add(machine_id)
        set_machine_heading_id(soup, heading, machine_id)
        text, digest = canonical_article(heading, asset_dir)
        entries.append(
            {
                "id": machine_id,
                "year": edition,
                "edition": edition,
                "document": document,
                "citation": f"제{article}조",
                "text": text,
                "href": f"#{machine_id}",
                "content_hash": digest,
            }
        )
        top_number = 0
        for ordered_list in iter_direct_ordered_lists(heading):
            for item in ordered_list.find_all("li", recursive=False):
                top_number += 1
                append_list_entry(item, document, edition, article, (top_number,), entries, seen, asset_dir)
    assign_rule_keys(soup, entries, document)
    return soup, entries


def apply_figure_widths(soup: BeautifulSoup, source: str) -> None:
    r"""Apply figure widths independently of the installed Pandoc version."""
    for match in FIGURE_PATTERN.finditer(source):
        if match.group(1) is not None:
            asset, raw_width = match.group(1, 4)
        else:
            asset, raw_width = match.group(5, 7)
        try:
            percentage = float(raw_width) * 100
        except ValueError:
            continue
        if not 0 < percentage <= 100:
            continue
        image = soup.find("img", src=f"assets/{asset}.jpg")
        if image is not None:
            image["style"] = f"width:{percentage:g}%"


def resolve_html_reference_labels(soup: BeautifulSoup, rules: list[dict]) -> bool:
    """Normalize reference labels from the annotated clause structure."""
    citations = {rule["id"]: rule["citation"] for rule in rules}
    changed = False
    for link in soup.select("a[href^='#']"):
        anchor = str(link.get("href", ""))[1:]
        target = soup.find(id=anchor)
        citation = None
        if target is not None and anchor.startswith("fig-"):
            figure = target.find_parent("figure")
            caption = figure.find("figcaption") if figure else None
            match = re.search(r"그림\s+\d+", caption.get_text(" ", strip=True) if caption else "")
            citation = match.group(0) if match else None
        elif target is not None:
            clause = target if target.get("data-clause-id") else target.find_parent(attrs={"data-clause-id": True})
            if clause is None:
                clause = target.find_previous(["h1", "h2"])
            clause_id = str(clause.get("data-clause-id", "")) if clause else ""
            citation = citations.get(clause_id)
            if citation is None and clause is not None and clause.name == "h1":
                match = re.search(r"제\d+장", clause.get_text(" ", strip=True))
                citation = match.group(0) if match else None
            if citation and anchor.startswith("item-"):
                # LaTeX's item references read as "4번" in prose, while the
                # machine-readable citation intentionally keeps "4호".
                citation = re.sub(r"(\d+)호$", r"\1번", citation)
        if citation and link.get_text(" ", strip=True) != citation:
            link.string = citation
            changed = True
    return changed


def unresolved_reference_labels(soup: BeautifulSoup) -> list[str]:
    return sorted(
        {
            match.group(0)
            for link in soup.select("a[href^='#']")
            for match in re.finditer(r"\[[^\]]+:[^\]]+\]", link.get_text(" ", strip=True))
        }
    )


def broken_internal_references(soup: BeautifulSoup) -> list[str]:
    return sorted(
        {
            str(link.get("href", ""))
            for link in soup.select("a[href^='#']")
            if str(link.get("href", "")) != "#" and soup.find(id=str(link.get("href", ""))[1:]) is None
        }
    )


def toc_html(soup: BeautifulSoup) -> str:
    links: list[str] = []
    for heading in soup.find_all(["h1", "h2"]):
        identifier = heading.get("id")
        if not identifier:
            continue
        class_name = "toc-chapter" if heading.name == "h1" else "toc-article"
        links.append(
            f'<a class="{class_name}" href="#{html.escape(str(identifier))}">'
            f"{html.escape(normalize_text(heading.get_text(' ', strip=True)))}</a>"
        )
    return "\n".join(links)


def render_document(
    soup: BeautifulSoup,
    title: str,
    edition: int,
    document: str,
    pdf_filename: str,
) -> str:
    config = json.dumps(
        {"edition": edition, "document": document, "pdf": pdf_filename}, ensure_ascii=False
    ).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{html.escape(title)} {edition} 웹 규정집">
  <title>{html.escape(str(edition))} {html.escape(title)}</title>
  <link rel="stylesheet" href="../../style.css">
  <script defer src="../../viewer.js"></script>
</head>
<body class="reader-page">
  <a class="skip-link" href="#rules-content">본문으로 건너뛰기</a>
  <header class="reader-toolbar">
    <button class="icon-button" id="toc-toggle" type="button" aria-label="목차" title="목차" aria-controls="toc" aria-expanded="false">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
    </button>
    <a class="brand" href="../../" aria-label="규정 선택">FSK Rules</a>
    <div class="document-selectors">
      <label><span>연도</span><select id="edition-select" aria-label="연도 선택"></select></label>
      <label><span>문서</span><select id="document-select" aria-label="문서 선택"></select></label>
    </div>
    <a class="toolbar-link" href="{html.escape(pdf_filename)}" target="_blank" rel="noopener">PDF</a>
    <button class="icon-button" id="theme-toggle" type="button" aria-label="어두운 테마로 전환" title="어두운 테마로 전환">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.2 15.3A8.5 8.5 0 0 1 8.7 3.8 8.5 8.5 0 1 0 20.2 15.3Z"/></svg>
    </button>
  </header>
  <aside id="toc" class="toc-panel" aria-label="문서 목차">
    <div class="toc-title"><strong>목차</strong><button id="toc-close" type="button" aria-label="목차 닫기">×</button></div>
    <nav>{toc_html(soup)}</nav>
  </aside>
  <main id="rules-content" class="rules-content">
    {str(soup)}
  </main>
  <button id="back-to-position" class="back-position" type="button" hidden>이전 위치</button>
  <script id="rules-config" type="application/json">{config}</script>
</body>
</html>
"""


def catalog_entry_for(path: Path) -> dict | None:
    catalog_path = ROOT / "rules" / "catalog.json"
    if not catalog_path.exists():
        return None
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    resolved = path.resolve()
    for entry in catalog["documents"]:
        if (ROOT / entry["tex"]).resolve() == resolved:
            return entry
    return None


def convert(args: argparse.Namespace) -> None:
    input_path = args.input.resolve()
    entry = catalog_entry_for(input_path) or {}
    edition = args.edition or entry.get("edition")
    document = args.document or entry.get("document")
    title = args.title or entry.get("title") or input_path.stem
    pdf_filename = args.pdf_filename or entry.get("pdf_filename") or f"{input_path.stem}.pdf"
    if not edition or not document:
        raise SystemExit("--edition과 --document가 필요합니다.")
    asset_dir = args.asset_dir or (ROOT / entry["assets"] if entry.get("assets") else None)
    aux_path = args.aux or input_path.with_suffix(".aux")
    source = resolve_references(input_path.read_text(encoding="utf-8"), parse_aux_file(aux_path))
    validate_rule_key_labels(source, document)
    fragment = run_pandoc(preprocess_tex(source))
    soup, rules = annotate_rules(fragment, int(edition), document, asset_dir)
    if resolve_html_reference_labels(soup, rules):
        # Recompute searchable text after fallback labels have been restored.
        # Content hashes stay stable because canonical references use hrefs.
        soup, rules = annotate_rules(str(soup), int(edition), document, asset_dir)
    unresolved = unresolved_reference_labels(soup)
    if unresolved:
        preview = ", ".join(unresolved[:5])
        raise ValueError(f"미해결 규정 참조 {len(unresolved)}개: {preview}")
    broken = broken_internal_references(soup)
    if broken:
        preview = ", ".join(broken[:5])
        raise ValueError(f"대상이 없는 내부 규정 참조 {len(broken)}개: {preview}")
    apply_figure_widths(soup, source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_document(soup, title, int(edition), document, pdf_filename), encoding="utf-8"
    )
    index_path = args.index_output or args.output.with_name("rules-index.json")
    index_path.write_text(
        json.dumps(
            {"schema_version": 2, "edition": int(edition), "document": document, "rules": rules},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"{args.output}: {len(rules)}개 조항 인덱스 생성")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--edition", type=int)
    parser.add_argument("--document")
    parser.add_argument("--title")
    parser.add_argument("--pdf-filename")
    parser.add_argument("--asset-dir", type=Path)
    parser.add_argument("--aux", type=Path)
    parser.add_argument("--index-output", type=Path)
    return parser.parse_args()


if __name__ == "__main__":
    convert(parse_args())
