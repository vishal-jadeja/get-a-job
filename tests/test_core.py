import base64
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from jobpilot.matching import match, contains
from jobpilot.materials import prepare
from jobpilot.roles import suggest_roles
from jobpilot.sources import normalize, clean_url, discover, plain
from jobpilot.store import Store, DEFAULT_PROFILE

PROFILE = {**DEFAULT_PROFILE, "name": "Example Candidate", "email": "example@example.com", "skills": ["Python", "SQL", "React"],
           "experience": ["Example Co | Developer | 2022–2024 — Built Python services and SQL reports."],
           "projects": ["Demo Project — Built a React dashboard."], "roles": ["Software Engineer"], "locations": ["India"], "years_experience": 2}
JOB = {"title": "Software Engineer", "company": "Example Co", "url": "https://jobs.lever.co/example/123/apply",
       "description": "Build Python and SQL services. React useful. Kubernetes required.", "source": "lever", "board": "example", "external_id": "123", "location": "India"}


class MatchingTests(unittest.TestCase):
    def test_runtime_role_suggestions(self):
        result = suggest_roles({**PROFILE, "roles": []})
        self.assertTrue(any(x["role"] == "Software Engineer" for x in result))
        self.assertEqual(suggest_roles(DEFAULT_PROFILE), [])

    def test_skill_gaps_explained_and_not_probability(self):
        result = match(JOB, PROFILE)
        self.assertEqual(result["qualification_percent"], 75)
        self.assertEqual(result["missing_skills"], ["kubernetes"])
        self.assertEqual(result["score"], 85)

    def test_remote_does_not_override_geography(self):
        result = match({**JOB, "location": "Remote — United States", "remote": True}, PROFILE)
        self.assertFalse(result["eligible"])
        self.assertTrue(result["warnings"])

    def test_company_and_phrase_filters(self):
        result = match(JOB, {**PROFILE, "excluded_companies": ["Example"], "required_keywords": ["rust"]})
        self.assertFalse(result["eligible"])
        self.assertEqual(len(result["blockers"]), 2)

    def test_old_posting_is_blocked(self):
        result = match({**JOB, "posted_at": (datetime.now(timezone.utc)-timedelta(days=90)).isoformat()}, PROFILE)
        self.assertFalse(result["eligible"])

    def test_word_boundaries(self):
        self.assertFalse(contains("reactive scripts", "react"))
        self.assertTrue(contains("C++ and C#", "C++"))

    def test_no_materials_claim_fabrication_and_html_escaped(self):
        p={**PROFILE, "name": "<script>alert(1)</script>"}
        materials=prepare(p, JOB)
        self.assertIn(PROFILE["experience"][0], materials["resume"])
        self.assertNotIn("Kubernetes", materials["resume"])
        self.assertNotIn("<script>", materials["resume_html"])
        self.assertIn(PROFILE["projects"][0], materials["resume"])

    def test_projects_only_candidate_can_prepare(self):
        self.assertTrue(prepare({**PROFILE,"experience":[]}, JOB))


class SourcesTests(unittest.TestCase):
    def test_greenhouse_decodes_html_without_fake_publication_date(self):
        jobs=normalize("greenhouse","example","Example",{"jobs":[{"id":1,"title":"Engineer","location":{"name":"India"},"absolute_url":JOB["url"],"content":"&lt;p&gt;Python &amp; SQL&lt;/p&gt;", "updated_at":"2026-09-25"}]})
        self.assertEqual(jobs[0]["description"],"Python & SQL")
        self.assertEqual(jobs[0]["posted_at"],"")

    def test_lever_pagination(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            return [{"id":str(i),"text":"Engineer","hostedUrl":f"https://jobs.lever.co/example/{i}","categories":{"location":"India"}} for i in range(100)] if len(calls)==1 else []
        self.assertEqual(len(discover({"kind":"lever","board":"example"},fetch)),100)
        self.assertIn("skip=100",calls[1])

    def test_ashby_unlisted_excluded(self):
        self.assertEqual(normalize("ashby","ex","Ex",{"jobs":[{"isListed":False}]}),[])

    def test_dedup_url_preserves_job_identity(self):
        self.assertEqual(clean_url("https://example.com/jobs?utm_source=x&gh_jid=123#apply"),"https://example.com/jobs?gh_jid=123")

    def test_url_rejects_unsafe_destinations(self):
        for url in ["javascript:alert(1)","http://example.com", "https://127.0.0.1/x", "https://localhost/x", "https://user:pw@example.com", "https://example.com:8888"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                clean_url(url)

    def test_no_script_content(self):
        self.assertEqual(plain("<script>bad()</script><p>Good</p>"),"Good")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(self.tmp.name)
        self.store.save_profile(PROFILE)
        self.store.upsert_jobs([JOB])
        self.jid=self.store.jobs()[0]["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def ready(self):
        self.store.action(self.jid,"prepare")
        self.store.action(self.jid,"approve")

    def test_import_duplicate_preserves_submitted_state(self):
        self.ready()
        self.store.action(self.jid,"submitted","Manual confirmation")
        self.assertEqual(self.store.upsert_jobs([{**JOB,"url":JOB["url"]+"?utm_source=test"}]),0)
        self.assertEqual(self.store.job(self.jid)["status"],"submitted")

    def test_cannot_approve_unprepared_or_submit_unapproved(self):
        for action in ["approve","claim","submitted","submitting"]:
            with self.assertRaises(ValueError):self.store.action(self.jid,action,"test")

    def test_profile_change_invalidates_approval(self):
        self.ready()
        self.store.save_profile({**PROFILE,"phone":"123"})
        self.assertEqual(self.store.job(self.jid)["status"],"discovered")
        with self.assertRaises(ValueError):self.store.action(self.jid,"claim")

    def test_resume_change_invalidates_approval(self):
        self.ready()
        self.store.save_resume("cv.txt",base64.b64encode(b"Evidence").decode())
        self.assertEqual(self.store.job(self.jid)["status"],"discovered")

    def test_posting_change_invalidates_approval(self):
        self.ready()
        self.store.upsert_jobs([{**JOB,"description":"A different role"}])
        self.assertEqual(self.store.job(self.jid)["status"],"discovered")

    def test_concurrent_claims_only_one_wins(self):
        self.ready()
        def claim():
            try:self.store.action(self.jid,"claim");return True
            except ValueError:return False
        with ThreadPoolExecutor(2) as pool:self.assertEqual(sum(pool.map(lambda _:claim(),range(2))),1)

    def test_uncertain_submission_never_retried(self):
        self.ready()
        self.store.action(self.jid,"claim")
        self.store.action(self.jid,"submitting")
        self.store.action(self.jid,"submission_unknown","No confirmation")
        for action in ["claim","approve","prepare"]:
            with self.assertRaises(ValueError):self.store.action(self.jid,action)
        self.assertIsNone(self.store.job(self.jid)["submitted_at"])

    def test_crash_recovery_distinguishes_before_and_after_submit(self):
        self.ready();self.store.action(self.jid,"claim");self.store.action(self.jid,"submitting")
        with self.store.db() as db:db.execute("UPDATE jobs SET lease_until='2000-01-01' WHERE id=?",(self.jid,))
        self.store.recover()
        self.assertEqual(self.store.job(self.jid)["status"],"submission_unknown")

    def test_submission_requires_confirmation_and_counts_once(self):
        self.ready()
        with self.assertRaises(ValueError):self.store.action(self.jid,"submitted","")
        self.store.action(self.jid,"submitted","Thank you for applying")
        with self.assertRaises(ValueError):self.store.action(self.jid,"submitted","duplicate")
        self.assertEqual(len([e for e in self.store.job(self.jid)["events"] if e["kind"]=="submitted"]),1)

    def test_import_is_atomic_for_bad_records(self):
        with self.assertRaises(ValueError):self.store.upsert_jobs([{**JOB,"external_id":"456","url":"https://example.com/456"},{"title":"Missing company"}])
        self.assertEqual(len(self.store.jobs()),1)

    def test_saved_empty_role_list_infers_at_runtime(self):
        result=self.store.save_profile({**PROFILE,"roles":[]})
        self.assertTrue(result["profile"]["roles"])


if __name__ == '__main__':unittest.main()
