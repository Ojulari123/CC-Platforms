"""The report domain: creation, the draft → submit → decide flow, the
append-only approval history, visibility rules, and comments.

Cast (all in department 1, team 3 unless noted):
- ENGINEER (10)      — writes reports, sees only their own
- ENGINEER_2 (11)    — a second engineer, to prove one can't see the other's
- LEAD (20)          — role manager AND the named lead of team 3 (leads=[3])
- MANAGER_NOLEAD (21)— role manager but leads no team: reads all, approves none
- DEPT_ADMIN (30)    — role admin: reads all, and can approve as the lead's cover
- OUTSIDER (40)      — belongs to a different department
- PLATFORM (99)      — platform admin: sees everything
"""
from datetime import date, timedelta

DEPT = 1
TEAM = 3

ENGINEER = dict(user_id=10, memberships=[{"dept_id": DEPT, "team_id": TEAM, "role": "engineer"}])
ENGINEER_2 = dict(user_id=11, memberships=[{"dept_id": DEPT, "team_id": TEAM, "role": "engineer"}])
LEAD = dict(user_id=20, memberships=[{"dept_id": DEPT, "team_id": TEAM, "role": "manager"}], leads=[TEAM])
MANAGER_NOLEAD = dict(user_id=21, memberships=[{"dept_id": DEPT, "team_id": None, "role": "manager"}])
DEPT_ADMIN = dict(user_id=30, memberships=[{"dept_id": DEPT, "team_id": None, "role": "admin"}])
OUTSIDER = dict(user_id=40, memberships=[{"dept_id": 2, "team_id": None, "role": "engineer"}])
PLATFORM = dict(user_id=99, memberships=[], is_platform_admin=True)


def _this_monday() -> date:
    t = date.today()
    return t - timedelta(days=t.weekday())


def _create(client, **body):
    body.setdefault("dept_id", DEPT)
    return client.post("/reports", json=body)


def _open_submitted(client, act_as):
    """Helper: engineer opens a report and submits it. Returns its id."""
    act_as(**ENGINEER)
    rid = _create(client).json()["id"]
    client.post(f"/reports/{rid}/submit")
    return rid


class TestCreate:
    def test_engineer_opens_a_draft(self, client, act_as):
        act_as(**ENGINEER)
        r = _create(client)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "draft"
        assert body["author_user_id"] == 10
        assert body["team_id"] == TEAM  # derived from the caller's membership
        assert body["week_start"] == _this_monday().isoformat()

    def test_non_member_cannot_create_in_the_department(self, client, act_as):
        act_as(**OUTSIDER)
        assert _create(client).status_code == 403

    def test_one_report_per_author_per_week(self, client, act_as):
        act_as(**ENGINEER)
        assert _create(client).status_code == 201
        assert _create(client).status_code == 409

    def test_week_start_is_normalised_to_its_monday(self, client, act_as):
        act_as(**ENGINEER)
        # 2026-07-22 is a Wednesday; its Monday is 2026-07-20.
        r = _create(client, week_start="2026-07-22")
        assert r.json()["week_start"] == "2026-07-20"

    def test_two_engineers_can_each_have_the_same_week(self, client, act_as):
        act_as(**ENGINEER)
        assert _create(client, week_start="2026-07-20").status_code == 201
        act_as(**ENGINEER_2)
        assert _create(client, week_start="2026-07-20").status_code == 201

    def test_requires_a_token(self, client):
        assert _create(client).status_code == 401


class TestVisibility:
    def _make_report(self, client, act_as):
        act_as(**ENGINEER)
        return _create(client).json()["id"]

    def test_author_reads_own(self, client, act_as):
        rid = self._make_report(client, act_as)
        act_as(**ENGINEER)
        assert client.get(f"/reports/{rid}").status_code == 200

    def test_other_engineer_is_forbidden(self, client, act_as):
        rid = self._make_report(client, act_as)
        act_as(**ENGINEER_2)
        assert client.get(f"/reports/{rid}").status_code == 403

    def test_team_lead_can_read(self, client, act_as):
        rid = self._make_report(client, act_as)
        act_as(**LEAD)
        assert client.get(f"/reports/{rid}").status_code == 200

    def test_manager_without_a_team_can_read_department_wide(self, client, act_as):
        rid = self._make_report(client, act_as)
        act_as(**MANAGER_NOLEAD)
        assert client.get(f"/reports/{rid}").status_code == 200

    def test_department_admin_can_read(self, client, act_as):
        rid = self._make_report(client, act_as)
        act_as(**DEPT_ADMIN)
        assert client.get(f"/reports/{rid}").status_code == 200

    def test_outsider_forbidden(self, client, act_as):
        rid = self._make_report(client, act_as)
        act_as(**OUTSIDER)
        assert client.get(f"/reports/{rid}").status_code == 403

    def test_platform_admin_can_read(self, client, act_as):
        rid = self._make_report(client, act_as)
        act_as(**PLATFORM)
        assert client.get(f"/reports/{rid}").status_code == 200

    def test_missing_report_is_404(self, client, act_as):
        act_as(**DEPT_ADMIN)
        assert client.get("/reports/9999").status_code == 404


class TestList:
    def _seed_two_authors(self, client, act_as):
        act_as(**ENGINEER)
        _create(client, week_start="2026-07-20")
        act_as(**ENGINEER_2)
        _create(client, week_start="2026-07-20")

    def test_engineer_sees_only_their_own(self, client, act_as):
        self._seed_two_authors(client, act_as)
        act_as(**ENGINEER)
        body = client.get(f"/reports?dept_id={DEPT}").json()
        assert body["total"] == 1
        assert body["items"][0]["author_user_id"] == 10

    def test_manager_sees_the_whole_department(self, client, act_as):
        self._seed_two_authors(client, act_as)
        act_as(**LEAD)
        assert client.get(f"/reports?dept_id={DEPT}").json()["total"] == 2

    def test_listing_requires_membership(self, client, act_as):
        self._seed_two_authors(client, act_as)
        act_as(**OUTSIDER)
        assert client.get(f"/reports?dept_id={DEPT}").status_code == 403

    def test_filter_by_status(self, client, act_as):
        _open_submitted(client, act_as)  # engineer 10: submitted
        act_as(**ENGINEER_2)
        _create(client, week_start="2026-07-20")  # engineer 11: draft
        act_as(**LEAD)
        submitted = client.get(f"/reports?dept_id={DEPT}&status=submitted").json()
        assert submitted["total"] == 1
        assert submitted["items"][0]["status"] == "submitted"

    def test_pagination_windows_results(self, client, act_as):
        act_as(**ENGINEER)
        for wk in ("2026-07-06", "2026-07-13", "2026-07-20"):
            _create(client, week_start=wk)
        page = client.get(f"/reports?dept_id={DEPT}&limit=2").json()
        assert page["total"] == 3
        assert len(page["items"]) == 2
        assert page["limit"] == 2


class TestWorkflow:
    def test_author_submits_and_history_records_it(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]
        r = client.post(f"/reports/{rid}/submit")
        assert r.status_code == 200 and r.json()["status"] == "submitted"
        history = client.get(f"/reports/{rid}/approvals").json()["items"]
        assert [h["action"] for h in history] == ["submitted"]

    def test_non_author_cannot_submit(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]
        act_as(**LEAD)
        assert client.post(f"/reports/{rid}/submit").status_code == 403

    def test_team_lead_approves(self, client, act_as):
        rid = _open_submitted(client, act_as)
        act_as(**LEAD)
        r = client.post(f"/reports/{rid}/approve")
        assert r.status_code == 200 and r.json()["status"] == "approved"
        assert [h["action"] for h in client.get(f"/reports/{rid}/approvals").json()["items"]] == ["submitted", "approved"]

    def test_manager_without_the_team_cannot_approve(self, client, act_as):
        # The heart of Decision 6: the manager ROLE reads everything but does not
        # approve — only the NAMED team lead (or an admin) does.
        rid = _open_submitted(client, act_as)
        act_as(**MANAGER_NOLEAD)
        assert client.post(f"/reports/{rid}/approve").status_code == 403

    def test_department_admin_can_approve_as_cover(self, client, act_as):
        rid = _open_submitted(client, act_as)
        act_as(**DEPT_ADMIN)
        assert client.post(f"/reports/{rid}/approve").status_code == 200

    def test_cannot_approve_a_report_that_was_never_submitted(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]  # still a draft
        act_as(**LEAD)
        assert client.post(f"/reports/{rid}/approve").status_code == 409

    def test_reject_records_a_note(self, client, act_as):
        rid = _open_submitted(client, act_as)
        act_as(**LEAD)
        r = client.post(f"/reports/{rid}/reject", json={"note": "needs more detail"})
        assert r.status_code == 200 and r.json()["status"] == "rejected"
        last = client.get(f"/reports/{rid}/approvals").json()["items"][-1]
        assert last["action"] == "rejected" and last["note"] == "needs more detail"

    def test_request_changes_then_edit_and_resubmit(self, client, act_as):
        rid = _open_submitted(client, act_as)
        act_as(**LEAD)
        assert client.post(f"/reports/{rid}/request-changes").json()["status"] == "changes_requested"
        act_as(**ENGINEER)
        assert client.patch(f"/reports/{rid}", json={"summary_manager": "v2"}).status_code == 200
        assert client.post(f"/reports/{rid}/submit").json()["status"] == "submitted"
        actions = [h["action"] for h in client.get(f"/reports/{rid}/approvals").json()["items"]]
        assert actions == ["submitted", "changes_requested", "submitted"]


class TestEdit:
    def test_author_edits_a_draft(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]
        r = client.patch(f"/reports/{rid}", json={"summary_manager": "shipped the thing"})
        assert r.status_code == 200 and r.json()["summary_manager"] == "shipped the thing"

    def test_a_submitted_report_is_locked(self, client, act_as):
        rid = _open_submitted(client, act_as)
        act_as(**ENGINEER)
        assert client.patch(f"/reports/{rid}", json={"summary_manager": "x"}).status_code == 409

    def test_only_the_author_may_edit(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]
        act_as(**LEAD)
        assert client.patch(f"/reports/{rid}", json={"summary_manager": "x"}).status_code == 403


class TestComments:
    def test_a_reader_can_comment(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]
        act_as(**LEAD)
        assert client.post(f"/reports/{rid}/comments", json={"body": "nice work"}).status_code == 201
        comments = client.get(f"/reports/{rid}/comments").json()["items"]
        assert len(comments) == 1
        assert comments[0]["author_user_id"] == 20 and comments[0]["body"] == "nice work"

    def test_a_non_reader_cannot_comment(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]
        act_as(**OUTSIDER)
        assert client.post(f"/reports/{rid}/comments", json={"body": "hi"}).status_code == 403

    def test_empty_comment_is_rejected(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]
        assert client.post(f"/reports/{rid}/comments", json={"body": ""}).status_code == 422


class TestReportDelete:
    def test_author_deletes_own_draft(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]
        assert client.delete(f"/reports/{rid}").status_code == 204
        act_as(**ENGINEER)
        assert client.get(f"/reports/{rid}").status_code == 404

    def test_a_submitted_report_can_never_be_deleted_by_anyone(self, client, act_as):
        # Transparency: once it's been seen, the record stands — author, lead,
        # department admin and platform admin all get refused.
        rid = _open_submitted(client, act_as)  # engineer's report, submitted
        for who in (ENGINEER, LEAD, DEPT_ADMIN, PLATFORM):
            act_as(**who)
            assert client.delete(f"/reports/{rid}").status_code == 409, who

    def test_admins_cannot_delete_someone_elses_draft(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]
        for who in (DEPT_ADMIN, PLATFORM, ENGINEER_2):
            act_as(**who)
            assert client.delete(f"/reports/{rid}").status_code == 403, who

    def test_deleting_a_draft_takes_its_comments_with_it(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]
        client.post(f"/reports/{rid}/comments", json={"body": "wip note"})
        assert client.delete(f"/reports/{rid}").status_code == 204
        act_as(**ENGINEER)
        assert client.get(f"/reports/{rid}").status_code == 404
        assert client.get(f"/reports/{rid}/comments").status_code == 404


class TestCommentEditDelete:
    def _make_comment(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]
        cid = client.post(f"/reports/{rid}/comments", json={"body": "first"}).json()["id"]
        return rid, cid

    def test_author_edits_own_comment_and_edited_at_is_stamped(self, client, act_as):
        rid, cid = self._make_comment(client, act_as)
        act_as(**ENGINEER)
        r = client.patch(f"/reports/{rid}/comments/{cid}", json={"body": "revised"})
        assert r.status_code == 200
        assert r.json()["body"] == "revised"
        assert r.json()["edited_at"] is not None  # was null before the edit

    def test_non_author_cannot_edit(self, client, act_as):
        rid, cid = self._make_comment(client, act_as)
        act_as(**LEAD)  # can read the report, but it's not their comment
        assert client.patch(f"/reports/{rid}/comments/{cid}", json={"body": "x"}).status_code == 403

    def test_author_deletes_own_comment(self, client, act_as):
        rid, cid = self._make_comment(client, act_as)
        act_as(**ENGINEER)
        assert client.delete(f"/reports/{rid}/comments/{cid}").status_code == 204
        assert client.get(f"/reports/{rid}/comments").json()["total"] == 0

    def test_non_author_cannot_delete(self, client, act_as):
        rid, cid = self._make_comment(client, act_as)
        act_as(**LEAD)
        assert client.delete(f"/reports/{rid}/comments/{cid}").status_code == 403

    def test_comment_must_belong_to_the_report_in_the_path(self, client, act_as):
        rid, cid = self._make_comment(client, act_as)
        act_as(**ENGINEER)
        other = _create(client, week_start="2026-06-01").json()["id"]  # a different report
        assert client.patch(f"/reports/{other}/comments/{cid}", json={"body": "x"}).status_code == 404


class TestListsArePaginated:
    def test_comments_paginate(self, client, act_as):
        act_as(**ENGINEER)
        rid = _create(client).json()["id"]
        for i in range(3):
            client.post(f"/reports/{rid}/comments", json={"body": f"c{i}"})
        page = client.get(f"/reports/{rid}/comments?limit=2").json()
        assert page["total"] == 3
        assert len(page["items"]) == 2
        assert page["limit"] == 2

    def test_approvals_paginate(self, client, act_as):
        rid = _open_submitted(client, act_as)          # approval 1: submitted
        act_as(**LEAD)
        client.post(f"/reports/{rid}/request-changes")  # approval 2
        act_as(**ENGINEER)
        client.post(f"/reports/{rid}/submit")           # approval 3
        page = client.get(f"/reports/{rid}/approvals?limit=2").json()
        assert page["total"] == 3
        assert len(page["items"]) == 2


class TestStatusFilterValidation:
    def test_unknown_status_value_is_rejected(self, client, act_as):
        act_as(**ENGINEER)
        assert client.get(f"/reports?dept_id={DEPT}&status=aproved").status_code == 422

    def test_valid_status_value_is_accepted(self, client, act_as):
        act_as(**ENGINEER)
        assert client.get(f"/reports?dept_id={DEPT}&status=draft").status_code == 200
