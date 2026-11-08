"""Upstream failures must preserve unknown measurements and catalog identities."""

import copy
import io
import json
import unittest
import urllib.error
from unittest.mock import Mock, patch

from data.build_catalog import DEFAULT_CONFIG, load_config
from data.enrichment import enrich_wikipedia
from data.normalizers import (SourceError, coordinates, identity_index, make_object,
                              measurement, number, positive_limit, slug)
from data.sources import JsonClient, fetch_exoplanets, fetch_small_bodies


class NormalizerEdges(unittest.TestCase):
    def test_invalid_numbers_and_unknown_measurements(self):
        for value in [None, True, False, "", "bad", {}, [], float("nan"),
                      float("inf"), 10**1000]:
            with self.subTest(value=str(value)[:30]):
                self.assertIsNone(number(value))
                self.assertIsNone(measurement(value))
        self.assertEqual(number("1.25"), 1.25)
        self.assertEqual(measurement(0), 0)
        self.assertIsNone(measurement(0, positive=True))
        self.assertIsNone(measurement(-1))

    def test_coordinates_invalid_angles_and_unknown_fields(self):
        for row in [dict(ra=-1), dict(ra=361), dict(dec=-91), dict(dec=91)]:
            with self.subTest(row=row), self.assertRaises(SourceError):
                coordinates(row)
        self.assertEqual(coordinates({}), dict(ra=None, dec=None, distance_ly=None))
        self.assertEqual(coordinates(dict(ra=360, dec=0, sy_dist=0)),
                         dict(ra=0, dec=0, distance_ly=0))

    def test_limits_and_slug_contract(self):
        self.assertEqual(positive_limit("12"), 12)
        self.assertEqual(slug("  HD-123 b "), "hd_123_b")
        for value in [True, -1, 0, "1.5", 1.5]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                positive_limit(value)
        with self.assertRaises(SourceError):
            slug("!!!")

    def test_existing_nonlatin_identity_is_preserved_without_slugging(self):
        config = load_config(DEFAULT_CONFIG)
        old = dict(id="saved_id", name="Звезда", kind="star", latin="Star",
                   rings={"inner": 1, "outer": 2}, atmosphere=True)
        snapshot = copy.deepcopy(old)
        index = identity_index([old])
        result = make_object("star", "Звезда", "local", config, index)
        self.assertEqual(result["id"], "saved_id")
        result["rings"]["inner"] = 100
        self.assertEqual(old, snapshot)


class HttpClientEdges(unittest.TestCase):
    def client(self, retries=2):
        return JsonClient(dict(timeout_seconds=3, retries=retries, user_agent="test"))

    def test_url_parameters_timeout_and_json_response(self):
        with patch("data.sources.urllib.request.urlopen") as get:
            get.return_value.__enter__.return_value = io.BytesIO(b'{"ok":true}')
            self.assertEqual(self.client().get("https://example.test/api", {"q": "a b"}), {"ok": True})
        request = get.call_args.args[0]
        self.assertIn("q=a+b", request.full_url)
        self.assertEqual(request.get_header("User-agent"), "test")
        self.assertEqual(get.call_args.kwargs["timeout"], 3)

    def test_transient_failure_backoff_and_recovery(self):
        with patch("data.sources.urllib.request.urlopen") as get, patch("data.sources.time.sleep") as sleep:
            response = Mock()
            response.__enter__ = Mock(return_value=io.BytesIO(b"[]"))
            response.__exit__ = Mock(return_value=False)
            get.side_effect = [TimeoutError("timeout"), OSError("network"), response]
            self.assertEqual(self.client().get("https://example.test"), [])
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])

    def test_http_status_retries_and_final_errors(self):
        for code, calls in [(400, 1), (403, 1), (404, 1), (429, 3), (500, 3), (503, 3)]:
            error = urllib.error.HTTPError("https://example.test", code, "failure", {}, None)
            self.addCleanup(error.close)
            with (self.subTest(code=code),
                  patch("data.sources.urllib.request.urlopen", side_effect=error) as get,
                  patch("data.sources.time.sleep")):
                with self.assertRaises(SourceError):
                    self.client().get("https://example.test")
                self.assertEqual(get.call_count, calls)

    def test_malformed_json_is_bounded_by_retry_limit(self):
        with patch("data.sources.urllib.request.urlopen") as get:
            get.return_value.__enter__.return_value = io.BytesIO(b"invalid")
            with self.assertRaises(SourceError):
                self.client(retries=0).get("https://example.test")
            self.assertEqual(get.call_count, 1)


class SourcePayloadEdges(unittest.TestCase):
    def setUp(self):
        self.config = load_config(DEFAULT_CONFIG)

    def test_exoplanet_malformed_rows_are_rejected(self):
        for rows in [None, {}, [], [None], [{}], [dict(pl_name=3, hostname="a")],
                     [dict(pl_name=" ", hostname="a")], [dict(pl_name="a", hostname=" ")]]:
            with self.subTest(rows=rows), self.assertRaises(SourceError):
                fetch_exoplanets(Mock(get=Mock(return_value=rows)), self.config, {}, 10)

    def test_repeated_host_merges_missing_data_without_duplicate_stars(self):
        rows = [dict(pl_name="A b", hostname="A", st_teff=None),
                dict(pl_name="A c", hostname="A", st_teff=5000, pl_eqt=300,
                     discoverymethod="Transit", disc_year=2020)]
        result = fetch_exoplanets(Mock(get=Mock(return_value=rows)), self.config, {}, 10)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["temperature_k"], 5000)
        self.assertEqual(result[1]["parent"], result[2]["parent"])
        self.assertIsNone(result[1]["temperature_k"])
        self.assertEqual(len(result[2]["facts"]), 3)

    def test_host_id_collision_is_not_silently_merged(self):
        rows = [dict(pl_name="A b", hostname="A-B"), dict(pl_name="A c", hostname="A B")]
        with self.assertRaisesRegex(SourceError, "collision"):
            fetch_exoplanets(Mock(get=Mock(return_value=rows)), self.config, {}, 10)

    def test_sbdb_malformed_envelopes_rows_and_names(self):
        fields = ["full_name", "pdes", "a", "per", "diameter"]
        for payload in [None, [], {}, dict(data=[[]], fields=[]),
                        dict(data=[[]], fields=fields), dict(data=["bad"], fields=fields),
                        dict(data=[[None, "id", 1, 2, 3]], fields=fields),
                        dict(data=[[" ", "id", 1, 2, 3]], fields=fields),
                        dict(data=[["Body", None, 1, 2, 3]], fields=fields)]:
            with self.subTest(payload=payload), self.assertRaises(SourceError):
                fetch_small_bodies(Mock(get=Mock(return_value=payload)), self.config, {}, "asteroid", 10)

    def test_sbdb_numeric_name_preserves_designation_and_unknown_diameter(self):
        payload = dict(fields=["full_name", "pdes", "a", "per", "diameter"],
                       data=[["123 (A801 AA)", "123", None, None, None]])
        result = fetch_small_bodies(Mock(get=Mock(return_value=payload)), self.config, {}, "asteroid", 1)
        self.assertEqual(result[0]["name"], "123 A801 AA")
        self.assertIsNone(result[0]["radius_km"])

    def test_optional_wikipedia_errors_preserve_existing_description(self):
        for response in [None, [], {"type": "disambiguation"}, {}, {"extract": " "}, {"extract": 3}]:
            obj = dict(id="a", wikipedia_title="A B", description="original")
            with self.subTest(response=response), self.assertLogs(level="WARNING"):
                enrich_wikipedia([obj], Mock(get=Mock(return_value=response)), self.config)
            self.assertEqual(obj["description"], "original")
        with self.assertLogs(level="WARNING"):
            enrich_wikipedia([obj], Mock(get=Mock(side_effect=SourceError("offline"))), self.config)
        client = Mock(get=Mock(return_value={"extract": "  updated  "}))
        enrich_wikipedia([obj, dict(id="skip")], client, self.config)
        self.assertEqual(obj["description"], "updated")
        self.assertIn("A%20B", obj["description_source"])
        self.assertEqual(client.get.call_count, 1)

class SourceUnitReferenceTests(unittest.TestCase):
    def test_sbdb_period_field_is_days_not_years(self):
        from pathlib import Path
        import json
        reference=json.loads((Path(__file__).parent/'fixtures/sbdb_field_units.json').read_text())
        units={field['name']:field['units'] for field in reference['fields']}
        self.assertEqual(units['per'],'d')
        self.assertEqual(units['per_y'],'years')
        self.assertEqual(units['epoch'],'TDB')
        self.assertEqual(units['a'],'au')
        # The production fetcher requests per, not per_y: the returned period
        # is already in days. Values in this fixture were fetched independently.
        from data.sources import fetch_small_bodies
        from unittest.mock import Mock
        client=Mock()
        client.get.return_value={'fields':['full_name','pdes','a','per','diameter'],
                                 'data':[['123 Test','123','2','700','10']]}
        config={'sources':{'asteroids':{'url':'sbdb'}},'display':{'asteroid':{'radius':1,'color':'#aaaaaa'}}}
        result=fetch_small_bodies(client,config,{},'asteroid',1)
        self.assertEqual(result[0]['period_days'],700)
        self.assertIn('per',client.get.call_args.args[1]['fields'].split(','))
        self.assertNotIn('per_y',client.get.call_args.args[1]['fields'].split(','))
