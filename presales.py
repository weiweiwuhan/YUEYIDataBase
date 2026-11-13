"""Pre-sales plans: one camera per station; incomplete uploads stay in a draft."""

TABLES = {"presales_plans", "presales_stations", "presales_product_photos"}
MAX_CAMERAS = 64


def row(connection, execute, table, rid):
    result = execute(
        connection, f"SELECT * FROM `{table}` WHERE id=?", (int(rid),)
    ).fetchone()
    if not result:
        raise ValueError("售前方案或工位不存在")
    return dict(result)


def check_version(plan, payload, conflict):
    if (
        "expected_updated_at" not in payload
        or plan.get("updated_at") != payload["expected_updated_at"]
    ):
        raise conflict("售前方案已被修改，请刷新后重新编辑，避免覆盖其他人的内容")


def validate_record(connection, execute, table, record):
    if table == "presales_stations":
        angle = record.get("lighting_angle_deg")
        if record["lighting_method"] == "倾斜打光":
            if angle is None or not 0 < angle <= 90:
                raise ValueError(
                    "倾斜打光必须填写大于0且不超过90°的倾斜角度（0°为平视）"
                )
        elif angle is not None:
            raise ValueError("只有倾斜打光需要填写倾斜角度，其他方式请留空")
        if record.get("image_asset_id"):
            validate_asset(connection, execute, record["image_asset_id"])
    elif table == "presales_product_photos":
        validate_asset(connection, execute, record["asset_id"])


def validate_asset(connection, execute, asset_id):
    asset = row(connection, execute, "assets", asset_id)
    if (
        asset["asset_type"] != "image"
        or asset["storage_mode"] != "file"
        or asset["status"] != "available"
    ):
        raise ValueError("售前照片必须使用已上传且可用的图片文件")
    return asset


def validate_complete(connection, execute, plan_id, image_check):
    plan = execute(
        connection, "SELECT * FROM presales_plans WHERE id=?", (plan_id,)
    ).fetchone()
    if not plan or plan["status"] != "已完成":
        return
    stations = execute(
        connection,
        "SELECT * FROM presales_stations WHERE plan_id=? ORDER BY station_no",
        (plan_id,),
    ).fetchall()
    count = plan["camera_count"]
    if len(stations) != count or [s["station_no"] for s in stations] != list(
        range(1, count + 1)
    ):
        raise ValueError("相机个数必须与工位数量一致，一个相机对应一个工位")
    photos = execute(
        connection,
        "SELECT asset_id FROM presales_product_photos WHERE plan_id=?",
        (plan_id,),
    ).fetchall()
    if not photos:
        raise ValueError("请至少上传一张原始产品手机照片")
    for photo in photos:
        validate_asset(connection, execute, photo["asset_id"])
        image_check(photo["asset_id"])
    for station in stations:
        validate_record(connection, execute, "presales_stations", dict(station))
        if not station["image_asset_id"]:
            raise ValueError(
                f"相机{station['station_no']}（{station['name']}）缺少实验室效果图：每相机/工位必须上传一张"
            )
        validate_asset(connection, execute, station["image_asset_id"])
        image_check(station["image_asset_id"])


def detail(connection, execute, plan_id):
    plan = row(connection, execute, "presales_plans", plan_id)
    stations = [
        dict(s)
        for s in execute(
            connection,
            "SELECT * FROM presales_stations WHERE plan_id=? ORDER BY station_no",
            (plan_id,),
        ).fetchall()
    ]
    photos = [
        dict(s)
        for s in execute(
            connection,
            "SELECT * FROM presales_product_photos WHERE plan_id=? ORDER BY id",
            (plan_id,),
        ).fetchall()
    ]
    assets = {}
    for aid in {s["image_asset_id"] for s in stations if s["image_asset_id"]} | {
        s["asset_id"] for s in photos
    }:
        assets[str(aid)] = row(connection, execute, "assets", aid)
    return {"plan": plan, "stations": stations, "photos": photos, "assets": assets}


def save_draft(connection, execute, save, payload, user, conflict):
    rid = payload.get("id")
    old = row(connection, execute, "presales_plans", rid) if rid else None
    if old:
        check_version(old, payload, conflict)
    record = dict(payload.get("record") or {})
    record.pop("id", None)
    record["status"] = "草稿"
    count = record.get("camera_count")
    if (
        isinstance(count, bool)
        or str(count).strip() != str(int(count or 0))
        or not 1 <= int(count) <= MAX_CAMERAS
    ):
        raise ValueError("相机个数必须是1至64的整数")
    count = int(count)
    stations = payload.get("stations")
    if not isinstance(stations, list) or len(stations) != count:
        raise ValueError("请按相机个数填写对应工位，一个相机对应一个工位")
    previous = {
        s["id"]: dict(s)
        for s in execute(
            connection, "SELECT * FROM presales_stations WHERE plan_id=?", (rid or 0,)
        ).fetchall()
    }
    retained = set()
    for number, station in enumerate(stations, 1):
        if not isinstance(station, dict):
            raise ValueError("工位配置格式无效")
        sid = station.get("id")
        if sid:
            if (
                sid not in previous
                or sid in retained
                or previous[sid]["station_no"] != number
            ):
                raise ValueError("工位不属于当前方案、重复或序号已改变，请刷新后重试")
            retained.add(sid)
    removed = set(previous) - retained
    if removed and user["role"] != "admin":
        raise PermissionError("仅管理员可以减少或移除已经保存的相机工位")
    rid = save(connection, "presales_plans", record, rid)
    for sid in removed:
        execute(connection, "DELETE FROM presales_stations WHERE id=?", (sid,))
    for number, station in enumerate(stations, 1):
        sid = station.get("id")
        item = dict(station)
        item.pop("id", None)
        item.update(plan_id=rid, station_no=number)
        save(connection, "presales_stations", item, sid)
    return detail(connection, execute, rid)


def finish(connection, execute, save, payload, conflict):
    plan = row(connection, execute, "presales_plans", payload["id"])
    check_version(plan, payload, conflict)
    save(connection, "presales_plans", {**plan, "status": "已完成"}, plan["id"])
    return detail(connection, execute, plan["id"])


def prepare_upload(connection, execute, query, conflict):
    plan = row(connection, execute, "presales_plans", query.get("plan_id", ["0"])[0])
    version = query.get("expected_updated_at")
    check_version(
        plan, {"expected_updated_at": version[0] if version else None}, conflict
    )
    kind = query["kind"][0]
    station = None
    if kind == "presales_station":
        station = row(
            connection, execute, "presales_stations", query.get("station_id", ["0"])[0]
        )
        if station["plan_id"] != plan["id"]:
            raise ValueError("该相机工位不属于当前售前方案")
    elif kind == "presales_product":
        if (
            execute(
                connection,
                "SELECT COUNT(*) AS n FROM presales_product_photos WHERE plan_id=?",
                (plan["id"],),
            ).fetchone()["n"]
            >= 100
        ):
            raise ValueError("单个方案最多保存100张原始产品照片")
    else:
        raise ValueError("未知售前图片用途")
    return plan, station


def bind_upload(connection, execute, save, plan, station, asset_id):
    if station:
        save(
            connection,
            "presales_stations",
            {**station, "image_asset_id": asset_id},
            station["id"],
        )
    else:
        save(
            connection,
            "presales_product_photos",
            {"plan_id": plan["id"], "asset_id": asset_id},
        )
    return detail(connection, execute, plan["id"])


def delete_plan(connection, execute, payload, conflict):
    plan = row(connection, execute, "presales_plans", payload["id"])
    check_version(plan, payload, conflict)
    if execute(
        connection,
        "SELECT id FROM knowledge_links WHERE target_table=? AND target_id=?",
        ("presales_plans", plan["id"]),
    ).fetchone():
        raise ValueError("方案仍被知识关联引用，请先解除关联")
    execute(
        connection,
        "DELETE FROM knowledge_links WHERE source_table=? AND source_id=?",
        ("presales_plans", plan["id"]),
    )
    execute(
        connection,
        "DELETE FROM entity_aliases WHERE entity_table=? AND entity_id=?",
        ("presales_plans", plan["id"]),
    )
    for table in ("presales_product_photos", "presales_stations"):
        execute(connection, f"DELETE FROM `{table}` WHERE plan_id=?", (plan["id"],))
    execute(connection, "DELETE FROM presales_plans WHERE id=?", (plan["id"],))
    return {"ok": True}
