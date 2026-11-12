# -*- coding: utf-8 -*-
"""Smoke-test local skill scripts with outbound sockets blocked."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import TestCase

from docx import Document
from openpyxl import Workbook, load_workbook
from pptx import Presentation
from reportlab.pdfgen.canvas import Canvas

SKILLS = Path(__file__).resolve().parents[1] / "assets/builtin_skills"
OFFLINE_RUNNER = """
import runpy, socket, sys
def blocked(*args, **kwargs):
    raise RuntimeError('Network is disabled in the skill smoke test')
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
script = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, str(__import__('pathlib').Path(script).parent))
runpy.run_path(script, run_name='__main__')
"""


class BuiltinSkillRuntimeTest(TestCase):
    """Check useful output, not merely importability or --help."""

    def setUp(self):
        self.output = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def run_script(self, path, *args):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                OFFLINE_RUNNER,
                str(SKILLS / path),
                *map(str, args),
            ],
            capture_output=True,
            text=True,
            cwd=self.output,
            timeout=40,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_meeting_template_accepts_session_output_path(self):
        path = self.output / "会议模板.docx"
        self.run_script(
            "gov-enterprise-meeting-minutes/build_template.py", "--out", path
        )
        self.assertTrue(path.is_file())
        self.assertTrue(Document(path).paragraphs)

    def test_excel_values_fill_word_without_network(self):
        workbook = Workbook()
        workbook.active.title = "数据"
        workbook.active.append(["公司", "内网样例公司"])
        excel = self.output / "data.xlsx"
        workbook.save(excel)
        document = Document()
        document.add_paragraph("公司：{{company}}")
        template = self.output / "template.docx"
        document.save(template)
        mapping = self.output / "mapping.json"
        mapping.write_text(
            json.dumps(
                [
                    {
                        "locate": {"type": "placeholder", "name": "company"},
                        "source": {"sheet": "数据", "key": "公司"},
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        output = self.output / "filled.docx"
        self.run_script(
            "excel-word-link/scripts/apply_mapping.py",
            mapping,
            template,
            output,
            "--excel",
            excel,
        )
        self.assertEqual(
            Document(output).paragraphs[0].text, "公司：内网样例公司"
        )
        self.assertEqual(
            Document(template).paragraphs[0].text, "公司：{{company}}"
        )

    def test_reconciliation_outputs_expected_differences_and_preserves_input(
        self,
    ):
        left = self.output / "left.csv"
        right = self.output / "right.csv"
        left.write_text(
            "no,amount\nA,100.00\nB,200.00\nC,50.00\n", encoding="utf-8"
        )
        right.write_text(
            "no,amount\nA,100.00\nB,220.00\nD,30.00\n", encoding="utf-8"
        )
        before = (left.read_bytes(), right.read_bytes())
        output = self.output / "对账.xlsx"
        config = {
            "left": {
                "file": str(left),
                "fields": {"no": "no", "amount": "amount"},
            },
            "right": {
                "file": str(right),
                "fields": {"no": "no", "amount": "amount"},
            },
            "match": {"direction_rule": "none"},
            "output": {"path": str(output)},
        }
        path = self.output / "config.yaml"
        # JSON is valid YAML and avoids ambiguous bare 'no' keys.
        path.write_text(json.dumps(config), encoding="utf-8")
        summary = json.loads(
            self.run_script(
                "fcs-reconcile/scripts/reconcile.py", "--config", path
            )
        )
        self.assertTrue(summary["quantity_reconciled"])
        self.assertTrue(summary["amount_reconciled"])
        for state in ("已自动匹配", "金额差异", "左侧单边", "右侧单边"):
            self.assertEqual(summary["counts"][state], 1)
        self.assertEqual(before, (left.read_bytes(), right.read_bytes()))
        self.assertTrue(load_workbook(output).sheetnames)
        self.assertTrue(Path(str(output) + ".manifest.json").is_file())

    def test_documents_validator_accepts_four_local_formats(self):
        word = self.output / "report.docx"
        doc = Document()
        doc.add_paragraph("内网办公验证")
        doc.save(word)
        excel = self.output / "table.xlsx"
        wb = Workbook()
        wb.active.append(["数量", 3])
        wb.save(excel)
        powerpoint = self.output / "slides.pptx"
        deck = Presentation()
        deck.slides.add_slide(deck.slide_layouts[0]).shapes.title.text = (
            "内网汇报"
        )
        deck.save(powerpoint)
        pdf = self.output / "report.pdf"
        canvas = Canvas(str(pdf))
        canvas.drawString(72, 720, "Local Office Report")
        canvas.save()
        report = json.loads(
            self.run_script(
                "documents/scripts/validate-documents.py",
                "--json",
                word,
                excel,
                powerpoint,
                pdf,
            )
        )
        self.assertEqual(report["exit_code"], 0)
        self.assertEqual(report["summary"]["passed"], 4)
