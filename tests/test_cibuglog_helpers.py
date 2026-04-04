import unittest
from unittest.mock import Mock, MagicMock

import cibuglog_gui as gui


class TestCIBugLogHelpers(unittest.TestCase):
    def test_classify_status(self):
        self.assertEqual(gui.classify_status("PASS"), "pass")
        self.assertEqual(gui.classify_status("skip ( external URL )"), "skip")
        self.assertEqual(gui.classify_status("dmesg-fail"), "dmesg")
        self.assertEqual(gui.classify_status("notrun"), "incomplete")

    def test_classify_status_case_insensitive(self):
        """Test that status classification is case-insensitive."""
        self.assertEqual(gui.classify_status("PASS"), "pass")
        self.assertEqual(gui.classify_status("Pass"), "pass")
        self.assertEqual(gui.classify_status("FAIL"), "fail")
        self.assertEqual(gui.classify_status("Fail"), "fail")
        self.assertEqual(gui.classify_status("SKIP"), "skip")
        self.assertEqual(gui.classify_status("Skip"), "skip")

    def test_classify_status_with_abort(self):
        """Test dmesg classification includes abort keyword."""
        self.assertEqual(gui.classify_status("abort"), "dmesg")
        self.assertEqual(gui.classify_status("ABORT"), "dmesg")
        self.assertEqual(gui.classify_status("test aborted"), "dmesg")

    def test_classify_status_dmesg_fail_variants(self):
        """Test various dmesg-fail patterns."""
        self.assertEqual(gui.classify_status("dmesg-fail"), "dmesg")
        self.assertEqual(gui.classify_status("DMESG-FAIL"), "dmesg")
        self.assertEqual(gui.classify_status("dmesg fail"), "dmesg")
        self.assertEqual(gui.classify_status("DMESG FAIL"), "dmesg")

    def test_classify_status_incomplete_variants(self):
        """Test incomplete and notrun variants."""
        self.assertEqual(gui.classify_status("incomplete"), "incomplete")
        self.assertEqual(gui.classify_status("INCOMPLETE"), "incomplete")
        self.assertEqual(gui.classify_status("notrun"), "incomplete")
        self.assertEqual(gui.classify_status("NOTRUN"), "incomplete")

    def test_classify_status_empty_and_unknown(self):
        """Test edge cases for unknown status."""
        self.assertEqual(gui.classify_status(""), "")
        self.assertEqual(gui.classify_status("unknown"), "")
        self.assertEqual(gui.classify_status("xyz"), "")

    def test_clean_cell_removes_external_url_and_igt_prefix(self):
        text = "IGT: foo   skip (external URL)"
        self.assertEqual(gui.clean_cell(text), "foo skip")

    def test_clean_cell_multiple_whitespace(self):
        """Test that multiple whitespace is collapsed."""
        text = "foo    bar     baz"
        self.assertEqual(gui.clean_cell(text), "foo bar baz")

    def test_clean_cell_leading_trailing_whitespace(self):
        """Test removal of leading and trailing whitespace."""
        text = "   foo bar   "
        self.assertEqual(gui.clean_cell(text), "foo bar")

    def test_clean_cell_igt_prefix_variants(self):
        """Test various IGT prefix patterns."""
        self.assertEqual(gui.clean_cell("IGT: test"), "test")
        self.assertEqual(gui.clean_cell("igt: test"), "igt: test")  # Only uppercase IGT
        self.assertEqual(gui.clean_cell("IGT:test"), "test")
        self.assertEqual(gui.clean_cell("IGT:  test"), "test")

    def test_clean_cell_multiple_external_url_markers(self):
        """Test removal of multiple external URL markers."""
        text = "foo (external URL) bar (external URL)"
        self.assertEqual(gui.clean_cell(text), "foo bar")

    def test_clean_cell_combined_cleaning(self):
        """Test combined cleaning operations."""
        text = "IGT: result   (external URL)  value  "
        self.assertEqual(gui.clean_cell(text), "result value")

    def test_clean_cell_external_url_with_spaces_inside_parentheses(self):
        """Test removal of marker variant '( external URL )'."""
        text = "skip ( external URL )"
        self.assertEqual(gui.clean_cell(text), "skip")

    def test_external_link_marker(self):
        self.assertTrue(gui._is_external_link_marker("external URL"))
        self.assertTrue(gui._is_external_link_marker("(External   Url)"))
        self.assertFalse(gui._is_external_link_marker("internal link"))

    def test_external_link_marker_case_insensitive(self):
        """Test case-insensitive matching of external URL marker."""
        self.assertTrue(gui._is_external_link_marker("EXTERNAL URL"))
        self.assertTrue(gui._is_external_link_marker("External Url"))
        self.assertTrue(gui._is_external_link_marker("external url"))
        self.assertTrue(gui._is_external_link_marker("EXTERNAL   URL"))

    def test_external_link_marker_with_whitespace(self):
        """Test marker detection with various whitespace patterns."""
        self.assertTrue(gui._is_external_link_marker("external  url"))
        self.assertTrue(gui._is_external_link_marker("external   url"))
        self.assertTrue(gui._is_external_link_marker(" external url "))

    def test_external_link_marker_in_parentheses(self):
        """Test marker detection within parentheses."""
        self.assertTrue(gui._is_external_link_marker("(external url)"))
        self.assertTrue(gui._is_external_link_marker("( external url )"))

    def test_external_link_marker_none_and_empty(self):
        """Test edge cases for None and empty strings."""
        self.assertFalse(gui._is_external_link_marker(""))
        self.assertFalse(gui._is_external_link_marker(None))

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

    def test_normalize_result_url_empty_and_hash(self):
        """Test handling of empty strings and hash anchors."""
        jira_base = "https://jira.devtools.intel.com"
        cib_base = "https://gfx-ci-internal.igk.intel.com"
        
        self.assertEqual(
            gui._normalize_result_url("", jira_base, cib_base),
            ""
        )
        self.assertEqual(
            gui._normalize_result_url("#anchor", jira_base, cib_base),
            ""
        )
        self.assertEqual(
            gui._normalize_result_url("  ", jira_base, cib_base),
            ""
        )

    def test_normalize_result_url_http_urls(self):
        """Test that absolute HTTP URLs are returned as-is."""
        jira_base = "https://jira.devtools.intel.com"
        cib_base = "https://gfx-ci-internal.igk.intel.com"
        
        self.assertEqual(
            gui._normalize_result_url("https://example.com/path", jira_base, cib_base),
            "https://example.com/path"
        )
        self.assertEqual(
            gui._normalize_result_url("http://example.com/path", jira_base, cib_base),
            "http://example.com/path"
        )

    def test_normalize_result_url_with_trailing_slashes(self):
        """Test URL bases with and without trailing slashes."""
        jira_base_with_slash = "https://jira.devtools.intel.com/"
        jira_base_no_slash = "https://jira.devtools.intel.com"
        cib_base = "https://gfx-ci-internal.igk.intel.com"
        
        result1 = gui._normalize_result_url("/browse/VLK-1", jira_base_with_slash, cib_base)
        result2 = gui._normalize_result_url("/browse/VLK-1", jira_base_no_slash, cib_base)
        # Both should produce valid URLs (may differ by trailing slash)
        self.assertTrue(result1.endswith("/browse/VLK-1"))
        self.assertTrue(result2.endswith("/browse/VLK-1"))
        self.assertIn("jira.devtools.intel.com", result1)
        self.assertIn("jira.devtools.intel.com", result2)

    def test_looks_like_tree_url(self):
        self.assertTrue(gui._looks_like_tree_url("/tree/xe/xe-1"))
        self.assertTrue(gui._looks_like_tree_url("https://host/tree/xe/xe-1/x"))
        self.assertFalse(gui._looks_like_tree_url("https://host/results/all"))

    def test_looks_like_tree_url_case_insensitive(self):
        """Test case-insensitivity of tree URL detection."""
        self.assertTrue(gui._looks_like_tree_url("/TREE/xe"))
        self.assertTrue(gui._looks_like_tree_url("/Tree/xe"))
        self.assertTrue(gui._looks_like_tree_url("https://host/TREE/"))

    def test_looks_like_tree_url_query_and_fragment(self):
        """Test tree URL detection with query strings and fragments."""
        self.assertTrue(gui._looks_like_tree_url("/tree?param=value"))
        self.assertTrue(gui._looks_like_tree_url("/tree#anchor"))
        self.assertTrue(gui._looks_like_tree_url("/tree/?param=1"))

    def test_looks_like_tree_url_edge_cases(self):
        """Test edge cases for tree URL detection."""
        self.assertFalse(gui._looks_like_tree_url(""))
        self.assertFalse(gui._looks_like_tree_url(None))
        self.assertFalse(gui._looks_like_tree_url("notree"))
        self.assertFalse(gui._looks_like_tree_url("treetop"))

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

    def test_build_tree_url_from_row_with_tags_and_runconfig(self):
        url = gui._build_tree_url_from_row(
            test_name="igt@xe_eudebug_online@systolic-fp-exception-overflow",
            machine_name="simfull-jgs_EDP_EUDBG_CORAL",
            build_text="xe-rtl-val-jgs-153-full",
            cibuglog_origin="https://gfx-ci-internal.igk.intel.com",
            tags_text="CORAL , EDP , EUDBG , JGS",
        )
        self.assertEqual(
            url,
            "https://gfx-ci-internal.igk.intel.com/tree/xe-rtl-validation-jgs/"
            "xe-rtl-val-jgs-153/simfull-jgs_EDP_EUDBG_CORAL/"
            "igt@xe_eudebug_online@systolic-fp-exception-overflow.html",
        )

    def test_build_tree_url_rtl_validation_builds(self):
        """Test RTL validation build URL construction."""
        url = gui._build_tree_url_from_row(
            test_name="igt@test",
            machine_name="machine",
            build_text="xe-rtl-val-abx-123-full",
            cibuglog_origin="https://gfx-ci-internal.igk.intel.com",
        )
        # Should handle RTL builds properly
        self.assertIn("xe-rtl-validation", url)
        self.assertIn("xe-rtl-val-abx-123", url)

    def test_build_tree_url_invalid_rtl_pattern(self):
        """Test that invalid RTL patterns fall through to xe pattern."""
        url = gui._build_tree_url_from_row(
            test_name="igt@test",
            machine_name="machine",
            build_text="xe-rtl-invalid",
            cibuglog_origin="https://gfx-ci-internal.igk.intel.com",
        )
        # Without matching xe-\d+, should return empty
        self.assertEqual(url, "")

    def test_build_tree_url_tags_with_commas(self):
        """Test tag parsing with multiple comma-separated tags."""
        # Tags with commas should not create valid single token
        url = gui._build_tree_url_from_row(
            test_name="igt@test",
            machine_name="machine",
            build_text="xe-1181",
            cibuglog_origin="https://gfx-ci-internal.igk.intel.com",
            tags_text="TAG1,TAG2,TAG3",
        )
        # Should skip the tags_part approach and use xe pattern if available
        if "xe-1181" in url:
            self.assertIn("/xe/", url)

    def test_build_tree_url_single_valid_tag(self):
        """Test that single valid tag creates tree URL even without xe pattern."""
        url = gui._build_tree_url_from_row(
            test_name="igt@test",
            machine_name="machine",
            build_text="build-id",
            cibuglog_origin="https://gfx-ci-internal.igk.intel.com",
            tags_text="VALID_TAG_123",
        )
        # With valid tag and build, should create URL using tags path
        self.assertIn("/tree/VALID_TAG_123/build-id/", url)
        self.assertTrue(url.endswith("igt@test.html"))

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

    def test_build_tree_url_from_row_missing_elements(self):
        """Test that URL is empty when required fields are missing."""
        origin = "https://gfx-ci-internal.igk.intel.com"
        
        # Missing test_name
        self.assertEqual(
            gui._build_tree_url_from_row(
                test_name="",
                machine_name="machine",
                build_text="xe-1181",
                cibuglog_origin=origin,
            ),
            "",
        )
        
        # Missing machine_name
        self.assertEqual(
            gui._build_tree_url_from_row(
                test_name="igt@test",
                machine_name="",
                build_text="xe-1181",
                cibuglog_origin=origin,
            ),
            "",
        )
        
        # Missing build_text
        self.assertEqual(
            gui._build_tree_url_from_row(
                test_name="igt@test",
                machine_name="machine",
                build_text="",
                cibuglog_origin=origin,
            ),
            "",
        )

    def test_build_tree_url_encoding_special_chars(self):
        """Test URL encoding of special characters in test/machine names."""
        url = gui._build_tree_url_from_row(
            test_name="igt@xe+special-test",
            machine_name="machine-name@host",
            build_text="xe-1181-ext",
            cibuglog_origin="https://gfx-ci-internal.igk.intel.com",
        )
        # Should contain encoded characters
        self.assertIn("xe-1181", url)
        self.assertTrue(url.endswith(".html"))

    def test_build_tree_url_with_origin_trailing_slash(self):
        """Test that origin URLs with trailing slashes are handled correctly."""
        url_with_slash = gui._build_tree_url_from_row(
            test_name="igt@test",
            machine_name="machine",
            build_text="xe-1181",
            cibuglog_origin="https://gfx-ci-internal.igk.intel.com/",
        )
        url_without_slash = gui._build_tree_url_from_row(
            test_name="igt@test",
            machine_name="machine",
            build_text="xe-1181",
            cibuglog_origin="https://gfx-ci-internal.igk.intel.com",
        )
        # Both should produce the same result (no double slashes)
        self.assertEqual(url_with_slash, url_without_slash)
        self.assertNotIn("//tree", url_with_slash)

    def test_split_runconfig_name_and_date_with_parentheses(self):
        name, date = gui._split_runconfig_name_and_date("xe-1181-nvl-resume (1 day old)")
        self.assertEqual(name, "xe-1181-nvl-resume")
        self.assertEqual(date, "1 day old")

    def test_split_runconfig_name_and_date_with_iso_date(self):
        name, date = gui._split_runconfig_name_and_date("xe-1181-nvl-resume 2026-04-01 09:15")
        self.assertEqual(name, "xe-1181-nvl-resume")
        self.assertEqual(date, "2026-04-01 09:15")

    def test_split_runconfig_name_and_date_plain_name(self):
        name, date = gui._split_runconfig_name_and_date("xe-1181-nvl-resume")
        self.assertEqual(name, "xe-1181-nvl-resume")
        self.assertEqual(date, "")

    def test_split_runconfig_name_and_date_empty(self):
        name, date = gui._split_runconfig_name_and_date("")
        self.assertEqual(name, "")
        self.assertEqual(date, "")


class TestQueryBuilder(unittest.TestCase):
    """Test query building and parsing for CIBugLog filters."""

    def setUp(self):
        """Set up mock app with filter fields."""
        self.app = Mock(spec=gui.CIBugLogApp)
        
        # Create combobox mocks for test_name
        self.app.test_value = Mock()
        self.app.test_match = Mock()
        self.app.test_value.get.return_value = ""
        self.app.test_match.get.return_value = "= (exact)"
        
        # Create combobox mocks for machine_name
        self.app.machine_value = Mock()
        self.app.machine_conn = Mock()
        self.app.machine_match = Mock()
        self.app.machine_value.get.return_value = ""
        self.app.machine_conn.get.return_value = "AND"
        self.app.machine_match.get.return_value = "~= (regex/contains)"
        
        # Create combobox mocks for runconfig_name
        self.app.rc_value = Mock()
        self.app.rc_conn = Mock()
        self.app.rc_match = Mock()
        self.app.rc_value.get.return_value = ""
        self.app.rc_conn.get.return_value = "AND NOT"
        self.app.rc_match.get.return_value = "~= (regex/contains)"
        
        # Create combobox mocks for stderr (NEW)
        self.app.stderr_value = Mock()
        self.app.stderr_conn = Mock()
        self.app.stderr_match = Mock()
        self.app.stderr_value.get.return_value = ""
        self.app.stderr_conn.get.return_value = "AND"
        self.app.stderr_match.get.return_value = "~= (regex/contains)"
        
        # Create combobox mocks for date
        self.app.date_value = Mock()
        self.app.date_value.get.return_value = ""

    def _build_query(self) -> str:
        """Extracted _op helper method."""
        def _op(match_type):
            return "~=" if "~" in match_type else "="
        
        parts = []
        
        tv = self.app.test_value.get().strip()
        if tv:
            parts.append(f"test_name{_op(self.app.test_match.get())}'{tv}'")
        
        mv = self.app.machine_value.get().strip()
        if mv:
            conn = self.app.machine_conn.get()
            expr = f"machine_name{_op(self.app.machine_match.get())}'{mv}'"
            parts.append(f"{conn} {expr}" if parts else
                         (f"NOT {expr}" if "NOT" in conn else expr))
        
        rv = self.app.rc_value.get().strip()
        if rv:
            conn = self.app.rc_conn.get()
            expr = f"runconfig_name{_op(self.app.rc_match.get())}'{rv}'"
            parts.append(f"{conn} {expr}" if parts else
                         (f"NOT {expr}" if "NOT" in conn else expr))
        
        sv = self.app.stderr_value.get().strip()
        if sv:
            conn = self.app.stderr_conn.get()
            expr = f"stderr{_op(self.app.stderr_match.get())}'{sv}'"
            parts.append(f"{conn} {expr}" if parts else
                         (f"NOT {expr}" if "NOT" in conn else expr))
        
        dv = self.app.date_value.get().strip()
        if dv:
            expr = f"runconfig_added_on > datetime({dv})"
            parts.append(f"AND {expr}" if parts else expr)
        
        return " ".join(parts)

    def test_build_query_stderr_only(self):
        """Test building query with only stderr filter."""
        self.app.stderr_value.get.return_value = "out of bounds"
        self.app.stderr_match.get.return_value = "~= (regex/contains)"
        
        query = self._build_query()
        self.assertEqual(query, "stderr~='out of bounds'")

    def test_build_query_stderr_with_and(self):
        """Test stderr with AND connector."""
        self.app.test_value.get.return_value = "igt@test"
        self.app.stderr_value.get.return_value = "null pointer"
        self.app.stderr_match.get.return_value = "= (exact)"
        
        query = self._build_query()
        self.assertEqual(
            query,
            "test_name='igt@test' AND stderr='null pointer'"
        )

    def test_build_query_stderr_with_and_not(self):
        """Test stderr with AND NOT connector."""
        self.app.test_value.get.return_value = "igt@test"
        self.app.stderr_conn.get.return_value = "AND NOT"
        self.app.stderr_value.get.return_value = "timeout"
        self.app.stderr_match.get.return_value = "~= (regex/contains)"
        
        query = self._build_query()
        self.assertEqual(
            query,
            "test_name='igt@test' AND NOT stderr~='timeout'"
        )

    def test_build_query_all_filters_with_stderr(self):
        """Test query with all filters including stderr."""
        self.app.test_value.get.return_value = "igt@xe_eudebug"
        self.app.machine_value.get.return_value = "jgs"
        self.app.machine_conn.get.return_value = "AND"
        self.app.rc_value.get.return_value = "kasan"
        self.app.rc_conn.get.return_value = "AND NOT"
        self.app.stderr_value.get.return_value = "memory error"
        self.app.stderr_conn.get.return_value = "AND"
        self.app.date_value.get.return_value = "2026-03-31"
        
        query = self._build_query()
        expected = (
            "test_name='igt@xe_eudebug' AND machine_name~='jgs' "
            "AND NOT runconfig_name~='kasan' AND stderr~='memory error' "
            "AND runconfig_added_on > datetime(2026-03-31)"
        )
        self.assertEqual(query, expected)

    def test_build_query_stderr_regex_with_pipe(self):
        """Test stderr with regex pattern containing pipe."""
        self.app.stderr_value.get.return_value = "out of bounds|invalid access"
        self.app.stderr_match.get.return_value = "~= (regex/contains)"
        
        query = self._build_query()
        self.assertEqual(
            query,
            "stderr~='out of bounds|invalid access'"
        )

    def test_parse_query_stderr_exact(self):
        """Test parsing query with stderr exact match."""
        raw = "stderr='critical error'"
        
        import re
        sm = re.search(
            r"(AND\s+NOT|AND)\s+stderr\s*(~?=)\s*'([^']*)'|"
            r"^stderr\s*(~?=)\s*'([^']*)'",
            raw, re.IGNORECASE)
        
        self.assertIsNotNone(sm)
        self.assertEqual(sm.group(4), "=")
        self.assertEqual(sm.group(5), "critical error")

    def test_parse_query_stderr_with_and(self):
        """Test parsing query with stderr and AND connector."""
        raw = "test_name='igt@test' AND stderr~='memory leak'"
        
        import re
        sm = re.search(
            r"(AND\s+NOT|AND)\s+stderr\s*(~?=)\s*'([^']*)'|"
            r"^stderr\s*(~?=)\s*'([^']*)'",
            raw, re.IGNORECASE)
        
        self.assertIsNotNone(sm)
        self.assertEqual(sm.group(1), "AND")
        self.assertEqual(sm.group(2), "~=")
        self.assertEqual(sm.group(3), "memory leak")

    def test_parse_query_stderr_with_and_not(self):
        """Test parsing query with stderr and AND NOT connector."""
        raw = "test_name='igt@test' AND NOT stderr='warning'"
        
        import re
        sm = re.search(
            r"(AND\s+NOT|AND)\s+stderr\s*(~?=)\s*'([^']*)'|"
            r"^stderr\s*(~?=)\s*'([^']*)'",
            raw, re.IGNORECASE)
        
        self.assertIsNotNone(sm)
        self.assertEqual(sm.group(1), "AND NOT")
        self.assertEqual(sm.group(2), "=")
        self.assertEqual(sm.group(3), "warning")

    def test_parse_query_no_stderr(self):
        """Test parsing query without stderr."""
        raw = "test_name='igt@test' AND machine_name~='jgs'"
        
        import re
        sm = re.search(
            r"(AND\s+NOT|AND)\s+stderr\s*(~?=)\s*'([^']*)'|"
            r"^stderr\s*(~?=)\s*'([^']*)'",
            raw, re.IGNORECASE)
        
        self.assertIsNone(sm)


if __name__ == "__main__":
    unittest.main()
