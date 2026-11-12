"""内网分发包的标准库冒烟验证，不依赖上游开发环境。"""
from contextlib import redirect_stdout
import io
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from docgen.cli import main  # noqa: E402


class IntranetPackageTest(unittest.TestCase):
    """覆盖断网导出、资源边界和分发内容。"""

    def test_exports_five_document_types_without_network(self):
        """常用文种在禁止网络连接时仍能输出可解析的 Word。"""
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for document_type in ["通知", "报告", "请示", "纪要", "工作总结"]:
                source = folder / "材料.md"
                source.write_text(
                    "# 关于系统内网试运行的通知\n\n"
                    "## 主送单位\n各部门：\n\n"
                    "## 正文\n根据用户提供的材料开展内网试运行。\n\n"
                    "## 落款\n测试单位\n2026年10月21日\n",
                    encoding="utf-8",
                )
                output = folder / f"{document_type}.docx"
                with (
                    patch.object(socket.socket, "connect", side_effect=AssertionError("禁止联网")),
                    patch.object(sys, "argv", ["generate_docx.py", str(source), "-o", str(output), "--doc-type", document_type]),
                    redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(main(), 0, document_type)
                with zipfile.ZipFile(output) as archive:
                    self.assertIsNone(archive.testzip())
                    document = ET.fromstring(archive.read("word/document.xml"))
                    self.assertIn("内网试运行", "".join(document.itertext()))
                    relationships = archive.read("word/_rels/document.xml.rels").decode()
                    self.assertNotIn('TargetMode="External"', relationships)

    def test_does_not_distribute_unverified_fonts(self):
        """授权未确认的字体二进制不进入共享分发包。"""
        fonts = ROOT / "assets/fonts"
        self.assertFalse([p for p in fonts.iterdir() if p.suffix.lower() in {".ttf", ".otf", ".ttc"}])

    def test_generated_entry_and_sources_require_intranet_operation(self):
        """生成入口和规则主源共同约定会话内输出与本地资源。"""
        entry = (ROOT / "SKILL.md").read_text("utf-8")
        self.assertIn("不访问公网", entry)
        self.assertNotIn('"curl"', entry)
        policy = (ROOT / "prompts/core/policy.md").read_text("utf-8")
        self.assertIn("不下载图片、字体", policy)
        workflow = (ROOT / "prompts/core/workflow.md").read_text("utf-8")
        self.assertNotIn("~/official-document-drafting-output/", workflow)
        self.assertIn("当前会话工作目录", workflow)


if __name__ == "__main__":
    unittest.main()
