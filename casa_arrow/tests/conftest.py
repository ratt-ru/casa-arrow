import multiprocessing as mp
import os
from pathlib import Path
from hashlib import sha256

import requests
import tarfile
import pytest

TAU_MS = "HLTau_B6cont.calavg.tav300s"
TAU_MS_TAR = f"{TAU_MS}.tar.xz"
TAU_MS_TAR_HASH = "fc2ce9261817dfd88bbdd244c8e9e58ae0362173938df6ef2a587b1823147f70"
DATA_URL = f"https://ratt-public-data.s3.af-south-1.amazonaws.com/test-data/{TAU_MS_TAR}"
DATA_CHUNK_SIZE = 2**20

def download_tau_ms(tau_ms_tar):
    if tau_ms_tar.exists():
        with open(tau_ms_tar, "rb") as f:
            digest = sha256()

            while data := f.read(DATA_CHUNK_SIZE):
                digest.update(data)

            if digest.hexdigest() == TAU_MS_TAR_HASH:
                return

            tau_ms_tar.unlink(missing_ok=True)
            raise ValueError(
                f"SHA256 digest mismatch for {tau_ms_tar}. "
                f"{digest.hexdigest()} != {TAU_MS_TAR_HASH}")
    else:
        response = requests.get(DATA_URL, stream=True)

        with open(tau_ms_tar, "wb") as fout:
            digest = sha256()

            for data in response.iter_content(chunk_size=DATA_CHUNK_SIZE):
                digest.update(data)
                fout.write(data)

            if digest.hexdigest() != TAU_MS_TAR_HASH:
                raise ValueError(
                    f"SHA256 digest mismatch for {DATA_URL}. "
                    f"{digest.hexdigest()} != {TAU_MS_TAR_HASH}")

@pytest.fixture(scope="session")
def tau_ms_tar():
    from appdirs import user_cache_dir
    cache_dir = Path(user_cache_dir("casa-arrow")) / "test-data"
    cache_dir.mkdir(parents=True, exist_ok=True)
    tau_ms_tar = cache_dir / TAU_MS_TAR

    download_tau_ms(tau_ms_tar)
    return tau_ms_tar


@pytest.fixture(scope="session")
def tau_ms(tau_ms_tar, tmp_path_factory):
    msdir = tmp_path_factory.mktemp("tau-ms")

    with tarfile.open(tau_ms_tar) as tar:
        tar.extractall(msdir)

    return str(msdir / TAU_MS)


@pytest.fixture(scope="session")
def partitioned_dataset(tau_ms, tmp_path_factory):
    import casa_arrow as ca
    import pyarrow as pa
    import pyarrow.dataset as pad

    dsdir = tmp_path_factory.mktemp("partition-dataset")

    AT = ca.table(tau_ms).to_arrow()
    partition_fields = [AT.schema.field(c) for c in ("FIELD_ID", "DATA_DESC_ID")]
    partition = pad.partitioning(pa.schema(partition_fields), flavor="hive")
    pad.write_dataset(AT, dsdir, partitioning=partition,
                      max_rows_per_group=25000,
                      max_rows_per_file=25000,
                      format="parquet")

    return dsdir


def generate_sorting_table(path):
    import pyrap.tables as pt
    table_name = os.path.join(str(path), "test.ms")

    create_table_query = f"""
    CREATE TABLE {table_name}
    [FIELD_ID I4,
    ANTENNA1 I4,
    ANTENNA2 I4,
    DATA_DESC_ID I4,
    SCAN_NUMBER I4,
    STATE_ID I4,
    TIME R8]
    LIMIT 10
    """
    # Common grouping columns
    field = [0, 0, 0, 1, 1, 1, 1, 2, 2, 2]
    ddid = [0, 0, 0, 0, 0, 0, 0, 1, 1, 1]
    scan = [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]

    # Common indexing columns
    time = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]
    ant1 = [0, 0, 1, 1, 1, 2, 1, 0, 0, 1]
    ant2 = [1, 2, 2, 3, 2, 1, 0, 1, 1, 2]

    # Column we'll write to
    state = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

    # Create the table
    with pt.taql(create_table_query) as ms:
        ms.putcol("FIELD_ID", field)
        ms.putcol("DATA_DESC_ID", ddid)
        ms.putcol("ANTENNA1", ant1)
        ms.putcol("ANTENNA2", ant2)
        ms.putcol("SCAN_NUMBER", scan)
        ms.putcol("STATE_ID", state)
        ms.putcol("TIME", time)

    return table_name


@pytest.fixture
def sorting_table(tmp_path_factory):
    return casa_table_at_path(generate_sorting_table,
                              tmp_path_factory.mktemp("column_cases"))


def generate_column_cases_table(path):
    import pyrap.tables as pt
    import numpy as np

    # Table descriptor
    table_desc = [
        {
            "desc": {
                "_c_order": True,
                "comment": "VARIABLE column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "ndim": 3,
                "maxlen": 0,
                "option": 0,
                "valueType": "int",
            },
            "name": "VARIABLE",
        },
        {
            "desc": {
                "_c_order": True,
                "comment": "VARIABLE_STRING column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "ndim": 3,
                "maxlen": 0,
                "option": 0,
                "valueType": "string",
            },
            "name": "VARIABLE_STRING",
        },
        {
            "desc": {
                "_c_order": True,
                "comment": "FIXED column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "ndim": 2,
                "shape": [2, 4],
                "maxlen": 0,
                "option": 0,
                "valueType": "int",
            },
            "name": "FIXED",
        },
        {
            "desc": {
                "_c_order": True,
                "comment": "FIXED_STRING column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "ndim": 2,
                "shape": [2, 4],
                "maxlen": 0,
                "option": 0,
                "valueType": "string",
            },
            "name": "FIXED_STRING",
        },
        {
            "desc": {
                "_c_order": True,
                "comment": "SCALAR column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "maxlen": 0,
                "option": 0,
                "valueType": "int",
            },
            "name": "SCALAR",
        },
        {
            "desc": {
                "_c_order": True,
                "comment": "SCALAR_STRING column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "maxlen": 0,
                "option": 0,
                "valueType": "string",
            },
            "name": "SCALAR_STRING",
        },
        {
            "desc": {
                "_c_order": True,
                "comment": "UNCONSTRAINED column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "maxlen": 0,
                "ndim": -1,
                "option": 0,
                "valueType": "int",
            },
            "name": "UNCONSTRAINED",
        }

    ]

    table_desc = pt.maketabdesc(table_desc)
    table_name = os.path.join(path, "test.table")
    nrow = 3

    with pt.table(table_name, table_desc, nrow=nrow, ack=False) as T:
        for i in range(nrow):
            T.putcell("VARIABLE", i, np.full((3, 1 + i, 2), i))
            T.putcell("FIXED", i, np.full((2, 4), i))
            T.putcell("SCALAR", i, i)

            T.putcell("VARIABLE_STRING", i, np.full((3, 1 + i, 2), str(i)))
            T.putcell("FIXED_STRING", i, np.full((2, 4), str(i)))
            T.putcell("SCALAR_STRING", i, str(i))

        T.putcell("UNCONSTRAINED", 0, np.full((2, 3, 4), 0))
        T.putcell("UNCONSTRAINED", 1, np.full((4, 3), 1))
        T.putcell("UNCONSTRAINED", 2, 2)

        for i in range(nrow):  # Sanity check
            assert T.iscelldefined("UNCONSTRAINED", i)

    return table_name


def casa_table_at_path(factory, path):
    with mp.get_context("spawn").Pool(1) as pool:
        try:
            return pool.apply(factory, (str(path),))
        except ImportError as e:
            if e.msg == "No module named 'pyrap'":
                pytest.skip("python-casacore isn't available")
            else:
                raise


@pytest.fixture
def column_case_table(tmp_path_factory):
    return casa_table_at_path(generate_column_cases_table,
                              tmp_path_factory.mktemp("column_cases"))

def generate_complex_case_table(path):
    import numpy as np
    import pyrap.tables as pt

    table_desc = [
        {
            "desc": {
                "_c_order": True,
                "comment": "COMPLEX column",
                "dataManagerGroup": "",
                "dataManagerType": "",
                "keywords": {},
                "ndim": 2,
                "maxlen": 0,
                "shape": [2, 4],
                "option": 0,
                "valueType": "dcomplex",
            },
            "name": "COMPLEX",
        }]

    table_desc = pt.maketabdesc(table_desc)
    table_name = os.path.join(path, "test.table")
    nrow = 3

    with pt.table(table_name, table_desc, nrow=nrow, ack=False) as T:
        for i in range(nrow):
            T.putcell("COMPLEX", i, np.full((2, 4), i))

    return table_name

@pytest.fixture
def complex_case_table(tmp_path_factory):
    return casa_table_at_path(generate_complex_case_table,
                              tmp_path_factory.mktemp("complex_cases"))
