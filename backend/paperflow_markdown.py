"""Obsidian Markdown normalization and pre-publication format checks."""
import html
import re


def without_comments(line, inside):
    visible = []
    while line:
        if inside:
            end = line.find('-->')
            if end < 0:
                return ''.join(visible), True
            line, inside = line[end+3:], False
        else:
            token = re.search(r'(`+).*?\1|<!--', line)
            if not token:
                visible.append(line)
                break
            visible.append(line[:token.start()])
            if token[0] == '<!--':
                inside = True
            else:
                visible.append(token[0])
            line = line[token.end():]
    return ''.join(visible), inside


def lines_outside_code(text, blocks=None, *, exclude_math=False):
    fence = None
    display_math = False
    comment = False
    opening, language = None, None
    for index, line in enumerate(text.splitlines()):
        if fence is None and not display_math:
            line, comment = without_comments(line, comment)
        content = re.sub(r'^\s*(?:>\s*)*', '', line)
        if exclude_math and fence is None:
            if content.strip() == '$$':
                display_math = not display_math
                continue
            if display_math:
                continue
        match = re.match(r'^(`{3,}|~{3,})(.*)$', content)
        if match:
            marker, tail = match.groups()
            if fence is None:
                fence = marker
                opening, language = index, tail.strip()
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not tail.strip():
                if blocks is not None:
                    blocks.append((language, opening, index))
                fence = None
            continue
        if fence is None:
            yield index, line
    if fence:
        raise ValueError('Obsidian 格式：代码围栏未闭合')
    if display_math:
        raise ValueError('Obsidian 格式：块公式分隔符未闭合')
    if comment:
        raise ValueError('Obsidian 格式：HTML 注释未闭合')


def normalize(text):
    # Change syntax only, before validation. Never change facts or old notes.
    output = []
    plain = {index for index, _ in lines_outside_code(text, exclude_math=True)}
    for index, line in enumerate(text.splitlines()):
        if index in plain:
            chunks = re.split(r'(`+[^`]*`+)', line)
            for chunk_index in range(0, len(chunks), 2):
                for kind in ('P', 'E'):
                    def expand(match):
                        first, last = map(int, match.groups())
                        if 1 <= first <= last <= 99:
                            return ''.join(f'[{kind}{i:02d}]' for i in range(first, last + 1))
                        return match.group(0)
                    chunks[chunk_index] = re.sub(r'\[' + kind + r'(\d{2})\s*[-–—]\s*' + kind + r'?(\d{2})\]', expand, chunks[chunk_index])
            line = ''.join(chunks)
            line = re.sub(r'^\*\*([1-4])[．.、)]\s*(.*?)\*\*$', r'\1. **\2**', line)
        output.append(line)
    return '\n'.join(output)


def table_cells(line):
    cells, cell, escaped = [], [], False
    for char in line.strip():
        if char == '|' and not escaped:
            cells.append(''.join(cell)); cell = []
        else:
            cell.append(char)
        escaped = not escaped if char == '\\' else False
    cells.append(''.join(cell))
    if cells and not cells[0].strip(): cells.pop(0)
    if cells and not cells[-1].strip(): cells.pop()
    return cells


def validate(text, *, model_prose=False):
    if not model_prose:
        # Generated YAML stores source metadata verbatim; it is not Markdown prose.
        text = re.sub(r'\A---\n.*?\n---(?:\n|$)', '', text, count=1, flags=re.S)
    plain = [line for _,line in lines_outside_code(text, exclude_math=True)]
    for line in plain:
        # Inline code may legitimately show XML tokens or LaTeX examples.
        prose = re.sub(r'(`+).*?\1', '', line)
        prose = re.sub(r'<!--.*?-->', '', prose)
        prose = re.sub(r'\$[^$\n]+\$', '', prose)
        prose = re.sub(r'<(?:https?://|zotero://|mailto:)[^<>\s]+>', '', prose)
        prose = re.sub(r'(?<=\]\()<[^<>\n]*>(?=\))', '', prose)
        if re.search(r'(?<!\\)</?[A-Za-z][^>]*>', prose):
            raise ValueError('Obsidian 格式：正文禁止原生 HTML；折叠内容请用 callout')
        if model_prose and re.search(r'\\[\[\]()]', prose):
            raise ValueError('Obsidian 格式：数学公式请用 $ 或 $$ 分隔')
        if any(len(match[1]) % 2 == 0 for match in re.finditer(r'(\\*)\[[PE]\d{2}\s*[-–—,，]', prose)):
            raise ValueError('Obsidian 格式：来源编号必须逐个书写')
    def container(line):
        match = re.match(r'^\s*((?:>\s*)*)(.*)$', line)
        return match[1].count('>'), match[2]
    rows = [container(line) for line in plain]
    table_count = 0
    for index in range(1, len(rows)):
        depth, separator = rows[index]
        separator = separator.strip()
        cells = table_cells(separator)
        if '|' not in separator or not cells or not all(re.fullmatch(r':?-{3,}:?', cell.strip()) for cell in cells):
            continue
        count = len(table_cells(separator))
        if rows[index-1][0] != depth or len(table_cells(rows[index-1][1])) != count:
            raise ValueError('Obsidian 格式：表格表头列数不一致')
        table_count += 1
        for row_depth, row in rows[index+1:]:
            if row_depth != depth or '|' not in row or not row.strip(): break
            if len(table_cells(row)) != count:
                raise ValueError('Obsidian 格式：表格列数不一致；单元格内的竖线需转义')
    return table_count


def validate_answers(section):
    questions = list(re.finditer(r'^\s*([1-4])[.、)]\s*\S.*$', section, re.M))
    if [q[1] for q in questions] != ['1', '2', '3', '4']:
        raise ValueError('自测需按 1–4 编号列出四个问题')
    for index, question in enumerate(questions):
        end = questions[index+1].start() if index+1 < len(questions) else len(section)
        lines = section[question.end():end].strip().splitlines()
        if not lines or not re.fullmatch(r'> \[!note\]- 参考答案\s*', lines[0]):
            raise ValueError('Obsidian 格式：每个自测答案都需使用原生折叠 callout')
        if any(not line.startswith('>') for line in lines[1:]):
            raise ValueError('Obsidian 格式：callout 答案和内部空行都需带 > 前缀')
        if not any(line.lstrip('>').strip() for line in lines[1:]):
            raise ValueError('Obsidian 格式：折叠 callout 需包含非空答案')


def literal(text):
    """Keep source metadata/quotes visible without activating their markup."""
    text = html.escape(' '.join(str(text).split()), quote=False)
    return re.sub(r'([\\`*_\[\]$~#^])', r'\\\1', text)


def folded_quote(evidence, url):
    locator = literal(evidence['locator'])
    quote = literal(evidence['quote'])
    return (f"> [!quote]- {evidence['id']} · {locator}\n"
            f"> [PDF p.{evidence['page']}]({url})\n>\n> {quote}\n\n"
            f"^{evidence['id']}\n\n")
