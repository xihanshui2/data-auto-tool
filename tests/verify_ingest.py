"""验证脚本：测试多 sheet Excel、中文 CSV、ZIP 导入和指纹去重。"""

import sys
import os
import tempfile
from pathlib import Path
from io import BytesIO

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb
import pandas as pd

from core.ingest import (
    ingest_excel_sheets,
    ingest_uploaded,
    record_fingerprint,
    is_new_file,
    _make_table_name,
    _slug,
)
from core.watcher import scan_folder, mark_processed


def test_slug():
    assert _slug("Hello World") == "hello_world"
    assert _slug("  报表-2024  ") == "报表_2024"
    assert _slug("---") == "data"
    assert _slug("Sheet 1 (副本)") == "sheet_1_副本"
    print("OK _slug test passed")


def test_make_table_name():
    t1 = _make_table_name("sales.xlsx")
    assert t1.startswith("sales_")
    assert len(t1.split("_")[-1]) == 8

    t2 = _make_table_name("sales.xlsx", "Sheet1")
    parts = t2.split("_")
    assert parts[0] == "sales"
    assert parts[1] == "sheet1"
    assert len(parts[-1]) == 8
    print("OK _make_table_name test passed")


def test_ingest_excel_sheets():
    con = duckdb.connect(":memory:")
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df1 = pd.DataFrame({"姓名": ["张三", "李四"], "年龄": [30, 25]})
        df2 = pd.DataFrame({"产品": ["A", "B"], "销量": [100, 200]})
        df1.to_excel(writer, sheet_name="人员", index=False)
        df2.to_excel(writer, sheet_name="销售", index=False)
    data = buf.getvalue()

    tables = ingest_excel_sheets(con, data, "test.xlsx")
    assert len(tables) == 2, f"expected 2 tables, got {len(tables)}"

    for t in tables:
        result = con.execute(f"SELECT * FROM \"{t}\"").fetchdf()
        assert len(result) > 0

    # verify Chinese column names preserved
    t_person = [t for t in tables if "人员" in t][0]
    cols = con.execute(f"SELECT * FROM \"{t_person}\" LIMIT 0").fetchdf().columns.tolist()
    assert "姓名" in cols
    assert "年龄" in cols

    print(f"OK multi-sheet Excel test passed, tables: {tables}")
    con.close()


def test_csv_chinese_encoding():
    con = duckdb.connect(":memory:")
    # GB18030 encoded CSV
    csv_data = "姓名,年龄\n张三,30\n李四,25\n".encode("gb18030")

    class FakeUploaded:
        name = "test.csv"
        _data = csv_data
        def read(self):
            return self._data

    uf = FakeUploaded()
    result = ingest_uploaded(con, uf)
    assert isinstance(result, str)

    df = con.execute(f"SELECT * FROM \"{result}\"").fetchdf()
    assert "姓名" in df.columns
    assert df.iloc[0]["姓名"] == "张三"

    print(f"OK GB18030 CSV test passed, table: {result}")
    con.close()


def test_zip_import():
    con = duckdb.connect(":memory:")
    import zipfile

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        csv_data = "姓名,年龄\n张三,30\n".encode("utf-8")
        zf.writestr("people.csv", csv_data)
        excel_buf = BytesIO()
        with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
            pd.DataFrame({"产品": ["A", "B"], "销量": [100, 200]}).to_excel(writer, sheet_name="Sheet1", index=False)
        zf.writestr("sales.xlsx", excel_buf.getvalue())

    class FakeUploaded:
        name = "archive.zip"
        _data = buf.getvalue()
        def read(self):
            return self._data

    uf = FakeUploaded()
    result = ingest_uploaded(con, uf)
    assert isinstance(result, list)
    assert len(result) >= 2, f"expected at least 2 tables, got {len(result)}"

    print(f"OK ZIP import test passed, tables: {result}")
    con.close()


def test_fingerprint_dedup():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "processed.jsonl"
        test_file = Path(tmpdir) / "data.csv"
        test_file.write_text("a,b\n1,2\n", encoding="utf-8")

        assert is_new_file(test_file, log_path) is True
        record_fingerprint(test_file, log_path)
        assert is_new_file(test_file, log_path) is False

        # modify file should be considered new
        import time
        time.sleep(0.1)
        test_file.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
        assert is_new_file(test_file, log_path) is True

        print("OK fingerprint dedup test passed")


def test_scan_folder():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "processed.jsonl"
        data_dir = Path(tmpdir) / "data"
        data_dir.mkdir()
        (data_dir / "file1.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        (data_dir / "file2.xlsx").write_bytes(b"")  # empty file, will be skipped
        (data_dir / "file3.csv").write_text("c,d\n3,4\n", encoding="utf-8")

        # mark file1 as processed
        record_fingerprint(data_dir / "file1.csv", log_path)

        new_files = scan_folder(data_dir, processed_log=log_path)
        names = [f.name for f in new_files]
        assert "file1.csv" not in names
        assert "file3.csv" in names

        mark_processed(new_files, processed_log=log_path)
        new_files2 = scan_folder(data_dir, processed_log=log_path)
        assert len(new_files2) == 0

        print("OK folder scan test passed")


if __name__ == "__main__":
    test_slug()
    test_make_table_name()
    test_ingest_excel_sheets()
    test_csv_chinese_encoding()
    test_zip_import()
    test_fingerprint_dedup()
    test_scan_folder()
    print("\nAll verification tests passed!")
