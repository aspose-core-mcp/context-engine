from adcs.worker.celery_app import create_celery_app


def test_worker_bootstrap_default_settings() -> None:
    app = create_celery_app()

    assert app.main == "adcs-worker"
    assert app.conf.task_default_queue == "adcs.default"
    assert app.conf.task_routes["adcs.source_sync.execute"]["queue"] == "adcs.source-sync"
    assert app.conf.task_routes["adcs.layout_detection.execute"]["queue"] == (
        "adcs.layout-detection"
    )
    assert app.conf.task_routes["adcs.ingestion.execute"]["queue"] == "adcs.ingestion"


def test_worker_consumes_every_routed_queue_by_default() -> None:
    app = create_celery_app()

    consumed = {queue.name for queue in app.conf.task_queues}
    routed = {route["queue"] for route in app.conf.task_routes.values()}
    assert routed | {app.conf.task_default_queue} <= consumed
