from apwlib.models import OTPEntry, PasswordEntry


def test_password_entry_from_raw() -> None:
    entry = PasswordEntry._from_raw(
        {
            "USR": "me@example.com",
            "PWD": "hunter2",
            "sites": ["https://github.com", "https://github.io"],
            "customTitle": "GitHub",
            "highLevelDomain": "github.com",
        }
    )
    assert entry.username == "me@example.com"
    assert entry.domain == "https://github.com"
    assert entry.password == "hunter2"
    assert entry.title == "GitHub"
    assert entry.sites == ["https://github.com", "https://github.io"]


def test_password_not_included_becomes_none() -> None:
    entry = PasswordEntry._from_raw({"USR": "a", "PWD": "Not Included", "sites": ["x"]})
    assert entry.password is None


def test_otp_entry_from_raw() -> None:
    entry = OTPEntry._from_raw({"username": "me", "domain": "x.com", "code": "123456"})
    assert entry.username == "me"
    assert entry.code == "123456"
