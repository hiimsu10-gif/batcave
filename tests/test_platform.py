from suprm import totp
from suprm.jobs import enqueue, handler, run_pending
from suprm.models import Job, JobStatus
from suprm.storage import LocalStorage


def test_totp_matches_rfc6238_vector():
    # RFC 6238 test secret "12345678901234567890" at T=59s -> 94287082 (last 6 digits)
    import base64

    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp.current_code(secret, at=59) == "287082"
    assert totp.verify(secret, "287082", at=59)
    assert totp.verify(secret, "287082", at=59 + 30)      # one step of clock drift is fine
    assert not totp.verify(secret, "287082", at=59 + 120)
    assert not totp.verify(secret, "abc")


def test_jobs_retry_then_fail(session):
    calls = []

    @handler("flaky")
    def _flaky(sess, payload):
        calls.append(payload)
        raise RuntimeError("store SFTP is down")

    job = enqueue(session, "flaky", {"n": 1})
    session.commit()
    assert run_pending(session) == 1
    session.refresh(job)
    assert job.status == JobStatus.queued and job.attempts == 1  # rescheduled with backoff
    job.run_after = job.created_at  # skip the wait
    job.max_attempts = 2
    session.commit()
    run_pending(session)
    session.refresh(job)
    assert job.status == JobStatus.failed and "SFTP is down" in job.last_error
    assert len(calls) == 2


def test_local_storage_blocks_path_escape(tmp_path):
    store = LocalStorage(tmp_path / "media")
    try:
        store.delete("../../etc/passwd")
    except ValueError:
        pass
    else:
        raise AssertionError("escape not blocked")
