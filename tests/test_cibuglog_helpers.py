import unittest

import cibuglog_gui as gui


class TestCIBugLogHelpers(unittest.TestCase):
    def test_classify_status(self):
        self.assertEqual(gui.classify_status("PASS"), "pass")
        self.assertEqual(gui.classify_status("skip ( external URL )"), "skip")
        self.assertEqual(gui.classify_status("dmesg-fail"), "dmesg")
        self.assertEqual(gui.classify_status("notrun"), "incomplete")

    def test_clean_cell_removes_external_url_and_igt_prefix(self):
        text = "IGT: foo   skip (external URL)"
        self.assertEqual(gui.clean_cell(text), "foo skip")

    def test_external_link_marker(self):
        self.assertTrue(gui._is_external_link_marker("external URL"))
        self.assertTrue(gui._is_external_link_marker("(External   Url)"))
        self.assertFalse(gui._is_external_link_marker("internal link"))

    def test_normalize_result_url(self):
        jira_base = "https://jira.devtools.intel.com"
        cib_base = "https://gfx-ci-internal.igk.intel.com"

        self.assertEqual(
            gui._normalize_result_url("/browse/VLK-1", jira_base, cib_base),
            "https://jira.devtools.intel.com/browse/VLK-1",
        )
        self.assertEqual(
            gui._normalize_result_url("/tree/xe/xe-1/m/t.html", jira_base, cib_base),
            "https://gfx-ci-internal.igk.intel.com/tree/xe/xe-1/m/t.html",
        )
        self.assertEqual(
            gui._normalize_result_url("//example.com/a", jira_base, cib_base),
            "https://example.com/a",
        )

    def test_looks_like_tree_url(self):
        self.assertTrue(gui._looks_like_tree_url("/tree/xe/xe-1"))
        self.assertTrue(gui._looks_like_tree_url("https://host/tree/xe/xe-1/x"))
        self.assertFalse(gui._looks_like_tree_url("https://host/results/all"))

    def test_build_tree_url_from_row(self):
        url = gui._build_tree_url_from_row(
            test_name="igt@xe_eudebug_online@pagefault-one-of-many",
            machine_name="hwre-NVL_P-061",
            build_text="xe-1181-nvl-resume (1 day old)",
            cibuglog_origin="https://gfx-ci-internal.igk.intel.com",
        )
        self.assertEqual(
            url,
            "https://gfx-ci-internal.igk.intel.com/tree/xe/xe-1181/"
            "hwre-NVL_P-061/igt@xe_eudebug_online@pagefault-one-of-many.html",
        )

    def test_build_tree_url_from_row_returns_empty_when_build_id_missing(self):
        self.assertEqual(
            gui._build_tree_url_from_row(
                test_name="igt@test",
                machine_name="machine",
                build_text="nightly-build",
                cibuglog_origin="https://gfx-ci-internal.igk.intel.com",
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()
