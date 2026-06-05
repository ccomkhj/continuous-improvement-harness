import cih

def test_package_exposes_version():
    assert isinstance(cih.__version__, str)
    assert cih.__version__.count(".") >= 1
