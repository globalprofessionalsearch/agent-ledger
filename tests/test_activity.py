from ledger.activity import bucket_size_minutes

def test_bucket_size_over_7_days():
    assert bucket_size_minutes(8 * 24 * 60 * 60) == 1440

def test_bucket_size_7_days_exact():
    assert bucket_size_minutes(7 * 24 * 60 * 60) == 1440

def test_bucket_size_3_days():
    assert bucket_size_minutes(3 * 24 * 60 * 60) == 60

def test_bucket_size_1_day_exact():
    assert bucket_size_minutes(24 * 60 * 60) == 60

def test_bucket_size_12_hours():
    assert bucket_size_minutes(12 * 60 * 60) == 15

def test_bucket_size_1_hour_exact():
    assert bucket_size_minutes(60 * 60) == 15

def test_bucket_size_30_minutes():
    assert bucket_size_minutes(30 * 60) == 5

def test_bucket_size_under_1_hour():
    assert bucket_size_minutes(59 * 60) == 5
