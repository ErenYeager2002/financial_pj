from pathlib import Path

from app import workflow_service


def test_fetched_data_preview_keeps_delivery_amount_local(monkeypatch, tmp_path: Path):
    for prefix in ("回款记录", "订单交付", "核销明细", "订单明细"):
        (tmp_path / f"{prefix}_20260902.xlsx").write_bytes(b"fixture")

    def records(path: Path):
        if path.name.startswith("回款记录"):
            return [{"回款记录ID": "AR26090004"}]
        if path.name.startswith("订单交付"):
            return [{
                "回款记录ID": "AR26090004",
                "SO": "SO26060803",
                "交付额/原币": 8844.0,
                "交付额/本币": 63605.16,
            }]
        return []

    monkeypatch.setattr(workflow_service, "_preview_workbook_records", records)

    groups = workflow_service._fetched_ar_groups(tmp_path, "2026-09-02")

    delivery = groups[0].orders[0].deliveries[0]
    assert delivery.delivery_amount_original == 8844.0
    assert delivery.delivery_amount_local == 63605.16
