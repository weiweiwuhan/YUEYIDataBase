"""Bounded, non-destructive import helpers for after-sales and RAG knowledge.

CSV files may use UTF-8 (with an optional BOM) or GB18030. XLSX imports read
the first worksheet, without evaluating formulas. A question-only Q&A sheet
uses the first 191 characters as its title and keeps the complete question in
``symptom``; explicitly supplied titles are never silently shortened.

This module only prepares records. The caller must check ``errors`` and repeat
``prepare_import`` inside its write lock/transaction before committing a file.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
import hashlib
import io
import json
import re
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET
import zipfile


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_CELL_CHARS = 20000
MAX_TITLE_CHARS = 191
MAX_XLSX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_XLSX_MEMBERS = 10000
MAX_COLUMNS = 100
PREVIEW_ROWS = 20

RECORD_FIELDS = (
    "project_id", "product_id", "name", "service_date", "status", "symptom",
    "cause", "resolution", "experience", "remark",
)
STATUSES = {"待处理", "处理中", "已解决"}


def _header_key(value: str) -> str:
    return re.sub(r"[\s_-]+", "", value.strip().lstrip("\ufeff")).casefold()


_ALIASES = {
    "project_id": ("project_id", "project", "项目", "项目ID", "项目编号", "项目名称", "绑定项目"),
    "product_id": ("product_id", "product", "产品", "产品ID", "产品编号", "产品名称", "绑定产品"),
    "name": ("name", "title", "问题标题", "标题", "售后标题"),
    "service_date": ("service_date", "date", "售后日期", "日期"),
    "status": ("status", "处理状态", "状态"),
    "symptom": ("symptom", "问题现象", "故障现象"),
    "cause": ("cause", "原因分析", "故障原因"),
    "resolution": ("resolution", "solution", "answer", "处理方案", "解决方案", "答案"),
    "experience": ("experience", "经验与预防措施", "经验", "预防措施"),
    "remark": ("remark", "notes", "备注"),
    "question": ("question", "问题描述", "问题", "问句"),
    "category": ("category", "taxonomy", "问题类型", "分类", "类别"),
    "id": ("id", "编号"),
    "created_by": ("created_by", "录入作者"),
    "created_at": ("created_at", "录入时间"),
    "updated_by": ("updated_by", "最后修改人"),
    "updated_at": ("updated_at", "最后修改时间"),
}
HEADER_ALIASES = {_header_key(alias): key for key, aliases in _ALIASES.items() for alias in aliases}
IGNORED_READONLY_FIELDS = {"id", "created_by", "created_at", "updated_by", "updated_at"}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time().isoformat() == "00:00:00" else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _check_upload(content: bytes, filename: str) -> str:
    if not isinstance(content, bytes):
        raise ValueError("上传内容必须为文件字节。")
    if not content:
        raise ValueError("上传的文件为空。")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("文件大小不能超过 5 MB。")
    suffix = str(filename).rsplit(".", 1)[-1].casefold() if "." in str(filename) else ""
    if suffix not in ("csv", "xlsx"):
        raise ValueError("仅支持 CSV 和 XLSX 文件。")
    return suffix


def _headers(values: Iterable[Any]) -> list[str]:
    headers = [_as_text(value).lstrip("\ufeff") for value in values]
    while headers and not headers[-1]:
        headers.pop()
    if not headers:
        raise ValueError("未找到表头，请在第一行填写字段名称。")
    if len(headers) > MAX_COLUMNS:
        raise ValueError(f"表格最多支持 {MAX_COLUMNS} 列。")
    seen: set[str] = set()
    canonical_seen: set[str] = set()
    for header in headers:
        if not header:
            raise ValueError("表头中存在空列名，请补全或删除该列。")
        if len(header) > MAX_CELL_CHARS:
            raise ValueError("表头过长。")
        key = _header_key(header)
        canonical = HEADER_ALIASES.get(key)
        if key in seen or (canonical is not None and canonical in canonical_seen):
            raise ValueError(f"表头重复或含义重复：{header}。")
        seen.add(key)
        if canonical:
            canonical_seen.add(canonical)
    return headers


def _row_dict(headers: list[str], values: list[Any], number: int) -> dict[str, str]:
    # Excel formatting can leave trailing empty cells outside the actual table.
    if any(_as_text(value) for value in values[len(headers):]):
        raise ValueError(f"第 {number} 行存在没有表头的数据列。")
    return {header: _as_text(values[index]) if index < len(values) else "" for index, header in enumerate(headers)}


def _csv_rows(content: bytes) -> list[tuple[int, dict[str, str]]]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            decoded = content.decode("gb18030")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV 编码无效，请使用 UTF-8 或 GB18030 编码保存。") from exc
    if "\x00" in decoded:
        raise ValueError("CSV 文件包含无效的空字符。")
    try:
        dialect = csv.Sniffer().sniff(decoded[:65536], delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(decoded, newline=""), delimiter=delimiter, strict=True)
    headers = None
    result = []
    previous_line = 0
    try:
        for values in reader:
            number = previous_line + 1
            previous_line = reader.line_num
            if not any(_as_text(value) for value in values):
                continue
            if headers is None:
                headers = _headers(values)
                continue
            if len(result) >= MAX_ROWS:
                raise ValueError(f"每次最多导入 {MAX_ROWS} 行数据。")
            result.append((number, _row_dict(headers, values, number)))
    except csv.Error as exc:
        raise ValueError(f"CSV 格式无效（第 {reader.line_num} 行）：{exc}。") from exc
    if headers is None:
        raise ValueError("文件中没有表头。")
    return result


def _xlsx_rows(content: bytes) -> list[tuple[int, dict[str, str]]]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > MAX_XLSX_MEMBERS:
                raise ValueError("XLSX 压缩包文件数量超过安全限制。")
            if sum(member.file_size for member in members) > MAX_XLSX_UNCOMPRESSED_BYTES:
                raise ValueError("XLSX 解压后大小不能超过 50 MB。")
            if any(member.flag_bits & 1 for member in members):
                raise ValueError("不支持加密的 XLSX 文件。")
            # Dimension metadata and far-away cell coordinates are both
            # untrusted. Check coordinates before openpyxl can expand sparse
            # XML into a tuple with millions of empty columns.
            for member in members:
                if re.fullmatch(r"xl/worksheets/[^/]+\.xml", member.filename):
                    with archive.open(member) as worksheet:
                        for event, element in ET.iterparse(worksheet, events=("start", "end")):
                            if event == "start" and element.tag.rsplit("}", 1)[-1] == "c":
                                reference = element.attrib.get("r", "")
                                match = re.fullmatch(r"([A-Za-z]+)([0-9]+)", reference)
                                if not match:
                                    raise ValueError("XLSX 包含无效的单元格坐标。")
                                column = 0
                                for letter in match[1].upper():
                                    column = column * 26 + ord(letter) - ord("A") + 1
                                    if column > MAX_COLUMNS:
                                        raise ValueError(f"表格最多支持 {MAX_COLUMNS} 列，请删除远端单元格。")
                            if event == "end":
                                element.clear()
    except (zipfile.BadZipFile, OSError, ET.ParseError) as exc:
        raise ValueError("XLSX 文件格式无效。") from exc
    try:
        import openpyxl
    except ImportError as exc:
        raise ValueError("XLSX 导入依赖 openpyxl，请先安装项目依赖。") from exc
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
    except Exception as exc:
        raise ValueError("无法读取 XLSX 文件，请重新另存为标准 XLSX 格式。") from exc
    result = []
    try:
        if not workbook.worksheets:
            raise ValueError("XLSX 文件中没有工作表。")
        sheet = workbook.worksheets[0]
        # Ignore untrusted worksheet dimension metadata (a single formatted
        # cell can otherwise allocate a million columns for every data row).
        sheet.reset_dimensions()
        headers = None
        for number, cells in enumerate(sheet.iter_rows(max_col=MAX_COLUMNS), 1):
            if number > MAX_ROWS + 1000:
                raise ValueError("工作表包含过多空行，请整理后重新上传。")
            if len(cells) > MAX_COLUMNS:
                if any(cell.value is not None for cell in cells[MAX_COLUMNS:]):
                    raise ValueError(f"表格最多支持 {MAX_COLUMNS} 列。")
                cells = cells[:MAX_COLUMNS]
            if any(cell.data_type == "f" for cell in cells):
                raise ValueError(f"第 {number} 行包含公式，请转换为普通文本或数值后上传。")
            if any(cell.data_type == "e" for cell in cells):
                raise ValueError(f"第 {number} 行包含 Excel 错误值，请更正后上传。")
            values = [cell.value for cell in cells]
            if not any(_as_text(value) for value in values):
                continue
            if headers is None:
                headers = _headers(values)
                continue
            if len(result) >= MAX_ROWS:
                raise ValueError(f"每次最多导入 {MAX_ROWS} 行数据。")
            result.append((number, _row_dict(headers, values, number)))
        if headers is None:
            raise ValueError("文件中没有表头。")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("XLSX 工作表数据损坏，无法完成导入。") from exc
    finally:
        workbook.close()
    return result


def _read_table(content: bytes, filename: str) -> list[tuple[int, dict[str, str]]]:
    return _xlsx_rows(content) if _check_upload(content, filename) == "xlsx" else _csv_rows(content)


def _validate_cells(raw: Mapping[str, Any]) -> None:
    for header, value in raw.items():
        if len(_as_text(value)) > MAX_CELL_CHARS:
            raise ValueError(f"“{header}”超过 {MAX_CELL_CHARS} 字符，请拆分该条内容。")


def parse_table(content: bytes, filename: str) -> list[dict[str, str]]:
    """Read a bounded CSV/XLSX table, retaining the original column labels.

    Structural errors, formulas and overlong cells raise ``ValueError``.
    Completely blank rows are skipped; the first nonblank row is the header.
    """
    rows = _read_table(content, filename)
    for number, raw in rows:
        try:
            _validate_cells(raw)
        except ValueError as exc:
            raise ValueError(f"第 {number} 行：{exc}") from exc
    return [raw for _, raw in rows]


def _canonical_values(raw: Mapping[str, Any]) -> dict[str, str]:
    _validate_cells(raw)
    values = {}
    for header, value in raw.items():
        text = _as_text(value)
        canonical = HEADER_ALIASES.get(_header_key(header))
        # Application exports include audit columns. Accept their presence,
        # but only the server may assign IDs and current-author metadata.
        if canonical in IGNORED_READONLY_FIELDS:
            continue
        if canonical:
            values[canonical] = text
        elif text:
            raise ValueError(f"不支持的列“{header}”，请使用导入模板字段。")
    return values


def _resolve_binding(value: Any, choices: Iterable[Mapping[str, Any]], label: str) -> int:
    text = _as_text(value)
    if not text:
        raise ValueError(f"缺少{label}，请在表格中填写或选择统一绑定的{label}。")
    options = [dict(option) for option in choices]
    # Numeric source values are identifiers. They must never fall back to a
    # similarly named product if the referenced record has been removed.
    if re.fullmatch(r"\d+(?:\.0+)?", text):
        identifier = int(float(text)) if "." in text else int(text)
        matches = [option for option in options if str(option.get("id")) == str(identifier)]
        if not matches:
            raise ValueError(f"{label}编号 {identifier} 不存在。")
        return identifier
    matches = [option for option in options if text in {_as_text(option.get("name")), _as_text(option.get("code"))}]
    if not matches:
        raise ValueError(f"找不到{label}“{text}”，请先创建对应记录。")
    identifiers = {int(option["id"]) for option in matches}
    if len(identifiers) != 1:
        raise ValueError(f"{label}“{text}”对应多条记录，请改填唯一编号。")
    return identifiers.pop()


def _normalize_date(value: str) -> str | None:
    if not value:
        return None
    normalized = value.replace("/", "-").replace("年", "-").replace("月", "-").replace("日", "")
    try:
        # Date fields do not accept a time silently: spreadsheet midnight
        # dates were already converted to ISO dates when reading cells.
        parts = normalized.split("-")
        if len(parts) != 3:
            raise ValueError
        return date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
    except (ValueError, TypeError) as exc:
        raise ValueError("售后日期无效，请使用 YYYY-MM-DD。") from exc


def _content_fields(values: Mapping[str, str]) -> dict[str, Any]:
    question = values.get("question", "")
    name = values.get("name", "")
    symptom = values.get("symptom", "")
    if not name:
        name = (question or symptom)[:MAX_TITLE_CHARS]
    elif len(name) > MAX_TITLE_CHARS:
        raise ValueError(f"问题标题不能超过 {MAX_TITLE_CHARS} 字符；长问题请填写在问题现象或问题描述列。")
    if not name:
        raise ValueError("缺少问题标题或问题描述。")
    if question:
        # Keep both descriptions when a template supplies a separate symptom.
        symptom = question if not symptom or symptom == question else f"{question}\n\n问题现象：{symptom}"
    remark = values.get("remark", "")
    if values.get("category"):
        category_line = "问题类型：" + values["category"]
        remark = category_line + ("\n" + remark if remark else "")
    record = {
        "name": name,
        "service_date": _normalize_date(values.get("service_date", "")),
        "symptom": symptom or None,
        "cause": values.get("cause") or None,
        "resolution": values.get("resolution") or None,
        "experience": values.get("experience") or None,
        "remark": remark or None,
    }
    for field, value in record.items():
        if value is not None and len(value) > MAX_CELL_CHARS:
            raise ValueError(f"合并后的“{field}”超过 {MAX_CELL_CHARS} 字符，请拆分该条内容。")
    return record


def record_fingerprint(record: Mapping[str, Any]) -> str:
    """Hash content only; author, primary key and timestamps are excluded."""
    canonical = {}
    for field in RECORD_FIELDS:
        value = record.get(field)
        if field in ("project_id", "product_id"):
            canonical[field] = int(value) if value not in (None, "") else None
        else:
            canonical[field] = _as_text(value) or None
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def prepare_import(
    content: bytes,
    filename: str,
    projects: Iterable[Mapping[str, Any]],
    products: Iterable[Mapping[str, Any]],
    existing: Iterable[Mapping[str, Any]],
    defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and deduplicate after-sales rows without changing any data.

    ``rows`` and ``preview`` contain ``{row: physical_row, record: {...}}``.
    ``valid_count`` is the number of new records, not the duplicate count.
    A nonempty ``errors`` list means the caller must not commit any rows.
    """
    source = _read_table(content, filename)
    project_choices, product_choices = list(projects), list(products)
    defaults = defaults or {}
    seen = {record_fingerprint(dict(record)) for record in existing}
    rows = []
    errors = []
    duplicates = 0
    for number, raw in source:
        try:
            values = _canonical_values(raw)
            record = _content_fields(values)
            record["project_id"] = _resolve_binding(values.get("project_id") or defaults.get("project_id"), project_choices, "项目")
            record["product_id"] = _resolve_binding(values.get("product_id") or defaults.get("product_id"), product_choices, "产品")
            status = values.get("status") or _as_text(defaults.get("status")) or ("已解决" if record["resolution"] else "待处理")
            status = {"pending": "待处理", "in_progress": "处理中", "resolved": "已解决"}.get(status.casefold(), status)
            if status not in STATUSES:
                raise ValueError("处理状态必须是待处理、处理中或已解决。")
            record["status"] = status
            fingerprint = record_fingerprint(record)
            if fingerprint in seen:
                duplicates += 1
                continue
            seen.add(fingerprint)
            rows.append({"row": number, "record": record})
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append({"row": number, "message": str(exc)})
    return {
        "total": len(source), "valid_count": len(rows), "duplicate_count": duplicates,
        "errors": errors, "rows": rows, "preview": rows[:PREVIEW_ROWS],
    }


def knowledge_documents(content: bytes, filename: str) -> list[dict[str, str]]:
    """Read Q&A/after-sales content as knowledge without inventing bindings.

    Returns deterministic, deduplicated documents. The source filename is not
    part of the content hash, so importing a renamed copy remains idempotent.
    An invalid row rejects the complete upload with its row number.
    """
    documents = []
    seen = set()
    for number, raw in _read_table(content, filename):
        try:
            values = _canonical_values(raw)
            fields = _content_fields(values)
            if not any(fields.get(key) for key in ("resolution", "cause", "experience")):
                raise ValueError("知识条目缺少解决方案、原因分析或经验内容。")
            question = values.get("question") or fields["name"]
            sections = [f"问题：{question}"]
            if fields["symptom"] and fields["symptom"] != question:
                sections.append(f"问题现象：{fields['symptom']}")
            for key, label in (("cause", "原因分析"), ("resolution", "解决方案"), ("experience", "经验与预防措施"), ("remark", "备注")):
                if fields[key]:
                    sections.append(f"{label}：{fields[key]}")
            text = "\n\n".join(sections)
            category = values.get("category", "")
            payload = json.dumps({"title": fields["name"], "text": text, "category": category}, ensure_ascii=False, sort_keys=True)
            identifier = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if identifier in seen:
                continue
            seen.add(identifier)
            documents.append({
                "id": identifier, "title": fields["name"], "text": text,
                "category": category, "source_type": "knowledge", "source_id": identifier,
            })
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"第 {number} 行：{exc}") from exc
    return documents
