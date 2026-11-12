"""Explicit correction of material/process bindings without deleting products."""


def deletion_message(connection, execute, table, record_id):
    """Explain references that must be corrected before a dictionary can go."""
    if table not in ("materials", "process_types"):
        return ""
    label = "材质" if table == "materials" else "工艺"
    query = (
        "SELECT COUNT(*) AS n FROM products WHERE material_id=?"
        if table == "materials"
        else "SELECT COUNT(*) AS n FROM product_processes WHERE process_id=?"
    )
    products = execute(connection, query, (record_id,)).fetchone()["n"]
    knowledge = execute(
        connection,
        "SELECT COUNT(*) AS n FROM knowledge_links WHERE target_table=? AND target_id=?",
        (table, record_id),
    ).fetchone()["n"]
    blockers = []
    if products:
        blockers.append(f"{products} 个产品")
    if knowledge:
        blockers.append(f"{knowledge} 条知识关联")
    if not blockers:
        return ""
    return (
        f"该{label}仍被"
        + "、".join(blockers)
        + "引用。请在“详情与关联”中更正产品或解除错误绑定，再删除字典条目。"
    )


def unlink_binding(connection, execute, save, payload, conflict_error):
    """Admin caller only: remove one observed binding with optimistic locking.

    The caller supplies its existing save function so author stamps and schema
    validation stay consistent. It must validate affected test evidence before
    commit. The transaction is owned by the caller; nothing commits here.
    """
    kind = payload.get("kind")
    if kind not in ("product_material", "product_process"):
        raise ValueError("仅支持解除产品的材质或工艺绑定")
    table = "products" if kind == "product_material" else "product_processes"
    record_id = int(payload.get("id") or 0)
    row = execute(
        connection, f"SELECT * FROM `{table}` WHERE id=?", (record_id,)
    ).fetchone()
    if not row:
        raise conflict_error("该绑定已不存在，请刷新后确认")
    row = dict(row)
    field = "material_id" if kind == "product_material" else "process_id"
    if (
        "expected_updated_at" not in payload
        or row.get("updated_at") != payload["expected_updated_at"]
        or not row.get(field)
        or row[field] != int(payload.get("target_id") or 0)
    ):
        raise conflict_error("该绑定已被修改，请刷新详情后再操作")
    if kind == "product_material":
        save(connection, "products", {**row, "material_id": None}, record_id)
        product_id = record_id
    else:
        execute(connection, "DELETE FROM product_processes WHERE id=?", (record_id,))
        product_id = row["product_id"]
    return {"ok": True, "product_id": product_id}
