from sqlalchemy.orm import Session
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.indexing_job import IndexingJob


def test_user_model(db_session: Session):
    user = User(
        email="dev@acme.dev",
        full_name="Developer Alex",
        workspace_name="Engineering Core",
        avatar_initials="DA"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.id is not None
    assert user.email == "dev@acme.dev"
    assert user.is_active is True


def test_repository_and_job_relationship(db_session: Session):
    repo = Repository(
        name="billing-service",
        full_name="acme/billing-service",
        primary_language="Python",
        files_count=42,
        symbols_count=18
    )
    db_session.add(repo)
    db_session.commit()
    db_session.refresh(repo)

    job = IndexingJob(
        repository_id=repo.id,
        status="in_progress",
        progress_percent=50,
        files_processed=21,
        total_files=42
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    assert job.id is not None
    assert len(repo.indexing_jobs) == 1
    assert repo.indexing_jobs[0].progress_percent == 50

    # Test cascade delete
    db_session.delete(repo)
    db_session.commit()
    remaining_jobs = db_session.query(IndexingJob).filter(IndexingJob.id == job.id).all()
    assert len(remaining_jobs) == 0
