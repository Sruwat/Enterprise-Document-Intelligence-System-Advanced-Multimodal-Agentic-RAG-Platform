from app.services.worker import AiwanaWorker, WorkerQueue


def test_worker_queue_local_fallback_and_heartbeat():
    queue = WorkerQueue(redis_service=None)
    job = queue.enqueue("embedding", {"source_path": "missing.pdf"}, job_id="job-1")
    assert job.job_id == "job-1"
    assert queue.status()["queued"] == 1

    worker = AiwanaWorker(queue=queue)
    result = worker.process_one()

    assert result["status"] == "processed"
    assert result["result"]["skipped"] is True
    assert worker.heartbeat()["status"] == "ok"


def test_worker_retries_unknown_job_type():
    queue = WorkerQueue(redis_service=None)
    queue.enqueue("unknown", {}, job_id="job-bad", max_attempts=2)
    worker = AiwanaWorker(queue=queue)

    first = worker.process_one()

    assert first["status"] == "retrying"
    assert queue.status()["queued"] == 1
