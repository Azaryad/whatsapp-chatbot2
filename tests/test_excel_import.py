import subprocess, sys

def test_driver_template_parseable():
    """The generated driver_template.xlsx must parse without error."""
    result = subprocess.run(
        [sys.executable, "create_driver_template.py"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr

    from app.utils.excel_import import parse_driver_excel
    with open("driver_template.xlsx", "rb") as f:
        drivers = parse_driver_excel(f.read())
    assert len(drivers) == 4
    assert drivers[0].drivercode == "DR001"
    assert drivers[1].vehicle_type.value == "executive_minivan"
