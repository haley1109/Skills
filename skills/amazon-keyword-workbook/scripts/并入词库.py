"""Attach an Artifact Tool worksheet without reserializing source sheets."""

from argparse import ArgumentParser
from copy import deepcopy
from pathlib import Path
from posixpath import basename, dirname, join, normpath, relpath
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile
import re

from lxml import etree


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPE = "http://schemas.openxmlformats.org/package/2006/content-types"
EXTENDED = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
WORKBOOK = "xl/workbook.xml"
CONTENT = "[Content_Types].xml"
TAB_NAME = "词库"
STYLE_ORDER = (
    "numFmts", "fonts", "fills", "borders", "cellStyleXfs", "cellXfs",
    "cellStyles", "dxfs", "tableStyles", "colors", "extLst",
)


def tag(name, namespace=MAIN):
    return f"{{{namespace}}}{name}"


def load_xml(archive, part):
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    return etree.fromstring(archive.read(part), parser=parser)


def xml_bytes(root):
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


def relationships_path(part):
    return join(dirname(part), "_rels", basename(part) + ".rels")


def resolve_target(owner, target):
    resolved = normpath(target.lstrip("/") if target.startswith("/") else join(dirname(owner), target))
    if resolved.startswith("../"):
        raise ValueError(f"Invalid package part: {target}")
    return resolved


def workbook_related_part(relationships, kind):
    relation = next((item for item in relationships if item.get("Type") == f"{OFFICE_REL}/{kind}"), None)
    return resolve_target(WORKBOOK, relation.get("Target")) if relation is not None else None


def free_numbered_part(parts, stem):
    pattern = re.compile(re.escape(stem) + r"(\d+)\.xml$")
    used = [int(match.group(1)) for part in parts if (match := pattern.fullmatch(part))]
    return f"{stem}{max(used, default=0) + 1}.xml"


def add_content_type(root, part, kind):
    etree.SubElement(root, tag("Override", CONTENT_TYPE), PartName="/" + part,
                     ContentType=f"application/vnd.openxmlformats-officedocument.spreadsheetml.{kind}+xml")


def style_collection(root, name):
    existing = root.find(tag(name))
    if existing is not None:
        return existing
    group = etree.Element(tag(name))
    later = {tag(other) for other in STYLE_ORDER[STYLE_ORDER.index(name) + 1:]}
    position = next((index for index, child in enumerate(root) if child.tag in later), len(root))
    root.insert(position, group)
    return group


def append_styles(target, donor, name, remap=None):
    additions = donor.find(tag(name))
    if additions is None:
        return 0
    collection = style_collection(target, name)
    offset = len(collection)
    for child in additions:
        entry = deepcopy(child)
        if remap is not None:
            remap(entry)
        collection.append(entry)
    collection.set("count", str(len(collection)))
    return offset


def add_number_formats(target, donor):
    source_formats = donor.find(tag("numFmts"))
    if source_formats is None:
        return {}
    collection = style_collection(target, "numFmts")
    existing = {entry.get("formatCode"): int(entry.get("numFmtId")) for entry in collection}
    new_id = max([163, *existing.values()]) + 1
    ids = {}
    for entry in source_formats:
        code = entry.get("formatCode")
        if code not in existing:
            existing[code] = new_id
            etree.SubElement(collection, tag("numFmt"), numFmtId=str(new_id), formatCode=code)
            new_id += 1
        ids[int(entry.get("numFmtId"))] = existing[code]
    collection.set("count", str(len(collection)))
    return ids


def add_attribute_offset(element, attribute, offset):
    value = element.get(attribute)
    if value is not None:
        element.set(attribute, str(int(value) + offset))


def combine_styles(target, donor):
    format_ids = add_number_formats(target, donor)
    components = {
        "fontId": append_styles(target, donor, "fonts"),
        "fillId": append_styles(target, donor, "fills"),
        "borderId": append_styles(target, donor, "borders"),
    }

    def remap_number_format(element):
        identifier = int(element.get("numFmtId", "0"))
        if identifier in format_ids:
            element.set("numFmtId", str(format_ids[identifier]))

    def remap_components(element):
        remap_number_format(element)
        for name, offset in components.items():
            add_attribute_offset(element, name, offset)

    base_style_offset = append_styles(target, donor, "cellStyleXfs", remap_components)

    def remap_cell_style(element):
        remap_components(element)
        add_attribute_offset(element, "xfId", base_style_offset)

    def remap_conditional_format(element):
        for fmt in element.iter(tag("numFmt")):
            remap_number_format(fmt)

    offset = append_styles(target, donor, "cellXfs", remap_cell_style)
    conditional_offset = append_styles(target, donor, "dxfs", remap_conditional_format)
    return offset, conditional_offset


def inline_strings(worksheet, donor_strings):
    for cell in worksheet.iter(tag("c")):
        if cell.get("t") != "s":
            continue
        value = cell.find(tag("v"))
        if value is None or value.text is None:
            raise ValueError(f"Shared string is missing for {cell.get('r')}")
        entry = donor_strings[int(value.text)]
        if cell.find(tag("f")) is not None:
            # Formula caches store scalar text under t="str".
            cell.set("t", "str")
            value.text = "".join(text.text or "" for text in entry.iter(tag("t")))
        else:
            cell.set("t", "inlineStr")
            inline = etree.Element(tag("is"))
            inline.extend(deepcopy(child) for child in entry)
            value.getparent().replace(value, inline)


def remap_differential_styles(root, offset):
    for element in root.iter():
        for attribute in element.attrib:
            if attribute.lower().endswith("dxfid"):
                add_attribute_offset(element, attribute, offset)


def remap_worksheet(sheet, style_offset, conditional_offset):
    for cell in sheet.iter(tag("c")):
        cell.set("s", str(int(cell.get("s", "0")) + style_offset))
    for row in sheet.iter(tag("row")):
        add_attribute_offset(row, "s", style_offset)
    for column in sheet.iter(tag("col")):
        add_attribute_offset(column, "style", style_offset)
    remap_differential_styles(sheet, conditional_offset)


def attach_tables(source, donor, old_sheet_part, new_sheet_part, content, conditional_offset):
    relationships = relationships_path(old_sheet_part)
    if relationships not in donor.namelist():
        return {}
    root = load_xml(donor, relationships)
    source_parts = set(source.namelist())
    table_files = [part for part in source_parts if re.fullmatch(r"xl/tables/table\d+\.xml", part)]
    source_tables = [load_xml(source, part) for part in table_files]
    table_names = {table.get("displayName", "").casefold() for table in source_tables}
    table_id = max((int(table.get("id")) for table in source_tables), default=0) + 1
    new_parts = {}
    for relation in root:
        if relation.get("TargetMode") == "External":
            continue
        if relation.get("Type") != f"{OFFICE_REL}/table":
            raise ValueError("待并入页包含当前合并流程未处理的内部引用。")
        old_table_part = resolve_target(old_sheet_part, relation.get("Target"))
        if relationships_path(old_table_part) in donor.namelist():
            raise ValueError("待并入页表格包含当前合并流程未处理的引用。")
        table = load_xml(donor, old_table_part)
        name = table.get("displayName", "").casefold()
        if name in table_names:
            raise ValueError(f"表格名重复：{table.get('displayName')}")
        table_names.add(name)
        new_table_part = free_numbered_part(source_parts | new_parts.keys(), "xl/tables/table")
        table.set("id", str(table_id))
        table_id += 1
        remap_differential_styles(table, conditional_offset)
        relation.set("Target", relpath(new_table_part, dirname(new_sheet_part)))
        add_content_type(content, new_table_part, "table")
        new_parts[new_table_part] = xml_bytes(table)
    new_parts[relationships_path(new_sheet_part)] = xml_bytes(root)
    return new_parts


def metadata_update(source, old_names, tab_name):
    part = "docProps/app.xml"
    if part not in source.namelist():
        return {}
    root = load_xml(source, part)
    titles = root.find(f"{tag('TitlesOfParts', EXTENDED)}/{tag('vector', VT)}")
    headings = root.find(f"{tag('HeadingPairs', EXTENDED)}/{tag('vector', VT)}")
    if titles is None or headings is None or len(headings) != 2:
        return {}
    count = headings[1].find(tag("i4", VT))
    if count is None or [item.text for item in titles] != old_names or count.text != str(len(old_names)):
        return {}
    etree.SubElement(titles, tag("lpstr", VT)).text = tab_name
    titles.set("size", str(len(titles)))
    count.text = str(len(titles))
    return {part: xml_bytes(root)}


def integration_parts(source, donor, tab_name=TAB_NAME):
    source_workbook = load_xml(source, WORKBOOK)
    donor_workbook = load_xml(donor, WORKBOOK)
    source_tabs = source_workbook.find(tag("sheets"))
    donor_tabs = donor_workbook.find(tag("sheets"))
    old_names = [tab.get("name") for tab in source_tabs]
    if any(name.casefold() == tab_name.casefold() for name in old_names):
        raise ValueError(f"完整操作表已有「{tab_name}」页。")
    if [tab.get("name") for tab in donor_tabs] != [tab_name]:
        raise ValueError(f"待并入文件须只含「{tab_name}」工作表。")

    workbook_rels = relationships_path(WORKBOOK)
    source_rels = load_xml(source, workbook_rels)
    donor_rels = load_xml(donor, workbook_rels)
    rel_id = donor_tabs[0].get(tag("id", OFFICE_REL))
    donor_rel = next(item for item in donor_rels if item.get("Id") == rel_id)
    donor_sheet_part = resolve_target(WORKBOOK, donor_rel.get("Target"))
    donor_sheet = load_xml(donor, donor_sheet_part)
    string_part = workbook_related_part(donor_rels, "sharedStrings")
    inline_strings(donor_sheet, load_xml(donor, string_part) if string_part is not None else [])

    source_style_part = workbook_related_part(source_rels, "styles")
    donor_style_part = workbook_related_part(donor_rels, "styles")
    source_style = load_xml(source, source_style_part)
    donor_style = load_xml(donor, donor_style_part)
    style_offset, conditional_offset = combine_styles(source_style, donor_style)
    remap_worksheet(donor_sheet, style_offset, conditional_offset)

    content = load_xml(source, CONTENT)
    new_sheet_part = free_numbered_part(source.namelist(), "xl/worksheets/sheet")
    used_ids = {item.get("Id") for item in source_rels}
    used_numbers = {int(item[3:]) for item in used_ids if re.fullmatch(r"rId\d+", item)}
    new_rel_id = f"rId{max(used_numbers, default=0) + 1}"
    sheet_id = str(max(int(tab.get("sheetId")) for tab in source_tabs) + 1)
    etree.SubElement(source_tabs, tag("sheet"),
                     {"name": tab_name, "sheetId": sheet_id, tag("id", OFFICE_REL): new_rel_id})
    etree.SubElement(source_rels, tag("Relationship", PACKAGE_REL), Id=new_rel_id,
                     Type=f"{OFFICE_REL}/worksheet", Target=relpath(new_sheet_part, dirname(WORKBOOK)))
    add_content_type(content, new_sheet_part, "worksheet")
    table_parts = attach_tables(source, donor, donor_sheet_part, new_sheet_part, content, conditional_offset)

    return {
        WORKBOOK: xml_bytes(source_workbook), workbook_rels: xml_bytes(source_rels),
        source_style_part: xml_bytes(source_style), CONTENT: xml_bytes(content),
        new_sheet_part: xml_bytes(donor_sheet), **table_parts,
        **metadata_update(source, old_names, tab_name),
    }


def merge_keyword_tab(source_path, donor_path, output_path, tab_name=TAB_NAME):
    if source_path == donor_path or output_path == donor_path:
        raise ValueError("完整操作表和输出文件须与待并入文件分开。")
    original_stamp = source_path.stat()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=output_path.parent, prefix=".merge-keywords-", delete=False) as staged:
        staged_path = Path(staged.name)
    try:
        with ZipFile(source_path) as source, ZipFile(donor_path) as donor:
            changed = integration_parts(source, donor, tab_name)
            with ZipFile(staged_path, mode="w", compression=ZIP_DEFLATED) as result:
                for item in source.infolist():
                    data = changed.pop(item.filename) if item.filename in changed else source.read(item)
                    result.writestr(item, data)
                for name, data in changed.items():
                    result.writestr(name, data)
        if source_path == output_path:
            observed = source_path.stat()
            if (observed.st_ino, observed.st_mtime_ns, observed.st_size) != (
                original_stamp.st_ino, original_stamp.st_mtime_ns, original_stamp.st_size,
            ):
                raise ValueError("源操作表已经更新，请用保存后的版本重试。")
        staged_path.chmod(original_stamp.st_mode & 0o777)
        staged_path.replace(output_path)
    finally:
        staged_path.unlink(missing_ok=True)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="完整操作表")
    parser.add_argument("donor", type=Path, help="只含待并入页的临时文件")
    parser.add_argument("output", type=Path, help="并入后输出的完整操作表")
    parser.add_argument("--tab-name", default=TAB_NAME, help="待并入工作表名")
    args = parser.parse_args()
    merge_keyword_tab(args.source.resolve(), args.donor.resolve(), args.output.resolve(), args.tab_name)


if __name__ == "__main__":
    main()
