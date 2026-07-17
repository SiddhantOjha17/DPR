from datetime import datetime, timedelta, timezone

from app import analytics, charts, operations


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _make_lot(conn, brand_ids, stage_ids, user_id, brand, ct, qty=100):
    return operations.create_lot(
        conn,
        brand_id=brand_ids[brand],
        ct_number=ct,
        total_qty=qty,
        starting_stage_id=stage_ids["Under Cutting"],
        moved_by=user_id,
        entered_at=_iso(20),
    )


# --- Brand filtering ---

def test_longest_time_in_stage_filters_by_brand(conn, brand_ids, stage_ids, user_id):
    _make_lot(conn, brand_ids, stage_ids, user_id, "SPYKAR", "S1")
    _make_lot(conn, brand_ids, stage_ids, user_id, "PEPE", "P1")

    spykar_only = analytics.longest_time_in_stage(conn, brand_id=brand_ids["SPYKAR"])
    assert {r["ct_number"] for r in spykar_only} == {"S1"}

    everyone = analytics.longest_time_in_stage(conn)
    assert {r["ct_number"] for r in everyone} == {"S1", "P1"}


def test_avg_days_per_stage_filters_by_brand(conn, brand_ids, stage_ids, user_id):
    lot_a = _make_lot(conn, brand_ids, stage_ids, user_id, "SPYKAR", "S1")
    operations.move_pieces(
        conn, lot_id=lot_a, from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"], qty=100, moved_at=_iso(1),
    )
    lot_b = _make_lot(conn, brand_ids, stage_ids, user_id, "PEPE", "P1")
    operations.move_pieces(
        conn, lot_id=lot_b, from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["Under Sewing"], qty=100, moved_at=_iso(1),
    )

    spykar_avgs = analytics.avg_days_per_stage(conn, brand_id=brand_ids["SPYKAR"])
    assert "Under Cutting" in spykar_avgs
    pepe_avgs = analytics.avg_days_per_stage(conn, brand_id=brand_ids["PEPE"])
    assert "Under Cutting" in pepe_avgs

    other_brand_id = brand_ids["KKCL"]
    assert analytics.avg_days_per_stage(conn, brand_id=other_brand_id) == {}


def test_throughput_filters_by_brand(conn, brand_ids, stage_ids, user_id):
    lot_a = _make_lot(conn, brand_ids, stage_ids, user_id, "SPYKAR", "S1")
    operations.move_pieces(
        conn, lot_id=lot_a, from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["FI Done"], qty=100, moved_at=_iso(1),
    )
    spykar_throughput = analytics.throughput(conn, brand_id=brand_ids["SPYKAR"])
    assert sum(r["qty"] for r in spykar_throughput) == 100

    pepe_throughput = analytics.throughput(conn, brand_id=brand_ids["PEPE"])
    assert sum(r["qty"] for r in pepe_throughput) == 0


def test_wip_over_time_filters_by_brand(conn, brand_ids, stage_ids, user_id):
    _make_lot(conn, brand_ids, stage_ids, user_id, "SPYKAR", "S1", qty=50)
    _make_lot(conn, brand_ids, stage_ids, user_id, "PEPE", "P1", qty=70)

    spykar_wip = analytics.wip_over_time(conn, brand_id=brand_ids["SPYKAR"])
    total_spykar = sum(sum(s["by_stage"].values()) for s in spykar_wip[-1:])
    assert total_spykar == 50

    all_wip = analytics.wip_over_time(conn)
    total_all = sum(all_wip[-1]["by_stage"].values())
    assert total_all == 120


def test_fi_date_risk_filters_by_brand(conn, brand_ids, stage_ids, user_id):
    lot_a = operations.create_lot(
        conn, brand_id=brand_ids["SPYKAR"], ct_number="S1", total_qty=100,
        starting_stage_id=stage_ids["Under Cutting"], moved_by=user_id,
        fi_date="2020-01-01",
    )
    risk_spykar = analytics.fi_date_risk(conn, brand_id=brand_ids["SPYKAR"])
    assert len(risk_spykar) == 1
    risk_pepe = analytics.fi_date_risk(conn, brand_id=brand_ids["PEPE"])
    assert risk_pepe == []


# --- summary_kpis ---

def test_summary_kpis_open_lots_and_pipeline(conn, brand_ids, stage_ids, user_id):
    _make_lot(conn, brand_ids, stage_ids, user_id, "SPYKAR", "S1", qty=100)
    _make_lot(conn, brand_ids, stage_ids, user_id, "SPYKAR", "S2", qty=200)
    _make_lot(conn, brand_ids, stage_ids, user_id, "PEPE", "P1", qty=50)

    kpis = analytics.summary_kpis(conn)
    assert kpis["open_lots_count"] == 3
    assert kpis["pieces_in_pipeline"] == 350

    spykar_kpis = analytics.summary_kpis(conn, brand_id=brand_ids["SPYKAR"])
    assert spykar_kpis["open_lots_count"] == 2
    assert spykar_kpis["pieces_in_pipeline"] == 300


def test_summary_kpis_cycle_time_needs_at_least_three_closed_lots(conn, brand_ids, stage_ids, user_id):
    for ct in ["S1", "S2"]:
        lot_id = _make_lot(conn, brand_ids, stage_ids, user_id, "SPYKAR", ct)
        operations.move_pieces(
            conn, lot_id=lot_id, from_stage_id=stage_ids["Under Cutting"],
            to_stage_id=stage_ids["FI Done"], qty=100,
        )
        operations.mark_shipped(conn, lot_id=lot_id)

    kpis = analytics.summary_kpis(conn)
    assert kpis["avg_cycle_time_days"] is None  # only 2 closed lots so far

    lot_id = _make_lot(conn, brand_ids, stage_ids, user_id, "SPYKAR", "S3")
    operations.move_pieces(
        conn, lot_id=lot_id, from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["FI Done"], qty=100,
    )
    operations.mark_shipped(conn, lot_id=lot_id)

    kpis = analytics.summary_kpis(conn)
    assert kpis["avg_cycle_time_days"] is not None
    assert kpis["avg_cycle_time_days"] >= 0


def test_summary_kpis_shipped_this_week(conn, brand_ids, stage_ids, user_id):
    lot_id = _make_lot(conn, brand_ids, stage_ids, user_id, "SPYKAR", "S1", qty=150)
    operations.move_pieces(
        conn, lot_id=lot_id, from_stage_id=stage_ids["Under Cutting"],
        to_stage_id=stage_ids["FI Done"], qty=150,
    )
    operations.mark_shipped(conn, lot_id=lot_id)

    kpis = analytics.summary_kpis(conn)
    assert kpis["shipped_this_week"] == 150


# --- Chart helper smoke tests ---

def test_bar_chart_horizontal_handles_empty_data():
    assert "Not enough data" in charts.bar_chart_horizontal([])


def test_bar_chart_horizontal_renders_svg_with_data():
    svg = charts.bar_chart_horizontal([("Under Cutting", 5.0), ("Under Sewing", 3.0)])
    assert svg.startswith("<svg")
    assert "Under Cutting" in svg
    assert "<title>" in svg


def test_bar_chart_vertical_handles_empty_data():
    assert "Not enough data" in charts.bar_chart_vertical([])


def test_bar_chart_vertical_renders_svg_with_data():
    svg = charts.bar_chart_vertical([("W25", 100), ("W26", 200)])
    assert svg.startswith("<svg")
    assert "W25" in svg


def test_stacked_bar_chart_handles_empty_data():
    assert "No movement history" in charts.stacked_bar_chart_vertical([], [], {})


def test_stacked_bar_chart_renders_with_data():
    svg = charts.stacked_bar_chart_vertical(
        ["2026-07-01", "2026-07-02"],
        ["Fabric Received", "Under Cutting", "FI Done"],
        {
            "2026-07-01": {"Fabric Received": 100, "Under Cutting": 50},
            "2026-07-02": {"Under Cutting": 100, "FI Done": 50},
        },
    )
    assert svg.startswith("<svg")


def test_stacked_bar_chart_colors_least_complete_stage_lightest():
    # stage_order arrives most-complete-first, matching the real call site
    # (routes/analytics.py orders stages by rank ascending, rank 1 = FI Done).
    # The ordinal ramp is light->dark = least-complete->most-complete, so the
    # legend's FIRST (lightest) swatch must label the LAST stage in that list
    # (Fabric Received here), not the first (FI Done) - regression test for a
    # bug where this came out backwards.
    svg = charts.stacked_bar_chart_vertical(
        ["2026-07-01"],
        ["FI Done", "Under Cutting", "Fabric Received"],
        {"2026-07-01": {"FI Done": 10, "Under Cutting": 20, "Fabric Received": 30}},
    )
    lightest_swatch_pos = svg.find(f'fill="{charts.ORDINAL_RAMP[0]}"')
    fabric_received_pos = svg.find("Fabric Received")
    fi_done_pos = svg.find("FI Done")
    assert lightest_swatch_pos != -1 and fabric_received_pos != -1
    # the lightest color swatch's legend label should be Fabric Received, which
    # means "Fabric Received" text must appear before "FI Done" in the legend
    assert fabric_received_pos < fi_done_pos


def test_bucket_stages_caps_bucket_count():
    stages = [f"Stage {i}" for i in range(13)]
    buckets = charts.bucket_stages(stages, max_buckets=5)
    assert len(buckets) <= 5
    # every stage must appear in exactly one bucket
    all_bucketed = [s for _, group in buckets for s in group]
    assert all_bucketed == stages


def test_bucket_stages_no_bucketing_needed_when_few_stages():
    stages = ["A", "B", "C"]
    buckets = charts.bucket_stages(stages, max_buckets=5)
    assert buckets == [("A", ["A"]), ("B", ["B"]), ("C", ["C"])]


def test_heatmap_color_is_monotonic_with_value():
    low = charts.heatmap_color(0, 0, 10)
    mid = charts.heatmap_color(5, 0, 10)
    high = charts.heatmap_color(10, 0, 10)
    # lightness should decrease (colors should get darker) as value increases
    def brightness(hex_color):
        r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
        return r + g + b
    assert brightness(low) > brightness(mid) > brightness(high)


def test_heatmap_color_handles_degenerate_range():
    # min == max shouldn't crash (division by zero guard)
    color = charts.heatmap_color(5, 5, 5)
    assert color.startswith("#")


def test_heatmap_text_color_picks_readable_contrast():
    assert charts.heatmap_text_color("#0d366b") == "#ffffff"  # dark bg -> white text
    assert charts.heatmap_text_color("#cde2fb") != "#ffffff"  # light bg -> dark text
