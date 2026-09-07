import unittest
from unittest.mock import patch
import json

from app import printer_service


class PrinterServiceTests(unittest.TestCase):
    def test_supplies_from_snmp_rows_calculates_percent_and_status(self):
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.43.11.1.1.6.1.1 = STRING: "Black Ink"
.1.3.6.1.2.1.43.11.1.1.7.1.1 = INTEGER: 15
.1.3.6.1.2.1.43.11.1.1.8.1.1 = INTEGER: 100
.1.3.6.1.2.1.43.11.1.1.9.1.1 = INTEGER: 8
.1.3.6.1.2.1.43.11.1.1.6.1.2 = STRING: "Cyan Ink"
.1.3.6.1.2.1.43.11.1.1.7.1.2 = INTEGER: 15
.1.3.6.1.2.1.43.11.1.1.8.1.2 = INTEGER: 100
.1.3.6.1.2.1.43.11.1.1.9.1.2 = INTEGER: 52
            """
        )

        supplies = printer_service.supplies_from_snmp_rows(rows)

        self.assertEqual(supplies[0]["color"], "Cyan")
        self.assertEqual(supplies[0]["percent"], 52)
        self.assertEqual(supplies[0]["status"], "ok")
        self.assertEqual(supplies[1]["name"], "Black Ink")
        self.assertEqual(supplies[1]["percent"], 8)
        self.assertEqual(supplies[1]["status"], "low")

    def test_supplies_are_sorted_cmyk_then_waste(self):
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.43.11.1.1.6.1.1 = STRING: "Black Ink"
.1.3.6.1.2.1.43.11.1.1.8.1.1 = INTEGER: 100
.1.3.6.1.2.1.43.11.1.1.9.1.1 = INTEGER: 24
.1.3.6.1.2.1.43.11.1.1.6.1.2 = STRING: "Wasted Ink"
.1.3.6.1.2.1.43.11.1.1.8.1.2 = INTEGER: 100
.1.3.6.1.2.1.43.11.1.1.9.1.2 = INTEGER: 77
.1.3.6.1.2.1.43.11.1.1.6.1.3 = STRING: "Cyan Ink"
.1.3.6.1.2.1.43.11.1.1.8.1.3 = INTEGER: 100
.1.3.6.1.2.1.43.11.1.1.9.1.3 = INTEGER: 11
.1.3.6.1.2.1.43.11.1.1.6.1.4 = STRING: "Magenta Ink"
.1.3.6.1.2.1.43.11.1.1.8.1.4 = INTEGER: 100
.1.3.6.1.2.1.43.11.1.1.9.1.4 = INTEGER: 22
.1.3.6.1.2.1.43.11.1.1.6.1.5 = STRING: "Yellow Ink"
.1.3.6.1.2.1.43.11.1.1.8.1.5 = INTEGER: 100
.1.3.6.1.2.1.43.11.1.1.9.1.5 = INTEGER: 29
            """
        )

        supplies = printer_service.supplies_from_snmp_rows(rows)

        self.assertEqual([item["name"] for item in supplies], [
            "Cyan Ink",
            "Magenta Ink",
            "Yellow Ink",
            "Black Ink",
            "Waste Collection Unit",
        ])

    def test_gp_4600s_compact_ink_labels_map_and_sort_all_seven_colors(self):
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.43.11.1.1.6.1.1 = STRING: "Ink Tank O"
.1.3.6.1.2.1.43.11.1.1.9.1.1 = INTEGER: 61
.1.3.6.1.2.1.43.11.1.1.6.1.2 = STRING: "Ink Tank MBK"
.1.3.6.1.2.1.43.11.1.1.9.1.2 = INTEGER: 72
.1.3.6.1.2.1.43.11.1.1.6.1.3 = STRING: "Ink Tank GY"
.1.3.6.1.2.1.43.11.1.1.9.1.3 = INTEGER: 83
.1.3.6.1.2.1.43.11.1.1.6.1.4 = STRING: "Ink Tank K"
.1.3.6.1.2.1.43.11.1.1.9.1.4 = INTEGER: 94
.1.3.6.1.2.1.43.11.1.1.6.1.5 = STRING: "Ink Tank Y"
.1.3.6.1.2.1.43.11.1.1.9.1.5 = INTEGER: 55
.1.3.6.1.2.1.43.11.1.1.6.1.6 = STRING: "Ink Tank M"
.1.3.6.1.2.1.43.11.1.1.9.1.6 = INTEGER: 66
.1.3.6.1.2.1.43.11.1.1.6.1.7 = STRING: "Ink Tank C"
.1.3.6.1.2.1.43.11.1.1.9.1.7 = INTEGER: 77
            """
        )

        supplies = printer_service.supplies_from_snmp_rows(rows)

        self.assertEqual([item["color"] for item in supplies], [
            "Cyan",
            "Magenta",
            "Yellow",
            "Matte Black",
            "Black",
            "Gray",
            "Orange",
        ])
        self.assertEqual([item["percent"] for item in supplies], [77, 66, 55, 72, 94, 83, 61])

    def test_gp_4600s_zero_level_with_low_alert_is_not_reported_empty(self):
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.1.1.0 = STRING: "Canon GP-4600S /P"
.1.3.6.1.2.1.43.11.1.1.6.1.1 = STRING: "CANON Photo Black Ink Tank"
.1.3.6.1.2.1.43.11.1.1.8.1.1 = INTEGER: 3300
.1.3.6.1.2.1.43.11.1.1.9.1.1 = INTEGER: 0
.1.3.6.1.2.1.43.11.1.1.6.1.2 = STRING: "CANON Gray Ink Tank"
.1.3.6.1.2.1.43.11.1.1.8.1.2 = INTEGER: 3300
.1.3.6.1.2.1.43.11.1.1.9.1.2 = INTEGER: 0
.1.3.6.1.2.1.43.18.1.1.2.1.1 = INTEGER: 4
.1.3.6.1.2.1.43.18.1.1.7.1.1 = INTEGER: 1105
.1.3.6.1.2.1.43.18.1.1.8.1.1 = STRING: "Ink tank supply low at black."
.1.3.6.1.2.1.43.18.1.1.2.1.2 = INTEGER: 4
.1.3.6.1.2.1.43.18.1.1.7.1.2 = INTEGER: 1105
.1.3.6.1.2.1.43.18.1.1.8.1.2 = STRING: "Ink tank supply low at gray."
            """
        )
        device = type("Device", (), {"model": "Canon GP-4600S", "host": "10.1.1.128"})()

        status = printer_service.build_status(device, rows)
        photo_black, gray = status["appliance"]["inkLevels"]

        for supply in (photo_black, gray):
            self.assertEqual(supply["rawLevel"], 0)
            self.assertIsNone(supply["level"])
            self.assertIsNone(supply["percent"])
            self.assertEqual(supply["status"], "low")
            self.assertEqual(supply["levelLabel"], "Low")
            self.assertEqual(supply["measurement"], "threshold-only")

    def test_unknown_capacity_keeps_supply_without_percent(self):
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.43.11.1.1.6.1.3 = STRING: "Waste Ink Collector"
.1.3.6.1.2.1.43.11.1.1.8.1.3 = INTEGER: -2
.1.3.6.1.2.1.43.11.1.1.9.1.3 = INTEGER: -3
            """
        )

        supply = printer_service.supplies_from_snmp_rows(rows)[0]

        self.assertEqual(supply["color"], "Waste")
        self.assertIsNone(supply["percent"])
        self.assertEqual(supply["status"], "unknown")

    def test_waste_supply_reports_remaining_capacity(self):
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.43.11.1.1.6.1.2 = STRING: "Wasted Ink"
.1.3.6.1.2.1.43.11.1.1.8.1.2 = INTEGER: 100
.1.3.6.1.2.1.43.11.1.1.9.1.2 = INTEGER: 77
            """
        )

        supply = printer_service.supplies_from_snmp_rows(rows)[0]

        self.assertEqual(supply["name"], "Waste Collection Unit")
        self.assertEqual(supply["reportedName"], "Wasted Ink")
        self.assertEqual(supply["rawLevel"], 77)
        self.assertEqual(supply["level"], 23)
        self.assertEqual(supply["percent"], 23)
        self.assertEqual(supply["measurement"], "remaining")

    def test_waste_capacity_is_not_counted_as_lowest_ink(self):
        ink = {"supplyType": "ink", "color": "Matte Black", "name": "Ink Tank", "percent": 40}
        waste = {"supplyType": "ink", "color": "Waste", "name": "Waste Collection Unit", "percent": 30}

        self.assertTrue(printer_service._is_measured_ink_supply(ink))
        self.assertFalse(printer_service._is_measured_ink_supply(waste))

    def test_sg500_percentage_supply_uses_level_when_max_is_missing(self):
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.43.11.1.1.6.1.3 = STRING: "Cyan Ink"
.1.3.6.1.2.1.43.11.1.1.9.1.3 = INTEGER: 11
            """
        )

        supply = printer_service.supplies_from_snmp_rows(rows)[0]

        self.assertEqual(supply["name"], "Cyan Ink")
        self.assertEqual(supply["max"], 100)
        self.assertEqual(supply["level"], 11)
        self.assertEqual(supply["percent"], 11)

    def test_sg500_waste_uses_remaining_capacity_when_max_is_missing(self):
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.43.11.1.1.6.1.2 = STRING: "Wasted Ink"
.1.3.6.1.2.1.43.11.1.1.9.1.2 = INTEGER: 77
            """
        )

        supply = printer_service.supplies_from_snmp_rows(rows)[0]

        self.assertEqual(supply["name"], "Waste Collection Unit")
        self.assertEqual(supply["max"], 100)
        self.assertEqual(supply["level"], 23)
        self.assertEqual(supply["percent"], 23)

    def test_media_rows_are_parsed(self):
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.43.8.2.1.13.1.1 = STRING: "Roll 1"
.1.3.6.1.2.1.43.8.2.1.18.1.1 = STRING: "Matte paper"
.1.3.6.1.2.1.43.8.2.1.9.1.1 = INTEGER: 100
.1.3.6.1.2.1.43.8.2.1.10.1.1 = INTEGER: 75
.1.3.6.1.2.1.43.8.2.1.11.1.1 = INTEGER: 0
            """
        )

        media = printer_service.media_from_snmp_rows(rows)

        self.assertEqual(media[0]["name"], "Roll 1")
        self.assertEqual(media[0]["description"], "Matte paper")
        self.assertEqual(media[0]["percent"], 75)

    def test_media_negative_level_codes_are_labels_not_counts(self):
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.43.8.2.1.13.1.1 = STRING: "Drawer 1"
.1.3.6.1.2.1.43.8.2.1.9.1.1 = INTEGER: 100
.1.3.6.1.2.1.43.8.2.1.10.1.1 = INTEGER: -3
.1.3.6.1.2.1.43.8.2.1.11.1.1 = INTEGER: 0
            """
        )

        media = printer_service.media_from_snmp_rows(rows)

        self.assertEqual(media[0]["name"], "Drawer 1")
        self.assertIsNone(media[0]["level"])
        self.assertEqual(media[0]["rawLevel"], -3)
        self.assertEqual(media[0]["levelLabel"], "Loaded")
        self.assertIsNone(media[0]["percent"])
        self.assertIsNone(media[0]["status"])

    def test_alert_rows_include_readable_severity(self):
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.43.18.1.1.2.1.1 = INTEGER: 3
.1.3.6.1.2.1.43.18.1.1.7.1.1 = INTEGER: 801
.1.3.6.1.2.1.43.18.1.1.8.1.1 = STRING: "Cover open{123}"
            """
        )

        alerts = printer_service.alerts_from_snmp_rows(rows)

        self.assertEqual(alerts[0]["severity"], 3)
        self.assertEqual(alerts[0]["severityLabel"], "Critical")
        self.assertEqual(alerts[0]["code"], 801)
        self.assertEqual(alerts[0]["description"], "Cover open")

    def test_offline_status_preserves_cached_ink_snapshot(self):
        device = type("Device", (), {"host": "10.0.0.9", "model": "Canon GP-4600S"})()
        cached = {
            "appliance": {
                "inkLevels": [{"name": "Cyan", "percent": 44}],
                "checkedAt": "2026-07-04T12:00:00+00:00",
            }
        }

        status = printer_service.offline_status(device, cached, "Printer did not respond.", "2026-07-04T12:05:00+00:00")

        self.assertFalse(status["is_on"])
        self.assertTrue(status["appliance"]["stale"])
        self.assertEqual(status["appliance"]["inkLevels"][0]["percent"], 44)
        self.assertEqual(status["appliance"]["lastOnlineAt"], "2026-07-04T12:00:00+00:00")

    def test_cups_socket_uri_becomes_discovery_candidate(self):
        candidate = printer_service._candidate_from_printer_uri("socket://192.168.10.55:9100")

        self.assertEqual(candidate["host"], "192.168.10.55")
        self.assertEqual(candidate["port"], 9100)

    def test_cups_dnssd_uri_resolves_to_host(self):
        with patch("app.printer_service._resolve_bonjour", return_value={"host": "canon.local", "port": 631, "model": "Canon GP-4600S"}):
            candidate = printer_service._candidate_from_printer_uri(
                "dnssd://Canon%20GP-4600S._ipp._tcp.local./?uuid=abc"
            )

        self.assertEqual(candidate["host"], "canon.local")
        self.assertEqual(candidate["model"], "Canon GP-4600S")
        self.assertEqual(candidate["service_type"], "_ipp._tcp")

    def test_requested_single_ip_preserves_model_hint(self):
        candidates = printer_service._requested_host_candidates(["192.168.10.130"], "Canon G6020")

        self.assertEqual(candidates[0]["host"], "192.168.10.130")
        self.assertEqual(candidates[0]["name"], "Canon G6020")
        self.assertEqual(candidates[0]["model"], "Canon G6020")

    def test_guess_model_handles_target_printers(self):
        self.assertEqual(printer_service._guess_model("Sawgrass SG500 RPCS-R"), "Sawgrass SG500")
        self.assertEqual(printer_service._guess_model("Canon PIXMA G6020"), "Canon G6020")
        self.assertEqual(printer_service._guess_model("Canon G 6020 series"), "Canon G6020")
        self.assertEqual(printer_service._guess_model("Canon G6000 series /P"), "Canon G6020")
        self.assertEqual(printer_service._guess_model("Canon imagePROGRAF GP-4600S"), "Canon GP-4600S")
        self.assertEqual(printer_service._guess_model("Magicard 300 Card Printer"), "Magicard 300")

    def test_magicard_ribbon_is_a_percentage_supply(self):
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.43.11.1.1.6.1.1 = STRING: "YMCKO Dye Film Ribbon"
.1.3.6.1.2.1.43.11.1.1.9.1.1 = INTEGER: 64
            """
        )

        supply = printer_service.supplies_from_snmp_rows(rows)[0]

        self.assertEqual(supply["supplyType"], "ribbon")
        self.assertEqual(supply["max"], 100)
        self.assertEqual(supply["percent"], 64)

    def test_magicard_status_uses_card_printer_supply_labels(self):
        device = type("Device", (), {"host": "10.0.0.30", "model": "Magicard 300"})()
        rows = printer_service.parse_snmp_output(
            """
.1.3.6.1.2.1.1.1.0 = STRING: "Magicard 300 Card Printer"
.1.3.6.1.2.1.43.11.1.1.6.1.1 = STRING: "YMCKO Film"
.1.3.6.1.2.1.43.11.1.1.9.1.1 = INTEGER: 80
            """
        )

        appliance = printer_service.build_status(device, rows)["appliance"]

        self.assertEqual(appliance["model"], "Magicard 300")
        self.assertEqual(appliance["supplyLabel"], "Ribbon and supplies")
        self.assertEqual(appliance["supplyMetricLabel"], "Lowest supply")

    def test_magicard_network_fallback_reports_online_without_snmp(self):
        device = type("Device", (), {
            "name": "Magicard 300",
            "host": "10.1.1.108",
            "model": "Magicard 300",
            "device_key": json.dumps({
                "community": "public",
                "serial": "74765224",
                "printhead_serial": "KJ2/14-00524/R2809",
                "firmware": "13.49",
                "dye_film_type": "MC300YMCKO",
                "hand_feed": "No",
            }),
        })()

        status = printer_service.magicard_network_status(device, "2026-07-21T20:00:00+00:00")

        self.assertTrue(status["is_on"])
        self.assertEqual(status["appliance"]["status"], "Online")
        self.assertEqual(status["appliance"]["supplyLabel"], "Ribbon and supplies")
        self.assertFalse(status["raw"]["snmpSupported"])
        self.assertEqual(status["raw"]["port"], 9100)
        self.assertEqual(status["appliance"]["serial"], "74765224")
        self.assertEqual(status["appliance"]["printheadSerial"], "KJ2/14-00524/R2809")
        self.assertEqual(status["appliance"]["firmware"], "13.49")
        self.assertEqual(status["appliance"]["dyeFilmType"], "MC300YMCKO")

    def test_ipp_output_value_extracts_printer_identity(self):
        output = 'printer-make-and-model (textWithoutLanguage) = Canon G6020 series\nprinter-name (nameWithoutLanguage) = Canon G6020'

        self.assertEqual(printer_service._ipp_output_value(output, "printer-make-and-model"), "Canon G6020 series")
        self.assertEqual(printer_service._guess_model(output), "Canon G6020")

    def test_canon_remote_ui_ink_levels_use_ui_bucket_scale(self):
        levels = printer_service._parse_canon_remote_ui_ink_levels(
            "inktank[0]=[0,8,0];\ninktank[1]=[1,0,0];\ninktank[2]=[2,1,0];\ninktank[3]=[3,0,0];"
        )

        self.assertEqual([item["color"] for item in levels], ["Black", "Cyan", "Magenta", "Yellow"])
        self.assertEqual([item["percent"] for item in levels], [20, 100, 90, 100])

    def test_gp_4600s_remote_ui_maps_colors_and_low_threshold(self):
        levels = printer_service._parse_canon_remote_ui_ink_levels(
            "var inkCOL = ['InkGry', 'InkPbk', 'InkOra', 'InkMbk', 'InkYel', 'InkMaz', 'InkCia'];\n"
            "inktank[0]=[0,10,1,'PFI-3300 GY SETUP'];\n"
            "inktank[1]=[1,10,1,'PFI-3300 PBK SETUP'];\n"
            "inktank[2]=[2,3,0,'PFI-2700 O'];\n"
            "inktank[3]=[3,6,0,'PFI-2700 MBK'];\n"
            "var g_cartridge_rest = [3,0];"
        )

        self.assertEqual([item["color"] for item in levels], ["Gray", "Photo Black", "Orange", "Matte Black", "Waste"])
        self.assertEqual([item["percent"] for item in levels], [None, None, 70, 40, 30])
        self.assertEqual([item["status"] for item in levels], ["low", "low", "ok", "ok", "ok"])
        self.assertEqual(levels[0]["name"], "PFI-3300 GY SETUP")
        self.assertEqual(levels[-1]["name"], "Maintenance Cartridge")

    def test_canon_remote_ui_status_is_available_when_snmp_is_not(self):
        device = type("Device", (), {
            "name": "Canon GP-4600S",
            "model": "Canon GP-4600S",
            "host": "10.1.1.128",
        })()
        remote_levels = [
            {"color": "Gray", "name": "PFI-3300 GY", "percent": None, "levelIndex": 10, "marker": 1, "status": "low"},
            {"color": "Cyan", "name": "PFI-3700 C", "percent": 70, "levelIndex": 3, "marker": 0, "status": "ok"},
        ]

        with patch("app.printer_service._canon_remote_ui_ink_levels", return_value=remote_levels):
            status = printer_service._canon_remote_ui_status(device, "2026-07-21T21:00:00+00:00")

        self.assertTrue(status["is_on"])
        self.assertEqual(status["raw"]["source"], "canon-remote-ui")
        self.assertEqual(status["appliance"]["inkLevels"][0]["status"], "low")
        self.assertIsNone(status["appliance"]["inkLevels"][0]["percent"])
        self.assertEqual(status["appliance"]["lowestInkPercent"], 70)

    def test_manual_refill_override_marks_supply_full(self):
        device = type("Device", (), {
            "device_key": json.dumps({"community": "public", "ink_refills": {"black": {"refilled_at": "2026-07-08T12:00:00+00:00"}}})
        })()
        status = {
            "appliance": {
                "status": "Needs attention",
                "message": "",
                "alerts": [],
                "lowestInkPercent": 20,
                "inkLevels": [
                    {"color": "Black", "level": 20, "percent": 20, "status": "watch", "measurement": "remote-ui-estimate"},
                    {"color": "Cyan", "level": 100, "percent": 100, "status": "ok", "measurement": "remote-ui-estimate"},
                ],
            },
            "raw": {},
        }

        printer_service._apply_manual_ink_refills(device, status)

        black = status["appliance"]["inkLevels"][0]
        self.assertEqual(black["percent"], 100)
        self.assertEqual(black["status"], "ok")
        self.assertEqual(black["measurement"], "manual-refill")
        self.assertEqual(status["appliance"]["lowestInkPercent"], 100)
        self.assertTrue(status["raw"]["manualInkRefill"])

    def test_txt_record_value_stops_before_next_key(self):
        output = "ty=EPSON ET-4750 Series usb_MFG=EPSON product=(EPSON ET-4750 Series) UUID=abc"

        self.assertEqual(printer_service._txt_record_value(output, "ty"), "EPSON ET-4750 Series")

    def test_single_ip_subnet_includes_host(self):
        self.assertEqual(printer_service._network_hosts("10.1.1.20/32"), ["10.1.1.20"])

    def test_requested_single_ip_becomes_direct_candidate(self):
        candidates = printer_service._requested_host_candidates(["10.1.1.20"])

        self.assertEqual(candidates[0]["host"], "10.1.1.20")
        self.assertEqual(candidates[0]["source"], "direct")


if __name__ == "__main__":
    unittest.main()
