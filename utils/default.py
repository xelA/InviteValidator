from datetime import datetime, UTC


def utcnow() -> datetime:
    """ Returns the current time in UTC """
    return datetime.now(UTC)


def legacy_utcnow() -> datetime:
    """ Replicates the deprecated utcnow function """
    return utcnow().replace(tzinfo=None)
