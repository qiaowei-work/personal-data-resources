import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import dedupe  # noqa: E402
import feishu  # noqa: E402
import normalize  # noqa: E402
from store import Store  # noqa: E402


def job(**kwargs):
    base = {
        "company": "万华化学集团股份有限公司",
        "title": "2027届校园招聘-工艺工程师",
        "city": "四川省 - 成都市",
        "education": "硕士",
        "majors": "化学工程与技术",
        "description": "2027届硕士，化学工程与技术，工作地点成都。",
        "grad_year": 2027,
        "job_type": "校招",
        "source": "scbdc",
        "source_type": "official_platform",
        "source_job_id": "1001",
        "url": "https://example.com/job/1001",
    }
    base.update(kwargs)
    return normalize.prepare_job(base, normalize.DEFAULT_CONFIG)


class TestNormalize(unittest.TestCase):
    def test_company_suffix(self):
        self.assertEqual(dedupe.normalize_company_name("万华化学集团股份有限公司"), "万华化学")
        self.assertEqual(dedupe.normalize_company_name("中国石油化工股份有限公司"), "中国石油化工")

    def test_company_alias(self):
        resolver = dedupe.CompanyResolver(
            os.path.join(HERE, "..", "data", "company_aliases.json")
        )
        a, _ = resolver.resolve("中石化")
        b, _ = resolver.resolve("中国石油化工集团有限公司")
        self.assertEqual(a, b)

    def test_title(self):
        self.assertEqual(dedupe.normalize_title("【秋招】2027届-工艺工程师（成都）"), "工艺工程师")
        self.assertEqual(dedupe.normalize_title("工艺工程师（校招）"), "工艺工程师")

    def test_city(self):
        self.assertEqual(normalize.normalize_city("四川省 - 成都市"), "成都")
        self.assertEqual(normalize.normalize_city("南京市"), "南京")

    def test_grad_year(self):
        self.assertEqual(normalize.infer_grad_year("2027届校园招聘"), 2027)
        self.assertEqual(normalize.infer_grad_year("2026届毕业生"), 2026)
        self.assertIsNone(normalize.infer_grad_year("社会招聘"))

    def test_job_type(self):
        self.assertEqual(normalize.infer_job_type("2027届校招", "", "全职"), "校招")
        self.assertEqual(normalize.infer_job_type("日常实习", "", "实习"), "实习")
        self.assertEqual(normalize.infer_job_type("社会招聘", "", "全职"), "社招")


class TestGates(unittest.TestCase):
    def test_actionable(self):
        j = job()
        self.assertEqual(j["recommendation"], "可投")
        self.assertTrue(j["base_hit"])

    def test_2026_excluded(self):
        j = job(title="2026届工艺工程师", description="2026届本科，化学工程")
        j["grad_year"] = 2026
        # prepare_job 已经根据新标题重算，单独构造验证硬门槛
        raw = {
            "company": "某化工公司", "title": "2026届工艺工程师",
            "city": "成都", "education": "硕士", "majors": "化学工程",
            "description": "2026届", "grad_year": 2026, "job_type": "校招",
            "source": "scbdc", "source_job_id": "x", "url": "",
        }
        out = normalize.prepare_job(raw, normalize.DEFAULT_CONFIG)
        self.assertEqual(out["recommendation"], "不推荐")

    def test_internship_excluded(self):
        raw = {
            "company": "某化工公司", "title": "工艺实习生",
            "city": "成都", "education": "硕士", "majors": "化学工程",
            "description": "2027届日常实习", "job_type": "实习",
            "source": "scbdc", "source_job_id": "x", "url": "",
        }
        out = normalize.prepare_job(raw, normalize.DEFAULT_CONFIG)
        self.assertEqual(out["recommendation"], "不推荐")

    def test_remote(self):
        raw = {
            "company": "某化工公司", "title": "2027届工艺工程师",
            "city": "宁波", "education": "硕士", "majors": "化学工程",
            "description": "2027届", "job_type": "校招",
            "source": "scbdc", "source_job_id": "x", "url": "",
        }
        out = normalize.prepare_job(raw, normalize.DEFAULT_CONFIG)
        self.assertEqual(out["recommendation"], "异地")

    def test_unknown_major(self):
        raw = {
            "company": "某化工公司", "title": "2027届管培生",
            "city": "成都", "education": "硕士", "majors": "",
            "description": "2027届，专业不限", "job_type": "校招",
            "source": "scbdc", "source_job_id": "x", "url": "",
        }
        out = normalize.prepare_job(raw, normalize.DEFAULT_CONFIG)
        self.assertEqual(out["recommendation"], "可投")

    def test_announcement_not_actionable(self):
        raw = {
            "company": "某汽车公司", "title": "2027届校园招聘",
            "city": "成都", "education": "硕士", "majors": "不限专业",
            "description": "2027届校园招聘，含研发、销售等岗位", "job_type": "校招",
            "source": "scbdc", "source_job_id": "x", "url": "",
        }
        out = normalize.prepare_job(raw, normalize.DEFAULT_CONFIG)
        self.assertEqual(out["recommendation"], "待核实")

    def test_bank_announcement_excluded(self):
        raw = {
            "company": "华夏银行股份有限公司成都分行", "title": "2027届秋季校园招聘",
            "city": "成都", "education": "本科", "majors": "不限专业",
            "description": "2027届校园招聘", "job_type": "校招",
            "source": "scbdc", "source_job_id": "x", "url": "",
        }
        out = normalize.prepare_job(raw, normalize.DEFAULT_CONFIG)
        self.assertEqual(out["recommendation"], "不推荐")


class TestFeishuCompanyPayload(unittest.TestCase):
    def test_one_row_per_company_no_title(self):
        jobs = [
            {
                "company_name": "宁德时代", "company_type": "民营企业",
                "recommendation": "可投", "city": "南京", "reasons": ["专业命中"],
                "source": "ats", "verification_status": "employer_verified",
                "source_job_id": "a1", "url": "https://example.com/a",
                "deadline": "2026-12-31",
            },
            {
                "company_name": "宁德时代", "company_type": "民营企业",
                "recommendation": "异地", "city": "厦门", "reasons": ["异地"],
                "source": "ats", "verification_status": "employer_verified",
                "source_job_id": "a2", "url": "https://example.com/a",
                "deadline": "2026-11-30",
            },
        ]
        payload = feishu._company_payload(jobs)
        self.assertNotIn("岗位名称", payload)
        self.assertEqual(payload["公司"], "宁德时代")
        self.assertEqual(payload["优先级"], ["首选"])
        self.assertIn("南京", payload["城市"])
        self.assertIn("其他", payload["城市"])
        self.assertIn("2 个岗位", payload["备注"])
        self.assertEqual(payload["截止日期"], "2026-11-30")

    def test_all_non_target_skipped(self):
        jobs = [{"company_name": "某银行", "recommendation": "不推荐"}]
        self.assertEqual(feishu._company_payload(jobs), {})


class TestStoreDedupe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "radar.db"),
                           alias_path=os.path.join(HERE, "..", "data", "company_aliases.json"))

    def tearDown(self):
        self.store.close()

    def test_cross_source_merge(self):
        a = job(source="scbdc", source_job_id="1001")
        id1, new1, _ = self.store.upsert_job(a, "2026-10-21")
        self.assertTrue(new1)

        b = job(company="万华化学", title="工艺工程师",
                city="成都", source="sicau", source_job_id="r-1",
                url="https://example.com/sicau/r-1")
        id2, new2, merged2 = self.store.upsert_job(b, "2026-10-21")
        self.assertFalse(new2)
        self.assertEqual(id1, id2)
        self.assertTrue(merged2)
        row = self.store.list_jobs()[0]
        self.assertEqual(len(row["sources"]), 2)

    def test_different_city_not_merged(self):
        a = job(source="scbdc", source_job_id="1001")
        id1, _, _ = self.store.upsert_job(a, "2026-10-21")
        b = job(city="宁波", source="scbdc", source_job_id="1002")
        id2, new2, _ = self.store.upsert_job(b, "2026-10-21")
        self.assertTrue(new2)
        self.assertNotEqual(id1, id2)

    def test_different_title_not_merged(self):
        a = job(source="scbdc", source_job_id="1001")
        id1, _, _ = self.store.upsert_job(a, "2026-10-21")
        b = job(title="2027届校园招聘-研发工程师", source="scbdc", source_job_id="1002")
        id2, new2, _ = self.store.upsert_job(b, "2026-10-21")
        self.assertTrue(new2)
        self.assertNotEqual(id1, id2)

    def test_repeat_run_not_new(self):
        a = job(source="scbdc", source_job_id="1001")
        id1, new1, _ = self.store.upsert_job(a, "2026-10-21")
        id2, new2, _ = self.store.upsert_job(a, "2026-10-22")
        self.assertTrue(new1)
        self.assertFalse(new2)
        self.assertEqual(id1, id2)
        self.assertEqual(len(self.store.list_jobs()), 1)

    def test_empty_city_merges(self):
        a = job(source="scbdc", source_job_id="1001")
        id1, _, _ = self.store.upsert_job(a, "2026-10-21")
        b = job(city="", source="sicau", source_job_id="r-2")
        id2, new2, merged2 = self.store.upsert_job(b, "2026-10-21")
        self.assertFalse(new2)
        self.assertTrue(merged2)
        self.assertEqual(id1, id2)


if __name__ == "__main__":
    unittest.main()
