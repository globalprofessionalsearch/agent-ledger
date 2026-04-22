from ledger.activity import bucket_size_minutes, build_buckets, _find_natural_breaks

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

def _insert_user_msg(conn, ts, session_id="sess-1", is_sidechain=0):
    conn.execute("""
        INSERT INTO messages(session_id, role, subtype, timestamp, date, hour, is_sidechain)
        VALUES (?, 'user', 'human', ?, '2026-04-21', 14, ?)
    """, [session_id, ts, is_sidechain])
    conn.commit()

def test_build_buckets_empty_range(conn):
    result = build_buckets(conn, "2026-04-21T14:00:00Z", "2026-04-21T15:00:00Z", None, 15)
    assert len(result) == 4  # four 15-min buckets
    assert all(b["count"] == 0 for b in result)

def test_build_buckets_counts_user_messages(conn):
    _insert_user_msg(conn, "2026-04-21T14:05:00Z")
    _insert_user_msg(conn, "2026-04-21T14:07:00Z")
    _insert_user_msg(conn, "2026-04-21T14:32:00Z")
    result = build_buckets(conn, "2026-04-21T14:00:00Z", "2026-04-21T15:00:00Z", None, 15)
    assert result[0]["count"] == 2   # 14:00–14:15
    assert result[1]["count"] == 0   # 14:15–14:30
    assert result[2]["count"] == 1   # 14:30–14:45
    assert result[3]["count"] == 0   # 14:45–15:00

def test_build_buckets_excludes_sidechains(conn):
    _insert_user_msg(conn, "2026-04-21T14:05:00Z", is_sidechain=1)
    result = build_buckets(conn, "2026-04-21T14:00:00Z", "2026-04-21T15:00:00Z", None, 15)
    assert all(b["count"] == 0 for b in result)

def test_build_buckets_excludes_non_user_roles(conn):
    conn.execute("""
        INSERT INTO messages(session_id, role, subtype, timestamp, date, hour, is_sidechain)
        VALUES ('sess-1', 'assistant', 'text', '2026-04-21T14:05:00Z', '2026-04-21', 14, 0)
    """)
    conn.commit()
    result = build_buckets(conn, "2026-04-21T14:00:00Z", "2026-04-21T15:00:00Z", None, 15)
    assert all(b["count"] == 0 for b in result)

def test_build_buckets_filters_by_project(conn):
    conn.execute("INSERT INTO sessions(session_id, project) VALUES ('sess-other', 'other')")
    conn.commit()
    conn.execute("""
        INSERT INTO messages(session_id, role, subtype, timestamp, date, hour, is_sidechain)
        VALUES ('sess-other', 'user', 'human', '2026-04-21T14:05:00Z', '2026-04-21', 14, 0)
    """)
    conn.commit()
    result = build_buckets(conn, "2026-04-21T14:00:00Z", "2026-04-21T15:00:00Z", "test-project", 15)
    assert all(b["count"] == 0 for b in result)

def test_build_buckets_start_end_format(conn):
    result = build_buckets(conn, "2026-04-21T14:00:00Z", "2026-04-21T15:00:00Z", None, 15)
    assert result[0]["start"] == "2026-04-21T14:00:00Z"
    assert result[0]["end"]   == "2026-04-21T14:15:00Z"
    assert result[3]["start"] == "2026-04-21T14:45:00Z"
    assert result[3]["end"]   == "2026-04-21T15:00:00Z"


def test_natural_breaks_empty():
    assert _find_natural_breaks([]) == []

def test_natural_breaks_single_value():
    assert _find_natural_breaks([5]) == []

def test_natural_breaks_all_same():
    # No gap larger than median — no breaks
    assert _find_natural_breaks([3, 3, 3, 3]) == []

def test_natural_breaks_one_clear_gap():
    # Counts: [1, 1, 10, 11] — big gap between 1 and 10
    # gaps: [0, 9, 1] — median = 1, significant: [9] at index 1
    # break at sorted_counts[1] = 1
    breaks = _find_natural_breaks([1, 1, 10, 11])
    assert len(breaks) == 1
    assert breaks[0] == 1

def test_natural_breaks_two_clear_gaps():
    # Counts: [1, 2, 10, 11, 50, 51]
    # gaps: [1, 8, 1, 39, 1] — median = 1, significant: [8, 39]
    # breaks at sorted_counts[1]=2 and sorted_counts[3]=11
    breaks = _find_natural_breaks([1, 2, 10, 11, 50, 51])
    assert len(breaks) == 2
    assert breaks == [2, 11]

def test_natural_breaks_caps_at_two():
    # Even with three clear gaps, returns at most 2 breaks (the two largest)
    breaks = _find_natural_breaks([1, 10, 20, 30, 100])
    assert len(breaks) <= 2
