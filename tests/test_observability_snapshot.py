from app.services.observability import ObservabilityDashboard


class _Store:
    def recent_query_logs(self, limit=200):
        return [{"confidence": 0.2, "abstained": True, "latency_ms": {"total": 123}, "citations": []}]

    def table_names(self):
        return ["users", "workspaces"]


class _Broken:
    def status(self):
        return {"status": "error", "detail": "down"}


def test_observability_snapshot_reports_degraded_components():
    snapshot = ObservabilityDashboard(_Store(), redis_service=_Broken(), graph_repository=_Broken()).snapshot()

    assert snapshot["quality"]["failure_rate"] == 1.0
    assert snapshot["components"]["redis"]["status"] == "error"
    assert snapshot["components"]["graph_db"]["status"] == "error"
