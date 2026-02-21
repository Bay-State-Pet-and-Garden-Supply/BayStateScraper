from unittest.mock import MagicMock, patch

from core.api_client import ClaimedChunk, JobConfig, ScraperConfig
from runner.chunk_mode import run_chunk_worker_mode


def _make_job_config() -> JobConfig:
    return JobConfig(
        job_id="job-123",
        skus=["SKU-1", "SKU-2"],
        scrapers=[
            ScraperConfig(name="amazon"),
            ScraperConfig(name="target"),
        ],
        test_mode=False,
        max_workers=2,
    )


def test_chunk_worker_does_not_mutate_base_scraper_list_between_chunks() -> None:
    client = MagicMock()
    client.get_job_config.return_value = _make_job_config()
    client.claim_chunk.side_effect = [
        ClaimedChunk(
            chunk_id="chunk-1",
            job_id="job-123",
            chunk_index=0,
            skus=["SKU-1"],
            scrapers=["amazon"],
        ),
        ClaimedChunk(
            chunk_id="chunk-2",
            job_id="job-123",
            chunk_index=1,
            skus=["SKU-2"],
            scrapers=[],
        ),
        None,
    ]
    captured_scrapers: list[list[str]] = []

    def fake_run_job(job_config, runner_name=None, progress_callback=None):
        _ = runner_name, progress_callback
        captured_scrapers.append([s.name for s in job_config.scrapers])
        return {"data": {}, "skus_processed": len(job_config.skus)}

    with patch("runner.chunk_mode.run_job", side_effect=fake_run_job):
        run_chunk_worker_mode(client, "job-123", "runner-1")

    assert captured_scrapers == [["amazon"], ["amazon", "target"]]


def test_chunk_worker_fails_chunk_when_filter_resolves_to_zero_scrapers() -> None:
    client = MagicMock()
    client.get_job_config.return_value = _make_job_config()
    client.claim_chunk.side_effect = [
        ClaimedChunk(
            chunk_id="chunk-1",
            job_id="job-123",
            chunk_index=0,
            skus=["SKU-1"],
            scrapers=["does-not-exist"],
        ),
        None,
    ]

    with patch("runner.chunk_mode.run_job") as mocked_run_job:
        run_chunk_worker_mode(client, "job-123", "runner-1")

    mocked_run_job.assert_not_called()
    assert client.submit_chunk_results.call_count == 1
    args = client.submit_chunk_results.call_args.args
    assert args[0] == "chunk-1"
    assert args[1] == "failed"
    assert "resolved to zero scrapers" in str(client.submit_chunk_results.call_args.kwargs.get("error_message", ""))
